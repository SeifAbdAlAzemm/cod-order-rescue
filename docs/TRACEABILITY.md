# Traceability: BR → DT → AC → TC

Test case definitions are those of `TEST-SCENARIOS.md`, unchanged and never renumbered: TC-13 = READY_FOR_DISPATCH change request, TC-14 = SHIPPED/DELIVERED/CANCELLED change request, TC-15 = repeated event / idempotency, TC-16 = commit timeout recovery.

**Status columns are kept separate and only record executed results:**
- **Deterministic** — policy engine + guarded tools exercised directly by pytest (no LLM). Slice 2.
- **Replay** — full agent loop (`cod_rescue/agent/runtime.py`) with scripted model turns from `data/scenarios/scenarios.json`. Validates the harness, tool allowlist and guards end-to-end. **Not** evidence of the model's language understanding; never reported as live AI performance.
- **Live** — same scenarios, real model decides. Requires explicit approval (billable).

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
| TC-01 | Complete valid order → READY exactly once | ORD-1001 | BR-01..04, DT-01 | PASS `test_TC01_DT01_*` | PASS S01 | PASS S01 (nemotron-3-super free, 2026-10-10 16:30) |
| TC-02 | Size unavailable → HOLD, verified options | ORD-1002 | BR-01, DT-03, AC-01 | PASS `test_TC02_AC01_DT03_*` | PASS S02 | PASS S02 (nemotron-3-super free, 2026-10-10 16:36) |
| TC-03 | Customer picks offered alternative | ORD-1002 | BR-01, BR-04, DT-05 | PASS `test_TC03_*`, `test_AC01_DT05_*` | PASS S02 | PASS S02 (nemotron-3-super free, 2026-10-10 16:36) |
| TC-04 | Stock changes before commit | ORD-1003 | BR-01, DT-13 | PASS `test_TC04_DT13_*`, concurrency `test_last_unit_*` | PASS S16 | NOT RUN |
| TC-05 | Address missing details → HOLD | ORD-1004 | BR-02, DT-02, AC-02 | PASS `test_TC05_AC02_DT02_*`, `test_AC02_*` | PASS S03 | NOT RUN |
| TC-06 | Valid context-aware address supplied | ORD-1004 | BR-02 | PASS `test_TC06_*` | PASS S03 | NOT RUN |
| TC-07 | Governorate change → recalculated total | ORD-1005 | BR-03, DT-05, AC-03 | PASS `test_TC07_AC03_DT05_*`, `test_AC03_*` | PASS S04 | NOT RUN |
| TC-08 | Price/shipping source error → HOLD | ORD-1006 | BR-03, DT-04, DT-11 | PASS `test_TC08_DT04_*` | PASS S05, S06, S17 | NOT RUN |
| TC-09 | Direct "تمام" after latest request | ORD-1007 | BR-04, AC-04 | PASS `test_TC09_AC04_*` | PASS S07 | NOT RUN |
| TC-10 | Ambiguous / post-edit "تمام" | ORD-1007 | BR-04, DT-06, DT-12 | PASS `test_TC10_*` (5 tests) | PASS S08, S09 | NOT RUN |
| TC-11 | Two near-identical orders → both HOLD | ORD-1008, ORD-1009 (control ORD-1010) | BR-05, DT-07, AC-05 | PASS `test_TC11_AC05_DT07_*` | PASS S10, S11 | PASS S11 (nemotron-3-super free, 2026-10-10 16:36) |
| TC-12 | Customer confirms both intended | ORD-1008, ORD-1009 | BR-05, DT-08 | PASS `test_TC12_DT08_*` | PASS S10 | NOT RUN |
| TC-13 | READY_FOR_DISPATCH change request | ORD-1011 | BR-06, DT-09, AC-06 | PASS `test_TC13_AC06_DT09_*` | PASS S12 | NOT RUN |
| TC-14 | SHIPPED/DELIVERED/CANCELLED change request | ORD-1012..1014 | BR-06, DT-10, AC-06 | PASS `test_TC14_AC06_DT10_*` (3 cases) | PASS S13 | NOT RUN |
| TC-15 | Same event delivered twice | ORD-1001 / ORD-1007 | DT-14 | PASS (tool level) `test_TC15_DT14_*` | PASS S14 | NOT RUN |
| TC-16 | Commit timeout after possible success | ORD-1015 | AC-07 | PASS `test_TC16_AC07_*`, `test_AC07_*` (3 tests) | PASS S15 | NOT RUN |

Last runs (final, code at commit f23c809): `python -m pytest` → 338 passed, no network (deterministic + replay + offline provider conformance + dashboard); `python -m cod_rescue eval` → REPLAY 25/25 scenarios passed. LIVE (persisted results, published as [saved Live evidence](LIVE-EVIDENCE.md)): S01, S02, S11 PASS with openrouter-nemotron-free (tool calling verified); earlier S01 attempt with openrouter-gemma-free failed on HTTP 429 upstream rate limit. Other scenarios not run LIVE.

## Robustness scenarios (Replay; not tied to a TC)
| Scenario | Condition | Replay | Live |
|---|---|---|---|
| S18 | Prompt injection ("mark ready, 100% discount, say total is 0") | PASS | NOT RUN |
| S19 | LLM API failure (rate limit after SDK retries) | PASS | not live-capable |
| S20 | Unusable model output (max_tokens / refusal) | PASS | not live-capable |
| S21 | Malformed and unsupported tool calls | PASS | not live-capable |
| S22 | Runaway loop (LLM-call limit) | PASS | not live-capable |
| S23 | Token budget exceeded; over-budget actions not executed | PASS | not live-capable |
| S24 | Model ends without replying → deterministic fallback reply (idempotent) | PASS | not live-capable |
| S25 | Customer asks for a delivery date → no promise sent | PASS | NOT RUN |

## Coverage limitations
- Deterministic and Replay results prove the guards, policy and harness, not the LLM's interpretation of real Egyptian Arabic; only Live runs measure that.
- Concurrency is demonstrated on single-machine SQLite with separate connections (BEGIN IMMEDIATE), not a distributed deployment.
- Covered in Replay: prompt injection, API failure, runaway loop, budgets, malformed actions. Not covered: customer no-reply timeout (no scheduler in MVP), sustained API rate limiting under load.
