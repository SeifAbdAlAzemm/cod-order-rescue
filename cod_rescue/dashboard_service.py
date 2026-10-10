"""Service layer for the COD Rescue Control Center dashboard (Streamlit UI calls only these functions).

It reuses the existing backend: evaluation engine (isolated per-scenario databases), agent runtime,
guarded tools, provider factory and synthetic seed. It contains no business rules of its own.

Credential handling: a key typed into the dashboard lives only in the caller's memory (Streamlit
session state) and is passed per invocation to the provider factory. It is never written to the
environment, SQLite, files, logs, URLs or results. Developer keys from the environment/.env are NOT
used by the dashboard unless COD_RESCUE_DASHBOARD_USE_ENV_KEYS=1 is set by the person running it.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from cod_rescue import PROJECT_ROOT
from cod_rescue.agent.evaluation import FIXED_CLOCK, _with_faults, load_scenarios, results_root, run_suite
from cod_rescue.agent.providers import build_provider
from cod_rescue.agent.providers.base import sanitize
from cod_rescue.agent.providers.capabilities import check_profile, key_destination
from cod_rescue.agent.providers.replay import ReplayLLM
from cod_rescue.agent.runtime import handle_event
from cod_rescue.config import ConfigError, Settings, allowed_env_keys, load_dotenv, load_settings, model_pricing
from cod_rescue.context import ToolContext
from cod_rescue.db import SCHEMA_VERSION, connect, schema_version, table_names
from cod_rescue.seed import SeedError, is_synthetic_demo_db, seed

ENV_KEYS_FLAG = "COD_RESCUE_DASHBOARD_USE_ENV_KEYS"


# ---------------------------------------------------------------- settings & credentials

def settings_for(profile_name: str | None = None) -> Settings:
    s = load_settings()
    if profile_name and profile_name in s.llm.profiles:
        s = dataclasses.replace(s, llm=dataclasses.replace(s.llm, active_profile=profile_name))
    return s


def profile_summaries(settings: Settings) -> list[dict]:
    out = []
    for p in settings.llm.profiles.values():
        url, trusted = key_destination(p)
        out.append({"name": p.name, "provider": p.provider, "model": p.model, "pricing": p.pricing.status,
                    "endpoint": url or "(provider default)", "endpoint_trusted": trusted, "key_env": p.api_key_env})
    return out


def env_keys_allowed() -> bool:
    return os.environ.get(ENV_KEYS_FLAG) == "1"


def resolve_key(settings: Settings, ui_key: str | None) -> str | None:
    """Key for one invocation: the dashboard-entered key, or (only if explicitly allowed) the developer's env key."""
    if ui_key and ui_key.strip():
        return ui_key.strip()
    if env_keys_allowed():
        load_dotenv(allowed=allowed_env_keys(settings))
        return os.environ.get(settings.llm.profile.api_key_env)
    return None


def live_preflight(settings: Settings, ui_key: str | None, fetch=None) -> dict:
    """Non-billable checks before any LIVE call. Never returns or displays the key."""
    profile = settings.llm.profile
    key = resolve_key(settings, ui_key)
    report = check_profile(settings, profile, fetch=fetch, api_key=key)
    try:
        model_pricing(settings, profile)
    except ConfigError as e:
        if str(e) not in report["problems"]:
            report["problems"].append(str(e))
    if not key:
        report["problems"] = [p for p in report["problems"] if "not set" not in p]
        report["problems"].append("enter an API key for this profile (kept in memory for this session only)")
    report["live_ready"] = not report["problems"]
    report["key_source"] = ("dashboard (memory only)" if ui_key and ui_key.strip()
                            else "developer environment" if key else "none")
    return report


# ---------------------------------------------------------------- scenarios & evaluation

def list_scenarios() -> list[dict]:
    return [{"id": s["id"], "title": s["title"], "test_cases": s.get("test_cases", []), "live": s.get("live", True),
             "events": [{"order_id": e["order_id"], "text": e["text"], "event_id": e["event_id"]} for e in s["events"]],
             "faults": s.get("setup", {}).get("faults", {})}
            for s in load_scenarios()]


