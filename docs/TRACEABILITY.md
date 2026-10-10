# Traceability: BR → DT → AC → TC

Test case definitions are those of `TEST-SCENARIOS.md`, unchanged and never renumbered: TC-13 = READY_FOR_DISPATCH change request, TC-14 = SHIPPED/DELIVERED/CANCELLED change request, TC-15 = repeated event / idempotency, TC-16 = commit timeout recovery.

**Status columns are kept separate and only record executed results:**
- **Deterministic** — policy engine + guarded tools exercised directly by pytest (no LLM). Slice 2.
- **Replay** — full agent loop with a scripted LLM stand-in. Slice 3+. Never reported as live AI performance.
- **Live** — full agent loop with the real model. Slice 3+.

## Rule map

| Rule | Decision table | Acceptance | Test cases | Implemented in |
|---|---|---|---|---|
| BR-01 Inventory | DT-03, DT-11, DT-13 | AC-01 | TC-02, TC-03, TC-04 | `services.check_stock/list_alternatives`, `tools.apply_customer_change`, `tools.commit_ready` |
| BR-02 Customer/address | DT-02 | AC-02 | TC-05, TC-06 | `services.validate_customer`, grounding in `tools.apply_customer_change` |
| BR-03 Pricing | DT-04, DT-05 | AC-03 | TC-07, TC-08 | `services.compute_quote`, `policy.evaluate` |
| BR-04 Confirmation | DT-01, DT-05, DT-06, DT-12 | AC-04 | TC-01, TC-09, TC-10 | `services.summary_hash/is_unambiguous_affirmative`, `tools.request_confirmation/record_confirmation` |
| BR-05 Duplicates | DT-07, DT-08 | AC-05 | TC-11, TC-12 | `services.find_duplicate_candidates`, `tools.flag_duplicates/clear_duplicate_flag`, commit-time re-check |
| BR-06 Lifecycle | DT-09, DT-10 | AC-06 | TC-13, TC-14 | `tools.apply_customer_change`, `policy.evaluate`, DB triggers |
| Engineering (webinar-derived) | DT-14 | AC-07 | TC-15, TC-16 | `tools.ingest_event/send_message/commit_ready/resolve_commit_outcome` |

## Test cases

| TC | Scenario (TEST-SCENARIOS.md) | Fixture | Rules | Deterministic (Slice 2) | Replay | Live |
|---|---|---|---|---|---|---|
| TC-01 | Complete valid order → READY exactly once | ORD-1001 | BR-01..04, DT-01 | PASS `test_TC01_DT01_*` | NOT RUN | NOT RUN |
| TC-02 | Size unavailable → HOLD, verified options | ORD-1002 | BR-01, DT-03, AC-01 | PASS `test_TC02_AC01_DT03_*` | NOT RUN | NOT RUN |
| TC-03 | Customer picks offered alternative | ORD-1002 | BR-01, BR-04, DT-05 | PASS `test_TC03_*`, `test_AC01_DT05_*` | NOT RUN | NOT RUN |
| TC-04 | Stock changes before commit | ORD-1003 | BR-01, DT-13 | PASS `test_TC04_DT13_*`, concurrency `test_last_unit_*` | NOT RUN | NOT RUN |
| TC-05 | Address missing details → HOLD | ORD-1004 | BR-02, DT-02, AC-02 | PASS `test_TC05_AC02_DT02_*`, `test_AC02_*` | NOT RUN | NOT RUN |
| TC-06 | Valid context-aware address supplied | ORD-1004 | BR-02 | PASS `test_TC06_*` | NOT RUN | NOT RUN |
| TC-07 | Governorate change → recalculated total | ORD-1005 | BR-03, DT-05, AC-03 | PASS `test_TC07_AC03_DT05_*`, `test_AC03_*` | NOT RUN | NOT RUN |
| TC-08 | Price/shipping source error → HOLD | ORD-1006 | BR-03, DT-04, DT-11 | PASS `test_TC08_DT04_*` | NOT RUN | NOT RUN |
| TC-09 | Direct "تمام" after latest request | ORD-1007 | BR-04, AC-04 | PASS `test_TC09_AC04_*` | NOT RUN | NOT RUN |
| TC-10 | Ambiguous / post-edit "تمام" | ORD-1007 | BR-04, DT-06, DT-12 | PASS `test_TC10_*` (5 tests) | NOT RUN | NOT RUN |
| TC-11 | Two near-identical orders → both HOLD | ORD-1008, ORD-1009 (control ORD-1010) | BR-05, DT-07, AC-05 | PASS `test_TC11_AC05_DT07_*` | NOT RUN | NOT RUN |
| TC-12 | Customer confirms both intended | ORD-1008, ORD-1009 | BR-05, DT-08 | PASS `test_TC12_DT08_*` | NOT RUN | NOT RUN |
| TC-13 | READY_FOR_DISPATCH change request | ORD-1011 | BR-06, DT-09, AC-06 | PASS `test_TC13_AC06_DT09_*` | NOT RUN | NOT RUN |
| TC-14 | SHIPPED/DELIVERED/CANCELLED change request | ORD-1012..1014 | BR-06, DT-10, AC-06 | PASS `test_TC14_AC06_DT10_*` (3 cases) | NOT RUN | NOT RUN |
| TC-15 | Same event delivered twice | ORD-1001 | DT-14 | PARTIAL — tool level only `test_TC15_DT14_*` (event, outbound, change, commit idempotency). Full "no repeated outbound reply" needs the agent loop (Slice 3). | NOT RUN | NOT RUN |
| TC-16 | Commit timeout after possible success | ORD-1015 | AC-07 | PASS `test_TC16_AC07_*`, `test_AC07_*` (3 tests) | NOT RUN | NOT RUN |

Last deterministic run: Slice 2, `python -m pytest` → 155 passed (see Slice 2 report).

## Coverage limitations
- Deterministic results prove the guards and policy, not the LLM's interpretation of real customer wording; that is measured in Replay/Live.
- Concurrency is demonstrated on single-machine SQLite with separate connections (BEGIN IMMEDIATE), not a distributed deployment.
- Extra stress/security tests from `TEST-SCENARIOS.md` (prompt injection, rate limits, runaway loop, no-reply timeout) are not run yet; concurrent last-unit allocation is covered.
