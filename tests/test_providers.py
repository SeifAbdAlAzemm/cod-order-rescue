"""Provider abstraction: offline adapter conformance, profile config, capability checks, result separation.

No network: SDK clients and the OpenRouter models listing are faked.
"""

import dataclasses
import json
from types import SimpleNamespace

import httpx2
import openai
import pytest

from cod_rescue.agent.providers import REGISTRY, build_provider
from cod_rescue.agent.providers.anthropic_provider import AnthropicLLM, to_anthropic_messages
from cod_rescue.agent.providers.base import (
    AssistantTurn, LLMError, ToolCall, ToolResult, ToolResultsTurn, UserTurn,
)
from cod_rescue.agent.providers.capabilities import check_profile
from cod_rescue.agent.providers.openai_compatible import (
    OpenAICompatibleLLM, parse_arguments, to_openai_messages, to_openai_tools,
)
from cod_rescue.agent.runtime import handle_event
from cod_rescue.agent.evaluation import results_dir
from cod_rescue.agent.toolbox import TOOL_SPECS
from cod_rescue.config import ConfigError, DEFAULT_SETTINGS_PATH, load_dotenv, load_settings, model_pricing
from cod_rescue.context import ToolContext
from tests.conftest import FIXED_NOW
from tests.helpers import count

OR = "openrouter-gemma-free"


@pytest.fixture
def or_settings():
    return load_settings(env={"COD_RESCUE_LLM_PROFILE": OR})


# ---------------------------------------------------------------- fakes

class FakeCompletions:
    def __init__(self, responses=None, exc=None):
        self.responses, self.exc, self.calls = list(responses or []), exc, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.responses.pop(0)


class FakeOpenAIClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)
        self.timeouts = []

    def with_options(self, timeout=None, **_):
        self.timeouts.append(timeout)
        return self


def oa_resp(content="", tool_calls=None, finish="stop", prompt=900, completion=60, cost=None, choices=True):
    calls = [SimpleNamespace(id=tid, type="function", function=SimpleNamespace(name=name, arguments=args))
             for tid, name, args in (tool_calls or [])]
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, model_extra={"cost": cost} if cost is not None else {})
    msg = SimpleNamespace(content=content, tool_calls=calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)] if choices else [],
                           usage=usage, model_extra={})


def oa_llm(settings, responses=None, exc=None):
    comp = FakeCompletions(responses, exc)
    return OpenAICompatibleLLM(settings, client=FakeOpenAIClient(comp)), comp


# ---------------------------------------------------------------- neutral -> native translation

CONV = [UserTurn("ctx"),
        AssistantTurn("checking", [ToolCall("c1", "list_alternatives", {"sku": "X"})]),
        ToolResultsTurn([ToolResult("c1", '{"ok": true}', False)]),
        AssistantTurn("", [ToolCall("c2", "commit_ready", "{bad json")]),
        ToolResultsTurn([ToolResult("c2", '{"ok": false}', True)])]


