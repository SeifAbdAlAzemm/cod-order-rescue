"""Anthropic Messages API adapter (LIVE). Behaviour unchanged from Slice 3; now speaks the neutral interface."""

from __future__ import annotations

import time

from cod_rescue.agent.providers.base import (
    AssistantTurn, LLMError, LLMResponse, ToolCall, ToolResultsTurn, UserTurn, attempt_timeout,
    classify_status_error, llm_error_from_status,
)

ACCEPTED_STOP_REASONS = {"end_turn", "tool_use", "stop_sequence"}


def check_stop(stop_reason: str) -> None:
    if stop_reason == "refusal":
        raise LLMError("REFUSAL", "model declined the request")
    if stop_reason == "max_tokens":
        raise LLMError("MAX_TOKENS", "model output truncated at max_tokens")
    if stop_reason not in ACCEPTED_STOP_REASONS:
        raise LLMError("UNEXPECTED_STOP", f"unsupported stop_reason {stop_reason!r}")


def to_anthropic_messages(conversation) -> list[dict]:
    out = []
    for turn in conversation:
        if isinstance(turn, UserTurn):
            out.append({"role": "user", "content": turn.text})
        elif isinstance(turn, AssistantTurn):
            content = turn.raw if turn.raw is not None else (
                ([{"type": "text", "text": turn.text}] if turn.text else [])
                + [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in turn.tool_calls])
            out.append({"role": "assistant", "content": content})
        elif isinstance(turn, ToolResultsTurn):
            out.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
                for r in turn.results]})
    return out


class AnthropicLLM:
    mode = "LIVE"
    provider = "anthropic"

    def __init__(self, settings, profile=None, client=None, api_key: str | None = None):
        self.settings = settings
        self.profile = profile or settings.llm.profile
        self.model = self.profile.model
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise LLMError("SDK_MISSING", "pip install -r requirements.txt") from e
        self._anthropic = anthropic
        # Credentials: an in-memory key for this invocation only (dashboard), else the env var named by the
        # profile; never from code or config. The endpoint is always explicit and allowlisted, so an
        # ANTHROPIC_BASE_URL environment variable cannot redirect the key elsewhere.
        import os
        from cod_rescue.agent.providers.capabilities import key_destination
        url, trusted = key_destination(self.profile)
        if not trusted:
            raise LLMError("UNSUPPORTED_CAPABILITY", f"refusing to send credentials to untrusted host {url!r}")
        self.client = client or anthropic.Anthropic(
            api_key=api_key or os.environ.get(self.profile.api_key_env) or None, base_url=url,
            timeout=settings.llm.request_timeout_s, max_retries=settings.llm.max_retries)

    def attempt_timeout(self, remaining_s: float | None) -> float:
        return attempt_timeout(self.settings.llm.request_timeout_s, self.settings.llm.max_retries, remaining_s)

    def create(self, system: str, tools: list[dict], conversation, remaining_s: float | None = None) -> LLMResponse:
        a = self._anthropic
        started = time.monotonic()
        kwargs = {}
        if self.profile.options.get("effort"):
            kwargs["output_config"] = {"effort": self.profile.options["effort"]}
        try:
            resp = self.client.with_options(timeout=self.attempt_timeout(remaining_s)).messages.create(
                model=self.model,
                max_tokens=self.settings.llm.max_tokens,
                system=system,
                tools=tools,
                messages=to_anthropic_messages(conversation),
                **kwargs,
            )
        # most specific first; APITimeoutError subclasses APIConnectionError
        except a.APITimeoutError as e:
            raise LLMError("TIMEOUT", str(e)) from e
        except a.APIStatusError as e:  # every HTTP status error: neutral kind + structured, sanitized fields
            kind = classify_status_error(a, e)
            note = {"AUTH": f"authentication/permission failed (check {self.profile.api_key_env})",
                    "NOT_FOUND": f"model or endpoint not found ({self.model})"}.get(kind, "")
            raise llm_error_from_status(e, kind, note) from e
        except a.APIConnectionError as e:
            raise LLMError("CONNECTION", str(e)) from e
        latency = int((time.monotonic() - started) * 1000)
        check_stop(resp.stop_reason)
        usage = resp.usage
        input_tokens = (usage.input_tokens + (getattr(usage, "cache_read_input_tokens", 0) or 0)
                        + (getattr(usage, "cache_creation_input_tokens", 0) or 0))
        calls = [ToolCall(b.id, b.name, b.input) for b in resp.content if b.type == "tool_use"]
        return LLMResponse(
            text="".join(b.text for b in resp.content if b.type == "text"),
            tool_calls=calls,
            stop_reason="tool_use" if calls else "end_turn",
            input_tokens=input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=latency,
            raw=list(resp.content),  # keeps thinking/tool_use blocks intact for the next request
        )
