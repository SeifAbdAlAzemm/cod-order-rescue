"""Build the version-controlled SAVED LIVE EVIDENCE snapshot from existing local LIVE results.

Reads (never re-runs): results/live/<provider>/<model>/eval-*.json and the per-scenario run databases
saved next to them (for per-model-call latency). Writes:
  evidence/live/<name>.json   - sanitized snapshot (shown in the dashboard, no API key needed)
  docs/LIVE-EVIDENCE.md       - human-readable report

Sanitization: no API keys/headers/environment, no absolute paths, no raw logs; tool inputs were already
PII-redacted at trace time; customer addresses are cut from confirmation summaries; data is synthetic.

Usage: python scripts/build_live_evidence.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cod_rescue.dashboard_service import BLOCK_EXPLANATIONS  # noqa: E402

SOURCE_DIR = ROOT / "results" / "live" / "openai_compatible" / "nvidia_nemotron-3-super-120b-a12b_free"
SOURCE_FILES = ["eval-20261010-163035.json", "eval-20261010-163641.json"]  # S01; S02 + S11
OUT_JSON = ROOT / "evidence" / "live" / "nemotron-3-super-free_2026-10-10.json"
OUT_MD = ROOT / "docs" / "LIVE-EVIDENCE.md"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_reply(text: str) -> str:
    """Cut the (synthetic) delivery address from confirmation summaries; amounts and items stay."""
    return text.split("العنوان:")[0].strip() + (" [address omitted]" if "العنوان:" in text else "")


def model_call_latencies(db: Path, run_id: str) -> list[int]:
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    try:
        return [r[0] for r in con.execute(
            "SELECT latency_ms FROM agent_steps WHERE run_id = ? AND kind = 'LLM_CALL' ORDER BY step_no", (run_id,))]
    finally:
        con.close()


def tool_action(step: dict) -> dict:
    out = json.loads(step.get("output_json") or "{}")
    inp = json.loads(step.get("input_json") or "{}")
    detail = ""
    if step["name"] == "apply_customer_change":
        items = (inp.get("changes") or {}).get("items")
        detail = "items -> " + ", ".join(f"{i['sku']} x{i['quantity']}" for i in items) if items else \
            "fields: " + ", ".join(sorted((inp.get("changes") or {}).keys()))
    elif step["name"] == "list_alternatives":
        detail = f"{inp.get('sku')} -> verified in stock: " + ", ".join(a["sku"] for a in out.get("alternatives", []))
    elif step["name"] == "escalate_to_human":
        detail = f"reason {inp.get('reason')}"
    elif step["name"] == "commit_ready" and out.get("ok"):
        detail = "reserved " + ", ".join(f"{r['sku']} x{r['quantity']}" for r in out.get("reserved", []))
    elif step["name"] == "flag_duplicates":
        detail = "possible duplicates: " + ", ".join(out.get("duplicates", []))
    action = {"tool": step["name"], "ok": out.get("ok"), "status": out.get("status"), "detail": detail}
    if out.get("ok") is False:
        action["safety_block"] = BLOCK_EXPLANATIONS.get(out.get("status"), "")
    return action


def build() -> dict:
    scenario_defs = {s["id"]: s for s in json.loads((ROOT / "data/scenarios/scenarios.json").read_text(encoding="utf-8"))["scenarios"]}
    sources, scenarios, meta = [], [], None
    for name in SOURCE_FILES:
        f = SOURCE_DIR / name
        report = json.loads(f.read_text(encoding="utf-8"))
        meta = meta or {k: report[k] for k in ("mode", "provider", "profile", "model", "pricing_status")}
        sources.append({"source_file": f.relative_to(ROOT).as_posix(), "sha256": sha256(f), "run_at": report["run_at"],
                        "scenarios": [s["id"] for s in report["scenarios"]],
                        "tool_support_verified_live": report["tool_support_verified_live"]})
        for s in report["scenarios"]:
            db = SOURCE_DIR / "dbs" / f"{s['id']}-live.sqlite3"
            events = []
            for e in s["events"]:
                r = e["result"]
                lat = model_call_latencies(db, r["run_id"])
                events.append({
                    "event_id": e["event"], "order_id": e["order_id"], "customer_message": e["customer_text"],
                    "outcome": r["outcome"], "lifecycle_state": r["lifecycle_state"], "order_version": r["version"],
                    "run_status": r["status"], "error_class": r.get("error_class"), "error_kind": r.get("error_kind"),
                    "model_calls": r["llm_calls"], "tool_calls": r["tool_calls"],
                    "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"],
                    "run_latency_ms": r["latency_ms"], "model_call_latencies_ms": lat, "model_time_ms": sum(lat) if lat else None,
                    "estimated_cost_usd": r["cost_usd"], "provider_reported_cost_usd": r.get("provider_cost_usd"),
                    "cost_basis": r["cost_basis"], "fallback_reply_used": r.get("fallback_reply_used"),
                    "tool_actions": [tool_action(st) for st in e["trace"] if st["kind"] == "TOOL_CALL"],
                    "agent_replies": [{"kind": m["kind"], "source": "system template" if m.get("template") else
                                       ("system summary" if m["kind"] in ("CONFIRMATION_REQUEST", "DUPLICATE_INTENT_REQUEST") else "model-written"),
                                       "text": clean_reply(m["text"])} for m in r.get("messages_sent", [])],
                    "model_summary": r.get("agent_summary", ""),
                })
            scenarios.append({"id": s["id"], "title": s["title"], "test_cases": scenario_defs[s["id"]].get("test_cases", []),
                              "passed": s["passed"], "assertion_failures": s["failures"], "events": events,
                              "recorded_at": report["run_at"]})
    all_events = [e for s in scenarios for e in s["events"]]
    model_lat = [ms for e in all_events for ms in e["model_call_latencies_ms"]]
    totals = {
        "scenarios": len(scenarios), "scenarios_passed": sum(s["passed"] for s in scenarios), "events": len(all_events),
        "model_calls": sum(e["model_calls"] for e in all_events), "tool_calls": sum(e["tool_calls"] for e in all_events),
        "input_tokens": sum(e["input_tokens"] for e in all_events), "output_tokens": sum(e["output_tokens"] for e in all_events),
        "run_latency_ms_total": sum(e["run_latency_ms"] for e in all_events),
        "model_time_ms_total": sum(model_lat), "model_call_latency_ms_min": min(model_lat), "model_call_latency_ms_max": max(model_lat),
        "model_call_latency_ms_mean": round(sum(model_lat) / len(model_lat)),
        "estimated_cost_usd_total": round(sum(e["estimated_cost_usd"] for e in all_events), 6),
        "provider_reported_cost_usd_total": round(sum(e["provider_reported_cost_usd"] or 0 for e in all_events), 6),
        "events_with_provider_reported_cost": sum(e["provider_reported_cost_usd"] is not None for e in all_events),
        "blocked_tool_calls": sum(1 for e in all_events for a in e["tool_actions"] if a["ok"] is False),
        "escalations": sum(e["outcome"] == "ESCALATE_TO_HUMAN" for e in all_events),
        "fallback_replies": sum(bool(e["fallback_reply_used"]) for e in all_events),
    }
    totals["per_event_mean"] = {k: round(totals[k] / totals["events"], 1) for k in
                                ("model_calls", "tool_calls", "input_tokens", "output_tokens", "run_latency_ms_total")}
    return {
        "evidence_type": "SAVED_LIVE_EVIDENCE",
        "notice": "Recorded LIVE runs from 2026-10-10. Viewing this file is NOT a new LIVE execution.",
        "disclosure": {"data": "synthetic orders, customers, prices and stock for a fictional shop (StyleHub Egypt)",
                       "messaging": "simulated outbox; no WhatsApp/Instagram/SMS message was sent",
                       "deployment": "local MVP; not deployed, not production-ready"},
        "provider": "OpenRouter (OpenAI-compatible API)", "profile": meta["profile"], "model": meta["model"],
        "pricing_status": meta["pricing_status"],
        "cost_note": ("estimated_cost_usd = tokens x configured price (verified free model: $0). "
                      "provider_reported_cost_usd = cost returned by OpenRouter usage accounting."),
        "latency_note": ("model_call_latencies_ms = measured duration of each model API call (incl. SDK retries); "
                         "run_latency_ms = whole agent run for the event (model calls + local tools + DB)."),
        "sources": sources, "scenarios": scenarios, "totals": totals,
        "safety_observations": [
            {"title": "Premature confirmation blocked", "where": "S01, EVT-S01-1",
             "observation": "Right after sending the summary, the model called record_confirmation on the customer's first "
                            "message. The deterministic guard refused it (NOT_DIRECT_REPLY); the order stayed VERIFIED/ON_HOLD "
                            "until the customer's explicit \"تمام\" in the next event."},
            {"title": "Only verified alternatives offered", "where": "S02, EVT-S02-1",
             "observation": "The model listed in-stock alternatives (L, M) before asking; the out-of-stock XL was not "
                            "substituted automatically. The customer asked when it would arrive; the reply made no "
                            "delivery-date promise."},
            {"title": "Customer-authorized change, then fresh confirmation", "where": "S02",
             "observation": "The size change created order version 2 and a new summary; the commit happened only after "
                            "\"تمام\" to version 2."},
            {"title": "Duplicate handled without cancellation", "where": "S11",
             "observation": "Both orders were held and the system question named ORD-1008 and ORD-1009. When the customer "
                            "wanted only one, the model escalated (DUPLICATE_ONE_INTENDED); it did not attempt to clear the "
                            "duplicate flag and no order was cancelled."},
            {"title": "Amounts only from the system", "where": "all events",
             "observation": "Every price and total appears only in system-generated summaries; READY and escalation "
                            "notices are system templates."},
        ],
        "limitations": [
            "Only three selected scenarios (S01, S02, S11) were run LIVE; the other 22 scenarios are REPLAY-only evidence.",
            "One model (nvidia/nemotron-3-super-120b-a12b:free) on a free, rate-limited endpoint; results may differ "
            "for other models, endpoints or times.",
            "Single run per scenario: no repeated trials, so no variance or reliability rate can be stated.",
            "Synthetic data and simulated messaging; no real SME orders, customers or operating conditions.",
            "Free model: $0 cost does not represent paid-model or production costs.",
            "An earlier S01 attempt with google/gemma-4-31b-it:free failed on an upstream HTTP 429 rate limit "
            "(not included in these totals).",
        ],
    }


def to_markdown(ev: dict) -> str:
    t = ev["totals"]
    lines = [
        "# Saved Live Evidence",
        "",
        f"> **SAVED LIVE EVIDENCE** — recorded LIVE runs, not a new execution. Model `{ev['model']}` via "
        f"{ev['provider']} (profile `{ev['profile']}`, pricing `{ev['pricing_status']}`). "
        f"Data: {ev['disclosure']['data']}. Messaging: {ev['disclosure']['messaging']}.",
        "",
        "Generated by `python scripts/build_live_evidence.py` from the local result files below (SHA-256 recorded); "
        f"machine-readable snapshot: [`{OUT_JSON.relative_to(ROOT).as_posix()}`](../{OUT_JSON.relative_to(ROOT).as_posix()}). "
        "Also viewable in the dashboard: Judge Lab → *Saved Live evidence* (no API key needed).",
        "",
        "## Results",
        "",
        "| Scenario | Test cases | Result | Events | Model calls | Tool calls | Tokens in / out | Model time (ms) | Run time (ms) | Est. cost | Provider-reported cost |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in ev["scenarios"]:
        ev_ = s["events"]
        lines.append(
            f"| {s['id']} {s['title']} | {', '.join(s['test_cases'])} | {'PASS' if s['passed'] else 'FAIL'} | {len(ev_)} | "
            f"{sum(e['model_calls'] for e in ev_)} | {sum(e['tool_calls'] for e in ev_)} | "
            f"{sum(e['input_tokens'] for e in ev_):,} / {sum(e['output_tokens'] for e in ev_):,} | "
            f"{sum(e['model_time_ms'] or 0 for e in ev_):,} | {sum(e['run_latency_ms'] for e in ev_):,} | "
            f"${sum(e['estimated_cost_usd'] for e in ev_):.4f} | ${sum(e['provider_reported_cost_usd'] or 0 for e in ev_):.4f} |")
    lines += [
        f"| **Total** | | **{t['scenarios_passed']}/{t['scenarios']} PASS** | {t['events']} | {t['model_calls']} | {t['tool_calls']} | "
        f"{t['input_tokens']:,} / {t['output_tokens']:,} | {t['model_time_ms_total']:,} | {t['run_latency_ms_total']:,} | "
        f"${t['estimated_cost_usd_total']:.4f} | ${t['provider_reported_cost_usd_total']:.4f} |",
        "",
        f"Per model call: {t['model_call_latency_ms_min']:,}–{t['model_call_latency_ms_max']:,} ms (mean {t['model_call_latency_ms_mean']:,} ms). "
        f"Per event (mean): {t['per_event_mean']['model_calls']} model calls, {t['per_event_mean']['tool_calls']} tool calls, "
        f"{t['per_event_mean']['input_tokens']:,} input / {t['per_event_mean']['output_tokens']:,} output tokens, "
        f"{t['per_event_mean']['run_latency_ms_total']:,} ms. "
        f"Blocked tool calls: {t['blocked_tool_calls']}. Escalations: {t['escalations']}. Fallback replies: {t['fallback_replies']}.",
        "",
        f"*Costs:* {ev['cost_note']} *Latency:* {ev['latency_note']}",
        "",
        "## Event by event",
    ]
    for s in ev["scenarios"]:
        lines += ["", f"### {s['id']} — {s['title']} ({'PASS' if s['passed'] else 'FAIL'}, recorded {s['recorded_at']})"]
        for e in s["events"]:
            lines += ["", f"**{e['event_id']}** · `{e['order_id']}` · customer: <span dir=\"rtl\">{e['customer_message']}</span>", ""]
            for a in e["tool_actions"]:
                mark = "✅" if a["ok"] else "⛔"
                extra = f" — {a['detail']}" if a["detail"] else ""
                block = f" — *blocked: {a['safety_block']}*" if a.get("safety_block") else ""
                lines.append(f"- {mark} `{a['tool']}` → `{a['status']}`{extra}{block}")
            for m in e["agent_replies"]:
                lines.append(f"- 💬 [{m['kind']}, {m['source']}] <span dir=\"rtl\">{m['text']}</span>")
            lines.append(f"- Result: outcome `{e['outcome']}`, lifecycle `{e['lifecycle_state']}`, v{e['order_version']} · "
                         f"{e['model_calls']} model / {e['tool_calls']} tool calls · {e['input_tokens']:,}/{e['output_tokens']:,} tokens · "
                         f"model {e['model_time_ms']:,} ms of {e['run_latency_ms']:,} ms")
    lines += [
        "",
        "## Safety observations (from the records above)",
        "",
    ] + [f"- **{o['title']} ({o['where']}):** {o['observation']}" for o in ev["safety_observations"]] + [
        "",
        "## Limitations",
        "",
    ] + [f"- {x}" for x in ev["limitations"]] + [
        "",
        "## Sources",
        "",
        "| File (local, not version-controlled) | Recorded | Scenarios | SHA-256 |",
        "|---|---|---|---|",
    ] + [f"| `{s['source_file']}` | {s['run_at']} | {', '.join(s['scenarios'])} | `{s['sha256'][:16]}…` |" for s in ev["sources"]] + [
        "",
        "Per-call model latencies come from the run databases saved next to each file (`dbs/<scenario>-live.sqlite3`, table `agent_steps`).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ev = build()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(ev, ensure_ascii=False, indent=1)
    if re.search(r"[A-Za-z]:\\\\|/Users/|sk-[A-Za-z]{0,8}-?[A-Za-z0-9]{16,}|Bearer ", text):
        raise SystemExit("refusing to write: snapshot contains a path or credential-like string")
    OUT_JSON.write_text(text + "\n", encoding="utf-8")
    OUT_MD.write_text(to_markdown(ev), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")
    print(json.dumps(ev["totals"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
