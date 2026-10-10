"""COD Rescue Control Center - local Streamlit demo dashboard.

Run:  streamlit run dashboard/app.py
All data is synthetic, all customer messaging is simulated. Views are demo views, not authenticated roles.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cod_rescue import dashboard_service as svc  # noqa: E402

st.set_page_config(page_title="COD Rescue Control Center", page_icon="📦", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Cairo:wght@400;600&display=swap');
html, body, [class*="css"], .stMarkdown, .stText { font-family: 'Inter', 'Cairo', system-ui, sans-serif; }
.block-container { padding-top: 1.6rem; max-width: 1400px; }
.hero { background: linear-gradient(120deg, #0f766e 0%, #134e4a 100%); color: #fff; padding: 18px 22px;
        border-radius: 14px; margin-bottom: 14px; }
.hero h1 { font-size: 1.55rem; margin: 0 0 4px 0; color: #fff; }
.hero p { margin: 0; opacity: .9; font-size: .95rem; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600;
         letter-spacing: .02em; margin: 0 4px 4px 0; border: 1px solid transparent; }
.b-green { background: #dcfce7; color: #166534; border-color: #bbf7d0; }
.b-amber { background: #fef3c7; color: #92400e; border-color: #fde68a; }
.b-red { background: #fee2e2; color: #991b1b; border-color: #fecaca; }
.b-blue { background: #dbeafe; color: #1e40af; border-color: #bfdbfe; }
.b-purple { background: #ede9fe; color: #5b21b6; border-color: #ddd6fe; }
.b-gray { background: #f1f5f9; color: #334155; border-color: #e2e8f0; }
.card { border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px 16px; background: #fff; margin-bottom: 10px; }
.muted { color: #64748b; font-size: .85rem; }
.bubble { padding: 10px 14px; border-radius: 14px; margin: 6px 0; max-width: 92%; line-height: 1.7;
          font-family: 'Cairo', 'Inter', sans-serif; font-size: .97rem; }
.b-customer { background: #f1f5f9; margin-left: auto; border-bottom-right-radius: 4px; }
.b-shop { background: #ecfdf5; border: 1px solid #d1fae5; margin-right: auto; border-bottom-left-radius: 4px; }
.b-meta { font-family: 'Inter', sans-serif; font-size: .72rem; color: #64748b; margin-bottom: 2px; direction: ltr; text-align: left; }
.step { border-left: 3px solid #cbd5e1; padding: 4px 10px; margin: 6px 0; font-size: .88rem; }
.step-ok { border-left-color: #22c55e; }
.step-block { border-left-color: #ef4444; background: #fef2f2; }
.step code { font-size: .8rem; }
.verdict-pass { background: #dcfce7; color: #14532d; padding: 10px 16px; border-radius: 10px; font-weight: 700; }
.verdict-fail { background: #fee2e2; color: #7f1d1d; padding: 10px 16px; border-radius: 10px; font-weight: 700; }
.future { border: 1px dashed #94a3b8; border-radius: 12px; padding: 14px 16px; background: #f8fafc; height: 100%; }
</style>
""", unsafe_allow_html=True)

TONE = {"READY_FOR_DISPATCH": "green", "ON_HOLD": "amber", "ESCALATE_TO_HUMAN": "red", "PENDING": "gray",
        "VERIFIED": "blue", "SHIPPED": "purple", "DELIVERED": "green", "CANCELLED": "gray", "REPLAY": "blue",
        "LIVE": "purple", "PASS": "green", "FAIL": "red"}


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def badge(text, tone: str | None = None) -> str:
    return f'<span class="badge b-{tone or TONE.get(str(text), "gray")}">{esc(text)}</span>'


def bubble(text: str, who: str, meta: str = "") -> None:
    cls = "b-customer" if who == "customer" else "b-shop"
    st.markdown(f'<div class="bubble {cls}" dir="rtl" style="text-align:right">'
                f'<div class="b-meta">{esc(meta)}</div>{esc(text)}</div>', unsafe_allow_html=True)


def state_badges(lifecycle, outcome, version) -> str:
    return (f'{badge(lifecycle)} {badge(outcome or "no outcome yet", TONE.get(str(outcome), "gray"))} '
            f'<span class="muted">v{esc(version)}</span>')