def run_scenario_ui(settings: Settings, scenario_id: str, mode: str, ui_key: str | None = None,
                    out_dir: Path | None = None, fetch=None) -> dict:
    """Run ONE scenario on an isolated database (never the demo DB). LIVE requires a passing preflight."""
    mode = mode.upper()
    scenario = next((s for s in load_scenarios() if s["id"] == scenario_id), None)
    if scenario is None:
        return {"ok": False, "error": f"unknown scenario {scenario_id}"}
    factory = None
    if mode == "LIVE":
        if not scenario.get("live", True):
            return {"ok": False, "error": f"{scenario_id} simulates model/API failures and only runs in REPLAY"}
        pre = live_preflight(settings, ui_key, fetch=fetch)
        if not pre["live_ready"]:
            return {"ok": False, "error": "LIVE preflight failed", "preflight": pre}
        key = resolve_key(settings, ui_key)
        factory = lambda s: build_provider(s, api_key=key)  # noqa: E731 - key captured in memory only
    try:
        report = run_suite(settings, mode, [scenario_id], out_dir=out_dir, live_llm_factory=factory)
    except Exception as e:  # never surface stack traces or secrets to visitors
        return {"ok": False, "error": f"run failed: {type(e).__name__}: {sanitize(e, 300)}"}
    return {"ok": True, "report": report}


