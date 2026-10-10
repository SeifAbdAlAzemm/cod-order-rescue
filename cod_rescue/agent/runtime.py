"""Agent run loop: decide (LLM) -> tool (guarded) -> observe -> validate -> continue/stop.

Hard limits (LLM calls, tool calls, invalid actions, wall time, tokens, cost) are enforced here,
not by the model. Every failure fails closed: the order is never made ready by an error path,
and the final agent outcome is read from the database, never from the model's text.
"""

from __future__ import annotations

import json
import time
import uuid

from cod_rescue.agent.providers.base import AssistantTurn, LLMError, ToolResult, ToolResultsTurn, UserTurn
from cod_rescue.agent.prompts import SYSTEM_PROMPT, build_turn
from cod_rescue.agent.templates import fallback_message
from cod_rescue.agent.toolbox import TOOL_SPECS, Dispatcher
from cod_rescue.config import model_pricing
from cod_rescue.context import ToolContext, redact
from cod_rescue.policy import READY, evaluate
from cod_rescue.services import load_order
from cod_rescue.tools import (escalate, ingest_event, record_decision, request_confirmation, save_event_result,
                              send_message)


class _Stop(Exception):
    def __init__(self, error_class: str, detail: str):
        super().__init__(detail)
        self.error_class = error_class
        self.detail = detail


class _Run:
    def __init__(self, ctx: ToolContext, llm, order_id: str, event_id: str):
        self.ctx, self.llm = ctx, llm
        self.run_id = f"run-{uuid.uuid4().hex[:12]}"
        self.live = llm.mode == "LIVE"
        self.provider = getattr(llm, "provider", "unknown")
        self.profile = (getattr(llm, "profile", None) or ctx.settings.llm.profile) if self.live else None
        self.pricing = model_pricing(ctx.settings, self.profile) if self.live else None
        if not self.live:
            self.cost_basis = "NOT_APPLICABLE_REPLAY"
        elif self.pricing.status == "verified_free":
            self.cost_basis = "VERIFIED_FREE_MODEL"
        else:
            self.cost_basis = "ESTIMATED_FROM_TOKEN_USAGE"
        self.step = 0
        self.llm_calls = self.tool_calls = self.invalid = 0
        self.input_tokens = self.output_tokens = 0
        self.cost = 0.0                      # local estimate from token usage x configured prices
        self.provider_cost: float | None = None   # what the provider itself reported, if anything
        self.started = time.monotonic()
        ctx.run_id = self.run_id
        ctx.conn.execute(
            "INSERT INTO agent_runs (run_id, mode, provider, model, order_id, event_id, status, cost_basis, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?)",
            (self.run_id, llm.mode, self.provider, llm.model, order_id, event_id, self.cost_basis, ctx.now()))

    def trace(self, kind, name, inp, out, latency_ms=None, in_tok=None, out_tok=None):
        self.step += 1
        self.ctx.conn.execute(
            "INSERT INTO agent_steps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.run_id, self.step, kind, name,
             json.dumps(redact(inp), ensure_ascii=False, default=str) if inp is not None else None,
             json.dumps(redact(out), ensure_ascii=False, default=str) if out is not None else None,
             latency_ms, in_tok, out_tok, self.ctx.now()))

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

    def check_budget(self) -> None:
        b = self.ctx.settings.agent_budget
        if self.elapsed_s() > b.max_wall_time_s:
            raise _Stop("TIMEOUT", f"wall time budget {b.max_wall_time_s}s exceeded")
        if self.input_tokens > b.max_input_tokens or self.output_tokens > b.max_output_tokens:
            raise _Stop("BUDGET_EXCEEDED", f"token budget exceeded ({self.input_tokens} in / {self.output_tokens} out)")
        spent = max(self.cost, self.provider_cost or 0.0)  # enforce on the higher of estimate / reported
        if spent > b.max_cost_usd:
            raise _Stop("BUDGET_EXCEEDED", f"cost budget ${b.max_cost_usd} exceeded (${spent:.5f})")


