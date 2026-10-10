"""Provider-neutral LLM types. The agent runtime only ever sees these.

Conversation = list of turns:
  UserTurn(text)                                  - trusted context + untrusted customer message
  AssistantTurn(text, tool_calls, raw)            - raw = adapter-private native content (replayed verbatim)
  ToolResultsTurn([ToolResult(call_id, content, is_error)])
Tool specs are neutral JSON Schema dicts: {"name", "description", "input_schema"}.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union


class LLMError(Exception):
    """Model call failed or returned something unusable. The run fails closed."""

    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind  # TIMEOUT | RATE_LIMIT | CONNECTION | AUTH | NOT_FOUND | BAD_REQUEST | SERVER | API_STATUS
        #                  | REFUSAL | MAX_TOKENS | UNEXPECTED_STOP | UNSUPPORTED_CAPABILITY | SCRIPT_EXHAUSTED
        #                  | SDK_MISSING


@dataclass
class ToolCall:
    id: str
    name: str
    input: Any            # dict when well-formed; raw string/other when the model produced malformed arguments


@dataclass
class UserTurn:
    text: str


@dataclass
class AssistantTurn:
    text: str
    tool_calls: list[ToolCall]
    raw: Any = None


@dataclass
class ToolResult:
    call_id: str
    content: str          # JSON text
    is_error: bool


@dataclass
class ToolResultsTurn:
    results: list[ToolResult]


Turn = Union[UserTurn, AssistantTurn, ToolResultsTurn]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str                    # neutral: "end_turn" | "tool_use"
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    raw: Any = None                     # adapter-private, stored on the AssistantTurn
    simulated: bool = False             # replay: token counts, if any, are script values
    provider_cost_usd: float | None = None   # cost reported by the provider itself (e.g. OpenRouter usage accounting)
    extra: dict = field(default_factory=dict)


def attempt_timeout(request_timeout_s: float, max_retries: int, remaining_s: float | None) -> float:
    """Per-attempt timeout so that ALL SDK attempts (1 + max_retries) fit in the remaining wall budget."""
    if remaining_s is None:
        return request_timeout_s
    return max(1.0, min(request_timeout_s, remaining_s / (max_retries + 1)))
