# COD Order Rescue Agent — Project Brief

**Status:** Business scope agreed for hackathon MVP; real SME validation pending  
**Track:** Agents at Work, Egyptian SME use case  
**Source basis:** Team business-discovery decisions; `sessions_notes.md` (three webinar notes); user-supplied hackathon program details.

## Problem and target SME
- **Sector:** Egyptian small e-commerce businesses.
- **MVP niche:** Small clothing shops taking cash-on-delivery (COD) orders through social channels such as Instagram and WhatsApp.
- **Example SME:** *StyleHub Egypt* is a **fictional test persona**, not a verified customer.
- **Problem hypothesis:** Manual verification of COD orders before dispatch can consume staff time and create risk of orders shipping with missing addresses, outdated variants, unconfirmed prices, or unresolved duplicates.
- **Validation status:** This problem statement is a hypothesis, not a quantified claim from a real merchant.

## Product vision versus MVP
- **Long-term vision:** E-commerce operations assistance across order intake, delivery exceptions and returns.
- **In-scope MVP:** Pre-dispatch COD verification and exception handling only: understand customer messages; verify stock, customer data, prices and shipping; resolve safe ambiguities; detect potential duplicates; request final confirmation; produce dispatch-readiness decision; escalate when needed.
- **Out of scope:** Shipment tracking after dispatch; carrier reattempts/failed-delivery recovery; post-shipment returns and exchanges; refunds; collecting payments; real tax invoices; fully autonomous cancellation/merging; production integrations that the team has not implemented or authorized.

## Users and participants
- Customer: responds to clarification and confirms order.
- Shop operations / customer service employee: resolves escalations and manages fulfillment.
- Agent: coordinates safe verification; **does not invent data or override shop policies**.
- Data/tools: order store, inventory source, pricing/shipping source, message channel (can be simulated).

## Core workflow (To-Be, proposed)
1. Receive an existing unverified COD order and customer messages.
2. Read the latest order record and lifecycle status; refuse unsupported mutations.
3. Check for possible duplicate orders and unresolved conflicts.
4. Validate product, variant, quantity and current stock.
5. Extract and validate contact/address fields without fabrication.
6. Calculate item price, verified delivery fee, permitted discounts and COD total from authoritative data.
7. Ask targeted clarification questions, if required, and apply only customer-authorized changes.
8. Produce a **version-bound final order summary** and ask for explicit confirmation.
9. Re-check lifecycle state, version, stock and all business rules immediately before marking ready; apply safe inventory reservation/commit if provided by the actual order system.
10. Output `READY_FOR_DISPATCH`, `ON_HOLD` or `ESCALATE_TO_HUMAN` with reason and auditable evidence.

## Outcomes and impact
- **Business KPIs to measure:** staff active handling minutes per order; correct resolution rate; percentage of orders reaching verified readiness; avoided invalid-ready decisions; human escalation rate; cost per verified order.
- **Do not claim measured merchant savings or extra revenue without merchant data.** Simulated results must be labeled as simulations; illustrative ROI assumptions must be visible.

## Open business questions
- Merchant-specific address and delivery eligibility rules.
- Duplicate-candidate window and matching logic.
- Maximum clarification attempts and timeouts.
- Source of truth for inventory reservation and price-lock policy.
- Available real integrations, permissions, and participating merchant.
- Whether customer-facing messages are sent in a real channel or simulation (MVP default: simulation).
