"""Scripted model turns (REPLAY). No API call, no cost, provider-independent.
It exercises the harness and guarded tools deterministically; it is NOT evidence of model understanding."""

from __future__ import annotations

from cod_rescue.agent.providers.anthropic_provider import check_stop
from cod_rescue.agent.providers.base import LLMError, LLMResponse, ToolCall


class ReplayLLM:
    """Each step is one of:
       {"tool_calls": [{"name": ..., "input": {...}}], "text": "..."}   -> tool_use turn
       {"text": "..."}                                                  -> end_turn
       {"error": "TIMEOUT" | "RATE_LIMIT" | ...}                        -> raises LLMError
       {"stop_reason": "refusal" | "max_tokens" | ...}                  -> unusable response
       optional "simulated_usage": {"input_tokens": n, "output_tokens": m} for budget tests
    """

    mode = "REPLAY"
    provider = "replay"
    model = "replay-script"
    profile = None

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.calls = 0

    def create(self, system: str, tools: list[dict], conversation, remaining_s: float | None = None) -> LLMResponse:
        if self.calls >= len(self.script):
            raise LLMError("SCRIPT_EXHAUSTED", "replay script has no more turns")
        step = self.script[self.calls]
        self.calls += 1
        if "error" in step:
            raise LLMError(step["error"], f"simulated {step['error']}")
        calls = [ToolCall(f"replay_{self.calls}_{i}", c.get("name"), c.get("input", {}))
                 for i, c in enumerate(step.get("tool_calls", []))]
        check_stop(step.get("stop_reason", "tool_use" if calls else "end_turn"))
        usage = step.get("simulated_usage", {})
        return LLMResponse(step.get("text", ""), calls, "tool_use" if calls else "end_turn",
                           usage.get("input_tokens", 0), usage.get("output_tokens", 0), 0, simulated=True)