def render_steps(steps: list[dict]) -> None:
    tool_steps = [s for s in steps if s["kind"] in ("TOOL_CALL", "LLM_CALL")]
    if not tool_steps:
        st.caption("No model or tool steps recorded for this event (e.g. saved result replayed).")
        return
    for s in tool_steps:
        if s["kind"] == "LLM_CALL":
            try:
                out = json.loads(s["output_json"] or "{}")
            except ValueError:
                out = {}
            if out.get("error"):
                diag = ", ".join(f"{k}={out[k]}" for k in ("error_kind", "http_status", "provider_error_code",
                                                          "upstream_provider", "retry_after") if out.get(k) is not None)
                st.markdown(f'<div class="step step-block">⚠️ <b>Model call failed</b> - {esc(diag)}</div>',
                            unsafe_allow_html=True)
            continue
        info = svc.explain_tool_output(s["output_json"])
        ok = info["ok"]
        icon = "✅" if ok else "⛔"
        cls = "step-ok" if ok else "step-block"
        args = (s.get("input_json") or "{}")
        args = args if len(args) < 140 else args[:140] + "…"
        expl = f'<div class="muted">{esc(info["explanation"])}</div>' if (not ok and info["explanation"]) else ""
        st.markdown(f'<div class="step {cls}">{icon} <b>{esc(s["name"])}</b> → <code>{esc(info["status"])}</code>'
                    f'<div class="muted"><code>{esc(args)}</code></div>{expl}</div>', unsafe_allow_html=True)


def render_result_event(idx: int, ev: dict, before: dict) -> dict:
    r = ev["result"]
    after = {"lifecycle_state": r.get("lifecycle_state"), "agent_outcome": r.get("outcome"), "version": r.get("version")}
    with st.container(border=True):
        top = st.columns([3, 2])
        top[0].markdown(f"**Event {idx}** · `{esc(ev['order_id'])}` · `{esc(ev['event'])}`"
                        + ("  " + badge("saved result replayed (idempotent)", "blue")
                           if r.get("replayed_from_saved_result") else ""), unsafe_allow_html=True)
        top[1].markdown(f'{state_badges(before.get("lifecycle_state"), before.get("agent_outcome"), before.get("version"))}'
                        f' → {state_badges(after["lifecycle_state"], after["agent_outcome"], after["version"])}',
                        unsafe_allow_html=True)
        left, right = st.columns([1, 1])
        with left:
            st.markdown("**Conversation** <span class='muted'>(simulated channel)</span>", unsafe_allow_html=True)
            bubble(ev["customer_text"], "customer", "customer")
            for m in r.get("messages_sent", []):
                tag = "system template" if m.get("template") else "agent-written"
                bubble(m["text"], "shop", f"shop · {m['kind']} · {tag}")
            if not r.get("messages_sent") and not r.get("replayed_from_saved_result"):
                st.caption("No outbound message recorded.")
        with right:
            st.markdown("**Agent activity** <span class='muted'>(persisted trace)</span>", unsafe_allow_html=True)
            render_steps(ev.get("trace", []))
            facts = [f"model calls {r.get('llm_calls', 0)}", f"tool calls {r.get('tool_calls', 0)}",
                     f"tokens {r.get('input_tokens', 0)}/{r.get('output_tokens', 0)}", f"latency {r.get('latency_ms', 0)} ms"]
            if r.get("error_class"):
                facts.append(f"error {r.get('error_class')}/{r.get('error_kind') or '-'} (failed closed)")
            if r.get("fallback_reply_used"):
                facts.append("deterministic fallback reply")
            st.caption(" · ".join(facts))
            if r.get("reasons"):
                st.caption("Decision reasons: " + ", ".join(r["reasons"]))
        if ev.get("failures"):
            for f in ev["failures"]:
                st.error(f"Assertion failed: {f}")
    return after


# ================================================================ sidebar

