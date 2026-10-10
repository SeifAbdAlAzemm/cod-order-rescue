"""LLM clients behind one interface.

- AnthropicLLM: real Claude tool use (LIVE). Billable; needs ANTHROPIC_API_KEY.
- ReplayLLM: a fixed script of model turns (REPLAY). No API call, no cost. It exercises the
  harness and guarded tools deterministically; it is NOT evidence of model understanding.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from cod_rescue.config import Settings

ACCEPTED_STOP_REASONS = {"end_turn", "tool_use", "stop_sequence"}


class LLMError(Exception):
    """Model call failed or returned something unusable. The run fails closed."""

    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind  # TIMEOUT | RATE_LIMIT | CONNECTION | AUTH | NOT_FOUND | BAD_REQUEST | SERVER | API_STATUS
        #                  | REFUSAL | MAX_TOKENS | UNEXPECTED_STOP | SCRIPT_EXHAUSTED | SDK_MISSING


@dataclass
class ToolCall:
    id: str
    name: str
    input: Any


@dataclass
class LLMResponse:
    assistant_content: list           # appended back unchanged (keeps thinking/tool_use blocks intact)
    tool_calls: list[ToolCall]
    text: str
    stop_reason: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    simulated: bool = False           # True for replay (token counts, if any, are script values)
    extra: dict = field(default_factory=dict)


def _check_stop(stop_reason: str) -> None:
    if stop_reason == "refusal":
        raise LLMError("REFUSAL", "model declined the request")
    if stop_reason == "max_tokens":
        raise LLMError("MAX_TOKENS", "model output truncated at max_tokens")
    if stop_reason not in ACCEPTED_STOP_REASONS:
        raise LLMError("UNEXPECTED_STOP", f"unsupported stop_reason {stop_reason!r}")


class AnthropicLLM:
    mode = "LIVE"

    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self.model = settings.llm.model
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - depends on environment
            raise LLMError("SDK_MISSING", "pip install -r requirements.txt") from e
        self._anthropic = anthropic
        # Credentials resolve from the environment (ANTHROPIC_API_KEY); never passed in code.
        self.client = client or anthropic.Anthropic(
            timeout=settings.llm.request_timeout_s, max_retries=settings.llm.max_retries)

    def create(self, system: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        a = self._anthropic
        started = time.monotonic()
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=self.settings.llm.max_tokens,
                system=system,
                tools=tools,
                messages=messages,
                output_config={"effort": self.settings.llm.effort},
            )
        # most specific first; APITimeoutError subclasses APIConnectionError
        except a.APITimeoutError as e:
            raise LLMError("TIMEOUT", str(e)) from e
        except a.AuthenticationError as e:
            raise LLMError("AUTH", "authentication failed (check ANTHROPIC_API_KEY)") from e
        except a.NotFoundError as e:
            raise LLMError("NOT_FOUND", f"model or endpoint not found ({self.model})") from e
        except a.RateLimitError as e:
            raise LLMError("RATE_LIMIT", str(e)) from e
        except a.BadRequestError as e:
            raise LLMError("BAD_REQUEST", str(e)) from e
        except a.InternalServerError as e:
            raise LLMError("SERVER", str(e)) from e
        except a.APIStatusError as e:
            raise LLMError("API_STATUS", str(e)) from e
        except a.APIConnectionError as e:
            raise LLMError("CONNECTION", str(e)) from e
        latency = int((time.monotonic() - started) * 1000)
        _check_stop(resp.stop_reason)
        usage = resp.usage
        input_tokens = (usage.input_tokens + (getattr(usage, "cache_read_input_tokens", 0) or 0)
                        + (getattr(usage, "cache_creation_input_tokens", 0) or 0))
        return LLMResponse(
            assistant_content=list(resp.content),
            tool_calls=[ToolCall(b.id, b.name, b.input) for b in resp.content if b.type == "tool_use"],
            text="".join(b.text for b in resp.content if b.type == "text"),
            stop_reason=resp.stop_reason,
            input_tokens=input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=latency,
        )


class ReplayLLM:
    """Plays back scripted model turns. Each step is one of:
       {"tool_calls": [{"name": ..., "input": {...}}], "text": "..."}   -> tool_use turn
       {"text": "..."}                                                  -> end_turn
       {"error": "TIMEOUT" | "RATE_LIMIT" | ...}                        -> raises LLMError
       {"stop_reason": "refusal" | "max_tokens" | ...}                  -> unusable response
       optional "simulated_usage": {"input_tokens": n, "output_tokens": m} for budget tests
    """

    mode = "REPLAY"
    model = "replay-script"

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.calls = 0

    def create(self, system: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        if self.calls >= len(self.script):
            raise LLMError("SCRIPT_EXHAUSTED", "replay script has no more turns")
        step = self.script[self.calls]
        self.calls += 1
        if "error" in step:
            raise LLMError(step["error"], f"simulated {step['error']}")
        calls = [ToolCall(f"replay_{self.calls}_{i}", c.get("name"), c.get("input", {}))
                 for i, c in enumerate(step.get("tool_calls", []))]
        stop = step.get("stop_reason", "tool_use" if calls else "end_turn")
        _check_stop(stop)
        content: list[dict] = []
        if step.get("text"):
            content.append({"type": "text", "text": step["text"]})
        content += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in calls]
        usage = step.get("simulated_usage", {})
        return LLMResponse(content, calls, step.get("text", ""), stop,
                           usage.get("input_tokens", 0), usage.get("output_tokens", 0), 0, simulated=True)
