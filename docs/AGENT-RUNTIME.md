# Agent Runtime (Slice 3)

One constrained LLM agent orchestrates the deterministic guarded tools. The model interprets the customer's Egyptian Arabic message and chooses tools; code enforces every rule.

```
customer message ─► ingest_event (dedupe by event_id) ─► agent loop ─► finalize (outcome read from DB) ─► saved result
                                                    │
     system prompt + <order_context> (policy decision) + <customer_message> (untrusted, tags escaped)
                                                    │
     model ─► allowlisted tool call ─► schema validation ─► guarded tool (re-reads state, enforces BR-01..06) ─► result
```

## Modes
| Mode | Model turns | API calls / cost | Evidence of |
|---|---|---|---|
| REPLAY | Scripted per scenario (`data/scenarios/scenarios.json`) | None / not applicable | Harness, allowlist, guards, fail-closed paths |
| LIVE | Real Claude model (`claude-haiku-5-5`, configurable) | Billable; cost estimated from measured token usage | Model's understanding and tool selection |

Runs are stored in `agent_runs` (mode, model, status, error class, calls, tokens, cost, cost basis, latency, final outcome) and `agent_steps` (every model call, tool call and stop, PII-redacted). The schema refuses a REPLAY run with a model-cost basis and vice versa. Eval reports go to `results/replay/` and `results/live/` separately.

## Tools the model may call (allowlist)
`get_order_status`, `list_alternatives`, `send_customer_message` (CLARIFICATION/INFO only, no amounts), `apply_customer_change`, `request_confirmation`, `record_confirmation`, `commit_ready`, `flag_duplicates`, `request_duplicate_intent`, `resolve_duplicate_both_intended`, `escalate_to_human`.
The model never supplies order IDs, versions or event IDs for its own order; the harness binds them.

## Stop conditions and error classes (per customer event)
| Condition | Limit | Error class |
|---|---|---|
| Model calls | 6 | BUDGET_EXCEEDED |
| Tool calls | 8 | BUDGET_EXCEEDED |
| Malformed / unknown tool calls | 2 | VALIDATION_ERROR |
| Wall time | 60 s | TIMEOUT |
| Tokens | 40k in / 12k out | BUDGET_EXCEEDED |
| Estimated cost | $0.05 | BUDGET_EXCEEDED |
| API error after SDK retries (2), refusal, truncation | — | LLM_ERROR / TIMEOUT |
| Unexpected tool/infra exception | — | TOOL_ERROR |
| Commit outcome unknown after timeout | — | TIMEOUT (escalated) |

Business-rule refusals (e.g. AMBIGUOUS_REPLY) are normal tool results the model sees, not run errors. On any error the order is escalated to staff and never made READY by an error path; an order committed earlier in the run stays READY.

## Enabling LIVE mode (requires your approval: billable)
1. Get an Anthropic API key (Console). Never put it in code, config, prompts or git.
2. Provide it via the environment, e.g. PowerShell `$env:ANTHROPIC_API_KEY = "<key>"`, or a local `.env` file (git-ignored; only `ANTHROPIC_API_KEY` and `COD_RESCUE_*` are read).
3. Verify the model ID is available to the key (Models API, not billed): `python -m cod_rescue check-model`
4. Run one scenario first: `python -m cod_rescue eval --mode live --scenario S01 -v`, then the full live suite: `python -m cod_rescue eval --mode live`.
5. Optional: `COD_RESCUE_MODEL=<id>` switches model; a price entry under `[llm.pricing_usd_per_mtok."<id>"]` is required or LIVE refuses to run.

Expected live cost (estimate, not measured): about 2–5 model calls per event at a few thousand input tokens each on `claude-haiku-5-5` ($0.10 / $0.50 per 1M tokens) — roughly $0.001–0.003 per event; the 17 live-capable scenarios (~24 events) should cost well under $0.10. Actual figures are reported by the eval.