base_settings = svc.settings_for()
with st.sidebar:
    st.markdown("### 📦 COD Rescue\n**Control Center**")
    view = st.radio("Demo view", ["🧪 Judge Lab", "📊 Business Owner", "🛠️ Operator Workspace", "🚀 Future Enhancements"],
                    label_visibility="collapsed")
    st.caption("Demo views - **not** authenticated roles.")
    st.divider()
    st.markdown("**LLM provider** · used only in LIVE mode")
    names = list(base_settings.llm.profiles)
    profile_name = st.selectbox("Profile", names, index=names.index(base_settings.llm.active_profile),
                                format_func=lambda n: f"{n}  ({base_settings.llm.profiles[n].pricing.status})")
    p = base_settings.llm.profiles[profile_name]
    st.caption(f"`{p.provider}` · `{p.model}`")
    st.text_input("API key", type="password", key="ui_api_key", placeholder=f"{p.api_key_env} (optional)",
                  help="Kept in memory for this browser session only. Never written to disk, logs, URLs or results.")
    if svc.env_keys_allowed():
        st.caption("Developer environment keys enabled for this local session.")
    if st.button("Validate profile (no model call)", width="stretch"):
        with st.spinner("Checking listing, pricing and declared tool support…"):
            st.session_state["preflight"] = svc.live_preflight(svc.settings_for(profile_name),
                                                               st.session_state.get("ui_api_key"))
    pre = st.session_state.get("preflight")
    if pre and pre.get("profile") == profile_name:
        if pre["live_ready"]:
            st.success(f"Ready for LIVE · tools {pre['tool_support']} · pricing {pre['pricing_status']}")
        else:
            st.warning("Not ready for LIVE")
            for prob in pre["problems"]:
                st.caption(f"• {prob}")
    st.divider()
    st.markdown(f'{badge("Synthetic data", "gray")}{badge("Simulated messaging", "gray")}'
                f'{badge("Local MVP · not production", "amber")}', unsafe_allow_html=True)

settings = svc.settings_for(profile_name)
ui_key = st.session_state.get("ui_api_key") or None


def db_gate() -> bool:
    status = svc.demo_db_status(settings.db_path)
    if status["ready"]:
        return True
    st.info(f"{status['message']} The dashboard keeps its demo data in a separate synthetic database "
            f"(`{Path(settings.db_path).name}`); scenario evaluations always use isolated databases.")
    if st.button("Create synthetic demo database", type="primary"):
        res = svc.create_or_reset_demo_db(settings, settings.db_path)
        if res["ok"]:
            st.rerun()
        st.error(res.get("error", "could not create the demo database"))
    return False


# ================================================================ Judge Lab

