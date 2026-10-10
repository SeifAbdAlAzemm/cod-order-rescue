# COD Order Rescue Agent

A pre-dispatch verification agent for a **fictional** Egyptian clothing shop (*StyleHub Egypt*) that sells cash-on-delivery orders over Instagram/WhatsApp. One LLM agent reads the customer's Egyptian Arabic message and chooses among 11 allowlisted tools; deterministic code enforces every business rule (stock, address, prices, version-bound confirmation, duplicates, lifecycle). Outcome per order: `READY_FOR_DISPATCH`, `ON_HOLD` or `ESCALATE_TO_HUMAN`.

**Status (honest):** working **local MVP** on **synthetic data** with **simulated messaging**. Not deployed, not production-ready, no real merchant data. Deterministic tests and all 25 REPLAY scenarios pass. **LIVE:** 3 selected scenarios (S01, S02, S11) passed with `nvidia/nemotron-3-super-120b-a12b:free` via OpenRouter on 2026-10-10 — see the **[saved Live evidence](docs/LIVE-EVIDENCE.md)**. One earlier attempt with the Gemma free model failed on an upstream HTTP 429 rate limit. The full LIVE suite has not been run.

| Read next | |
|---|---|
| [Dashboard walkthrough](docs/DASHBOARD.md) | Views, safety, how keys are handled |
| [Saved Live evidence](docs/LIVE-EVIDENCE.md) | Recorded LIVE runs: tools, outcomes, tokens, latency, cost (also in the dashboard, no key needed) |
| [Impact report](docs/IMPACT.md) | Measured technical results vs projected (not observed) business impact |
| [Traceability](docs/TRACEABILITY.md) | BR → DT → AC → TC, with deterministic / REPLAY / LIVE results kept separate |

## Judge quickstart (Windows PowerShell, no API key needed)
Requires Python 3.11+.
```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run dashboard\app.py
```
Open **http://localhost:8501** → **Judge Lab** → keep **S01** and **REPLAY** → **Run scenario**. Then try **S08** (contradictory "تمام") and **S11** (possible duplicate orders, customer says "only one"). The **Saved Live evidence** tab shows the recorded real-model runs; opening it makes no API call. The dashboard is described in [docs/DASHBOARD.md](docs/DASHBOARD.md).

Command-line alternative (macOS/Linux: use `.venv/bin/python`):
```powershell
.\.venv\Scripts\python -m pytest                 # 300+ tests, no network
.\.venv\Scripts\python -m cod_rescue eval -v     # REPLAY: 25 agent scenarios, scripted model turns
```
REPLAY runs the full agent loop with scripted model turns and **no API calls**. It proves the harness, tool allowlist and guards end-to-end; it is **not** evidence of model language understanding (that is what LIVE measures).

## Optional: LIVE mode with a real model (billable or free-tier)
Provider choice is independent of mode. Profiles live in `config/settings.toml`:

| Profile | Provider | Model | Pricing |
|---|---|---|---|
| `anthropic-haiku` (default) | Anthropic | `claude-haiku-5-5` | known |
| `openrouter-gemma-free` | OpenRouter (OpenAI-compatible) | `google/gemma-4-31b-it:free` | verified free (listing re-checked before each LIVE run) |
| `openrouter-nemotron-free` | OpenRouter (OpenAI-compatible) | `nvidia/nemotron-3-super-120b-a12b:free` | verified free; used for the LIVE results above |

In the dashboard: choose the profile in the sidebar, paste a key into the masked field (memory only, never saved), click **Validate profile**, select **LIVE**, tick the acknowledgement and click **Run scenario**. From the command line:
```powershell
Copy-Item .env.example .env                       # then add your key; .env is git-ignored
.\.venv\Scripts\python -m cod_rescue --profile openrouter-nemotron-free check-provider     # non-billable checks
.\.venv\Scripts\python -m cod_rescue --profile openrouter-nemotron-free eval --mode live --scenario S01 -v
```
Hugging Face router and OpenAI are configuration-only templates (untested). See [docs/PROVIDERS.md](docs/PROVIDERS.md).

