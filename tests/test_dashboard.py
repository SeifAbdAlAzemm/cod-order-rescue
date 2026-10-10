"""Dashboard: service-layer tests and a headless Streamlit smoke test. No network, no LIVE calls."""

import dataclasses
import json
import os
import sqlite3
from pathlib import Path

import pytest

from cod_rescue import PROJECT_ROOT
from cod_rescue import dashboard_service as svc
from cod_rescue.agent.providers.capabilities import key_destination
from cod_rescue.config import DEFAULT_SETTINGS_PATH, load_settings

FAKE_KEY = "sk-or-v1-dashboardtestkeyFAKEFAKE0000"


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("COD_RESCUE_DB_PATH", str(tmp_path / "demo.sqlite3"))
    monkeypatch.setenv("COD_RESCUE_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.delenv(svc.ENV_KEYS_FLAG, raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


def _listing(url, **_):
    return {"data": [{"id": m, "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools"]}
                     for m in ("google/gemma-4-31b-it:free", "nvidia/nemotron-3-super-120b-a12b:free")]}


# ---------------------------------------------------------------- Judge Lab services

def test_replay_scenario_runs_isolated_and_passes(isolated_paths):
    s = svc.settings_for()
    res = svc.run_scenario_ui(s, "S01", "REPLAY")
    assert res["ok"] and res["report"]["scenarios"][0]["passed"] and res["report"]["mode"] == "REPLAY"
    assert Path(res["report"]["results_path"]).is_relative_to(isolated_paths / "results")
    assert not Path(os.environ["COD_RESCUE_DB_PATH"]).exists()  # demo DB untouched by evaluations
    assert svc.load_result_history()[0]["scenarios"][0]["id"] == "S01"


def test_live_is_refused_without_a_key_and_makes_no_call(monkeypatch):
    s = svc.settings_for("openrouter-nemotron-free")
    monkeypatch.setattr(svc, "build_provider", lambda *a, **k: pytest.fail("provider must not be built"))
    res = svc.run_scenario_ui(s, "S01", "LIVE", ui_key=None, fetch=_listing)
    assert not res["ok"] and "preflight" in res
    assert any("enter an API key" in p for p in res["preflight"]["problems"])


def test_replay_only_scenarios_cannot_run_live():
    res = svc.run_scenario_ui(svc.settings_for("openrouter-nemotron-free"), "S19", "LIVE", ui_key=FAKE_KEY)
    assert not res["ok"] and "only runs in REPLAY" in res["error"]


def test_developer_env_key_not_used_unless_explicitly_enabled(monkeypatch):
    s = svc.settings_for("openrouter-nemotron-free")
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    assert svc.resolve_key(s, None) is None
    monkeypatch.setenv(svc.ENV_KEYS_FLAG, "1")
    assert svc.resolve_key(s, None) == FAKE_KEY


def test_ui_key_is_memory_only_never_env_db_or_results(isolated_paths, monkeypatch):
    s = svc.settings_for("openrouter-nemotron-free")
    captured = {}
    from cod_rescue.agent.providers.replay import ReplayLLM

    class FakeLive(ReplayLLM):
        mode, provider = "LIVE", "openai_compatible"

        def __init__(self, settings, api_key=None):
            captured["key"] = api_key
            super().__init__([{"tool_calls": [{"name": "request_confirmation", "input": {}}]}, {"text": "done"}])
            self.profile, self.model = settings.llm.profile, settings.llm.model

    monkeypatch.setattr(svc, "build_provider", lambda settings, api_key=None: FakeLive(settings, api_key))
    pre = svc.live_preflight(s, FAKE_KEY, fetch=_listing)
    assert pre["live_ready"] and pre["key_source"] == "dashboard (memory only)" and FAKE_KEY not in json.dumps(pre)
    monkeypatch.setattr(svc, "live_preflight", lambda *a, **k: pre)
    res = svc.run_scenario_ui(s, "S01", "LIVE", ui_key=FAKE_KEY)
    assert res["ok"] and captured["key"] == FAKE_KEY
    assert "OPENROUTER_API_KEY" not in os.environ
    blob = json.dumps(res, default=str)
    for f in (isolated_paths / "results").rglob("*"):
        if f.is_file():
            blob += f.read_bytes().decode("latin-1")
    assert FAKE_KEY not in blob


