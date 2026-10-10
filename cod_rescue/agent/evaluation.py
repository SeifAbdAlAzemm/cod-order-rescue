"""Scenario evaluation for the agent. REPLAY and LIVE results are produced and stored separately.

Each scenario runs on a freshly seeded synthetic database. Expectations check authoritative
state (lifecycle, outcome, stock, ledger, messages), never the model's wording.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from cod_rescue import PROJECT_ROOT
from cod_rescue.agent.llm import ReplayLLM
from cod_rescue.agent.runtime import handle_event
from cod_rescue.config import Settings
from cod_rescue.context import CAIRO_TZ, ToolContext
from cod_rescue.db import connect
from cod_rescue.seed import seed

SCENARIOS_PATH = PROJECT_ROOT / "data" / "scenarios" / "scenarios.json"
FIXED_CLOCK = datetime(2026, 10, 10, 12, 0, 0, tzinfo=CAIRO_TZ)


def load_scenarios(path: Path = SCENARIOS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["scenarios"]


def _with_faults(settings: Settings, faults: dict) -> Settings:
    if not faults:
        return settings
    fi = dataclasses.replace(settings.simulation.fault_injection, **faults)
    return dataclasses.replace(settings, simulation=dataclasses.replace(settings.simulation, fault_injection=fi))


def check_expectations(conn, result: dict, expect: dict) -> list[str]:
    failures = []
    for oid, fields in expect.get("orders", {}).items():
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (oid,)).fetchone()
        for k, v in fields.items():
            if row[k] != v:
                failures.append(f"{oid}.{k} = {row[k]!r}, expected {v!r}")
    for oid, fields in expect.get("orders_not", {}).items():
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (oid,)).fetchone()
        for k, v in fields.items():
            if row[k] == v:
                failures.append(f"{oid}.{k} must not be {v!r}")
    for oid, fields in expect.get("orders_contains", {}).items():
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (oid,)).fetchone()
        for k, v in fields.items():
            if v not in (row[k] or ""):
                failures.append(f"{oid}.{k} = {row[k]!r}, expected to contain {v!r}")
    for sku, n in expect.get("stock", {}).items():
        got = conn.execute("SELECT available FROM inventory WHERE sku = ?", (sku,)).fetchone()[0]
        if got != n:
            failures.append(f"stock {sku} = {got}, expected {n}")
    for c in expect.get("counts", []):
        got = conn.execute(c["sql"]).fetchone()[0]
        if ("eq" in c and got != c["eq"]) or ("lte" in c and got > c["lte"]) or ("gte" in c and got < c["gte"]):
            failures.append(f"{c['sql']} -> {got}, expected {({k: c[k] for k in ('eq', 'lte', 'gte') if k in c})}")
    for oid in expect.get("escalated", []):
        if not conn.execute("SELECT 1 FROM escalations WHERE order_id = ? AND status = 'OPEN'", (oid,)).fetchone():
            failures.append(f"{oid}: expected an open escalation")
    for k, v in expect.get("result", {}).items():
        if result.get(k) != v:
            failures.append(f"result.{k} = {result.get(k)!r}, expected {v!r}")
    return failures


def run_scenario(scenario: dict, settings: Settings, mode: str, work_dir: Path, live_llm_factory=None) -> dict:
    db_path = work_dir / f"{scenario['id']}-{mode.lower()}.sqlite3"
    db_path.unlink(missing_ok=True)
    conn = connect(db_path)
    try:
        seed(conn, settings)
        ctx = ToolContext(conn, _with_faults(settings, scenario.get("setup", {}).get("faults", {})),
                          clock=lambda: FIXED_CLOCK)
        events, failures = [], []
        started = time.monotonic()
        for i, ev in enumerate(scenario["events"], start=1):
            for sql in ev.get("before_sql", []):  # simulated external change (e.g. a sale on another channel)
                conn.execute(sql)
            llm = ReplayLLM(ev.get("replay_script", [])) if mode == "REPLAY" else live_llm_factory(ctx.settings)
            result = handle_event(ctx, llm, ev["order_id"], ev["event_id"], ev["text"])
            fails = check_expectations(conn, result, ev.get("expect", {}))
            failures += [f"event {i}: {f}" for f in fails]
            steps = [dict(r) for r in conn.execute(
                "SELECT step_no, kind, name, input_json, output_json FROM agent_steps WHERE run_id = ? ORDER BY step_no",
                (result.get("run_id"),))] if result.get("run_id") and not result.get("replayed_from_saved_result") else []
            events.append({"event": ev["event_id"], "order_id": ev["order_id"], "customer_text": ev["text"],
                           "result": result, "trace": steps, "failures": fails})
        return {"id": scenario["id"], "title": scenario["title"], "test_cases": scenario.get("test_cases", []),
                "mode": mode, "passed": not failures, "failures": failures, "events": events,
                "elapsed_ms": int((time.monotonic() - started) * 1000)}
    finally:
        conn.close()


def results_root() -> Path:
    """results/ by default; COD_RESCUE_RESULTS_DIR redirects it (tests, isolated demos)."""
    return Path(os.environ.get("COD_RESCUE_RESULTS_DIR") or PROJECT_ROOT / "results")


def results_dir(settings: Settings, mode: str) -> Path:
    """REPLAY is provider-independent; LIVE results are kept per provider and model."""
    if mode == "REPLAY":
        return results_root() / "replay"
    p = settings.llm.profile
    return results_root() / "live" / p.provider / re.sub(r"[^A-Za-z0-9._-]+", "_", p.model)


def run_suite(settings: Settings, mode: str, scenario_ids: list[str] | None = None,
              out_dir: Path | None = None, live_llm_factory=None) -> dict:
    assert mode in ("REPLAY", "LIVE")
    profile = settings.llm.profile
    out_dir = out_dir or results_dir(settings, mode)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "dbs"
    work.mkdir(exist_ok=True)
    selected = [s for s in load_scenarios() if not scenario_ids or s["id"] in scenario_ids]
    skipped = []
    if mode == "LIVE":
        skipped = [s["id"] for s in selected if not s.get("live", True)]
        selected = [s for s in selected if s.get("live", True)]
    results = [run_scenario(s, settings, mode, work, live_llm_factory) for s in selected]
    totals = {
        "llm_calls": sum(e["result"].get("llm_calls", 0) for r in results for e in r["events"]),
        "input_tokens": sum(e["result"].get("input_tokens", 0) for r in results for e in r["events"]),
        "output_tokens": sum(e["result"].get("output_tokens", 0) for r in results for e in r["events"]),
        "cost_usd": round(sum(e["result"].get("cost_usd", 0) for r in results for e in r["events"]), 6),
    }
    reported = [e["result"]["provider_cost_usd"] for r in results for e in r["events"]
                if e["result"].get("provider_cost_usd") is not None and not e["result"].get("replayed_from_saved_result")]
    totals["provider_cost_usd"] = round(sum(reported), 6) if reported else None
    # Verified tool support: the real model produced at least one schema-valid tool call that the harness executed.
    verified = mode == "LIVE" and any(
        st["kind"] == "TOOL_CALL" and '"INVALID_INPUT"' not in (st["output_json"] or "")
        and '"UNKNOWN_TOOL"' not in (st["output_json"] or "")
        for r in results for e in r["events"] for st in e["trace"])
    report = {
        "mode": mode,
        "label": ("REPLAY: scripted model turns, no API calls; validates harness + guarded tools, NOT model "
                  "understanding" if mode == "REPLAY" else
                  f"LIVE: profile {profile.name} ({profile.provider}/{profile.model}); pricing {profile.pricing.status}; "
                  "local cost = tokens x configured prices; provider-reported cost shown separately"),
        "provider": "replay" if mode == "REPLAY" else profile.provider,
        "profile": None if mode == "REPLAY" else profile.name,
        "model": "replay-script" if mode == "REPLAY" else profile.model,
        "pricing_status": None if mode == "REPLAY" else profile.pricing.status,
        "tool_support_verified_live": verified if mode == "LIVE" else "n/a (replay)",
        "results_path": str(out_dir),
        "run_at": datetime.now(CAIRO_TZ).isoformat(timespec="seconds"),
        "passed": sum(r["passed"] for r in results), "total": len(results), "skipped_not_live_capable": skipped,
        "totals": totals, "scenarios": results,
    }
    stamp = datetime.now(CAIRO_TZ).strftime("%Y%m%d-%H%M%S")
    (out_dir / f"eval-{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                                                encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                                         encoding="utf-8")
    return report