def load_result_history(results_dir: Path | None = None) -> list[dict]:
    """All persisted evaluation reports (timestamped files), newest first. Empty in a fresh clone."""
    results_dir = results_dir or results_root()
    reports = []
    for f in sorted(results_dir.glob("**/eval-*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        r["_file"] = str(f.relative_to(results_dir))
        reports.append(r)
    return sorted(reports, key=lambda r: r.get("run_at", ""), reverse=True)


def metric_rows(reports: list[dict]) -> list[dict]:
    rows = []
    for r in reports:
        for s in r.get("scenarios", []):
            for i, e in enumerate(s.get("events", []), start=1):
                res = e.get("result", {})
                if res.get("replayed_from_saved_result") or "run_id" not in res:
                    continue
                rows.append({
                    "source": f"{str(r.get('mode', '')).title()} · local run", "event_label": f"{s['id']}·{i}",
                    "run_at": r.get("run_at"), "mode": r.get("mode"), "provider": r.get("provider"),
                    "model": r.get("model"), "scenario": s["id"], "scenario_passed": s.get("passed"),
                    "event": e.get("event"), "llm_calls": res.get("llm_calls", 0), "tool_calls": res.get("tool_calls", 0),
                    "input_tokens": res.get("input_tokens", 0), "output_tokens": res.get("output_tokens", 0),
                    "latency_ms": res.get("latency_ms"), "estimated_cost_usd": res.get("cost_usd"),
                    "provider_cost_usd": res.get("provider_cost_usd"), "cost_basis": res.get("cost_basis"),
                    "error_kind": res.get("error_kind"), "outcome": res.get("outcome"),
                })
    return rows


def saved_metric_rows(saved: list[dict]) -> list[dict]:
    """Per-event rows from SAVED LIVE EVIDENCE, same columns as metric_rows (values copied, never recomputed)."""
    rows = []
    for ev in saved:
        for s in ev.get("scenarios", []):
            for i, e in enumerate(s.get("events", []), start=1):
                rows.append({
                    "source": "Live · saved evidence", "event_label": f"{s['id']}·{i}",
                    "run_at": s.get("recorded_at"), "mode": "LIVE", "provider": "openai_compatible",
                    "model": ev.get("model"), "scenario": s["id"], "scenario_passed": s.get("passed"),
                    "event": e["event_id"], "llm_calls": e["model_calls"], "tool_calls": e["tool_calls"],
                    "input_tokens": e["input_tokens"], "output_tokens": e["output_tokens"],
                    "latency_ms": e["run_latency_ms"], "estimated_cost_usd": e["estimated_cost_usd"],
                    "provider_cost_usd": e["provider_reported_cost_usd"], "cost_basis": e["cost_basis"],
                    "error_kind": e.get("error_kind"), "outcome": e["outcome"],
                })
    return rows


def combined_metric_rows(reports: list[dict], saved: list[dict]) -> list[dict]:
    """Saved LIVE evidence + local runs. A local LIVE run identical to a saved one (same model, scenario,
    event and run time) is dropped so the same measurement is never counted twice."""
    saved_rows = saved_metric_rows(saved)
    keys = {(r["model"], r["scenario"], r["event"], r["run_at"]) for r in saved_rows}
    local = [r for r in metric_rows(reports)
             if not (r["mode"] == "LIVE" and (r["model"], r["scenario"], r["event"], r["run_at"]) in keys)]
    return saved_rows + local


def scenario_rows(reports: list[dict]) -> list[dict]:
    return [{"run_at": r.get("run_at"), "mode": r.get("mode"), "provider": r.get("provider"), "model": r.get("model"),
             "scenario": s["id"], "title": s.get("title"), "passed": s.get("passed"),
             "failures": len(s.get("failures", []))}
            for r in reports for s in r.get("scenarios", [])]


# ---------------------------------------------------------------- explanations & evidence

BLOCK_EXPLANATIONS = {
    "AMBIGUOUS_REPLY": "Reply was not an unambiguous confirmation (question, condition or extra request) - BR-04.",
    "NOT_DIRECT_REPLY": "Reply was not the only customer message after the latest confirmation request - BR-04.",
    "NO_OPEN_REQUEST": "No open confirmation request for the current order version - BR-04.",
    "STALE_REQUEST": "Confirmation request belongs to an older order version - BR-04.",
    "CONTENT_CHANGED": "Order content or prices changed since the summary was sent; confirmation invalidated - BR-03/04.",
    "STALE_VERSION": "Order changed since the agent last read it (optimistic concurrency).",
    "NOT_EXPLICITLY_BOTH_INTENDED": "Customer did not explicitly confirm both possible-duplicate orders - BR-05.",
    "NO_INTENT_QUESTION": "Duplicate can only be cleared after the system's duplicate-intent question - BR-05.",
    "UNGROUNDED_VALUE": "Value not present in the customer's own words - never fabricated (BR-02).",
    "ESCALATED_NOT_APPLIED": "Order is READY_FOR_DISPATCH: change not applied, referred to staff - BR-06.",
    "BLOCKED_LIFECYCLE_LOCKED": "Order is SHIPPED/DELIVERED/CANCELLED: no modification - BR-06.",
    "AMOUNTS_NOT_ALLOWED_IN_FREE_TEXT": "Agent text may not state amounts; only the system summary carries prices - BR-03.",
    "OPERATIONAL_COMMITMENT_NOT_ALLOWED": "Agent tried to promise a delivery date/refund/free item or a false status.",
    "ITEM_NOT_AVAILABLE": "Requested variant is not in stock - BR-01.",
    "OUT_OF_SCOPE_ITEM": "Only other sizes/quantities of ordered products may be chosen - BR-01.",
    "NOT_ELIGIBLE": "Summary can only be sent when every other check passes.",
    "INVALID_INPUT": "Malformed tool call rejected by schema validation (fail closed).",
    "UNKNOWN_TOOL": "Tool not on the allowlist (fail closed).",
    "SOURCE_UNAVAILABLE": "Authoritative source unavailable; nothing guessed (fail closed).",
    "REFUSED": "Readiness commit refused after re-validating every rule.",
    "SKU_NOT_IN_ORDER": "Alternatives can only be listed for SKUs in this order.",
}


def explain_tool_output(output_json: str | None) -> dict:
    """Parse a persisted tool result into status + human explanation (no invented content)."""
    try:
        out = json.loads(output_json or "{}")
    except ValueError:
        return {"ok": None, "status": "UNPARSEABLE", "explanation": ""}
    status = out.get("status", "")
    reasons = out.get("reasons") or out.get("violations") or out.get("fields") or []
    expl = BLOCK_EXPLANATIONS.get(status, "")
    if status == "REFUSED" and reasons:
        expl = f"{expl} Reasons: {', '.join(map(str, reasons))}."
    elif reasons and expl:
        expl = f"{expl} ({', '.join(map(str, reasons))})"
    return {"ok": out.get("ok"), "status": status, "explanation": expl}


EVIDENCE = [
    {"safeguard": "Idempotent events & commit", "risk": "Prevents the same order message or confirmation from being processed twice (no duplicate replies, no double stock reservation).", "tests": ["test_TC15_DT14_*", "test_TC01_DT01_*", "test_same_operation_retried_concurrently_commits_once"],
     "replay": ["S14", "S01"], "live_capable": True},
    {"safeguard": "Duplicate-order safeguards", "risk": "Prevents shipping two near-identical orders by mistake - or cancelling one without asking the customer.", "tests": ["test_TC11_*", "test_TC12_*", "test_DT08_negative_*", "test_concurrent_duplicates_are_both_held"],
     "replay": ["S10", "S11"], "live_capable": True},
    {"safeguard": "Version-bound confirmation", "risk": "Prevents shipping an order the customer never confirmed, or confirmed before a size, address or price change.", "tests": ["test_TC09_AC04_*", "test_TC10_*", "test_AC01_DT05_*"],
     "replay": ["S07", "S08", "S09"], "live_capable": True},
    {"safeguard": "Fail-closed errors (API, malformed, budget)", "risk": "Prevents a model or API failure from silently marking an order ready or sending a wrong reply.", "tests": ["test_llm_errors_fail_closed_and_escalate", "test_tool_call_budget_stops_parallel_spam"],
     "replay": ["S19", "S20", "S21", "S22", "S23"], "live_capable": False},
    {"safeguard": "Bounded retries & timeouts", "risk": "Prevents a slow or failing AI provider from hanging the agent or running up cost.", "tests": ["test_sdk_client_configured_with_bounded_retries_and_timeout", "test_per_attempt_timeout_fits_all_retries_in_remaining_budget"],
     "replay": [], "live_capable": False},
    {"safeguard": "Commit timeout recovery (no double allocation)", "risk": "Prevents a lost network response from causing a duplicate dispatch or double stock allocation.", "tests": ["test_TC16_AC07_*", "test_AC07_*"],
     "replay": ["S15"], "live_capable": True},
    {"safeguard": "Lifecycle protection (READY/SHIPPED)", "risk": "Prevents edits to orders that are already packed, shipped, delivered or cancelled.", "tests": ["test_TC13_*", "test_TC14_*", "test_BR06_database_triggers_*"],
     "replay": ["S12", "S13"], "live_capable": True},
    {"safeguard": "Prompt-injection resistance", "risk": "Prevents a customer message from tricking the agent into skipping checks or granting discounts.", "tests": ["test_prompt_marks_customer_text_untrusted_and_escapes_tags"],
     "replay": ["S18"], "live_capable": True},
]


SAVED_EVIDENCE_DIR = PROJECT_ROOT / "evidence" / "live"


def load_saved_live_evidence(evidence_dir: Path | None = None) -> list[dict]:
    """Version-controlled SAVED LIVE EVIDENCE snapshots (recorded runs; viewing them is not a new execution)."""
    out = []
    for f in sorted((evidence_dir or SAVED_EVIDENCE_DIR).glob("*.json")):
        try:
            ev = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if ev.get("evidence_type") == "SAVED_LIVE_EVIDENCE":
            ev["_file"] = f.name
            out.append(ev)
    return out


def saved_evidence_as_reports(saved: list[dict]) -> list[dict]:
    """Minimal LIVE pseudo-reports so the evidence matrix can cite saved runs (labelled 'saved')."""
    return [{"mode": "LIVE", "run_at": s["recorded_at"], "model": f"{ev['model']} · saved",
             "scenarios": [{"id": s["id"], "passed": s["passed"]}]}
            for ev in saved for s in ev.get("scenarios", [])]


def evidence_matrix(reports: list[dict]) -> list[dict]:
    """Per safeguard: automated tests (names), latest REPLAY status, and LIVE status only if a LIVE run exists."""
    latest: dict[tuple, dict] = {}
    for r in sorted(reports, key=lambda r: r.get("run_at", "")):
        for s in r.get("scenarios", []):
            latest[(r.get("mode"), s["id"])] = {"passed": s.get("passed"), "model": r.get("model"), "run_at": r.get("run_at")}
    rows = []
    for ev in EVIDENCE:
        rep = [f"{sid} {'PASS' if latest[('REPLAY', sid)]['passed'] else 'FAIL'}" if ("REPLAY", sid) in latest
               else f"{sid} not run" for sid in ev["replay"]]
        live = [f"{sid} {'PASS' if latest[('LIVE', sid)]['passed'] else 'FAIL'} ({latest[('LIVE', sid)]['model']})"
                for sid in ev["replay"] if ("LIVE", sid) in latest]
        rows.append({"Safeguard": ev["safeguard"], "Risk prevented": ev["risk"],
                     "Automated tests (pytest)": ", ".join(ev["tests"]),
                     "Replay scenarios": ", ".join(rep) or "-",
                     "Live evidence": ", ".join(live) if live else ("not run" if ev["live_capable"] else "not live-testable")})
    return rows


def run_test_suite(timeout_s: int = 300) -> dict:
    """Run the automated tests now (explicit button). Returns the pytest summary line only."""
    try:
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=PROJECT_ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=timeout_s,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        return {"ok": False, "summary": f"timed out after {timeout_s}s"}
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    summary = next((l for l in reversed(lines) if " passed" in l or " failed" in l or " error" in l), "no summary")
    return {"ok": proc.returncode == 0, "summary": summary.strip("= ").strip()}


# ---------------------------------------------------------------- demo database (Business Owner / Operator)

def demo_db_status(db_path: Path) -> dict:
    if not Path(db_path).exists():
        return {"exists": False, "ready": False, "message": "No demo database yet."}
    conn = connect(db_path)
    try:
        if not table_names(conn):
            return {"exists": True, "ready": False, "message": "Database is empty."}
        if not is_synthetic_demo_db(conn):
            return {"exists": True, "ready": False, "message": "Not a synthetic demo database: the dashboard will not use it."}
        if schema_version(conn) != SCHEMA_VERSION:
            return {"exists": True, "ready": False, "message": "Demo database uses an older schema: reset it."}
        return {"exists": True, "ready": True, "message": "Synthetic demo database ready."}
    finally:
        conn.close()


def create_or_reset_demo_db(settings: Settings, db_path: Path) -> dict:
    """Explicit UI action. Seeding refuses any database not marked as the synthetic demo store."""
    conn = connect(db_path)
    try:
        has_rows = bool(table_names(conn))
        seed(conn, settings, replace_existing=has_rows)
        return {"ok": True}
    except SeedError as e:
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params)]


