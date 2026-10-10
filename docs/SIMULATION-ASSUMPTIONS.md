# Simulation Assumptions

These fill open business questions (`REQUIREMENTS.md` → "Design assumptions requiring explicit decisions") **for the synthetic demo only**. They are **not** verified merchant policy. Each lives in `config/settings.toml` under `[simulation.*]` with `status = "SIMULATION_ASSUMPTION"`; the loader rejects any section without that label.

| ID | Topic | Assumption (configurable) | Config key | Open question it stands in for |
|---|---|---|---|---|
| SA-01 | Duplicate window | 24 hours | `simulation.duplicates.window_hours` | Duplicate-candidate window: TBD |
| SA-02 | Duplicate match | Same normalized phone **and** identical item signature (multiset of SKU/size/quantity); overlapping SKUs alone do not match; CANCELLED orders ignored | `simulation.duplicates.*` | Matching logic: TBD |
| SA-03 | Address completeness | Required: governorate, city, street, building. Optional: district, floor, apartment, landmark. A landmark never replaces street + building | `simulation.address.*` | Address rules for houses/landmarks/zones: TBD |
| SA-04 | Phone validity | Egyptian mobile `01[0125]` + 8 digits after normalization (+20 / spaces stripped) | `simulation.phone.pattern` | Contact rules: not specified |
| SA-05 | Clarification limit | 3 attempts, then `ESCALATE_TO_HUMAN`; no real-time reminders in MVP | `simulation.clarification.*` | Retry count and reminder cadence: TBD |
| SA-06 | Price changes | Prices re-read at commit; any change invalidates confirmation → ON_HOLD | `simulation.pricing.*` | Quote validity / price lock: TBD |
| SA-07 | Money | Whole EGP integers | `simulation.pricing.amounts_whole_egp` | — |
| SA-08 | Stock reservation | Stock decremented atomically at the READY commit, in the simulated order store | `simulation.inventory.reservation_point` | Inventory source of truth / reservation: TBD |
| SA-09 | Short confirmations | A short affirmative (e.g. "تمام") counts only if it is the first inbound message after the latest OPEN confirmation request, that request is bound to the current order version, and the reply contains no change. Otherwise → ask again | `simulation.confirmation.*` | Refines BR-04 mechanics |
| SA-10 | Messaging | Simulated outbox only; schema forbids any other delivery value | `simulation.messaging.mode` | Real vs simulated channel (MVP default: simulation) |
| SA-11 | Shipping fees | Invented per-governorate table; Matrouh intentionally has no rate | `data/fixtures/geography.json` | Merchant delivery eligibility and fees |
| SA-12 | Lifecycle meaning | `VERIFIED` = data checks passed, awaiting/holding customer confirmation | schema | Simplified proposed lifecycle model |
| SA-13 | Outcome mapping | Decision-table `BLOCK` → `ESCALATE_TO_HUMAN` with blocked flag; `REEVALUATE` → fresh evaluation; `IDEMPOTENT` → saved prior result returned | (Slice 2) | DT-08 / DT-10 / DT-14 outcomes outside the 3-value enum |

Test-only fault switches (`simulation.fault_injection.*`) are all `false` by default.

All orders, customers (placeholder names "عميل تجريبي N"), phone numbers, prices and stock levels are **synthetic**.