def handle_event(ctx: ToolContext, llm, order_id: str, event_id: str, text: str) -> dict:
    """Process one inbound customer message for one order. Idempotent per event_id."""
    ing = ingest_event(ctx, order_id, event_id, text)
    if not ing["ok"]:
        return {**ing, "status": "EVENT_REJECTED", "reason": ing["status"]}
    if ing["status"] == "DUPLICATE_EVENT":
        if ing["saved_result"] is not None:  # DT-14: same outcome, no new side effects, no LLM call
            return {**ing["saved_result"], "replayed_from_saved_result": True}
        res = escalate(ctx, order_id, "EVENT_PROCESSING_INCOMPLETE",
                       f"event {event_id} redelivered without a saved result; not re-run automatically")
        return {"status": "ESCALATED_INCOMPLETE_EVENT", "event_id": event_id, "escalation": res}

    run = _Run(ctx, llm, order_id, event_id)
    budget = ctx.settings.agent_budget
    dispatcher = Dispatcher(ctx, order_id, event_id, load_order(ctx.conn, order_id).version)
    conversation: list = [UserTurn(build_turn(ctx, order_id, event_id, text))]
    error_class = error_detail = None
    final_text = ""
    try:
        while True:
            if run.llm_calls >= budget.max_llm_calls:
                raise _Stop("BUDGET_EXCEEDED", f"max_llm_calls={budget.max_llm_calls} reached")
            run.check_budget()
            remaining = budget.max_wall_time_s - run.elapsed_s()
            if remaining < 1.0:
                raise _Stop("TIMEOUT", "less than 1s of wall-time budget left for a model call")
            try:
                resp = llm.create(SYSTEM_PROMPT, TOOL_SPECS, conversation, remaining_s=remaining)
            except LLMError as e:
                run.trace("LLM_CALL", llm.model, None, {"error": e.kind, "message": str(e)[:300]})
                raise _Stop("TIMEOUT" if e.kind == "TIMEOUT" else "LLM_ERROR", f"{e.kind}: {str(e)[:200]}")
            run.llm_calls += 1
            run.input_tokens += resp.input_tokens
            run.output_tokens += resp.output_tokens
            if run.live:
                run.cost += (resp.input_tokens * run.pricing.input + resp.output_tokens * run.pricing.output) / 1e6
                if resp.provider_cost_usd is not None:
                    run.provider_cost = (run.provider_cost or 0.0) + resp.provider_cost_usd
            run.trace("LLM_CALL", llm.model, None,
                      {"stop_reason": resp.stop_reason, "text": resp.text[:500],
                       "tool_calls": [c.name for c in resp.tool_calls], "simulated": resp.simulated,
                       "provider_cost_usd": resp.provider_cost_usd},
                      resp.latency_ms, resp.input_tokens, resp.output_tokens)
            run.check_budget()  # an over-budget response's actions are NOT executed
            conversation.append(AssistantTurn(resp.text, resp.tool_calls, resp.raw))
            if not resp.tool_calls:
                final_text = resp.text
                break
            results = []
            for call in resp.tool_calls:
                if run.tool_calls >= budget.max_tool_calls:
                    raise _Stop("BUDGET_EXCEEDED", f"max_tool_calls={budget.max_tool_calls} reached (possible loop)")
                run.tool_calls += 1
                t0 = time.monotonic()
                outcome = dispatcher.execute(call.name, call.input)
                run.trace("TOOL_CALL", call.name, call.input, outcome.result, int((time.monotonic() - t0) * 1000))
                if outcome.invalid:
                    run.invalid += 1
                    if run.invalid >= budget.max_invalid_actions:
                        raise _Stop("VALIDATION_ERROR", f"{run.invalid} malformed/unsupported tool calls")
                if outcome.stop:
                    raise _Stop(outcome.stop, outcome.result.get("status", "tool requested stop"))
                results.append(ToolResult(call.id, json.dumps(outcome.result, ensure_ascii=False, default=str),
                                          outcome.is_error))
            conversation.append(ToolResultsTurn(results))
    except _Stop as s:
        error_class, error_detail = s.error_class, s.detail
    except Exception as e:  # unexpected tool/infra failure: fail closed, keep state, log
        error_class, error_detail = "TOOL_ERROR", f"{type(e).__name__}: {str(e)[:200]}"
        if ctx.conn.in_transaction:
            ctx.conn.execute("ROLLBACK")

    # ---- finalize: authoritative outcome comes from the database
    o = load_order(ctx.conn, order_id)
    if o.lifecycle_state == READY and o.agent_outcome == READY:
        pass  # committed in this or an earlier run; an error afterwards never un-readies it
    elif error_class:
        if not dispatcher.escalated:
            escalate(ctx, order_id, f"AGENT_{error_class}", error_detail or error_class)
    elif not dispatcher.escalated:
        record_decision(ctx, order_id)  # persists ON_HOLD/ESCALATE from deterministic policy; never READY
    fallback_used = _ensure_reply(ctx, order_id, event_id, dispatcher)
    o = load_order(ctx.conn, order_id)
    reasons = (o.outcome_reason or "").split(",") if o.outcome_reason else []
    run.trace("STOP", error_class or "COMPLETED", None, {"outcome": o.agent_outcome, "detail": error_detail})

    status = "COMPLETED" if not error_class else ("STOPPED" if error_class in ("BUDGET_EXCEEDED", "VALIDATION_ERROR", "TIMEOUT") else "FAILED")
    latency_ms = int(run.elapsed_s() * 1000)
    result = {
        "run_id": run.run_id, "mode": llm.mode, "provider": run.provider, "model": llm.model,
        "profile": run.profile.name if run.profile else None, "order_id": order_id, "event_id": event_id,
        "outcome": o.agent_outcome, "lifecycle_state": o.lifecycle_state, "version": o.version,
        "reasons": reasons, "status": status, "error_class": error_class, "error_detail": error_detail,
        "llm_calls": run.llm_calls, "tool_calls": run.tool_calls,
        "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
        "cost_usd": round(run.cost, 6),
        "cost_basis": run.cost_basis,
        "provider_cost_usd": round(run.provider_cost, 6) if run.provider_cost is not None else None,
        "latency_ms": latency_ms, "messages_sent": dispatcher.messages_sent, "agent_summary": final_text[:500],
        "fallback_reply_used": fallback_used,
    }
    ctx.conn.execute(
        "UPDATE agent_runs SET status = ?, error_class = ?, error_detail = ?, llm_calls = ?, tool_calls = ?, "
        "input_tokens = ?, output_tokens = ?, cost_usd = ?, provider_cost_usd = ?, final_outcome = ?, "
        "final_lifecycle = ?, agent_summary = ?, latency_ms = ?, ended_at = ? WHERE run_id = ?",
        (status, error_class, error_detail, run.llm_calls, run.tool_calls, run.input_tokens, run.output_tokens,
         result["cost_usd"], result["provider_cost_usd"], o.agent_outcome, o.lifecycle_state, final_text[:500], latency_ms, ctx.now(), run.run_id))
    save_event_result(ctx, event_id, result)
    ctx.run_id = None
    return result


def _ensure_reply(ctx: ToolContext, order_id: str, event_id: str, dispatcher: Dispatcher) -> bool:
    """Every processed customer message gets a reply. If the agent sent none, send a deterministic,
    idempotent template chosen from authoritative state (never LLM text)."""
    if dispatcher.messages_sent:
        return False
    o = load_order(ctx.conn, order_id)
    decision = evaluate(ctx, order_id).to_dict()
    if o.agent_outcome != "ESCALATE_TO_HUMAN" and decision["next_action"] == "REQUEST_CONFIRMATION":
        res = request_confirmation(ctx, order_id, o.version)  # itself a trusted template
        if res["status"] == "REQUESTED":
            dispatcher.messages_sent.append({"kind": "CONFIRMATION_REQUEST", "text": res["message"], "template": True,
                                             "fallback": True})
            return True
    kind, text = fallback_message(order_id, o.agent_outcome, decision)
    res = send_message(ctx, order_id, kind, text, f"fallback:{event_id}")
    if res["ok"]:
        dispatcher.messages_sent.append({"kind": kind, "text": text, "template": True, "fallback": True})
    return True
