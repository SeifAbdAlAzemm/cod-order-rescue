# Test Scenarios — Proposed MVP Test Suite

**Execution status: ALL NOT RUN.** These are planned scenarios, not test results. Synthetic orders and customer messages only.

| ID | Scenario / setup | Expected observable result | Status |
|---|---|---|---|
| TC-01 | Complete, available, current, unambiguous order with valid confirmation | READY exactly once after final checks | NOT RUN |
| TC-02 | Product size unavailable; other sizes in stock | HOLD; verified options offered; no auto-substitution | NOT RUN |
| TC-03 | Customer explicitly chooses offered available alternative | Variant updated once in permitted state; prior confirmation cleared | NOT RUN |
| TC-04 | Final inventory count changes before commit | Stop readiness; no oversell/reservation duplication | NOT RUN |
| TC-05 | Address missing required locality details | HOLD; precise clarification; no fabricated details | NOT RUN |
| TC-06 | Customer supplies a valid context-aware address | Fields extracted; configured rules pass; continue checks | NOT RUN |
| TC-07 | Delivery governorate changes from quote basis | Recalculate fee/total; fresh summary and confirmation | NOT RUN |
| TC-08 | Shipping fee or product price source errors | HOLD; no estimated/fabricated charge | NOT RUN |
| TC-09 | Direct “تمام” after latest exact confirmation request | Accept only on linked latest version | NOT RUN |
| TC-10 | “تمام” appears ambiguously or after order edit | Do not accept as confirmation; ask again | NOT RUN |
| TC-11 | Two distinct near-identical order IDs | BOTH HOLD; clarification; no automatic cancellation/merge | NOT RUN |
| TC-12 | Customer verifies both flagged orders intended | Clear duplicate concern, separately re-evaluate each | NOT RUN |
| TC-13 | READY_FOR_DISPATCH order asks for size/address change | No mutation; escalation log recorded | NOT RUN |
| TC-14 | SHIPPED/DELIVERED/CANCELLED order asks for modification | No mutation; appropriate explanation/escalation | NOT RUN |
| TC-15 | Identical delivery of event/message repeated | Same logical outcome; no repeated writes or outbound messages | NOT RUN |
| TC-16 | Readiness commit times out after possible success | Check by stable operation ID; no blind retry / double allocation | NOT RUN |

## Evidence required per case
Input fixture; initial order and inventory state; message transcript; called tools and their outputs; final authoritative order state; decision reason; assertions; elapsed time; tokens/cost where applicable.

## Extra stress / security tests (post-core if time permits)
Concurrent final allocations of last SKU; unauthorized tools; malicious instruction embedded in customer message; tool rate limit/503; runaway loop; no customer reply and configured escalation timeout.