def test_openai_translation_of_tools_and_conversation():
    tools = to_openai_tools(TOOL_SPECS)
    assert len(tools) == 11 and tools[0]["type"] == "function" and "parameters" in tools[0]["function"]
    msgs = to_openai_messages("SYS", CONV)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "assistant", "tool"]
    assert msgs[2]["tool_calls"][0]["function"] == {"name": "list_alternatives", "arguments": '{"sku": "X"}'}
    assert msgs[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'}
    assert msgs[4]["content"] is None and msgs[4]["tool_calls"][0]["function"]["arguments"] == "{bad json"


def test_anthropic_translation_preserves_raw_and_tool_results():
    raw = [{"type": "thinking", "thinking": ""}, {"type": "tool_use", "id": "c1", "name": "x", "input": {}}]
    conv = [UserTurn("ctx"), AssistantTurn("", [ToolCall("c1", "x", {})], raw=raw),
            ToolResultsTurn([ToolResult("c1", "{}", True)]), AssistantTurn("done", [])]
    msgs = to_anthropic_messages(conv)
    assert msgs[1]["content"] is raw
    assert msgs[2]["content"][0] == {"type": "tool_result", "tool_use_id": "c1", "content": "{}", "is_error": True}
    assert msgs[3]["content"] == [{"type": "text", "text": "done"}]


@pytest.mark.parametrize("raw, expected", [('{"sku": "A"}', {"sku": "A"}), ("", {}), (None, {}),
                                           ("{bad", "{bad"), ("[1, 2]", [1, 2]), ({"a": 1}, {"a": 1})])
def test_argument_parsing_never_guesses(raw, expected):
    assert parse_arguments(raw) == expected


# ---------------------------------------------------------------- OpenAI-compatible adapter conformance

def test_openai_adapter_tool_call_usage_and_provider_cost(or_settings):
    llm, comp = oa_llm(or_settings, [oa_resp("", [("t1", "get_order_status", "{}")], "tool_calls", cost=0.0)])
    r = llm.create("SYS", TOOL_SPECS, [UserTurn("hi")], remaining_s=9.0)
    assert (r.stop_reason, r.tool_calls[0].name, r.tool_calls[0].input) == ("tool_use", "get_order_status", {})
    assert (r.input_tokens, r.output_tokens, r.provider_cost_usd) == (900, 60, 0.0)
    sent = comp.calls[0]
    assert sent["model"] == "google/gemma-4-31b-it:free" and sent["extra_body"] == {"usage": {"include": True}}
    assert sent["messages"][0] == {"role": "system", "content": "SYS"} and len(sent["tools"]) == 11
    assert llm.client.timeouts == [3.0]  # 9s remaining / (1 + 2 retries)


def test_openai_adapter_tool_calls_with_stop_finish_reason_still_tool_use(or_settings):
    llm, _ = oa_llm(or_settings, [oa_resp("", [("t1", "flag_duplicates", "{}")], "stop")])
    assert llm.create("S", TOOL_SPECS, [UserTurn("x")]).stop_reason == "tool_use"


def test_openai_adapter_malformed_arguments_reach_validator_as_raw(or_settings):
    llm, _ = oa_llm(or_settings, [oa_resp("", [("t1", "commit_ready", "{not json")], "tool_calls")])
    assert llm.create("S", TOOL_SPECS, [UserTurn("x")]).tool_calls[0].input == "{not json"


@pytest.mark.parametrize("resp, kind", [
    (oa_resp("cut", finish="length"), "MAX_TOKENS"),
    (oa_resp("", finish="content_filter"), "REFUSAL"),
    (oa_resp("", finish="weird"), "UNEXPECTED_STOP"),
    (oa_resp(choices=False), "SERVER"),
])
def test_openai_adapter_unusable_responses_fail_closed(or_settings, resp, kind):
    llm, _ = oa_llm(or_settings, [resp])
    with pytest.raises(LLMError) as e:
        llm.create("S", TOOL_SPECS, [UserTurn("x")])
    assert e.value.kind == kind


_REQ = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def _status(cls, code, msg="err"):
    return cls(msg, response=httpx2.Response(code, request=_REQ), body=None)


@pytest.mark.parametrize("exc, kind", [
    (openai.APITimeoutError(request=_REQ), "TIMEOUT"),
    (openai.APIConnectionError(request=_REQ), "CONNECTION"),
    (_status(openai.AuthenticationError, 401), "AUTH"),
    (_status(openai.PermissionDeniedError, 403), "AUTH"),
    (_status(openai.RateLimitError, 429), "RATE_LIMIT"),
    (_status(openai.NotFoundError, 404, "model not found"), "NOT_FOUND"),
    (_status(openai.NotFoundError, 404, "No endpoints found that support tool use"), "UNSUPPORTED_CAPABILITY"),
    (_status(openai.BadRequestError, 400, "tools are not supported by this model"), "UNSUPPORTED_CAPABILITY"),
    (_status(openai.BadRequestError, 400, "invalid messages"), "BAD_REQUEST"),
    (_status(openai.InternalServerError, 502), "SERVER"),
])
def test_openai_adapter_maps_sdk_errors(or_settings, exc, kind):
    llm, _ = oa_llm(or_settings, exc=exc)
    with pytest.raises(LLMError) as e:
        llm.create("S", TOOL_SPECS, [UserTurn("x")])
    assert e.value.kind == kind


def test_openai_client_built_from_profile_with_bounded_retries(or_settings, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-placeholder-not-a-key")
    llm = build_provider(or_settings)
    assert isinstance(llm, OpenAICompatibleLLM)
    assert str(llm.client.base_url).startswith("https://openrouter.ai/api/v1")
    assert llm.client.max_retries == 2 and llm.client.timeout == 30


def test_registry_and_anthropic_adapter_preserved(settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder-not-a-key")
    assert set(REGISTRY) == {"anthropic", "openai_compatible"}
    assert isinstance(build_provider(settings), AnthropicLLM)


# ---------------------------------------------------------------- end-to-end through the runtime (fake client)

def test_runtime_with_openai_adapter_records_provider_cost_and_free_basis(seeded, or_settings):
    ctx = ToolContext(seeded, or_settings, clock=lambda: FIXED_NOW)
    llm, comp = oa_llm(or_settings, [
        oa_resp("", [("call_a", "request_confirmation", "{}")], "tool_calls", prompt=2500, completion=40, cost=0.0),
        oa_resp("Sent summary.", None, "stop", prompt=2900, completion=20, cost=0.0)])
    r = handle_event(ctx, llm, "ORD-1001", "EVT-OR-1", "عايزة أأكد الأوردر")
    assert (r["provider"], r["profile"], r["cost_basis"]) == ("openai_compatible", OR, "VERIFIED_FREE_MODEL")
    assert (r["cost_usd"], r["provider_cost_usd"], r["input_tokens"], r["output_tokens"]) == (0, 0.0, 5400, 60)
    assert r["messages_sent"][0]["kind"] == "CONFIRMATION_REQUEST"
    second = comp.calls[1]["messages"]
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "call_a"
    run = seeded.execute("SELECT provider, model, cost_basis, provider_cost_usd FROM agent_runs").fetchone()
    assert tuple(run) == ("openai_compatible", "google/gemma-4-31b-it:free", "VERIFIED_FREE_MODEL", 0.0)


def test_runtime_known_pricing_profile_estimates_locally_without_provider_cost(seeded, settings):
    from cod_rescue.agent.providers.anthropic_provider import AnthropicLLM as A

    class FakeMsgs:
        def create(self, **kw):
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="ok")],
                                   usage=SimpleNamespace(input_tokens=1000, output_tokens=100))
    client = SimpleNamespace(messages=FakeMsgs(), with_options=lambda **k: client)
    r = handle_event(ToolContext(seeded, settings, clock=lambda: FIXED_NOW), A(settings, client=client),
                     "ORD-1001", "EVT-AN-1", "مرحبا")
    assert r["cost_basis"] == "ESTIMATED_FROM_TOKEN_USAGE" and r["provider_cost_usd"] is None
    assert r["cost_usd"] == pytest.approx((1000 * 0.10 + 100 * 0.50) / 1e6)


