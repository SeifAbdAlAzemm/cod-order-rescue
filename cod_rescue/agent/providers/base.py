"""Provider-neutral LLM types. The agent runtime only ever sees these.

Conversation = list of turns:
  UserTurn(text)                                  - trusted context + untrusted customer message
  AssistantTurn(text, tool_calls, raw)            - raw = adapter-private native content (replayed verbatim)
  ToolResultsTurn([ToolResult(call_id, content, is_error)])
Tool specs are neutral JSON Schema dicts: {"name", "description", "input_schema"}.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Union


_SECRET_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[^\s'\",]+"), r"\1[REDACTED]"),
    (re.compile(r"\b(sk-[A-Za-z]{0,8}-?)[A-Za-z0-9_\-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"\b(hf_)[A-Za-z0-9]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|authorization|x-api-key|token)['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"), r"\1[REDACTED]"),
]


def sanitize(text, limit: int = 1000) -> str:
    """Mask credential-like substrings and bound length before anything is logged or stored."""
    s = str(text or "")
    for pattern, repl in _SECRET_PATTERNS:
        s = pattern.sub(repl, s)
    return s[:limit]


class LLMError(Exception):
    """Model call failed or returned something unusable. The run fails closed.

    Structured, sanitized diagnostics (all optional): http_status, provider_error_code,
    upstream_provider, retry_after; `detail` is the sanitized provider message.
    """

    def __init__(self, kind: str, message: str = "", *, http_status: int | None = None,
                 provider_error_code=None, upstream_provider: str | None = None, retry_after: str | None = None):
        self.detail = sanitize(message or kind)
        super().__init__(self.detail)
        self.kind = kind  # TIMEOUT | RATE_LIMIT | CONNECTION | AUTH | NOT_FOUND | BAD_REQUEST | SERVER | API_STATUS
        #                  | REFUSAL | MAX_TOKENS | UNEXPECTED_STOP | UNSUPPORTED_CAPABILITY | SCRIPT_EXHAUSTED
        #                  | SDK_MISSING
        self.http_status = http_status
        self.provider_error_code = provider_error_code
        self.upstream_provider = sanitize(upstream_provider, 100) if upstream_provider else None
        self.retry_after = sanitize(retry_after, 40) if retry_after else None

    def diagnostics(self) -> dict:
        return {"error_kind": self.kind, "http_status": self.http_status,
                "provider_error_code": self.provider_error_code, "upstream_provider": self.upstream_provider,
                "retry_after": self.retry_after, "detail": self.detail}


def status_error_fields(e) -> dict:
    """Extract structured fields from an SDK HTTP status error (anthropic or openai), never headers/keys."""
    fields: dict = {"http_status": getattr(e, "status_code", None)}
    response = getattr(e, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        fields["retry_after"] = headers.get("retry-after") or headers.get("x-ratelimit-reset")
    body = getattr(e, "body", None)
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        fields["provider_error_code"] = err.get("code") or err.get("type")
        meta = err.get("metadata") if isinstance(err.get("metadata"), dict) else {}
        fields["upstream_provider"] = meta.get("provider_name")
        raw = meta.get("raw")
        fields["message"] = f"{err.get('message', '')}" + (f" | upstream: {raw}" if raw else "")
    else:
        fields["message"] = getattr(e, "message", None) or str(e)
    return fields


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


def llm_error_from_status(e, kind: str, note: str = "") -> "LLMError":
    f = status_error_fields(e)
    msg = f"{note} | {f.get('message', '')}" if note else f.get("message", "")
    return LLMError(kind, msg, http_status=f.get("http_status"), provider_error_code=f.get("provider_error_code"),
                    upstream_provider=f.get("upstream_provider"), retry_after=f.get("retry_after"))


def classify_status_error(sdk, e) -> str:
    """Map an SDK HTTP status error class to a neutral kind (works for anthropic and openai SDKs)."""
    for name, kind in (("AuthenticationError", "AUTH"), ("PermissionDeniedError", "AUTH"),
                       ("NotFoundError", "NOT_FOUND"), ("RateLimitError", "RATE_LIMIT"),
                       ("BadRequestError", "BAD_REQUEST"), ("InternalServerError", "SERVER")):
        cls = getattr(sdk, name, None)
        if cls is not None and isinstance(e, cls):
            return kind
    return "API_STATUS"


def attempt_timeout(request_timeout_s: float, max_retries: int, remaining_s: float | None) -> float:
    """Per-attempt timeout so that ALL SDK attempts (1 + max_retries) fit in the remaining wall budget."""
    if remaining_s is None:
        return request_timeout_s
    return max(1.0, min(request_timeout_s, remaining_s / (max_retries + 1)))