## What the agent guarantees (enforced in code, not by the prompt)
- Never marks an order ready without an explicit, **version- and content-bound** confirmation; "تمام" counts only as the direct reply to the latest summary.
- Offers only **verified in-stock** alternatives; never substitutes automatically.
- Never invents address fields (values must appear in the customer's own words), prices, fees, delivery dates or completed actions.
- Holds **both** possible duplicate orders; clears only on explicit, pair-bound "both" evidence; never cancels or merges.
- Never edits `READY_FOR_DISPATCH`/`SHIPPED`/`DELIVERED`/`CANCELLED` orders (DB triggers as backstop); escalates instead.
- Idempotent events and readiness commit (stable operation IDs; timeout recovery via ledger; no double stock allocation).
- Hard per-event limits: model calls, tool calls, invalid actions, wall time, tokens, cost. Every failure fails closed and escalates.

## Verified today vs future enhancements
| Verified (evidence in this repo) | How |
|---|---|
| Business rules BR-01…BR-06, guarded tools, DB lifecycle triggers, idempotency, concurrency | Automated tests (`python -m pytest`) |
| Full agent loop, tool allowlist, fail-closed errors, budgets, prompt-injection guards | 25 REPLAY scenarios (scripted model turns) |
| Real-model tool use in Egyptian Arabic for confirmation, alternative selection, duplicate escalation | 3 saved LIVE runs (S01, S02, S11) — [evidence](docs/LIVE-EVIDENCE.md) |
| Provider-agnostic LLM layer (Anthropic, OpenAI-compatible/OpenRouter) | Offline adapter tests; LIVE on OpenRouter only |
| Dashboard (Judge Lab, Business Owner, Operator Workspace) | UI smoke tests; manual QA |

**Not verified / not claimed:** real SME time savings, revenue or conversions (see the [projection](docs/IMPACT.md)), the other 22 scenarios on a real model, production deployment.
**Future enhancements (not implemented):** feedback-driven learning from human-reviewed corrections, token-efficiency work, cost optimisation and provider benchmarking, latency optimisation.

## Repository map
| Path | Contents |
|---|---|
| `cod_rescue/services.py`, `policy.py`, `tools.py` | Deterministic services, policy engine, guarded write tools |
| `cod_rescue/agent/` | Agent runtime, tool allowlist, prompts, templates, evaluation |
| `cod_rescue/agent/providers/` | Provider adapters (Anthropic, OpenAI-compatible, Replay) and capability checks |
| `dashboard/app.py`, `cod_rescue/dashboard_service.py` | COD Rescue Control Center (Streamlit UI + service layer) |
| `config/settings.toml` | Profiles, budgets, labelled simulation assumptions |
| `data/fixtures/`, `data/scenarios/` | Synthetic orders/catalog; evaluation scenarios |
| `evidence/live/`, `scripts/build_live_evidence.py` | Version-controlled, sanitized saved LIVE evidence and the script that builds it from local results |
| `docs/` | [Traceability](docs/TRACEABILITY.md), [simulation assumptions](docs/SIMULATION-ASSUMPTIONS.md), [agent runtime](docs/AGENT-RUNTIME.md), [providers](docs/PROVIDERS.md), [dashboard](docs/DASHBOARD.md), [Live evidence](docs/LIVE-EVIDENCE.md), [impact](docs/IMPACT.md) |

## Original context pack
The business specification this MVP implements (BR-01…BR-06 are approved **proposed MVP rules**, not validated policies of a real merchant):
`PROJECT-BRIEF.md` (problem, SME, scope) · `REQUIREMENTS.md` (rules, decision table, acceptance criteria) · `TEST-SCENARIOS.md` (TC-01…TC-16) · `QUALITY-CHECKLIST.md` (webinar-derived engineering checks) · `HACKATHON-SUBMISSION.md` (deliverables, judging) · `AGENT-ARCHITECTURE.md` · `AGENTS.md` (builder working agreement) · `WEBINAR-NOTES-SOURCE.md` (source notes).
Open business questions are implemented as configurable, labelled simulation assumptions — never as merchant policy.