def business_snapshot(db_path: Path) -> dict:
    conn = connect(db_path)
    try:
        return {
            "lifecycle": _rows(conn, "SELECT lifecycle_state AS state, COUNT(*) AS orders FROM orders GROUP BY 1 ORDER BY 1"),
            "outcomes": _rows(conn, "SELECT COALESCE(agent_outcome, 'NOT YET PROCESSED') AS outcome, COUNT(*) AS orders "
                                    "FROM orders GROUP BY 1 ORDER BY 1"),
            "orders": _rows(conn, """
                SELECT o.order_id, o.lifecycle_state, o.agent_outcome, o.version, o.outcome_reason, o.channel,
                       o.governorate, o.quoted_total_egp,
                       (SELECT GROUP_CONCAT(i.sku || ' x' || i.quantity, ', ') FROM order_items i WHERE i.order_id = o.order_id) AS items
                FROM orders o ORDER BY o.order_id"""),
            "escalations": _rows(conn, "SELECT escalation_id, order_id, reason_code, detail, created_at FROM escalations "
                                       "WHERE status = 'OPEN' ORDER BY escalation_id DESC"),
            "runs": _rows(conn, "SELECT run_id, mode, provider, model, order_id, status, error_class, final_outcome, "
                                "llm_calls, tool_calls, input_tokens, output_tokens, latency_ms, cost_usd, provider_cost_usd, "
                                "cost_basis, started_at FROM agent_runs ORDER BY started_at DESC, run_id DESC LIMIT 50"),
            "usage": _rows(conn, "SELECT mode, provider, model, COUNT(*) AS runs, SUM(llm_calls) AS model_calls, "
                                 "SUM(tool_calls) AS tool_calls, SUM(input_tokens) AS input_tokens, "
                                 "SUM(output_tokens) AS output_tokens, ROUND(AVG(latency_ms)) AS avg_latency_ms, "
                                 "ROUND(SUM(cost_usd), 6) AS estimated_cost_usd, ROUND(SUM(provider_cost_usd), 6) AS provider_cost_usd "
                                 "FROM agent_runs GROUP BY 1, 2, 3"),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------- Operator Workspace

def order_view(db_path: Path, order_id: str) -> dict:
    conn = connect(db_path)
    try:
        order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if order is None:
            return {}
        return {
            "order": dict(order),
            "items": _rows(conn, "SELECT i.sku, v.size, v.color, i.quantity, inv.available FROM order_items i "
                                 "JOIN variants v ON v.sku = i.sku JOIN inventory inv ON inv.sku = i.sku "
                                 "WHERE i.order_id = ? ORDER BY i.line_no", (order_id,)),
            "messages": _rows(conn, "SELECT seq, direction, kind, body, event_id, created_at FROM messages "
                                    "WHERE order_id = ? ORDER BY seq DESC LIMIT 20", (order_id,))[::-1],
            "escalations": _rows(conn, "SELECT reason_code, detail, status FROM escalations WHERE order_id = ? "
                                       "ORDER BY escalation_id DESC", (order_id,)),
        }
    finally:
        conn.close()


def replay_options(order_id: str) -> list[dict]:
    """Predefined scenario messages for this order. REPLAY can only play these scripted model turns."""
    opts = []
    for s in load_scenarios():
        for i, e in enumerate(s["events"], start=1):
            if e["order_id"] == order_id and e.get("replay_script"):
                opts.append({"label": f"{s['id']} step {i}/{len(s['events'])} - {s['title']}", "text": e["text"],
                             "script": e["replay_script"], "faults": s.get("setup", {}).get("faults", {})})
    return opts


def submit_message(settings: Settings, db_path: Path, order_id: str, text: str, mode: str,
                   replay_script: list | None = None, ui_key: str | None = None,
                   event_id: str | None = None, fetch=None, faults: dict | None = None) -> dict:
    """Process one simulated customer message through the real agent runtime on the demo DB.
    Messages go only to the simulated outbox. event_id reuse demonstrates idempotency."""
    mode = mode.upper()
    if not demo_db_status(db_path)["ready"]:
        return {"ok": False, "error": "create the synthetic demo database first"}
    if not text or not text.strip():
        return {"ok": False, "error": "message is empty"}
    if mode == "REPLAY":
        if not replay_script:
            return {"ok": False, "error": "REPLAY plays predefined scenario messages only; use LIVE for free text"}
        llm = ReplayLLM(replay_script)
    else:
        pre = live_preflight(settings, ui_key, fetch=fetch)
        if not pre["live_ready"]:
            return {"ok": False, "error": "LIVE preflight failed", "preflight": pre}
        llm = build_provider(settings, api_key=resolve_key(settings, ui_key))
    event_id = event_id or f"UI-{uuid.uuid4().hex[:12]}"
    conn = connect(db_path)
    try:
        ctx = ToolContext(conn, _with_faults(settings, faults or {}), clock=lambda: FIXED_CLOCK)
        result = handle_event(ctx, llm, order_id, event_id, text.strip())
        steps = _rows(conn, "SELECT step_no, kind, name, input_json, output_json FROM agent_steps WHERE run_id = ? "
                            "ORDER BY step_no", (result.get("run_id"),)) if result.get("run_id") and not result.get(
            "replayed_from_saved_result") else []
        return {"ok": True, "event_id": event_id, "result": result, "steps": steps}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {sanitize(e, 300)}"}
    finally:
        conn.close()


def fixture_order_state(order_id: str) -> dict:
    """Initial (seeded) lifecycle/version for an order, for 'before' state in scenario views."""
    data = json.loads((PROJECT_ROOT / "data" / "fixtures" / "orders.json").read_text(encoding="utf-8"))["orders"]
    o = next((x for x in data if x["order_id"] == order_id), {})
    return {"lifecycle_state": o.get("lifecycle_state"), "agent_outcome": o.get("agent_outcome"), "version": o.get("version")}
