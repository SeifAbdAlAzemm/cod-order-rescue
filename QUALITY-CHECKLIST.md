# Quality, Evaluation & Production-Safety Checklist

**Sources:** `sessions_notes.md` webinars 01–03. These are engineering priorities and webinar notes, **not all official scoring criteria**.

## Agent functional quality
- [ ] Explicit objective, decision rights, permitted tools and stop conditions.
- [ ] All six BR rules implemented; separate LLM interpretation from deterministic validation.
- [ ] Latest order state/version is read before any mutation.
- [ ] No fabricated address, pricing, inventory or payment status.
- [ ] Two distinct possible duplicates are held pending explicit clarification.
- [ ] Ambiguous “تمام” / old confirmations never accidentally authorize dispatch.
- [ ] Human approval and escalation for risky/unsupported changes.

## Safe execution
- [ ] Durable per-order state (DB or equivalent—not only conversation memory).
- [ ] Input validation/sanitization and clear schema/tool contracts.
- [ ] Idempotency key and deduplication on each side-effecting operation.
- [ ] Concurrency safety for stock allocation/readiness transitions.
- [ ] Bounded retries, backoff, timeouts, and explicit status checks after uncertain commits.
- [ ] Explicit max tool calls/iterations, execution time and token/cost budget; safe stops.
- [ ] Secrets protected; least-privilege tool access; no credentials in prompts/repo.
- [ ] PII minimized or fictional; safe logs with correlation/order IDs.
- [ ] Dev/test separate from production; rollback/recovery documented.

## Observability and evals
- [ ] Trace steps, tool invocations, tool outcomes, state transitions and reasons.
- [ ] Capture request latency, token usage, model costs and failures per test case.
- [ ] Run all test cases from `TEST-SCENARIOS.md` and record pass/fail **with evidence**.
- [ ] Evaluate happy paths, malformed/ambiguous messages, stale state, API errors, repeated events, race conditions, stop behavior.
- [ ] Optional self-improvement loop: collect user feedback/error patterns → propose improvements → test → human approves. **Do not self-edit live rules without governance.**

## Measurement
- [ ] Baseline manual workflow defined with clockable steps.
- [ ] Agent time and residual human-review time measured on comparable samples.
- [ ] Total operating costs (tokens + infrastructure + messaging + supervision) disclosed.
- [ ] Calculations reproducible and assumptions clearly labeled.
- [ ] Real business figures vs simulation visibly separated.

## Production terminology
**Working MVP** = demonstrates function under test. **Deployment** = accessible runtime. **Production-ready** = controls validated for real use, authorized integrations, operations/recovery and appropriate privacy protections. Do not conflate these levels.

## Webinar source notes and caveats
- Webinar 01 emphasizes working agent, accuracy, efficiency, self-improvement, ROI and harness/context/tools.
- Webinar 02 emphasizes decide → tool → observe → validate → continue/stop; state, permission gates, idempotency, observability, cost and failure-safe execution. “A demo proves it can work. Production proves it can fail safely.”
- Webinar 03 emphasizes harness, skills and persistent memory (Hermes example).
- Claims about any particular platform being unable to self-improve, or that all AI agents must use a given stack, are **speaker assertions in the notes**, not requirements or validated product limitations.