def judge_lab() -> None:
    st.markdown('<div class="hero"><h1>🧪 Judge Lab</h1><p>Run the real agent loop on a scenario and inspect every '
                'tool call, safety block and state change. REPLAY works with no API key.</p></div>',
                unsafe_allow_html=True)
    with st.expander("👋 First time here? 2-minute path", expanded=True):
        st.markdown("1. Keep **S01 · Complete order confirmation** and mode **REPLAY**.\n"
                    "2. Click **Run scenario** - it takes about a second, no API key needed.\n"
                    "3. Read the conversation (Arabic, right-to-left), the agent's tool calls, and the PASS/FAIL "
                    "assertions. Then try **S08** (contradictory \"تمام\") or **S11** (duplicate orders, customer says no).\n\n"
                    "**REPLAY** = scripted model turns through the real harness and guards (simulated model). "
                    "**LIVE** = the selected real model decides; external requests, rate limits and possible billing apply.")
    run_tab, saved_tab, evidence_tab, metrics_tab = st.tabs(
        ["▶ Run a scenario", "📁 Saved Live evidence", "🛡️ Safety evidence", "📈 Metrics"])

    with saved_tab:
        saved_live_evidence()

    with run_tab:
        scenarios = svc.list_scenarios()
        by_id = {s["id"]: s for s in scenarios}
        c1, c2, c3 = st.columns([3.2, 1.6, 1.2])
        sid = c1.selectbox("Scenario", list(by_id), format_func=lambda i: f"{i} · {by_id[i]['title']}"
                           + (f"  [{', '.join(by_id[i]['test_cases'])}]" if by_id[i]["test_cases"] else ""))
        mode = c2.radio("Mode", ["REPLAY", "LIVE"], horizontal=True)
        sc = by_id[sid]
        ack = True
        if mode == "LIVE":
            st.warning(f"LIVE calls **{settings.llm.model}** via `{settings.llm.provider}` (profile `{profile_name}`). "
                       "External requests are sent; rate limits and possible billing apply. Nothing runs until you click Run.")
            ack = st.checkbox("I understand this sends real requests to the selected provider.")
            if not sc["live"]:
                st.info(f"{sid} simulates model/API failures and is REPLAY-only.")
        else:
            st.info("REPLAY: scripted model turns, no API calls. Proves harness, allowlist and guards - "
                    "not model language understanding.")
        if sc["faults"]:
            st.caption("Injected fault for this scenario: " + ", ".join(k for k, v in sc["faults"].items() if v))
        with st.expander(f"Customer messages in {sid} ({len(sc['events'])})"):
            for e in sc["events"]:
                bubble(e["text"], "customer", f"{e['order_id']} · {e['event_id']}")
        disabled = mode == "LIVE" and (not ack or not sc["live"])
        if c3.button("Run scenario", type="primary", width="stretch", disabled=disabled):
            with st.status(f"Running {sid} in {mode}…", expanded=False) as status:
                st.write("Seeding an isolated synthetic database…")
                res = svc.run_scenario_ui(settings, sid, mode, ui_key)
                status.update(label=f"{sid} finished" if res.get("ok") else f"{sid} could not run",
                              state="complete" if res.get("ok") else "error")
            st.session_state["judge_result"] = res

        res = st.session_state.get("judge_result")
        if not res:
            st.caption("Results appear here after you run a scenario.")
            return
        if not res.get("ok"):
            st.error(res.get("error", "run failed"))
            for prob in (res.get("preflight") or {}).get("problems", []):
                st.caption(f"• {prob}")
            return
        report = res["report"]
        s = report["scenarios"][0]
        verdict = "PASS" if s["passed"] else "FAIL"
        st.markdown(f'<div class="verdict-{verdict.lower()}">{verdict} · {esc(s["id"])} · {esc(s["title"])} '
                    f'&nbsp; {badge(report["mode"])} {badge(report["model"], "gray")}</div>', unsafe_allow_html=True)
        st.caption(report["label"])
        events = s["events"]
        m = st.columns(6)
        real = [e["result"] for e in events if not e["result"].get("replayed_from_saved_result")]
        m[0].metric("Events", len(events))
        m[1].metric("Model calls", sum(r.get("llm_calls", 0) for r in real))
        m[2].metric("Tool calls", sum(r.get("tool_calls", 0) for r in real))
        m[3].metric("Tokens in / out", f"{sum(r.get('input_tokens', 0) for r in real)} / {sum(r.get('output_tokens', 0) for r in real)}")
        m[4].metric("Latency", f"{sum(r.get('latency_ms') or 0 for r in real)} ms")
        pc = [r.get("provider_cost_usd") for r in real if r.get("provider_cost_usd") is not None]
        m[5].metric("Cost (est. / provider)", f"${sum(r.get('cost_usd', 0) for r in real):.4f} / "
                    + (f"${sum(pc):.4f}" if pc else "n/a"))
        before = svc.fixture_order_state(events[0]["order_id"]) if events else {}
        states: dict[str, dict] = {}
        for i, ev in enumerate(events, start=1):
            prev = states.get(ev["order_id"]) or svc.fixture_order_state(ev["order_id"])
            states[ev["order_id"]] = render_result_event(i, ev, prev)
        st.caption(f"Saved to `results/{esc(report['results_path'].split('results')[-1].lstrip(chr(92)).lstrip('/'))}`")

    with evidence_tab:
        history = svc.load_result_history()
        st.markdown("Each safeguard is backed by **automated tests** (deterministic, no model), **REPLAY scenarios** "
                    "(full agent loop, scripted model) and - only where a run exists - **LIVE** evidence with a real model.")
        saved = svc.saved_evidence_as_reports(svc.load_saved_live_evidence())
        st.dataframe(pd.DataFrame(svc.evidence_matrix(history + saved)), width="stretch", hide_index=True)
        st.caption("REPLAY/LIVE columns come from persisted result files in `results/` on this machine and from the "
                   "version-controlled saved LIVE evidence (marked 'saved'). 'not run' = no such run recorded.")
        c1, c2 = st.columns([1, 3])
        if c1.button("Run automated test suite now"):
            with st.spinner("Running pytest (about 30 seconds)…"):
                st.session_state["pytest"] = svc.run_test_suite()
        t = st.session_state.get("pytest")
        if t:
            (c2.success if t["ok"] else c2.error)(f"pytest: {t['summary']}")
        else:
            c2.caption("Documented last run: see docs/TRACEABILITY.md. Click to measure on this machine.")

    with metrics_tab:
        history = svc.load_result_history()
        if not history:
            st.info("No evaluation results on this machine yet (fresh clone). Run the REPLAY suite to generate measured data.")
        if st.button("Run all REPLAY scenarios (no API calls)"):
            with st.spinner("Running 25 scenarios on isolated databases…"):
                rep = svc.run_suite(settings, "REPLAY")
            st.success(f"REPLAY: {rep['passed']}/{rep['total']} scenarios passed")
            history = svc.load_result_history()
        if not history:
            return
        rows = pd.DataFrame(svc.metric_rows(history))
        srows = pd.DataFrame(svc.scenario_rows(history))
        modes = st.multiselect("Modes", ["REPLAY", "LIVE"], default=["LIVE"] if (rows["mode"] == "LIVE").any() else ["REPLAY"])
        rows = rows[rows["mode"].isin(modes)] if not rows.empty else rows
        if rows.empty:
            st.caption("No runs for the selected modes.")
        else:
            rows["label"] = rows["scenario"] + " · " + rows["event"].str.replace("EVT-", "", regex=False) + " · " + rows["model"].astype(str).str.split("/").str[-1]
            c1, c2 = st.columns(2)
            c1.markdown("**Tokens per event (input vs output)**")
            c1.bar_chart(rows.set_index("label")[["input_tokens", "output_tokens"]])
            c2.markdown("**Model calls and tool calls per event**")
            c2.bar_chart(rows.set_index("label")[["llm_calls", "tool_calls"]])
            c3, c4 = st.columns(2)
            c3.markdown("**Latency per event (ms)**")
            c3.bar_chart(rows.set_index("label")[["latency_ms"]])
            c4.markdown("**Cost: local estimate vs provider-reported (USD)**")
            c4.dataframe(rows[["label", "cost_basis", "estimated_cost_usd", "provider_cost_usd"]], hide_index=True,
                         width="stretch")
            st.caption("REPLAY rows have no model cost (scripted). Free-model LIVE runs show $0 by verified pricing; "
                       "provider-reported cost appears only when the provider returns it.")
        st.markdown("**Scenario results (all persisted runs)**")
        st.dataframe(srows, hide_index=True, width="stretch")


