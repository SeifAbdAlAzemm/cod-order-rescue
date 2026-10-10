# Instructions for Claude Code / Technical Builder

## Mission
Implement a narrowly scoped, reproducible, tested **COD Order Rescue Agent** MVP for a fictional Egyptian small clothing shop, following `PROJECT-BRIEF.md`, `REQUIREMENTS.md`, `QUALITY-CHECKLIST.md` and `HACKATHON-SUBMISSION.md`.

## Working agreement
1. **Read all project Markdown files first.** Summarize understanding and any conflicts/open decisions **before** proposing implementation.
2. **First deliver a small technical plan:** MVP workflow, tool/data contracts, simplest viable architecture, safety controls, tests, demo plan, estimated effort/cost. **Do not start coding until the user approves the plan.**
3. Keep **approved business rules unchanged**. Any open question remains explicitly `TBD` or a clearly marked/configurable **simulation assumption**.
4. Prefer **one agent + deterministic functions** to a multi-agent stack unless concrete requirements justify multi-agent complexity.
5. LLM handles language understanding and ambiguous customer intent. Deterministic code enforces amounts, stock, state transitions, authorizations, validators, retries, budgets and commits.
6. No real customer personal data, live payments, live fulfillment, shipment booking, production account mutations or outgoing communications without explicit consent, configured credentials and reviewed permissions. Use synthetic data and simulated messaging by default.
7. Never invent a stock result, customer approval, price, shipping fee or completed tool action. Fail closed or escalate.
8. Version-bound confirmations; invalidate confirmations after material edits. Re-read authoritative state before all write actions; guard concurrent writes and make mutation tools idempotent.
9. Apply least privilege, secrets via environment variables (not code/prompts), bounded iterations/retries, timeouts and logs with PII redaction.
10. **Implement incrementally:** a small testable slice, run tests, report exactly what changed and evidence of passing/failing results. Ask before architectural scope changes.
11. No unearned claims of production readiness, revenue increases, real merchant savings or a live deployment. Distinguish mock, local, deployed and production-ready.
12. Optimise for hackathon delivery: working demo, GitHub README (judge runnable <5 min), impact deck, 2–3 min video.

## Review handoff (to ChatGPT)
For each meaningful milestone return: files changed; architecture/design decisions; exact test commands/results; sample execution logs (sanitized); remaining risks/TBDs; screenshots or a short scenario transcript; token and latency/cost measurements if available.

## Things to avoid
- Expanding into post-dispatch tracking, returns, exchanges, refunds or general CRM.
- Automatically cancelling, merging or modifying READY_FOR_DISPATCH+ orders.
- Calling a reminder-only workflow an intelligent agent without showing reasoning/tool selection.
- Unlimited tool permissions, blind transaction retries, fabricated tool responses, hidden failures.
