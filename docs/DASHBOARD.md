# COD Rescue Control Center (dashboard)

A local Streamlit demo on top of the existing backend (evaluation engine, agent runtime, guarded tools, provider factory). It contains **no business rules of its own**: every action goes through `cod_rescue/dashboard_service.py`, which calls the same code the CLI and tests use.

```powershell
.\.venv\Scripts\python -m streamlit run dashboard\app.py      # then open http://localhost:8501
```

## Views (demo views, not authenticated roles)
| View | What it shows | Writes |
|---|---|---|
| **Judge Lab** | Run any evaluation scenario (REPLAY default; LIVE opt-in), PASS/FAIL assertions, Arabic conversation (RTL), every persisted tool call with results and plain-language reasons for safety blocks, state transitions, structured error diagnostics. Tabs: **Saved Live evidence** (recorded real-model runs from `evidence/live/`, labelled SAVED LIVE EVIDENCE - viewing it makes no API call), safety evidence matrix (automated tests vs REPLAY vs LIVE) and metrics charts from persisted results. | Isolated per-scenario databases under `results/` only |
| **Business Owner** | Synthetic demo DB: lifecycle counts vs agent outcome counts (distinct concepts), orders, human exception queue, agent runs, tokens/latency/estimated vs provider-reported cost. | Explicit "create/reset demo DB" only |
| **Operator Workspace** | Pick an order, read its conversation, send a simulated customer message through the real runtime, redeliver the same event to see idempotency. REPLAY plays predefined scenario messages only (scripted model turns); LIVE accepts free text. | Demo DB via the agent runtime and guarded tools |
| **Future Enhancements** | Roadmap, clearly labelled not implemented. | None |

## Safety & isolation
- Synthetic data only; messaging goes to the simulated outbox. Scenario runs never touch the demo DB; the demo DB is created/reset only by an explicit click and seeding refuses any non-synthetic database.
- No LIVE call happens on page load, view switch or profile change: only after selecting LIVE, ticking the acknowledgement and clicking Run/Send. A non-billable preflight (key present, allowlisted endpoint, model listed, declared tools, pricing not unknown) runs first. REPLAY-only failure scenarios cannot be run LIVE.
- **API keys:** typed into a password field, held only in Streamlit session memory, passed per invocation to the provider factory. Never written to the process environment, SQLite, files, logs, URLs or results (tested). Developer keys from the environment/`.env` are **not** used by the dashboard unless the person running it sets `COD_RESCUE_DASHBOARD_USE_ENV_KEYS=1`.
- **Key destinations:** credentials are only sent to allowlisted https hosts (`api.anthropic.com`, `openrouter.ai`, `router.huggingface.co`, `api.openai.com`). The Anthropic endpoint is always passed explicitly, so an `ANTHROPIC_BASE_URL` environment variable cannot redirect a key. Non-allowlisted endpoints (including localhost) receive a placeholder, never a real key.
- Visitors see no stack traces (`showErrorDetails = "none"`); errors are summarized and sanitized. The server binds to `localhost` and usage statistics are off.
- **Not a secure multi-user deployment.** A password field does not make a shared/public deployment safe (TLS, authentication, per-user isolation, rate limiting and secret management would be required). Run it locally.

## Evidence sources
- **Automated tests** — deterministic pytest suite (no model). Button "Run automated test suite now" measures it on the judge's machine.
- **REPLAY** — full agent loop with scripted model turns; proves harness, allowlist and guards; not model understanding.
- **LIVE** — real model; shown only where a persisted LIVE result exists (`results/live/<provider>/<model>/eval-*.json`).
- **SAVED LIVE** — version-controlled snapshot of recorded LIVE runs (`evidence/live/*.json`, report [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md)), built by `scripts/build_live_evidence.py` from local results. Visible in a fresh clone without any key; never counted as REPLAY.

A fresh clone has no results: the Metrics tab shows an empty state and a "Run all REPLAY scenarios" button.

## Known limitations
- Charts come from persisted evaluation files and the demo DB; no historical baseline of manual handling time exists, so the dashboard shows **no time-saving or revenue numbers**.
- Operator REPLAY is limited to predefined scenario messages for the selected order; their scripted turns assume the scenario's starting state (guards still apply if the state differs).
- Fonts load from Google Fonts when online; offline the browser falls back to system fonts.

## Future Enhancements (not implemented)
1. **Feedback-driven learning** from human-reviewed corrections in the exception queue, proposing prompt/rule updates for human approval. No uncontrolled automatic policy changes.
2. **Token efficiency:** context reduction, fewer model calls per event, prompt optimisation measured on the scenario suite.
3. **Cost optimisation:** lower cost per safely resolved order; provider/model benchmarking on the same scenarios with safety assertions as the bar.
4. **Latency optimisation:** faster responses (model choice, fewer round-trips, streaming) while keeping every deterministic safeguard.