def saved_live_evidence() -> None:
    evidence = svc.load_saved_live_evidence()
    if not evidence:
        st.info("No saved LIVE evidence found in `evidence/live/`.")
        return
    for ev in evidence:
        t = ev["totals"]
        st.markdown(f'<div class="card">{badge("SAVED LIVE EVIDENCE", "purple")} {badge("not a new execution", "gray")}'
                    f'<br><b>{esc(ev["model"])}</b> via {esc(ev["provider"])} · profile <code>{esc(ev["profile"])}</code> · '
                    f'pricing {esc(ev["pricing_status"])}<br><span class="muted">{esc(ev["notice"])} '
                    f'{esc(ev["disclosure"]["data"].capitalize())}; {esc(ev["disclosure"]["messaging"])}.</span></div>',
                    unsafe_allow_html=True)
        m = st.columns(6)
        m[0].metric("Scenarios passed", f"{t['scenarios_passed']}/{t['scenarios']}")
        m[1].metric("Model calls", t["model_calls"])
        m[2].metric("Tool calls", t["tool_calls"])
        m[3].metric("Tokens in / out", f"{t['input_tokens']:,} / {t['output_tokens']:,}")
        m[4].metric("Model time", f"{t['model_time_ms_total'] / 1000:.1f} s",
                    help=f"Per model call {t['model_call_latency_ms_min']}–{t['model_call_latency_ms_max']} ms "
                         f"(mean {t['model_call_latency_ms_mean']} ms); total run time {t['run_latency_ms_total'] / 1000:.1f} s")
        m[5].metric("Cost (est. / provider)", f"${t['estimated_cost_usd_total']:.4f} / ${t['provider_reported_cost_usd_total']:.4f}",
                    help=ev["cost_note"])
        rows = [{"Scenario": f"{s['id']} · {s['title']}", "Test cases": ", ".join(s["test_cases"]),
                 "Result": "PASS" if s["passed"] else "FAIL", "Events": len(s["events"]),
                 "Model calls": sum(e["model_calls"] for e in s["events"]),
                 "Tool calls": sum(e["tool_calls"] for e in s["events"]),
                 "Input tokens": sum(e["input_tokens"] for e in s["events"]),
                 "Output tokens": sum(e["output_tokens"] for e in s["events"]),
                 "Model time (ms)": sum(e["model_time_ms"] or 0 for e in s["events"]),
                 "Est. cost ($)": sum(e["estimated_cost_usd"] for e in s["events"]),
                 "Provider cost ($)": sum(e["provider_reported_cost_usd"] or 0 for e in s["events"]),
                 "Recorded": s["recorded_at"]} for s in ev["scenarios"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.markdown("**Safety observations**")
        for o in ev.get("safety_observations", []):
            st.markdown(f"- **{esc(o['title'])}** ({esc(o['where'])}): {esc(o['observation'])}")
        for s in ev["scenarios"]:
            with st.expander(f"{'✅' if s['passed'] else '❌'} {s['id']} · {s['title']} - event by event"):
                for e in s["events"]:
                    with st.container(border=True):
                        st.markdown(f"**{esc(e['event_id'])}** · `{esc(e['order_id'])}` &nbsp; "
                                    f"{state_badges(e['lifecycle_state'], e['outcome'], e['order_version'])}",
                                    unsafe_allow_html=True)
                        c1, c2 = st.columns(2)
                        with c1:
                            bubble(e["customer_message"], "customer", "customer")
                            for r in e["agent_replies"]:
                                bubble(r["text"], "shop", f"shop · {r['kind']} · {r['source']}")
                        with c2:
                            for a in e["tool_actions"]:
                                cls = "step-ok" if a["ok"] else "step-block"
                                blk = f'<div class="muted">{esc(a["safety_block"])}</div>' if a.get("safety_block") else ""
                                det = f'<div class="muted">{esc(a["detail"])}</div>' if a["detail"] else ""
                                st.markdown(f'<div class="step {cls}">{"✅" if a["ok"] else "⛔"} <b>{esc(a["tool"])}</b> → '
                                            f'<code>{esc(a["status"])}</code>{det}{blk}</div>', unsafe_allow_html=True)
                            st.caption(f"{e['model_calls']} model / {e['tool_calls']} tool calls · "
                                       f"{e['input_tokens']:,}/{e['output_tokens']:,} tokens · model {e['model_time_ms']:,} ms "
                                       f"of {e['run_latency_ms']:,} ms")
        st.markdown("**Limitations**")
        for lim in ev["limitations"]:
            st.markdown(f"- {esc(lim)}")
        st.caption(f"Source snapshot: evidence/live/{esc(ev['_file'])} · full report: docs/LIVE-EVIDENCE.md")


# ================================================================ Business Owner

def business_owner() -> None:
    st.markdown('<div class="hero"><h1>📊 Business Owner</h1><p>Operational view of the synthetic demo shop. '
                'All numbers come from the local demo database - no real customers, no revenue claims.</p></div>',
                unsafe_allow_html=True)
    if not db_gate():
        return
    snap = svc.business_snapshot(settings.db_path)
    st.markdown("#### Order lifecycle - *authoritative order state*")
    cols = st.columns(max(len(snap["lifecycle"]), 1))
    for c, row in zip(cols, snap["lifecycle"]):
        c.metric(row["state"], row["orders"])
    st.markdown("#### Agent decision outcome - *what the agent concluded*")
    cols = st.columns(max(len(snap["outcomes"]), 1))
    for c, row in zip(cols, snap["outcomes"]):
        c.metric(row["outcome"], row["orders"])
    st.caption("Lifecycle and outcome are different: e.g. a READY_FOR_DISPATCH order whose customer later asks for a change "
               "keeps its lifecycle but gets outcome ESCALATE_TO_HUMAN.")
    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Orders")
        st.dataframe(pd.DataFrame(snap["orders"]), hide_index=True, width="stretch", height=380)
    with right:
        st.markdown("#### Human exception queue")
        if snap["escalations"]:
            st.dataframe(pd.DataFrame(snap["escalations"]), hide_index=True, width="stretch", height=380)
        else:
            st.success("No open escalations.")
    st.markdown("#### Agent runs & usage (this demo database)")
    if snap["runs"]:
        st.dataframe(pd.DataFrame(snap["usage"]), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(snap["runs"]), hide_index=True, width="stretch", height=260)
    else:
        st.info("No agent runs on the demo database yet. Send a message in the Operator Workspace, or see Judge Lab → "
                "Metrics for scenario evaluations (kept in isolated databases).")
    with st.expander("Reset demo data"):
        st.caption("Re-seeds the synthetic demo database (refused for any non-synthetic database).")
        if st.checkbox("I want to reset all demo orders, messages and runs") and st.button("Reset demo database"):
            res = svc.create_or_reset_demo_db(settings, settings.db_path)
            st.success("Demo database reset.") if res["ok"] else st.error(res.get("error"))


# ================================================================ Operator Workspace

def operator_workspace() -> None:
    st.markdown('<div class="hero"><h1>🛠️ Operator Workspace</h1><p>Send a simulated customer message to a synthetic '
                'order and watch the agent work. Nothing is sent to WhatsApp, Instagram or SMS.</p></div>',
                unsafe_allow_html=True)
    if not db_gate():
        return
    snap = svc.business_snapshot(settings.db_path)
    ids = [o["order_id"] for o in snap["orders"]]
    states = {o["order_id"]: o for o in snap["orders"]}
    oid = st.selectbox("Order", ids, format_func=lambda i: f"{i} · {states[i]['lifecycle_state']} · "
                                                           f"{states[i]['agent_outcome'] or 'not processed'}")
    data = svc.order_view(settings.db_path, oid)
    o = data["order"]
    left, right = st.columns([2, 3])
    with left:
        with st.container(border=True):
            st.markdown(f"**{esc(o['order_id'])}** · {esc(o['channel'])} &nbsp; "
                        f"{state_badges(o['lifecycle_state'], o['agent_outcome'], o['version'])}", unsafe_allow_html=True)
            st.markdown(f'<div dir="rtl" style="text-align:right">{esc(o["customer_name"])}<br>{esc(o["address_raw"])}</div>',
                        unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(data["items"]), hide_index=True, width="stretch")
            st.caption(f"Quoted total: {o['quoted_total_egp'] if o['quoted_total_egp'] is not None else '-'} EGP · "
                       f"reason: {o['outcome_reason'] or '-'}")
            for e in data["escalations"]:
                st.warning(f"Escalation {e['status']}: {e['reason_code']}")
    with right:
        st.markdown("**Conversation** <span class='muted'>(simulated channel)</span>", unsafe_allow_html=True)
        if not data["messages"]:
            st.caption("No messages yet.")
        for msg in data["messages"]:
            who = "customer" if msg["direction"] == "INBOUND" else "shop"
            bubble(msg["body"], who, f"{who} · {msg['kind']}")

    st.markdown("#### Send a simulated customer message")
    mode = st.radio("Mode", ["REPLAY", "LIVE"], horizontal=True, key="op_mode")
    text, script, faults, ack = None, None, None, True
    if mode == "REPLAY":
        opts = svc.replay_options(oid)
        if not opts:
            st.info("REPLAY can only play predefined scenario messages, and none exist for this order. "
                    "Use LIVE for free-text messages.")
        else:
            st.caption("REPLAY plays a predefined scenario message with **scripted model turns** through the real "
                       "runtime and guards. It is not a model's reply to arbitrary text.")
            choice = st.selectbox("Predefined message", range(len(opts)), format_func=lambda i: opts[i]["label"])
            text, script, faults = opts[choice]["text"], opts[choice]["script"], opts[choice]["faults"]
            bubble(text, "customer", "will be sent as customer")
    else:
        text = st.text_area("Customer message (Arabic or English)", placeholder="مثال: عايزة أغير المقاس لـ L")
        st.warning(f"LIVE uses {settings.llm.model} via profile `{profile_name}`: external requests, rate limits and "
                   "possible billing apply.")
        ack = st.checkbox("I understand this sends a real request to the selected provider.", key="op_ack")
    c1, c2 = st.columns([1, 2])
    if c1.button("Send message", type="primary", disabled=not text or not ack):
        with st.spinner("Agent working…"):
            res = svc.submit_message(settings, settings.db_path, oid, text, mode, replay_script=script,
                                     ui_key=ui_key, faults=faults)
        st.session_state["op_last"] = {"res": res, "oid": oid, "text": text, "mode": mode, "script": script,
                                       "faults": faults}
        st.rerun()
    last = st.session_state.get("op_last")
    if last and last["oid"] == oid and last["res"].get("ok"):
        if c2.button("Redeliver the same event (idempotency check)"):
            res = svc.submit_message(settings, settings.db_path, oid, last["text"], last["mode"],
                                     replay_script=last["script"], ui_key=ui_key,
                                     event_id=last["res"]["event_id"], faults=last["faults"])
            st.session_state["op_last"] = {**last, "res": res}
            st.rerun()
    if last and last["oid"] == oid:
        res = last["res"]
        if not res.get("ok"):
            st.error(res.get("error"))
            for prob in (res.get("preflight") or {}).get("problems", []):
                st.caption(f"• {prob}")
            return
        r = res["result"]
        st.markdown("#### Result of last message")
        if r.get("replayed_from_saved_result"):
            st.success("Same event delivered again: saved result returned - no new model call, no new messages, "
                       "no new writes.")
        st.markdown(state_badges(r.get("lifecycle_state"), r.get("outcome"), r.get("version")), unsafe_allow_html=True)
        cc1, cc2 = st.columns(2)
        with cc1:
            for m in r.get("messages_sent", []):
                bubble(m["text"], "shop", f"shop · {m['kind']} · {'system template' if m.get('template') else 'agent-written'}")
        with cc2:
            render_steps(res.get("steps", []))
            if r.get("error_class"):
                st.warning(f"Run failed closed: {r['error_class']} / {r.get('error_kind') or '-'} - order escalated.")


# ================================================================ Future enhancements

def future() -> None:
    st.markdown('<div class="hero"><h1>🚀 Future Enhancements</h1><p>Roadmap ideas - <b>not implemented</b> '
                'and not current capabilities.</p></div>', unsafe_allow_html=True)
    items = [
        ("Feedback-driven learning", "Learn from human-reviewed corrections in the exception queue to propose prompt "
         "or rule updates - reviewed and approved by a person. No uncontrolled automatic policy changes."),
        ("Token efficiency", "Smaller context (send only fields the next step needs), fewer model calls per event, "
         "and prompt optimisation measured against the scenario suite."),
        ("Cost optimisation", "Lower cost per safely resolved order through provider/model benchmarking on the same "
         "scenarios, with safety assertions as the quality bar."),
        ("Latency optimisation", "Reduce model response time (model choice, fewer round-trips, streaming) while "
         "keeping every deterministic safeguard."),
    ]
    cols = st.columns(4)
    for c, (title, body) in zip(cols, items):
        c.markdown(f'<div class="future">{badge("Not implemented", "amber")}<h4>{esc(title)}</h4>'
                   f'<p class="muted">{esc(body)}</p></div>', unsafe_allow_html=True)


VIEWS = {"🧪 Judge Lab": judge_lab, "📊 Business Owner": business_owner,
         "🛠️ Operator Workspace": operator_workspace, "🚀 Future Enhancements": future}
try:
    VIEWS[view]()
except Exception as exc:  # visitors never see stack traces or internal details
    st.error(f"Something went wrong in this view ({type(exc).__name__}). Check the terminal running the dashboard.")
    print(f"[dashboard] {type(exc).__name__}: {svc.sanitize(exc, 500)}", file=sys.stderr)
