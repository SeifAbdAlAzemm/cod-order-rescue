# Agent Architecture — Decision Pending

**Not an approved stack.** Build the architecture only **after** reviewing the business requirements and confirming the available implementation environment with the user.

## Logical components (platform-agnostic)
- Interface / simulated message adapter: receives customer replies and displays proposed actions.
- Agent runtime / harness: interprets message and plans constrained next action.
- Deterministic services: order lookup, inventory lookup/reservation, address validation, price/fee calculation, duplicate-candidate detection, confirmation versioning and policy guards.
- Persistent state: order/version, conversation linkage, approvals, operations ledger, escalation status, audit log.
- Tool adapter layer: replace mocks with approved real integrations only after explicit review.
- Evaluations and telemetry: task success, latency, token cost, action logs, failures.

## Questions Claude Code must answer BEFORE building
1. Which lowest-complexity setup fits: direct code, Hermes, n8n, framework, or hybrid? Provide a short comparative argument and recommendation based on actual environment.
2. How are order versions, stale confirmations, idempotency keys and atomic stock reservations enforced?
3. What is the authoritative source of truth and what happens when it is unavailable?
4. Which parts require LLM judgment, versus cheap deterministic code?
5. How do we get judge-run setup under 5 minutes and a 2–3 minute video?
6. What would be demo-only versus truly deployed/production-ready?

## Scope boundary
**One constrained agent is the default.** Multi-agent orchestration requires demonstrated additional value and must not delay required deliverables.