# ---------------------------------------------------------------- profiles & pricing configuration

def test_profile_switching_is_independent_of_mode(settings, or_settings):
    assert (settings.llm.provider, settings.llm.model) == ("anthropic", "claude-haiku-5-5")
    assert (or_settings.llm.provider, or_settings.llm.model) == ("openai_compatible", "google/gemma-4-31b-it:free")
    assert or_settings.llm.profile.pricing.status == "verified_free" and model_pricing(or_settings).input == 0


def test_cli_profile_flag_switches_provider(capsys):
    import cod_rescue.__main__ as cli
    assert cli.main(["--profile", OR, "--db", ":memory:", "status"]) == 0
    assert "openrouter-gemma-free (openai_compatible/google/gemma-4-31b-it:free)" in capsys.readouterr().out
    assert cli.main(["--profile", "nope", "status"]) == 2


def _with_profile(tmp_path, block):
    text = DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8") + "\n" + block
    p = tmp_path / "s.toml"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize("block, message", [
    ('[llm.profiles.x]\nprovider="openai_compatible"\nbase_url="https://e.com/v1"\nmodel="m"\napi_key_env="X_KEY"\n'
     'pricing="known"\nprice_input_per_mtok=0.0\nprice_output_per_mtok=0.0\n', "verified_free"),
    ('[llm.profiles.x]\nprovider="openai_compatible"\nbase_url="https://e.com/v1"\nmodel="m"\napi_key_env="X_KEY"\n'
     'pricing="verified_free"\nprice_input_per_mtok=0.1\nprice_output_per_mtok=0.0\npricing_source="s"\n', "both prices = 0"),
    ('[llm.profiles.x]\nprovider="openai_compatible"\nbase_url="https://e.com/v1"\nmodel="m"\napi_key_env="X_KEY"\n'
     'pricing="verified_free"\nprice_input_per_mtok=0.0\nprice_output_per_mtok=0.0\n', "pricing_source"),
    ('[llm.profiles.x]\nprovider="openai_compatible"\nbase_url="https://e.com/v1"\nmodel="m"\napi_key_env="X_KEY"\n'
     'pricing="unknown"\nprice_input_per_mtok=0.0\n', "must not set prices"),
    ('[llm.profiles.x]\nprovider="openai_compatible"\nbase_url="http://evil.example/v1"\nmodel="m"\napi_key_env="X_KEY"\n', "https"),
    ('[llm.profiles.x]\nprovider="openai_compatible"\nbase_url="https://e.com/v1"\nmodel="m"\napi_key_env="sk-or-abc123"\n', "NAME"),
    ('[llm.profiles.x]\nprovider="gemini_direct"\nmodel="m"\napi_key_env="X_KEY"\n', "provider must be"),
    ('[llm.profiles.x]\nprovider="anthropic"\nmodel="m"\napi_key_env="X_KEY"\napi_key="secret"\n', "unknown keys"),
])
def test_invalid_profiles_rejected(tmp_path, block, message):
    with pytest.raises(ConfigError, match=message):
        load_settings(_with_profile(tmp_path, block), env={})


