# Impact: methodology and report

This report separates four kinds of statements. Only the first two are measurements.

| Kind | What it is | Source |
|---|---|---|
| **Measured (technical)** | Model calls, tool calls, tokens, model-call latency, run time, scenario PASS/FAIL | Saved LIVE evidence ([LIVE-EVIDENCE.md](LIVE-EVIDENCE.md), `evidence/live/*.json`) |
| **Measured (cost)** | Cost reported by the provider (OpenRouter usage accounting) and locally estimated cost | Same snapshot |
| **Projection** | Staff time and money a shop *might* save, from stated assumptions | Calculation below — **not observed** |
| **Not measured** | Real SME time savings, revenue, conversions, failed-delivery reduction | Requires a pilot with a real merchant |

The project runs on **synthetic data with simulated messaging**. No real orders, customers or merchants were involved, and **no revenue gain, conversion uplift or verified human time saving is claimed.**

## 1. Measured technical results (LIVE)
Source: 3 recorded LIVE scenarios with `nvidia/nemotron-3-super-120b-a12b:free` via OpenRouter on 2026-10-10 (S01 complete confirmation, S02 out-of-stock with customer-chosen alternative, S11 possible duplicates where the customer wants only one). **All 3 passed their assertions.**

| Metric | Value |
|---|---|
| Customer messages processed (events) | 7 |
| Model calls / tool calls | 22 / 15 (mean 3.1 / 2.1 per message) |
| Input / output tokens | 71,610 / 4,172 (mean 10,230 / 596 per message) |
| Model-call latency | 842–5,297 ms per call, mean 2,285 ms |
| Model time vs total run time | 50,269 ms of 50,779 ms (≈99% of run time is waiting for the model) |
| Agent processing per order (all its messages) | S01 16.8 s · S02 18.2 s · S11 15.8 s |
| Provider-reported cost | **$0.00** on all 7 messages (free model) |
| Locally estimated cost | $0.00 (verified zero price) |
| Safety blocks during LIVE | 1 (a premature `record_confirmation` refused with `NOT_DIRECT_REPLY`) |
| Escalations to staff | 1 (S11: customer wanted only one of two possible-duplicate orders) |
| Deterministic fallback replies | 0 |

"Agent processing per order" is machine time while the agent works on each customer message. It is **not** the elapsed time to verify an order, which depends on how fast the customer replies.

Supporting (non-model) evidence: the automated test suite (deterministic rules, guards, concurrency, idempotency) and 25 REPLAY scenarios (full agent loop with scripted model turns). REPLAY numbers are **not** model performance and are excluded from the figures above.

## 2. Cost: measured vs projected
- **Measured:** $0 provider-reported cost. This reflects a free, rate-limited endpoint (one earlier free-model attempt hit an upstream HTTP 429). It is **not** representative of a production setup.
- **Projection, paid model:** applying the configured `anthropic-haiku` prices ($0.10 / $0.50 per 1M tokens) to the measured mean of 10,230 input / 596 output tokens per message gives ≈ **$0.0013 per message**. At 7 messages per 3 orders (≈2.3 per order) that is ≈ **$0.003 per order**. Caveats: a different model tokenizes differently and may need a different number of calls; prices change; this is an estimate, not spend.

## 3. Projection: staff time (illustrative, not observed)
The question is how many minutes of human attention one COD order needs before dispatch, with and without the agent. **None of the inputs below has been measured in a real shop.**

**Assumptions (replace with measured values from a pilot):**

| ID | Assumption | Base | Range | Why it is uncertain |
|---|---|---|---|---|
| A1 | Manual verification time per order *M* (read chat, check stock/address/price, send summary, confirm, update sheet) | 5 min | 3–8 min | Hypothesis; never timed |
| A2 | Orders per month *N* | 300 | 150–600 | Hypothetical small shop |
| A3 | Share of orders the agent escalates *e* | 20% | 10–40% | The LIVE sample (1 of 3 escalated) is curated and far too small to be a rate |
| A4 | Human time per escalated order *H* | = *M* | — | Conservative: escalation costs as much as manual handling |
| A5 | Human spot-check per agent-handled order *R* | 0.5 min | 0.5–1 min | Assumed review practice |
| A6 | Loaded staff cost *C* | 50 EGP/hour | — | Placeholder; use the shop's real figure |

**Formula** (from HACKATHON-SUBMISSION.md):
```
human_minutes_with_agent = e × H + (1 − e) × R
monthly_saved_hours      = N × (M − human_minutes_with_agent) / 60
monthly_staff_value      = monthly_saved_hours × C
net_monthly_value        = monthly_staff_value − model_costs − hosting − messaging − other costs
```

**Base case:** human minutes with agent = 0.2 × 5 + 0.8 × 0.5 = 1.4 min, so the saving is 5 − 1.4 = 3.6 min per order. 300 × 3.6 / 60 = **18 staff-hours per month** (projection). At 50 EGP/hour that is 900 EGP per month, before model, hosting and messaging costs (model cost at the paid-model estimate: 300 × $0.003 ≈ $0.9 per month). Hosting and WhatsApp/Instagram API costs are not included because nothing is deployed.

**Sensitivity:**

| Case | N | M | e | R | Saved per order | Saved hours / month |
|---|---|---|---|---|---|---|
| Low | 150 | 3 min | 40% | 1 min | 3 − (1.2 + 0.6) = 1.2 min | **3 h** |
| Base | 300 | 5 min | 20% | 0.5 min | 3.6 min | **18 h** |
| High | 600 | 8 min | 10% | 0.5 min | 8 − (0.8 + 0.45) = 6.75 min | **67.5 h** |

The range is wide on purpose. The result depends mostly on M and e, which only a real pilot can establish.

## 4. Not yet measured (and how to measure it)
| Potential impact | Status | How to measure |
|---|---|---|
| Staff time saved | Projection only | Time-and-motion baseline on ≥50 real orders; then agent in shadow mode (agent proposes, human acts); compare human minutes per order |
| Escalation rate *e* | Unknown | Share of real orders the agent escalates over ≥2 weeks |
| Invalid-ready orders avoided (wrong size or address, unconfirmed price) | Not measured | Audit dispatched orders before vs after; count orders that would have shipped with a defect |
| Failed COD deliveries / returns | Not measured | Merchant delivery and return records, before vs after |
| Revenue / conversion | Not claimed | Needs attributable merchant data; out of scope for this MVP |
| Cost per safely resolved order | Partly (tokens measured) | Real provider bills ÷ orders that reached READY without human help |

## 5. What the evidence supports today
- A working agent that, in 3 recorded LIVE runs on synthetic orders, completed confirmation, alternative-selection and duplicate-escalation flows correctly, at about 2.3 s per model call and $0 on a free model, with one premature action caught by the deterministic guards.
- Safety behaviour (version-bound confirmation, duplicate holds, lifecycle locks, idempotency, fail-closed errors) verified by the automated tests and REPLAY scenarios.
- Business impact stated here is **projected from assumptions**. Validating it needs a pilot with a real Egyptian SME.
