# Traceability: BR → DT → AC → TC

Test case definitions are those of `TEST-SCENARIOS.md`, unchanged. **Result** shows actual executed outcomes only; `NOT RUN` means the behaviour has not been implemented or tested yet.

## Rule map

| Rule | Decision table | Acceptance | Test cases |
|---|---|---|---|
| BR-01 Inventory | DT-03, DT-11, DT-13 | AC-01 | TC-02, TC-03, TC-04 |
| BR-02 Customer/address | DT-02 | AC-02 | TC-05, TC-06 |
| BR-03 Pricing | DT-04, DT-05 | AC-03 | TC-07, TC-08 |
| BR-04 Confirmation | DT-01, DT-05, DT-06, DT-12 | AC-04 | TC-01, TC-09, TC-10 |
| BR-05 Duplicates | DT-07, DT-08 | AC-05 | TC-11, TC-12 |
| BR-06 Lifecycle | DT-09, DT-10 | AC-06 | TC-13, TC-14 |
| Engineering (webinar-derived) | DT-14 | AC-07 | TC-15, TC-16 |

## Test cases

| TC | Scenario (from TEST-SCENARIOS.md) | Fixture | Rules | Replay result | Live result |
|---|---|---|---|---|---|
| TC-01 | Complete valid order → READY exactly once | ORD-1001 | BR-01..04, DT-01 | NOT RUN | NOT RUN |
| TC-02 | Size unavailable → HOLD, verified options | ORD-1002 | BR-01, DT-03, AC-01 | NOT RUN | NOT RUN |
| TC-03 | Customer picks offered alternative | ORD-1002 | BR-01, BR-04, DT-05 | NOT RUN | NOT RUN |
| TC-04 | Stock changes before commit | ORD-1003 | BR-01, DT-13 | NOT RUN | NOT RUN |
| TC-05 | Address missing details → HOLD | ORD-1004 | BR-02, DT-02, AC-02 | NOT RUN | NOT RUN |
| TC-06 | Valid context-aware address supplied | ORD-1004 | BR-02 | NOT RUN | NOT RUN |
| TC-07 | Governorate change → recalculated total | ORD-1005 | BR-03, DT-05, AC-03 | NOT RUN | NOT RUN |
| TC-08 | Price/shipping source error → HOLD | ORD-1006 | BR-03, DT-04, DT-11 | NOT RUN | NOT RUN |
| TC-09 | Direct "تمام" after latest request | ORD-1007 | BR-04, AC-04 | NOT RUN | NOT RUN |
| TC-10 | Ambiguous / post-edit "تمام" | ORD-1007 | BR-04, DT-06, DT-12 | NOT RUN | NOT RUN |
| TC-11 | Two near-identical orders → both HOLD | ORD-1008, ORD-1009 (control: ORD-1010) | BR-05, DT-07, AC-05 | NOT RUN | NOT RUN |
| TC-12 | Customer confirms both intended | ORD-1008, ORD-1009 | BR-05, DT-08 | NOT RUN | NOT RUN |
| TC-13 | READY_FOR_DISPATCH change request | ORD-1011 | BR-06, DT-09, AC-06 | NOT RUN | NOT RUN |
| TC-14 | SHIPPED/DELIVERED/CANCELLED change request | ORD-1012..1014 | BR-06, DT-10, AC-06 | NOT RUN | NOT RUN |
| TC-15 | Same event delivered twice | ORD-1001 | DT-14 | NOT RUN | NOT RUN |
| TC-16 | Commit timeout after possible success | ORD-1015 | AC-07 | NOT RUN | NOT RUN |

Decision (Slice 1 review): `TEST-SCENARIOS.md` is the source of truth and tests are never renumbered — TC-13 = READY_FOR_DISPATCH change request, TC-14 = SHIPPED/DELIVERED/CANCELLED change request, TC-15 = repeated event / idempotency, TC-16 = commit timeout recovery.

## Slice 1 evidence (foundations only, not acceptance results)
`tests/test_slice1_smoke.py` verifies that fixtures exist for every TC-01..TC-16 and that the initial data matches the AC preconditions (XL=0/L>0, the AC-02 raw address, 810 = 750 + 60, an OPEN request bound to version 3, Matrouh without a rate, lifecycle orders). These are **data checks**, not tests of agent behaviour.