def test_missing_pricing_is_unknown_never_free(tmp_path):
    block = '[llm.profiles.x]\nprovider="openai_compatible"\nbase_url="http://localhost:8000/v1"\nmodel="m"\napi_key_env="X_KEY"\n'
    s = load_settings(_with_profile(tmp_path, block), env={"COD_RESCUE_LLM_PROFILE": "x"})
    assert s.llm.profile.pricing.status == "unknown"
    with pytest.raises(ConfigError, match="never treated as free"):
        model_pricing(s)


def test_dotenv_loads_only_profile_key_names(tmp_path, or_settings):
    from cod_rescue.config import allowed_env_keys
    f = tmp_path / ".env"
    f.write_text("OPENROUTER_API_KEY=test-not-real\nAWS_SECRET_ACCESS_KEY=nope\n", encoding="utf-8")
    env = {}
    load_dotenv(f, env, allowed_env_keys(or_settings))
    assert env == {"OPENROUTER_API_KEY": "test-not-real"}


# ---------------------------------------------------------------- capability & pricing checks (fake listing)

def _listing(model="google/gemma-4-31b-it:free", prompt="0", completion="0", params=("tools", "tool_choice")):
    return lambda url, **k: {"data": [{"id": model, "pricing": {"prompt": prompt, "completion": completion},
                                       "supported_parameters": list(params), "context_length": 262144}]}


