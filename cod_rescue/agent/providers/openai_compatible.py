"""OpenAI-compatible Chat Completions adapter (LIVE): OpenRouter first; Hugging Face router, OpenAI or a
local server are configuration only (base_url + api_key_env). Uses the official OpenAI Python SDK."""

from __future__ import annotations

import json
import os
import time

from cod_rescue.agent.providers.base import (
    AssistantTurn, LLMError, LLMResponse, ToolCall, ToolResultsTurn, UserTurn, attempt_timeout,
    classify_status_error, llm_error_from_status,
)


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["input_schema"]}} for t in tools]


def to_openai_messages(system: str, conversation) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for turn in conversation:
        if isinstance(turn, UserTurn):
            out.append({"role": "user", "content": turn.text})
        elif isinstance(turn, AssistantTurn):
            msg: dict = {"role": "assistant", "content": turn.text or None}
            if turn.tool_calls:
                msg["tool_calls"] = [{
                    "id": c.id, "type": "function",
                    "function": {"name": c.name,
                                 "arguments": c.input if isinstance(c.input, str) else json.dumps(c.input, ensure_ascii=False)},
                } for c in turn.tool_calls]
            out.append(msg)
        elif isinstance(turn, ToolResultsTurn):
            out += [{"role": "tool", "tool_call_id": r.call_id, "content": r.content} for r in turn.results]
    return out


def parse_arguments(raw):
    """JSON object -> dict. Anything else is returned unchanged so the tool validator rejects it (fail closed)."""
    if isinstance(raw, dict):
        return raw
    if raw in (None, ""):
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    return value


def _is_tool_capability_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "tool" in msg and any(w in msg for w in ("support", "endpoint", "not available", "unsupported"))


class OpenAICompatibleLLM:
    mode = "LIVE"
    provider = "openai_compatible"

    def __init__(self, settings, profile=None, client=None):
        self.settings = settings
        self.profile = profile or settings.llm.profile
        self.model = self.profile.model
        try:
            import openai
        except ImportError as e:  # pragma: no cover
            raise LLMError("SDK_MISSING", "pip install -r requirements.txt") from e
        self._openai = openai
        headers = {}
        if self.profile.options.get("app_title"):  # OpenRouter optional attribution headers
            headers["X-Title"] = self.profile.options["app_title"]
        if self.profile.options.get("app_url"):
            headers["HTTP-Referer"] = self.profile.options["app_url"]
        self.client = client or openai.OpenAI(
            api_key=os.environ.get(self.profile.api_key_env) or "missing",
            base_url=self.profile.base_url,
            timeout=settings.llm.request_timeout_s, max_retries=settings.llm.max_retries,
            default_headers=headers or None)

    def attempt_timeout(self, remaining_s: float | None) -> float:
        return attempt_timeout(self.settings.llm.request_timeout_s, self.settings.llm.max_retries, remaining_s)

    def create(self, system: str, tools: list[dict], conversation, remaining_s: float | None = None) -> LLMResponse:
        o = self._openai
        extra_body = {}
        if self.profile.options.get("openrouter_usage"):
            extra_body["usage"] = {"include": True}  # OpenRouter reports the actual cost per request
        started = time.monotonic()
        try:
            resp = self.client.with_options(timeout=self.attempt_timeout(remaining_s)).chat.completions.create(
                model=self.model,
                messages=to_openai_messages(system, conversation),
                tools=to_openai_tools(tools),
                max_tokens=self.settings.llm.max_tokens,
                **({"extra_body": extra_body} if extra_body else {}),
            )
        except o.APITimeoutError as e:
            raise LLMError("TIMEOUT", str(e)) from e
        except o.APIStatusError as e:  # every HTTP status error: neutral kind + structured, sanitized fields
            kind = classify_status_error(o, e)
            if kind in ("NOT_FOUND", "BAD_REQUEST") and _is_tool_capability_error(e):
                kind = "UNSUPPORTED_CAPABILITY"
            note = {"AUTH": f"authentication/permission failed (check {self.profile.api_key_env})",
                    "NOT_FOUND": f"model or endpoint not found ({self.model})"}.get(kind, "")
            raise llm_error_from_status(e, kind, note) from e
        except o.APIConnectionError as e:
            raise LLMError("CONNECTION", str(e)) from e
        latency = int((time.monotonic() - started) * 1000)

        if not getattr(resp, "choices", None):
            err = getattr(resp, "error", None) or (getattr(resp, "model_extra", None) or {}).get("error")
            raise LLMError("SERVER", f"no choices returned: {str(err)[:200]}")
        choice = resp.choices[0]
        msg = choice.message
        finish = choice.finish_reason
        raw_calls = getattr(msg, "tool_calls", None) or []
        if finish == "length":
            raise LLMError("MAX_TOKENS", "model output truncated at max_tokens")
        if finish == "content_filter":
            raise LLMError("REFUSAL", "provider content filter stopped the response")
        if finish not in ("stop", "tool_calls", "function_call", None) and not raw_calls:
            raise LLMError("UNEXPECTED_STOP", f"unsupported finish_reason {finish!r}")
        calls = [ToolCall(tc.id or f"call_{i}", tc.function.name, parse_arguments(tc.function.arguments))
                 for i, tc in enumerate(raw_calls) if getattr(tc, "function", None)]

        usage = getattr(resp, "usage", None)
        provider_cost = None
        if usage is not None:
            provider_cost = getattr(usage, "cost", None)
            if provider_cost is None:
                provider_cost = (getattr(usage, "model_extra", None) or {}).get("cost")
        return LLMResponse(
            text=msg.content or "",
            tool_calls=calls,
            stop_reason="tool_use" if calls else "end_turn",
            input_tokens=(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
            output_tokens=(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
            latency_ms=latency,
            provider_cost_usd=float(provider_cost) if provider_cost is not None else None,
        )
