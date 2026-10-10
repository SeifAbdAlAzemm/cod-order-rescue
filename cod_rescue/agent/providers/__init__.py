"""Provider registry. Adding a provider = one adapter class + one entry here; the runtime is unchanged."""

from __future__ import annotations

from cod_rescue.agent.providers.anthropic_provider import AnthropicLLM
from cod_rescue.agent.providers.base import LLMError, LLMResponse, ToolCall
from cod_rescue.agent.providers.openai_compatible import OpenAICompatibleLLM
from cod_rescue.agent.providers.replay import ReplayLLM

REGISTRY = {
    "anthropic": AnthropicLLM,
    "openai_compatible": OpenAICompatibleLLM,
}


def build_provider(settings, profile=None):
    profile = profile or settings.llm.profile
    try:
        cls = REGISTRY[profile.provider]
    except KeyError:
        raise LLMError("UNSUPPORTED_CAPABILITY", f"unknown provider {profile.provider!r}") from None
    return cls(settings, profile)


__all__ = ["REGISTRY", "build_provider", "AnthropicLLM", "OpenAICompatibleLLM", "ReplayLLM",
           "LLMError", "LLMResponse", "ToolCall"]
