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
| LIVE | Real model from the active provider profile (Anthropic or OpenAI-compatible) | Local cost estimate + provider-reported cost (if any) | Model's understanding and tool selection |

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
| Per-attempt HTTP timeout | min(30 s, remaining wall budget ÷ 3) so 1 call + 2 SDK retries always fit in the remaining budget | TIMEOUT |
| Unexpected tool/infra exception | — | TOOL_ERROR |
| Commit outcome unknown after timeout | — | TIMEOUT (escalated) |

Customer-facing safety: agent free text cannot contain amounts or unverifiable commitments (delivery dates, refunds, free items, guarantees, false confirmed/shipped/cancelled claims). Critical messages are system templates (summary, duplicate question, READY notice, escalation notice). If the agent ends without replying, a deterministic idempotent fallback reply is sent.

Business-rule refusals (e.g. AMBIGUOUS_REPLY) are normal tool results the model sees, not run errors. On any error the order is escalated to staff and never made READY by an error path; an order committed earlier in the run stays READY.

## Enabling LIVE mode (requires approval when billable)
LIVE uses the active provider profile (default `anthropic-haiku`; also `openrouter-gemma-free`). Setup, pricing status, capability checks and result locations are in [PROVIDERS.md](PROVIDERS.md). In short: put the key in a git-ignored `.env`, run `python -m cod_rescue --profile <name> check-provider` (non-billable), then a single scenario with `eval --mode live --scenario S01 -v`.
