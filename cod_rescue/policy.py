"""Deterministic policy engine: the only component that decides an order's agent outcome.

Precedence (REQUIREMENTS.md, proposed): lifecycle → duplicates → sources & data → confirmation → commit.
`evaluate` is read-only. Outcome READY_FOR_DISPATCH is reported only for orders whose
authoritative lifecycle is already READY_FOR_DISPATCH; an order that passes every check gets
outcome=None with next_action=COMMIT_READY, because only the guarded commit may make it ready.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from cod_rescue.context import ToolContext
from cod_rescue.errors import ExternalSourceError
from cod_rescue.services import (
    LOCKED_STATES, check_stock, compute_quote, find_duplicate_candidates, list_alternatives, load_order,
    open_duplicate_flags, summary_hash, validate_customer,
)

READY = "READY_FOR_DISPATCH"
ON_HOLD = "ON_HOLD"
ESCALATE = "ESCALATE_TO_HUMAN"

_SOURCE_REASON = {"inventory": "INVENTORY_UNAVAILABLE", "prices": "PRICE_SOURCE_UNAVAILABLE",
                  "shipping_rates": "SHIPPING_SOURCE_UNAVAILABLE"}


@dataclass
class Decision:
    order_id: str
    version: int
    lifecycle_state: str
    outcome: str | None              # READY_FOR_DISPATCH | ON_HOLD | ESCALATE_TO_HUMAN | None (= commit pending)
    reasons: list[str]
    next_action: str                 # COMMIT_READY | REQUEST_CONFIRMATION | AWAIT_CONFIRMATION | OFFER_ALTERNATIVES
                                     # | ASK_CLARIFICATION | ASK_DUPLICATE_INTENT | HOLD_FOR_SOURCE | ESCALATE | NONE
    blocked: bool = False            # an attempted mutation was refused by lifecycle policy
    error_class: str | None = None   # TOOL_ERROR when an authoritative source failed
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(ctx: ToolContext, order_id: str, change_requested: bool = False) -> Decision:
    conn, settings = ctx.conn, ctx.settings
    o = load_order(conn, order_id)

    def decision(outcome, reasons, next_action, **kw):
        return Decision(o.order_id, o.version, o.lifecycle_state, outcome, reasons, next_action, **kw)

    # 1. Lifecycle (BR-06, DT-09, DT-10)
    if o.lifecycle_state in LOCKED_STATES:
        return decision(ESCALATE, ["LIFECYCLE_LOCKED"], "ESCALATE", blocked=change_requested)
    if o.lifecycle_state == READY:
        if change_requested:
            return decision(ESCALATE, ["READY_CHANGE_REQUIRES_HUMAN"], "ESCALATE", blocked=True)
        return decision(READY, ["ALREADY_READY"], "NONE")

    # Stop condition (SA-05)
    if o.clarification_attempts >= settings.simulation.clarification.max_attempts:
        return decision(ESCALATE, ["CLARIFICATION_LIMIT"], "ESCALATE")

    # 2. Duplicates (BR-05, DT-07): persisted open flags OR fresh detection both hold the order.
    duplicates = sorted(set(open_duplicate_flags(conn, o.order_id)) | set(find_duplicate_candidates(conn, settings, o)))
    if duplicates:
        return decision(ON_HOLD, ["DUPLICATE_SUSPECTED"], "ASK_DUPLICATE_INTENT", details={"duplicates": duplicates})

    # 3. Sources and data (BR-01, BR-02, BR-03)
    reasons: list[str] = []
    details: dict = {}
    source_failure = False
    try:
        bad = [l for l in check_stock(conn, settings, o.items) if not l.ok]
        for line in bad:
            reasons.append(line.reason)
            if line.reason == "OUT_OF_STOCK":
                details.setdefault("alternatives", {})[line.sku] = list_alternatives(
                    conn, settings, line.sku, line.requested)
    except ExternalSourceError as e:
        reasons.append(_SOURCE_REASON[e.source])
        source_failure = True

    customer_issues = validate_customer(conn, settings, o)
    for issue in customer_issues:
        reasons.append(issue["code"])
    if customer_issues:
        details["missing_fields"] = sorted({f for i in customer_issues for f in i["fields"]})

    quote = None
    try:
        pricing = compute_quote(conn, settings, o)
        quote = pricing.quote
        for issue in pricing.issues:
            if issue["code"] != "SHIPPING_DESTINATION_UNKNOWN" or "ADDRESS_INCOMPLETE" not in reasons:
                reasons.append(issue["code"])
    except ExternalSourceError as e:
        reasons.append(_SOURCE_REASON[e.source])
        source_failure = True

    if reasons:
        reasons = list(dict.fromkeys(reasons))
        if source_failure or any(r in ("SHIPPING_RATE_MISSING", "PRICE_MISSING") for r in reasons):
            nxt = "HOLD_FOR_SOURCE"
        elif "OUT_OF_STOCK" in reasons:
            nxt = "OFFER_ALTERNATIVES"
        else:
            nxt = "ASK_CLARIFICATION"
        return decision(ON_HOLD, reasons, nxt, error_class="TOOL_ERROR" if source_failure else None, details=details)

    # 4. Confirmation bound to current version AND content (BR-04, DT-05, DT-06)
    current_hash = summary_hash(o, quote)
    details["quote"] = asdict(quote)
    details["summary_hash"] = current_hash
    accepted = conn.execute(
        "SELECT confirmation_request_id FROM confirmation_requests WHERE order_id = ? AND status = 'ACCEPTED' "
        "AND order_version = ? AND summary_hash = ?",
        (o.order_id, o.version, current_hash),
    ).fetchone()
    if accepted:
        details["confirmation_request_id"] = accepted["confirmation_request_id"]
        return decision(None, ["ALL_CHECKS_PASSED"], "COMMIT_READY", details=details)

    reasons = ["CONFIRMATION_REQUIRED"]
    if o.quoted_total_egp is not None and o.quoted_total_egp != quote.total_egp:
        reasons.append("QUOTE_CHANGED")
        details["previous_total_egp"] = o.quoted_total_egp
    open_cr = conn.execute(
        "SELECT confirmation_request_id FROM confirmation_requests WHERE order_id = ? AND status = 'OPEN' "
        "AND order_version = ? AND summary_hash = ?",
        (o.order_id, o.version, current_hash),
    ).fetchone()
    if open_cr:
        details["confirmation_request_id"] = open_cr["confirmation_request_id"]
        return decision(ON_HOLD, reasons, "AWAIT_CONFIRMATION", details=details)
    return decision(ON_HOLD, reasons, "REQUEST_CONFIRMATION", details=details)
