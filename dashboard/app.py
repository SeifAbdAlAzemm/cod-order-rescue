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
.block-container { padding-top: 1rem; max-width: 1400px; }
.hero { background: linear-gradient(120deg, #0f766e 0%, #134e4a 100%); color: #fff; padding: 12px 20px;
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
.result { border-radius: 14px; padding: 14px 20px; margin: 8px 0 10px 0; border: 2px solid; }
.result-pass { background: #f0fdf4; border-color: #22c55e; }
.result-fail { background: #fef2f2; border-color: #ef4444; }
.r-verdict { font-size: 1.9rem; font-weight: 800; letter-spacing: .02em; line-height: 1.1; }
.result-pass .r-verdict { color: #15803d; } .result-fail .r-verdict { color: #b91c1c; }
.r-title { font-size: 1.15rem; font-weight: 700; color: #0f172a; margin: 2px 0 6px 0; }
.saved-banner { background: #f5f3ff; border: 2px solid #8b5cf6; border-radius: 14px; padding: 12px 18px; margin-bottom: 10px; }
.saved-banner .t { font-size: 1.2rem; font-weight: 800; color: #5b21b6; letter-spacing: .03em; }
.pass-card { border: 1px solid #bbf7d0; background: #f0fdf4; border-radius: 12px; padding: 10px 14px; height: 100%; }
.pass-card .v { color: #15803d; font-weight: 800; }
.future { border: 1px dashed #94a3b8; border-radius: 12px; padding: 14px 16px; background: #f8fafc; height: 100%; }
</style>
""", unsafe_allow_html=True)

TONE = {"READY_FOR_DISPATCH": "green", "ON_HOLD": "amber", "ESCALATE_TO_HUMAN": "red", "PENDING": "gray",
        "VERIFIED": "blue", "SHIPPED": "purple", "DELIVERED": "green", "CANCELLED": "gray", "REPLAY": "blue",
        "LIVE": "purple", "PASS": "green", "FAIL": "red"}


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def num(n) -> str:
    """Compact, screenshot-friendly integers: 4172 -> 4,172; 71610 -> 71.6k."""
    n = int(n or 0)
    return f"{n / 1000:.1f}k" if n >= 10000 else f"{n:,}"


def money(x) -> str:
    """Dollar amounts for st.metric; '$' is escaped so Markdown does not render '$..$' as LaTeX."""
    if x is None:
        return "n/a"
    return r"\$0" if float(x) == 0 else rf"\${float(x):.4f}"


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

def run_scenario_view() -> None:
    """Run tab body. Its early returns end only this tab, never the other Judge Lab tabs."""
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
        st.caption("🔵 **REPLAY** - scripted model turns, no API calls. Proves harness, allowlist and guards, "
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
        st.rerun()  # re-render with the result card on top and the guide collapsed

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
    events = s["events"]
    verdict = "PASS" if s["passed"] else "FAIL"
    final = events[-1]["result"] if events else {}
    assertion_note = ("all assertions met" if s["passed"]
                      else f"{len(s['failures'])} assertion(s) failed - see details below")
    st.markdown(
        f'<div class="result result-{verdict.lower()}"><div class="r-verdict">{"✅" if s["passed"] else "❌"} {verdict}</div>'
        f'<div class="r-title">{esc(s["id"])} · {esc(s["title"])}</div>'
        f'Final agent outcome: {badge(final.get("outcome") or "-", TONE.get(str(final.get("outcome")), "gray"))} '
        f'order state: {badge(final.get("lifecycle_state") or "-")} &nbsp;·&nbsp; {badge(report["mode"])} '
        f'{badge(report["model"], "gray")} <span class="muted">· {esc(assertion_note)}</span></div>',
        unsafe_allow_html=True)
    real = [e["result"] for e in events if not e["result"].get("replayed_from_saved_result")]
    pc = [r.get("provider_cost_usd") for r in real if r.get("provider_cost_usd") is not None]
    m = st.columns(6)
    m[0].metric("Messages", len(events))
    m[1].metric("Model calls", sum(r.get("llm_calls", 0) for r in real))
    m[2].metric("Tool calls", sum(r.get("tool_calls", 0) for r in real))
    m[3].metric("Tokens in / out", f"{num(sum(r.get('input_tokens', 0) for r in real))} / {num(sum(r.get('output_tokens', 0) for r in real))}")
    m[4].metric("Run time", f"{sum(r.get('latency_ms') or 0 for r in real) / 1000:.1f} s")
    m[5].metric("Cost est. / provider", f"{money(sum(r.get('cost_usd', 0) for r in real))} / "
                + (money(sum(pc)) if pc else "n/a"),
                help="Estimated = tokens x configured price. Provider = cost reported by the provider, if any.")
    st.caption(report["label"])
    st.markdown("##### Conversation, tool trace and state changes")
    states: dict[str, dict] = {}
    for i, ev in enumerate(events, start=1):
        prev = states.get(ev["order_id"]) or svc.fixture_order_state(ev["order_id"])
        states[ev["order_id"]] = render_result_event(i, ev, prev)
    st.caption(f"Saved to `results/{esc(report['results_path'].split('results')[-1].lstrip(chr(92)).lstrip('/'))}`")


def judge_lab() -> None:
    st.markdown('<div class="hero"><h1>🧪 Judge Lab</h1><p>Run the real agent loop on a scenario and inspect every '
                'tool call, safety block and state change. REPLAY works with no API key.</p></div>',
                unsafe_allow_html=True)
    ran_ok = bool((st.session_state.get("judge_result") or {}).get("ok"))
    with st.expander("👋 First-time guide (2 minutes)" if ran_ok else "👋 First time here? 2-minute path",
                     expanded=not ran_ok):
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
        run_scenario_view()

    with evidence_tab:
        history = svc.load_result_history()
        st.markdown("**What each safeguard protects against, and what proves it.** Evidence levels: "
                    "**automated tests** (deterministic code, no model) · **REPLAY** (full agent loop, scripted model) · "
                    "**LIVE** (real model; only where a recorded run exists, marked *saved* for the committed evidence). "
                    "*not live-testable* = failure simulations that cannot be triggered on a real API.")
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
        saved = svc.load_saved_live_evidence()
        rows = pd.DataFrame(svc.combined_metric_rows(history, saved))
        if rows.empty:
            st.info("No measurements yet. Run the REPLAY suite below to generate data.")
        else:
            sources = sorted(rows["source"].unique())
            f1, f2, f3, f4 = st.columns([2.2, 2.2, 2.2, 1.4])
            default_src = ["Live · saved evidence"] if "Live · saved evidence" in sources else sources[:1]
            sel_src = f1.multiselect("Source", sources, default=default_src,
                                     help="Live · saved evidence = committed recorded runs. Local runs = results on this machine.")
            pool = rows[rows["source"].isin(sel_src)]
            sel_model = f2.multiselect("Model", sorted(pool["model"].astype(str).unique()))
            sel_scen = f3.multiselect("Scenario", sorted(pool["scenario"].unique()))
            latest = f4.checkbox("Latest run only", value=True, help="Avoid counting repeated runs of the same scenario")
            if sel_model:
                pool = pool[pool["model"].astype(str).isin(sel_model)]
            if sel_scen:
                pool = pool[pool["scenario"].isin(sel_scen)]
            if latest and not pool.empty:
                last = pool.groupby(["source", "model", "scenario"])["run_at"].transform("max")
                pool = pool[pool["run_at"] == last]
            if pool.empty:
                st.caption("No measurements for this selection.")
            else:
                if pool["mode"].nunique() > 1:
                    st.warning("Mixed REPLAY and LIVE: REPLAY rows use scripted model turns (0 tokens, no model time). "
                               "Compare them separately.")
                pc = pool["provider_cost_usd"].dropna()
                k = st.columns(4)
                k[0].metric("Messages", len(pool))
                k[1].metric("Model calls", int(pool["llm_calls"].sum()))
                k[2].metric("Tool calls", int(pool["tool_calls"].sum()))
                k[3].metric("Run time", f"{pool['latency_ms'].sum() / 1000:.1f} s",
                            help=f"Mean {pool['latency_ms'].mean() / 1000:.1f} s per customer message")
                k = st.columns(4)
                k[0].metric("Input tokens", num(pool["input_tokens"].sum()), help=f"{int(pool['input_tokens'].sum()):,}")
                k[1].metric("Output tokens", num(pool["output_tokens"].sum()), help=f"{int(pool['output_tokens'].sum()):,}")
                k[2].metric("Estimated cost", money(pool["estimated_cost_usd"].sum()),
                            help="Tokens x configured price (verified free model: $0).")
                k[3].metric("Provider-reported cost", money(pc.sum()) if len(pc) else "n/a",
                            help="Cost returned by the provider itself; n/a when not reported (e.g. REPLAY).")
                chart = pool.copy()
                chart["label"] = chart["event_label"]
                dup = chart["label"].duplicated(keep=False)
                chart.loc[dup, "label"] = chart.loc[dup, "label"] + " " + chart.loc[dup, "run_at"].astype(str).str[11:16]
                chart = chart.set_index("label")
                c1, c2, c3 = st.columns(3)
                c1.markdown("**Tokens per message** (input vs output)")
                c1.bar_chart(chart[["input_tokens", "output_tokens"]])
                c2.markdown("**Model calls vs tool calls**")
                c2.bar_chart(chart[["llm_calls", "tool_calls"]])
                c3.markdown("**Run time per message (ms)**")
                c3.bar_chart(chart[["latency_ms"]])
                st.caption("Labels: S01·2 = scenario S01, customer message 2.")
                with st.expander("Cost detail per message (estimated vs provider-reported)"):
                    st.dataframe(pool[["event_label", "source", "model", "cost_basis", "estimated_cost_usd",
                                       "provider_cost_usd"]].rename(columns={
                        "event_label": "message", "estimated_cost_usd": "estimated ($)",
                        "provider_cost_usd": "provider-reported ($)"}), hide_index=True, width="stretch")
        with st.expander("Scenario results and Replay data"):
            srows = svc.scenario_rows(history) + [
                {"run_at": sc["recorded_at"], "mode": "LIVE (saved evidence)", "provider": "openai_compatible",
                 "model": ev["model"], "scenario": sc["id"], "title": sc["title"], "passed": sc["passed"],
                 "failures": len(sc["assertion_failures"])} for ev in saved for sc in ev["scenarios"]]
            if srows:
                st.dataframe(pd.DataFrame(srows), hide_index=True, width="stretch")
            if st.button("Run all REPLAY scenarios (no API calls)"):
                with st.spinner("Running 25 scenarios on isolated databases…"):
                    rep_ = svc.run_suite(settings, "REPLAY")
                st.success(f"REPLAY: {rep_['passed']}/{rep_['total']} scenarios passed")
                st.rerun()


def saved_live_evidence() -> None:
    evidence = svc.load_saved_live_evidence()
    if not evidence:
        st.info("No saved LIVE evidence found in `evidence/live/`.")
        return
    for ev in evidence:
        t = ev["totals"]
        st.markdown(f'<div class="saved-banner"><div class="t">📁 SAVED LIVE EVIDENCE — not a new execution</div>'
                    f'Recorded real-model runs: <b>{esc(ev["model"])}</b> via {esc(ev["provider"])} · profile '
                    f'<code>{esc(ev["profile"])}</code> · pricing {esc(ev["pricing_status"])}. Opening this tab makes no API call.'
                    f'<br><span class="muted">{esc(ev["disclosure"]["data"].capitalize())}; '
                    f'{esc(ev["disclosure"]["messaging"])}.</span></div>', unsafe_allow_html=True)
        cards = st.columns(len(ev["scenarios"]))
        for c, sc in zip(cards, ev["scenarios"]):
            evs = sc["events"]
            c.markdown(f'<div class="pass-card"><span class="v">{"✅ PASS" if sc["passed"] else "❌ FAIL"}</span> · '
                       f'<b>{esc(sc["id"])}</b> {esc(", ".join(sc["test_cases"]))}<br>{esc(sc["title"])}<br>'
                       f'<span class="muted">{len(evs)} messages · {sum(e["model_calls"] for e in evs)} model / '
                       f'{sum(e["tool_calls"] for e in evs)} tool calls · {sum(e["input_tokens"] for e in evs):,} / '
                       f'{sum(e["output_tokens"] for e in evs):,} tokens · model time '
                       f'{sum(e["model_time_ms"] or 0 for e in evs) / 1000:.1f} s · final '
                       f'{esc(evs[-1]["outcome"])}</span></div>', unsafe_allow_html=True)
        st.write("")
        m = st.columns(6)
        m[0].metric("Scenarios passed", f"{t['scenarios_passed']}/{t['scenarios']}")
        m[1].metric("Model calls", t["model_calls"])
        m[2].metric("Tool calls", t["tool_calls"])
        m[3].metric("Tokens in / out", f"{num(t['input_tokens'])} / {num(t['output_tokens'])}",
                    help=f"{t['input_tokens']:,} input / {t['output_tokens']:,} output")
        m[4].metric("Model time", f"{t['model_time_ms_total'] / 1000:.1f} s",
                    help=f"Per model call {t['model_call_latency_ms_min']}–{t['model_call_latency_ms_max']} ms "
                         f"(mean {t['model_call_latency_ms_mean']} ms); total run time {t['run_latency_ms_total'] / 1000:.1f} s")
        m[5].metric("Cost est. / provider", f"{money(t['estimated_cost_usd_total'])} / {money(t['provider_reported_cost_usd_total'])}",
                    help=ev["cost_note"])
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
    st.info("ℹ️ This page shows the shop's **local demo database** (synthetic orders). Judge Lab scenarios run on "
            "**separate temporary copies**, so running a scenario there does **not** change the numbers here. "
            "To change demo orders, send a message in the **Operator Workspace**.")
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
