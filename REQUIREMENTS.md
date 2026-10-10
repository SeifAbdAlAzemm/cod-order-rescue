# Requirements and Business Rules — COD Order Rescue MVP

**Legend:** `APPROVED` means user-approved **MVP proposal**, **not** verified policy of a real merchant. `PROPOSED` means design elaboration subject to review.

## Approved business rules
| Rule | Business rule | Handling if unmet |
|---|---|---|
| BR-01 | Product, variant/size and quantity must be currently available. If out of stock, offer **verified** alternatives; change only with customer's permission; re-check stock and reconfirm final order before Ready. | `ON_HOLD`; request selection; never substitute automatically. |
| BR-02 | Name, phone and shipping address must be sufficiently complete using **context-aware** validation. Ask for necessary missing particulars; **never fabricate an address**. | `ON_HOLD`; specific clarification. |
| BR-03 | Item prices, authorized discounts and delivery charges must come from trustworthy sources. Recalculate on changes and reconfirm changed total; if unavailable/untrusted, do not guess. | `ON_HOLD`. |
| BR-04 | Customer must explicitly confirm latest final summary. A direct, unambiguous “تمام” is acceptable **only** in direct response to the latest clearly phrased confirmation request and if no subsequent changes. | `ON_HOLD`; new summary/confirmation after material change. |
| BR-05 | If two distinct orders are possible duplicates, put **both** on hold and ask if the customer intended both. **Never auto-cancel or merge.** | `ON_HOLD`; escalate if unresolved. |
| BR-06 | Auto-edits are allowed only in permitted pre-dispatch states (`PENDING`, `VERIFIED`) subject to controls. For `READY_FOR_DISPATCH`, **no automatic edit**, log request and escalate. Do not change `SHIPPED`, `DELIVERED`, `CANCELLED` in MVP. | `ESCALATE_TO_HUMAN` for Ready-stage changes; block prohibited changes. |

## Separate concepts
- **Order lifecycle:** `PENDING`, `VERIFIED`, `READY_FOR_DISPATCH`, `SHIPPED`, `DELIVERED`, `CANCELLED` (simplified **proposed** test model).
- **Agent outcome:** `READY_FOR_DISPATCH`, `ON_HOLD`, `ESCALATE_TO_HUMAN`. Outcome is not a replacement for the order's authoritative lifecycle state.
- **Idempotency:** duplicate arrival of the **same event** is distinct from two **different but similar orders**.

## Decision table (implementation candidates)
| ID | Condition / trigger | Required action | Outcome |
|---|---|---|---|
| DT-01 | All checks pass, valid latest confirmation and safe final commit | Revalidate state/version/stock; commit at most once | READY_FOR_DISPATCH |
| DT-02 | Incomplete or ambiguous address | Ask precise missing details | ON_HOLD |
| DT-03 | Requested stock unavailable | Fetch and propose verified options; require choice | ON_HOLD |
| DT-04 | Price/shipping rate missing or untrusted | Never guess | ON_HOLD |
| DT-05 | Amount changes | Send recalculated summary; invalidate prior confirmation | ON_HOLD |
| DT-06 | Missing/stale/ambiguous confirmation | Ask for confirmation of latest version | ON_HOLD |
| DT-07 | Distinct orders flagged as possible duplicates | Hold both; ask customer | ON_HOLD |
| DT-08 | Customer clearly confirms both separate orders | Clear duplicate flag only; reevaluate each independently | REEVALUATE |
| DT-09 | `READY_FOR_DISPATCH` receives change request | Do not modify; log and refer to staff | ESCALATE_TO_HUMAN |
| DT-10 | `SHIPPED`, `DELIVERED` or `CANCELLED` receives change request | Reject automatic mutation; explain/refer when useful | BLOCK / ESCALATE |
| DT-11 | Inventory service unavailable | Do not assume inventory | ON_HOLD |
| DT-12 | Unclear reply | Ask clarification | ON_HOLD |
| DT-13 | Stock changed at final check | Stop commit; return to stock discussion | ON_HOLD |
| DT-14 | Exact same technical event delivered twice | Return saved result; no repeated side effects | IDEMPOTENT |

**Proposed evaluation precedence:** prohibit impermissible lifecycle changes first → assess duplicate conflict → verify required sources & information → require current confirmation → perform final guarded readiness commit. This ordering is **not yet a merchant-approved rule**.

## Acceptance criteria (Given / When / Then)
**AC-01 Inventory:** Given requested XL is out of stock and L is available, when evaluating order, then never mark XL ready; suggest only verified L; do not modify without customer selection; invalidate stale confirmation; re-check and safely allocate stock at commit.

**AC-02 Customer/address:** Given “الشرقية، الزقازيق، عند مسجد الفتح”, when checking shipping suitability, then extract only supplied fields; ask targeted question for the missing details required by configured delivery rules; hold until verified.

**AC-03 Pricing:** Given previously accepted COD total of 810 EGP, when destination changes, then recompute from approved data, show any change, invalidate prior confirmation; if rate lookup fails, hold without guessing.

**AC-04 Confirmation:** Given confirmation request clearly presents latest version 3, when customer immediately responds “تمام” with no intervening change or ambiguity, then accept for version 3 only; never reuse on version 4.

**AC-05 Duplicate:** Given two distinct similar orders, when potential duplicate is flagged, then hold both, clarify intent, auto-cancel neither; after explicit confirmation of both, independently re-evaluate both.

**AC-06 Lifecycle:** Given READY_FOR_DISPATCH order, when customer asks to change size, then do not auto-edit; log and escalate; never claim completed change. SHIPPED, DELIVERED and CANCELLED are likewise not modified.

**AC-07 Failure recovery (WEBINAR-DERIVED engineering requirement):** Given readiness transaction timed out, when retried, then look up prior result using stable operation ID; prevent double reservation/commit; if outcome cannot be established, stop and escalate.

## Design assumptions requiring explicit decisions
- Possible duplicate matching fields/time window: **TBD** (not agreed).
- Clarification retry count and reminder cadence: **TBD**.
- Address validation details for private houses/buildings, landmarks, zones: **TBD**.
- Stock allocation concurrency semantics: **TBD**, must be safe under simultaneous requests.
- Price changes mid-conversation and quote validity: **TBD**.
- Actual channels/integrations: **TBD**, default mock tools.

**Never silently implement one of these open decisions as if it were merchant policy.** For MVP mock demonstration, document a labeled simulation assumption and make it configurable.