def test_check_profile_free_model_declared_tools(or_settings, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-placeholder-not-a-key")
    r = check_profile(or_settings, or_settings.llm.profile, fetch=_listing())
    assert (r["model_listed"], r["tool_support"], r["pricing_check"], r["live_ready"]) == (
        True, "declared", "zero price confirmed", True)
    assert "test-placeholder" not in json.dumps(r)


@pytest.mark.parametrize("fetch, problem", [
    (_listing(prompt="0.0000002"), "configured verified_free"),
    (_listing(params=("temperature",)), "does not declare tool calling"),
    (_listing(model="other/model"), "not listed"),
])
def test_check_profile_detects_problems(or_settings, monkeypatch, fetch, problem):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-placeholder-not-a-key")
    r = check_profile(or_settings, or_settings.llm.profile, fetch=fetch)
    assert not r["live_ready"] and any(problem in p for p in r["problems"])


def test_check_profile_requires_key(or_settings, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = check_profile(or_settings, or_settings.llm.profile, fetch=_listing())
    assert r["key_present"] is False and not r["live_ready"]


def test_live_preflight_refuses_when_listing_not_free(or_settings, monkeypatch):
    import cod_rescue.__main__ as cli
    import cod_rescue.agent.providers.capabilities as caps
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-placeholder-not-a-key")
    monkeypatch.setattr(caps, "_get_json", _listing(prompt="0.000001"))
    with pytest.raises(ConfigError, match="failed preflight"):
        cli._require_live(or_settings)


# ---------------------------------------------------------------- result separation

def test_results_are_separated_by_mode_provider_and_model(settings, or_settings):
    assert results_dir(settings, "REPLAY").parts[-1] == "replay"
    assert results_dir(settings, "LIVE").parts[-3:] == ("live", "anthropic", "claude-haiku-5-5")
    assert results_dir(or_settings, "LIVE").parts[-3:] == ("live", "openai_compatible", "google_gemma-4-31b-it_free")


# ---------------------------------------------------------------- structured, sanitized error diagnostics

from cod_rescue.agent.providers.base import sanitize  # noqa: E402

FAKE_KEY = "sk-or-v1-0123456789abcdefFAKEFAKE"
S01_BODY = {"error": {"message": "Provider returned error", "code": 429, "metadata": {
    "raw": f"google/gemma-4-31b-it:free is temporarily rate-limited upstream. debug key={FAKE_KEY}",
    "provider_name": "Google AI Studio"}}}


def test_openrouter_429_from_s01_yields_structured_sanitized_fields(or_settings):
    exc = openai.RateLimitError("Error code: 429", body=S01_BODY,
                                response=httpx2.Response(429, request=_REQ, headers={"retry-after": "7"}))
    llm, _ = oa_llm(or_settings, exc=exc)
    with pytest.raises(LLMError) as e:
        llm.create("S", TOOL_SPECS, [UserTurn("x")])
    d = e.value.diagnostics()
    assert (d["error_kind"], d["http_status"], d["provider_error_code"], d["upstream_provider"], d["retry_after"]) == (
        "RATE_LIMIT", 429, 429, "Google AI Studio", "7")
    assert "rate-limited upstream" in d["detail"] and FAKE_KEY not in json.dumps(d)


def test_anthropic_status_error_fields(settings):
    from tests.test_slice3_runtime import _FakeClient, _FakeMessages
    body = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
    exc = anthropic_sdk().InternalServerError("Overloaded", body=body,
                                              response=httpx2.Response(529, request=_REQ))
    llm = AnthropicLLM(settings, client=_FakeClient(_FakeMessages(exc=exc)))
    with pytest.raises(LLMError) as e:
        llm.create("S", [], [])
    d = e.value.diagnostics()
    assert (d["error_kind"], d["http_status"], d["provider_error_code"], d["upstream_provider"]) == (
        "SERVER", 529, "overloaded_error", None)


def anthropic_sdk():
    import anthropic
    return anthropic


def test_auth_error_names_the_env_var_never_the_key(or_settings, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    exc = openai.AuthenticationError("bad key", body={"error": {"message": f"Invalid key {FAKE_KEY}", "code": 401}},
                                     response=httpx2.Response(401, request=_REQ))
    llm, _ = oa_llm(or_settings, exc=exc)
    with pytest.raises(LLMError) as e:
        llm.create("S", TOOL_SPECS, [UserTurn("x")])
    assert e.value.kind == "AUTH" and "OPENROUTER_API_KEY" in e.value.detail and FAKE_KEY not in e.value.detail


@pytest.mark.parametrize("raw", [
    "Authorization: Bearer abc.def.ghi", "sk-ant-api03-AAAAAAAAAAAAAAAA", f"key {FAKE_KEY}",
    "hf_AbCdEfGhIjKlMnOpQrStUv", 'api_key="supersecretvalue1"', "x-api-key: zzzzzzzzzzzzzzzz",
])
def test_sanitize_masks_credentials(raw):
    out = sanitize(raw)
    assert "[REDACTED]" in out
    for secret in ("abc.def.ghi", "AAAAAAAAAAAAAAAA", "0123456789abcdefFAKEFAKE", "AbCdEfGhIjKlMnOpQrStUv",
                   "supersecretvalue1", "zzzzzzzzzzzzzzzz"):
        assert secret not in out
    assert len(sanitize("x" * 5000)) == 1000


def test_runtime_records_structured_llm_error_and_still_fails_closed(seeded, settings):
    from cod_rescue.agent.providers.replay import ReplayLLM
    ctx = ToolContext(seeded, settings, clock=lambda: FIXED_NOW)
    script = [{"error": "RATE_LIMIT", "http_status": 429, "provider_error_code": 429,
               "upstream_provider": "Google AI Studio", "retry_after": "7",
               "message": f"temporarily rate-limited upstream {FAKE_KEY}"}]
    r = handle_event(ctx, ReplayLLM(script), "ORD-1001", "EVT-DIAG", "تمام")
    assert (r["error_class"], r["error_kind"], r["outcome"]) == ("LLM_ERROR", "RATE_LIMIT", "ESCALATE_TO_HUMAN")
    assert r["llm_error"] == {"error_kind": "RATE_LIMIT", "http_status": 429, "provider_error_code": 429,
                              "upstream_provider": "Google AI Studio", "retry_after": "7"}
    assert seeded.execute("SELECT lifecycle_state FROM orders WHERE order_id='ORD-1001'").fetchone()[0] == "PENDING"
    stored = " ".join(str(tuple(x)) for x in seeded.execute("SELECT * FROM agent_steps")) + str(
        tuple(seeded.execute("SELECT * FROM agent_runs").fetchone()))
    assert "Google AI Studio" in stored and "429" in stored and FAKE_KEY not in stored and FAKE_KEY not in json.dumps(r)


def test_backup_profile_is_separate_and_defaults_unchanged(settings):
    nemo = settings.llm.profiles["openrouter-nemotron-free"]
    gemma = settings.llm.profiles["openrouter-gemma-free"]
    assert settings.llm.active_profile == "anthropic-haiku"
    assert (nemo.provider, nemo.model, nemo.pricing.status) == (
        "openai_compatible", "nvidia/nemotron-3-super-120b-a12b:free", "verified_free")
    assert gemma.model == "google/gemma-4-31b-it:free" and gemma.pricing.status == "verified_free"
    assert results_dir(load_settings(env={"COD_RESCUE_LLM_PROFILE": "openrouter-nemotron-free"}), "LIVE").parts[-2:] == (
        "openai_compatible", "nvidia_nemotron-3-super-120b-a12b_free")