def test_untrusted_endpoints_never_receive_keys(tmp_path):
    block = ('\n[llm.profiles.evil]\nprovider="openai_compatible"\nbase_url="https://attacker.example/v1"\nmodel="m"\n'
             'api_key_env="X_KEY"\npricing="known"\nprice_input_per_mtok=1.0\nprice_output_per_mtok=1.0\n'
             '[llm.profiles.local]\nprovider="openai_compatible"\nbase_url="http://localhost:9000/v1"\nmodel="m"\n'
             'api_key_env="X_KEY"\npricing="known"\nprice_input_per_mtok=1.0\nprice_output_per_mtok=1.0\n')
    f = tmp_path / "s.toml"
    f.write_text(DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8") + block, encoding="utf-8")
    s = load_settings(f, env={})
    for name in ("evil", "local"):
        assert key_destination(s.llm.profiles[name])[1] is False
    from cod_rescue.agent.providers.openai_compatible import OpenAICompatibleLLM
    llm = OpenAICompatibleLLM(s, s.llm.profiles["evil"], api_key=FAKE_KEY)
    assert llm.client.api_key != FAKE_KEY  # placeholder sent, never the real key
    evil = dataclasses.replace(s, llm=dataclasses.replace(s.llm, active_profile="evil"))
    pre = svc.live_preflight(evil, FAKE_KEY, fetch=_listing)
    assert not pre["live_ready"] and any("allowlisted" in p for p in pre["problems"])
    for name in ("anthropic-haiku", "openrouter-gemma-free", "openrouter-nemotron-free"):
        assert key_destination(s.llm.profiles[name])[1] is True


def test_anthropic_endpoint_is_explicit_so_env_base_url_cannot_redirect(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://attacker.example")
    from cod_rescue.agent.providers.anthropic_provider import AnthropicLLM
    llm = AnthropicLLM(load_settings(env={}), api_key=FAKE_KEY)
    assert str(llm.client.base_url).startswith("https://api.anthropic.com")


def test_explanations_for_safety_blocks():
    e = svc.explain_tool_output(json.dumps({"ok": False, "status": "AMBIGUOUS_REPLY"}))
    assert e["ok"] is False and "BR-04" in e["explanation"]
    r = svc.explain_tool_output(json.dumps({"ok": False, "status": "REFUSED", "reasons": ["CONFIRMATION_REQUIRED"]}))
    assert "CONFIRMATION_REQUIRED" in r["explanation"]
    assert svc.explain_tool_output("not json")["status"] == "UNPARSEABLE"


def test_evidence_matrix_separates_tests_replay_and_live():
    reports = [{"mode": "REPLAY", "run_at": "1", "model": "replay-script", "scenarios": [{"id": "S14", "passed": True}]},
               {"mode": "LIVE", "run_at": "2", "model": "m-live", "scenarios": [{"id": "S11", "passed": True}]}]
    rows = {r["Safeguard"]: r for r in svc.evidence_matrix(reports)}
    assert "S14 PASS" in rows["Idempotent events & commit"]["Replay scenarios"]
    assert rows["Idempotent events & commit"]["Live evidence"] == "not run"
    assert "S11 PASS (m-live)" in rows["Duplicate-order safeguards"]["Live evidence"]
    assert rows["Fail-closed errors (API, malformed, budget)"]["Live evidence"] == "not live-testable"


def test_fresh_clone_has_empty_history():
    assert svc.load_result_history() == [] and svc.metric_rows([]) == []


# ---------------------------------------------------------------- Business Owner / Operator services

def test_demo_db_gate_create_snapshot_and_refuse_foreign_db(isolated_paths):
    s = svc.settings_for()
    assert svc.demo_db_status(s.db_path)["ready"] is False
    assert svc.create_or_reset_demo_db(s, s.db_path)["ok"]
    snap = svc.business_snapshot(s.db_path)
    assert sum(r["orders"] for r in snap["lifecycle"]) == 15 and snap["runs"] == []
    foreign = isolated_paths / "foreign.sqlite3"
    c = sqlite3.connect(foreign)
    c.execute("CREATE TABLE t(x)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()
    assert svc.demo_db_status(foreign)["ready"] is False
    assert svc.create_or_reset_demo_db(s, foreign)["ok"] is False


def test_operator_replay_message_and_idempotent_redelivery():
    s = svc.settings_for()
    svc.create_or_reset_demo_db(s, s.db_path)
    opt = next(o for o in svc.replay_options("ORD-1007") if o["label"].startswith("S07"))
    first = svc.submit_message(s, s.db_path, "ORD-1007", opt["text"], "REPLAY", replay_script=opt["script"])
    assert first["ok"] and first["result"]["outcome"] == "READY_FOR_DISPATCH" and first["steps"]
    again = svc.submit_message(s, s.db_path, "ORD-1007", opt["text"], "REPLAY", replay_script=opt["script"],
                               event_id=first["event_id"])
    assert again["result"]["replayed_from_saved_result"] and again["steps"] == []
    snap = svc.business_snapshot(s.db_path)
    assert len(snap["runs"]) == 1 and snap["usage"][0]["mode"] == "REPLAY"
    assert svc.order_view(s.db_path, "ORD-1007")["order"]["lifecycle_state"] == "READY_FOR_DISPATCH"


def test_operator_replay_refuses_free_text():
    s = svc.settings_for()
    svc.create_or_reset_demo_db(s, s.db_path)
    res = svc.submit_message(s, s.db_path, "ORD-1001", "free text", "REPLAY", replay_script=None)
    assert not res["ok"] and "predefined" in res["error"]


# ---------------------------------------------------------------- headless UI smoke test

def test_dashboard_renders_and_runs_replay_without_api_key():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(PROJECT_ROOT / "dashboard" / "app.py"), default_timeout=120).run()
    assert not at.exception
    next(b for b in at.button if b.label == "Run scenario").click().run()
    assert not at.exception
    assert any('class="verdict-pass"' in m.value for m in at.markdown)
    assert any("SAVED LIVE EVIDENCE" in m.value for m in at.markdown)  # visible without any key
    for view in ["📊 Business Owner", "🛠️ Operator Workspace", "🚀 Future Enhancements"]:
        at.sidebar.radio[0].set_value(view).run()
        assert not at.exception, view
    assert any("Not implemented" in m.value for m in at.markdown)


# ---------------------------------------------------------------- saved LIVE evidence (version-controlled)

def test_saved_live_evidence_is_consistent_and_labelled():
    [ev] = svc.load_saved_live_evidence()
    assert ev["evidence_type"] == "SAVED_LIVE_EVIDENCE" and "NOT a new LIVE execution" in ev["notice"]
    assert ev["model"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert [(s["id"], s["passed"]) for s in ev["scenarios"]] == [("S01", True), ("S02", True), ("S11", True)]
    events = [e for s in ev["scenarios"] for e in s["events"]]
    t = ev["totals"]
    assert t["events"] == len(events) == 7
    assert t["model_calls"] == sum(e["model_calls"] for e in events) == 22
    assert (t["input_tokens"], t["output_tokens"]) == (71610, 4172)
    assert t["model_time_ms_total"] == sum(sum(e["model_call_latencies_ms"]) for e in events)
    assert all(len(e["model_call_latencies_ms"]) == e["model_calls"] for e in events)
    assert any("Only three selected scenarios" in x for x in ev["limitations"])


def test_saved_live_evidence_contains_no_secrets_paths_or_pii():
    import re
    raw = (PROJECT_ROOT / "evidence" / "live" / "nemotron-3-super-free_2026-10-10.json").read_text(encoding="utf-8")
    raw += (PROJECT_ROOT / "docs" / "LIVE-EVIDENCE.md").read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]|/Users/|AppData|sk-[a-z]{0,8}-?[A-Za-z0-9]{12,}|(?i:bearer)|API_KEY|run-[0-9a-f]{12}", raw)
    assert "العنوان:" not in raw and "عميل تجريبي" not in raw  # addresses/names omitted


def test_saved_live_evidence_visible_in_fresh_clone_and_separate_from_replay():
    assert svc.load_result_history() == []  # fresh clone: no local results
    saved = svc.saved_evidence_as_reports(svc.load_saved_live_evidence())
    rows = {r["Safeguard"]: r for r in svc.evidence_matrix(saved)}
    assert "S11 PASS (nvidia/nemotron-3-super-120b-a12b:free · saved)" in rows["Duplicate-order safeguards"]["Live evidence"]
    assert "not run" in rows["Duplicate-order safeguards"]["Replay scenarios"]  # saved LIVE never counted as REPLAY
    assert svc.metric_rows(svc.load_result_history()) == []
