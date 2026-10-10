"""Guarded write tools: the ONLY code that mutates order state.

Every tool re-reads authoritative state inside a write-locked transaction, enforces
policy in code (callers, including the LLM, cannot override it), is idempotent, and
returns a JSON-serializable result. Business refusals are results (ok=False), not exceptions.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict

from cod_rescue.context import ToolContext
from cod_rescue.db import transaction
from cod_rescue.errors import CommitTimeout, ExternalSourceError, UnknownOrder
from cod_rescue.normalize import is_grounded, normalize_phone
from cod_rescue.policy import ESCALATE, ON_HOLD, READY, Decision, evaluate
from cod_rescue.services import (
    ADDRESS_FIELDS, EDITABLE_STATES, LOCKED_STATES, compute_quote, find_duplicate_candidates,
    is_explicit_both_intended, is_unambiguous_affirmative, load_order, outbound_violations, render_summary,
    resolve_governorate, summary_hash,
)

ALLOWED_TRANSITIONS = {
    ("PENDING", "VERIFIED"),             # checks passed, confirmation requested
    ("VERIFIED", "PENDING"),             # material change after verification
    ("PENDING", READY), ("VERIFIED", READY),  # guarded commit only
}
CHANGEABLE_FIELDS = {"customer_name", "phone_raw", "discount_code", "items", *ADDRESS_FIELDS}
MESSAGE_KINDS = {"CLARIFICATION", "INFO", "ESCALATION_NOTICE"}
MAX_MESSAGE_CHARS = 1000
MAX_ITEM_QUANTITY = 10
# Free-text messages may not state amounts; prices only appear in the deterministic summary.
_MONEY_RE = re.compile(r"\d[\d٠-٩,.]*\s*(جنيه|جنية|ج\.?م|egp|le\b|pounds?)|(جنيه|egp)\s*\d", re.IGNORECASE)


def _ok(status: str, **kw) -> dict:
    return {"ok": True, "status": status, **kw}


def _refused(status: str, **kw) -> dict:
    return {"ok": False, "status": status, **kw}


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _set_lifecycle(ctx: ToolContext, order_id: str, current: str, new: str) -> None:
    if current == new:
        return
    if (current, new) not in ALLOWED_TRANSITIONS:
        raise PermissionError(f"lifecycle transition {current} -> {new} is not permitted")
    cur = ctx.conn.execute(
        "UPDATE orders SET lifecycle_state = ?, updated_at = ? WHERE order_id = ? AND lifecycle_state = ?",
        (new, ctx.now(), order_id, current),
    )
    if cur.rowcount != 1:
        raise RuntimeError(f"{order_id}: lifecycle changed concurrently")


def _set_outcome(ctx: ToolContext, order_id: str, outcome: str, reason: str) -> None:
    """Agent outcome only (never the lifecycle). READY can only be set by commit_ready."""
    if outcome not in (ON_HOLD, ESCALATE):
        raise PermissionError("only commit_ready may set READY_FOR_DISPATCH")
    ctx.conn.execute(
        "UPDATE orders SET agent_outcome = ?, outcome_reason = ?, updated_at = ? WHERE order_id = ?",
        (outcome, reason, ctx.now(), order_id),
    )


def _open_escalation(ctx: ToolContext, order_id: str, reason_code: str, detail: str) -> int:
    row = ctx.conn.execute(
        "SELECT escalation_id FROM escalations WHERE order_id = ? AND reason_code = ? AND status = 'OPEN'",
        (order_id, reason_code),
    ).fetchone()
    if row:
        return row["escalation_id"]
    cur = ctx.conn.execute(
        "INSERT INTO escalations (order_id, reason_code, detail, created_at) VALUES (?, ?, ?, ?)",
        (order_id, reason_code, detail, ctx.now()),
    )
    ctx.audit("TOOL", "ESCALATION_OPENED", order_id, {"reason_code": reason_code, "detail": detail})
    return cur.lastrowid


def _invalidate_confirmations(ctx: ToolContext, order_id: str, reason: str) -> int:
    cur = ctx.conn.execute(
        "UPDATE confirmation_requests SET status = 'INVALIDATED', resolved_at = ? "
        "WHERE order_id = ? AND status IN ('OPEN', 'ACCEPTED')",
        (ctx.now(), order_id),
    )
    if cur.rowcount:
        ctx.audit("TOOL", "CONFIRMATIONS_INVALIDATED", order_id, {"count": cur.rowcount, "reason": reason})
    return cur.rowcount


def _lookup_operation(ctx: ToolContext, op_id: str) -> dict | None:
    if ctx.faults.ledger_unavailable:
        raise ExternalSourceError("ledger")
    row = ctx.conn.execute("SELECT result_json FROM operations WHERE op_id = ? AND status = 'SUCCEEDED'",
                           (op_id,)).fetchone()
    return json.loads(row["result_json"]) if row else None


def _record_operation(ctx: ToolContext, op_id: str, order_id: str, op_type: str, request: dict, result: dict) -> None:
    ctx.conn.execute(
        "INSERT INTO operations (op_id, order_id, op_type, status, request_json, result_json, created_at) "
        "VALUES (?, ?, ?, 'SUCCEEDED', ?, ?, ?)",
        (op_id, order_id, op_type, _canonical(request), _canonical(result), ctx.now()),
    )


def _flag_pairs(ctx: ToolContext, order_id: str, candidates: list[str]) -> None:
    hours = ctx.settings.simulation.duplicates.window_hours
    for other in candidates:
        a, b = sorted((order_id, other))
        ctx.conn.execute(
            "INSERT OR IGNORE INTO duplicate_flags (order_id_a, order_id_b, match_basis, status, created_at) "
            "VALUES (?, ?, ?, 'OPEN', ?)",
            (a, b, f"same normalized phone + identical item signature within {hours:g}h", ctx.now()),
        )
    for oid in [order_id, *candidates]:
        state = load_order(ctx.conn, oid).lifecycle_state
        if state in EDITABLE_STATES:
            _set_outcome(ctx, oid, ON_HOLD, "DUPLICATE_SUSPECTED")
        else:  # never modify a READY+/locked order; refer to staff instead
            _open_escalation(ctx, oid, "DUPLICATE_OF_NON_EDITABLE_ORDER",
                             f"possible duplicate pair with {', '.join(c for c in [order_id, *candidates] if c != oid)}")
    ctx.audit("TOOL", "DUPLICATES_FLAGGED", order_id, {"candidates": candidates})


# ---------------------------------------------------------------- events & messages

def ingest_event(ctx: ToolContext, order_id: str, event_id: str, text: str) -> dict:
    """Record an inbound customer message once. A redelivered event_id returns the saved result (DT-14)."""
    if not event_id or not text or not text.strip():
        return _refused("INVALID_EVENT")
    try:
        with transaction(ctx.conn):
            existing = ctx.conn.execute("SELECT * FROM messages WHERE event_id = ?", (event_id,)).fetchone()
            if existing is None:
                load_order(ctx.conn, order_id)
                cur = ctx.conn.execute(
                    "INSERT INTO messages (order_id, direction, kind, body, event_id, created_at) "
                    "VALUES (?, 'INBOUND', 'CUSTOMER', ?, ?, ?)",
                    (order_id, text.strip(), event_id, ctx.now()),
                )
                ctx.audit("TOOL", "EVENT_INGESTED", order_id, {"event_id": event_id, "body": text})
                return _ok("RECORDED", event_id=event_id, seq=cur.lastrowid)
    except UnknownOrder:
        return _refused("UNKNOWN_ORDER", order_id=order_id)
    except sqlite3.IntegrityError:  # same event inserted concurrently by another worker
        existing = ctx.conn.execute("SELECT * FROM messages WHERE event_id = ?", (event_id,)).fetchone()
    if existing["order_id"] != order_id:
        return _refused("EVENT_ORDER_MISMATCH", event_id=event_id)
    saved = ctx.conn.execute("SELECT result_json FROM event_results WHERE event_id = ?", (event_id,)).fetchone()
    return _ok("DUPLICATE_EVENT", event_id=event_id, seq=existing["seq"],
               saved_result=json.loads(saved["result_json"]) if saved else None)


def save_event_result(ctx: ToolContext, event_id: str, result: dict) -> None:
    """First saved result wins; replays of the event return it without new side effects."""
    ctx.conn.execute("INSERT OR IGNORE INTO event_results VALUES (?, ?, ?)",
                     (event_id, _canonical(result), ctx.now()))


def send_message(ctx: ToolContext, order_id: str, kind: str, body: str, idempotency_key: str) -> dict:
    """Queue a message in the SIMULATED outbox. Confirmation requests must use request_confirmation."""
    if kind not in MESSAGE_KINDS:
        return _refused("KIND_NOT_ALLOWED", allowed=sorted(MESSAGE_KINDS))
    if not body or not body.strip() or len(body) > MAX_MESSAGE_CHARS:
        return _refused("INVALID_BODY")
    if _MONEY_RE.search(body):
        return _refused("AMOUNTS_NOT_ALLOWED_IN_FREE_TEXT",
                        hint="prices and totals are only sent via request_confirmation")
    if not idempotency_key:
        return _refused("IDEMPOTENCY_KEY_REQUIRED")
    try:
        with transaction(ctx.conn):
            o = load_order(ctx.conn, order_id)
            existing = ctx.conn.execute("SELECT seq, order_id FROM messages WHERE idempotency_key = ?",
                                        (idempotency_key,)).fetchone()
            if existing:
                return _ok("DUPLICATE_MESSAGE", seq=existing["seq"])
            if kind == "CLARIFICATION" and o.lifecycle_state not in EDITABLE_STATES:
                return _refused("NOT_EDITABLE", lifecycle_state=o.lifecycle_state)
            violations = outbound_violations(body, o.lifecycle_state)
            if violations:
                ctx.audit("POLICY", "MESSAGE_REJECTED", order_id, {"violations": violations, "body": body})
                return _refused("OPERATIONAL_COMMITMENT_NOT_ALLOWED", violations=violations,
                                hint="do not promise delivery dates, refunds, free items, guarantees, or "
                                     "states the order is not in; say a team member will follow up")
            cur = ctx.conn.execute(
                "INSERT INTO messages (order_id, direction, kind, body, idempotency_key, created_at) "
                "VALUES (?, 'OUTBOUND', ?, ?, ?, ?)",
                (order_id, kind, body.strip(), idempotency_key, ctx.now()),
            )
            if kind == "CLARIFICATION":
                ctx.conn.execute("UPDATE orders SET clarification_attempts = clarification_attempts + 1 "
                                 "WHERE order_id = ?", (order_id,))
            ctx.audit("TOOL", "MESSAGE_QUEUED", order_id, {"kind": kind, "body": body, "delivery": "SIMULATED"})
            return _ok("QUEUED_SIMULATED", seq=cur.lastrowid, delivery="SIMULATED")
    except UnknownOrder:
        return _refused("UNKNOWN_ORDER", order_id=order_id)


# ---------------------------------------------------------------- decisions & escalation

def record_decision(ctx: ToolContext, order_id: str, change_requested: bool = False) -> dict:
    """Evaluate policy and persist a HOLD/ESCALATE agent outcome. Never sets READY."""
    try:
        with transaction(ctx.conn):
            d = evaluate(ctx, order_id, change_requested=change_requested)
            if d.outcome in (ON_HOLD, ESCALATE):
                _set_outcome(ctx, order_id, d.outcome, ",".join(d.reasons))
                if d.outcome == ESCALATE:
                    _open_escalation(ctx, order_id, d.reasons[0], _canonical(d.details) if d.details else d.reasons[0])
            ctx.audit("POLICY", "DECISION", order_id, d.to_dict())
            return _ok("EVALUATED", decision=d.to_dict())
    except UnknownOrder:
        return _refused("UNKNOWN_ORDER", order_id=order_id)


def escalate(ctx: ToolContext, order_id: str, reason_code: str, detail: str) -> dict:
    """Refer an order to staff. Changes only the agent outcome, never the lifecycle."""
    try:
        with transaction(ctx.conn):
            load_order(ctx.conn, order_id)
            esc_id = _open_escalation(ctx, order_id, reason_code, detail)
            _set_outcome(ctx, order_id, ESCALATE, reason_code)
            return _ok("ESCALATED", escalation_id=esc_id)
    except UnknownOrder:
        return _refused("UNKNOWN_ORDER", order_id=order_id)


# ---------------------------------------------------------------- customer-authorized changes

def apply_customer_change(ctx: ToolContext, order_id: str, expected_version: int, changes: dict,
                          source_event_id: str | None = None) -> dict:
    """Apply a customer-authorized change (BR-01/02/03/06).

    - Only PENDING/VERIFIED orders; READY_FOR_DISPATCH → escalate (DT-09); SHIPPED/DELIVERED/CANCELLED → block (DT-10).
    - Optimistic concurrency on `expected_version`.
    - Text values must literally appear in the customer's message (or, without an event, in the
      original order address text) — extracted data is never fabricated.
    - Item changes: same products only, active and in stock.
    - Any applied change is material: version+1, confirmations invalidated, lifecycle back to PENDING.
    """
    if not changes or not set(changes) <= CHANGEABLE_FIELDS:
        return _refused("INVALID_CHANGE_FIELDS", allowed=sorted(CHANGEABLE_FIELDS))
    op_id = "change:{}:{}:{}".format(order_id, source_event_id or "intake",
                                     hashlib.sha256(_canonical(changes).encode()).hexdigest()[:16])
    try:
        with transaction(ctx.conn):
            saved = _lookup_operation(ctx, op_id)
            if saved:
                return {**saved, "status": "DUPLICATE_OPERATION"}
            o = load_order(ctx.conn, order_id)

            if o.lifecycle_state == READY:
                esc = _open_escalation(ctx, order_id, "READY_CHANGE_REQUESTED",
                                       f"customer requested change of {sorted(changes)} after READY_FOR_DISPATCH")
                _set_outcome(ctx, order_id, ESCALATE, "READY_CHANGE_REQUIRES_HUMAN")
                ctx.audit("POLICY", "CHANGE_BLOCKED", order_id, {"state": o.lifecycle_state, "fields": sorted(changes)})
                return _refused("ESCALATED_NOT_APPLIED", blocked=True, escalation_id=esc,
                                lifecycle_state=o.lifecycle_state)
            if o.lifecycle_state in LOCKED_STATES:
                esc = _open_escalation(ctx, order_id, "LOCKED_ORDER_CHANGE_REQUESTED",
                                       f"customer requested change of {sorted(changes)} on {o.lifecycle_state} order")
                _set_outcome(ctx, order_id, ESCALATE, "LIFECYCLE_LOCKED")
                ctx.audit("POLICY", "CHANGE_BLOCKED", order_id, {"state": o.lifecycle_state, "fields": sorted(changes)})
                return _refused("BLOCKED_LIFECYCLE_LOCKED", blocked=True, escalation_id=esc,
                                lifecycle_state=o.lifecycle_state)
            if o.version != expected_version:
                return _refused("STALE_VERSION", current_version=o.version)

            if source_event_id:
                msg = ctx.conn.execute(
                    "SELECT body FROM messages WHERE event_id = ? AND order_id = ? AND direction = 'INBOUND'",
                    (source_event_id, order_id),
                ).fetchone()
                if msg is None:
                    return _refused("UNKNOWN_SOURCE_EVENT", event_id=source_event_id)
                source = msg["body"]
            else:
                if set(changes) - set(ADDRESS_FIELDS):
                    return _refused("EVENT_REQUIRED", hint="non-address changes need the customer's message as source")
                source = o.address_raw or ""

            updates, problem = _validated_updates(ctx, o, changes, source)
            if problem:
                return problem
            new_items = updates.pop("items", None)
            current_items = sorted((it.sku, it.quantity) for it in o.items)
            changed_fields = [k for k, v in updates.items() if getattr(o, k) != v]
            if new_items is not None and sorted((i["sku"], i["quantity"]) for i in new_items) != current_items:
                changed_fields.append("items")
            if not changed_fields:
                return _ok("NO_CHANGE", version=o.version)

            sets = {k: updates[k] for k in changed_fields if k != "items"}
            assignments = "".join(f"{k} = :{k}, " for k in sets)
            ctx.conn.execute(
                f"UPDATE orders SET {assignments}version = version + 1, agent_outcome = 'ON_HOLD', "
                "outcome_reason = 'ORDER_CHANGED', updated_at = :now WHERE order_id = :order_id",
                {**sets, "now": ctx.now(), "order_id": order_id},
            )
            if "items" in changed_fields:
                ctx.conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
                for n, item in enumerate(new_items, start=1):
                    ctx.conn.execute("INSERT INTO order_items VALUES (?, ?, ?, ?)",
                                     (order_id, n, item["sku"], item["quantity"]))
            invalidated = _invalidate_confirmations(ctx, order_id, "material change")
            _set_lifecycle(ctx, order_id, o.lifecycle_state, "PENDING")
            result = _ok("APPLIED", order_id=order_id, new_version=o.version + 1, changed_fields=sorted(changed_fields),
                         invalidated_confirmations=invalidated)
            _record_operation(ctx, op_id, order_id, "APPLY_CHANGE",
                              {"changes": changes, "source_event_id": source_event_id}, result)
            ctx.audit("TOOL", "CHANGE_APPLIED", order_id, {"changes": changes, "result": result})
            return result
    except UnknownOrder:
        return _refused("UNKNOWN_ORDER", order_id=order_id)
    except ExternalSourceError as e:
        return _refused("SOURCE_UNAVAILABLE", source=e.source, error_class="TOOL_ERROR")


def _validated_updates(ctx: ToolContext, o, changes: dict, source: str) -> tuple[dict, dict | None]:
    updates: dict = {}
    ungrounded = []
    for key, value in changes.items():
        if key == "items":
            continue
        value = (value or "").strip() if isinstance(value, str) else value
        if not isinstance(value, str) or not value:
            return {}, _refused("INVALID_VALUE", field=key)
        if key == "phone_raw":
            digits_in_source = {normalize_phone(m) for m in re.findall(r"[+\d٠-٩][\d٠-٩\s-]{7,}", source)}
            if normalize_phone(value) not in digits_in_source:
                ungrounded.append(key)
        elif not is_grounded(value, source):
            ungrounded.append(key)
        if key == "governorate":
            canonical = resolve_governorate(ctx.conn, value)
            if canonical is None:
                return {}, _refused("GOVERNORATE_UNKNOWN", value=value)
            value = canonical
        if key == "discount_code":
            value = value.upper()
        updates[key] = value
    if ungrounded:
        return {}, _refused("UNGROUNDED_VALUE", fields=sorted(ungrounded),
                            hint="values must appear in the customer's own words; ask instead of guessing")

    if "items" in changes:
        items = changes["items"]
        if not isinstance(items, list) or not items:
            return {}, _refused("INVALID_ITEMS")
        allowed_products = {it.product_id for it in o.items}
        for item in items:
            sku, qty = item.get("sku"), item.get("quantity")
            if not isinstance(qty, int) or not 1 <= qty <= MAX_ITEM_QUANTITY:
                return {}, _refused("INVALID_QUANTITY", sku=sku)
            if ctx.faults.inventory_unavailable:
                raise ExternalSourceError("inventory")
            row = ctx.conn.execute(
                "SELECT v.product_id, v.active, inv.available FROM variants v JOIN inventory inv ON inv.sku = v.sku "
                "WHERE v.sku = ?", (sku,)).fetchone()
            if row is None or not row["active"]:
                return {}, _refused("UNKNOWN_SKU", sku=sku)
            if row["product_id"] not in allowed_products:
                return {}, _refused("OUT_OF_SCOPE_ITEM", sku=sku, hint="only variant/quantity changes of ordered products")
            if row["available"] < qty:
                return {}, _refused("ITEM_NOT_AVAILABLE", sku=sku, available=row["available"])
        updates["items"] = [{"sku": i["sku"], "quantity": i["quantity"]} for i in items]
    return updates, None


# ---------------------------------------------------------------- confirmation (BR-04)

def request_confirmation(ctx: ToolContext, order_id: str, expected_version: int) -> dict:
    """Send the deterministic, version- and content-bound summary. Only when every other check passes."""
    try:
        with transaction(ctx.conn):
            d = evaluate(ctx, order_id)
            if d.version != expected_version:
                return _refused("STALE_VERSION", current_version=d.version)
            if d.next_action not in ("REQUEST_CONFIRMATION", "AWAIT_CONFIRMATION"):
                return _refused("NOT_ELIGIBLE", decision=d.to_dict())
            o = load_order(ctx.conn, order_id)
            quote = compute_quote(ctx.conn, ctx.settings, o).quote
            digest = summary_hash(o, quote)

            if d.next_action == "AWAIT_CONFIRMATION":
                cr_id = d.details["confirmation_request_id"]
                if not _inbound_after_request(ctx, order_id, cr_id):
                    return _ok("ALREADY_REQUESTED", confirmation_request_id=cr_id, order_version=o.version,
                               total_egp=quote.total_egp, summary_hash=digest)

            ctx.conn.execute(
                "UPDATE confirmation_requests SET status = 'SUPERSEDED', resolved_at = ? "
                "WHERE order_id = ? AND status = 'OPEN'", (ctx.now(), order_id))
            n = ctx.conn.execute("SELECT COUNT(*) FROM confirmation_requests WHERE order_id = ?",
                                 (order_id,)).fetchone()[0] + 1
            cr_id = f"CR-{order_id}-V{o.version}-{n}"
            ctx.conn.execute(
                "INSERT INTO confirmation_requests (confirmation_request_id, order_id, order_version, summary_hash, "
                "total_egp, status, created_at) VALUES (?, ?, ?, ?, ?, 'OPEN', ?)",
                (cr_id, order_id, o.version, digest, quote.total_egp, ctx.now()),
            )
            text = render_summary(ctx.conn, o, quote)
            ctx.conn.execute(
                "INSERT INTO messages (order_id, direction, kind, body, idempotency_key, confirmation_request_id, "
                "created_at) VALUES (?, 'OUTBOUND', 'CONFIRMATION_REQUEST', ?, ?, ?, ?)",
                (order_id, text, f"out:{cr_id}", cr_id, ctx.now()),
            )
            ctx.conn.execute(
                "UPDATE orders SET quoted_version = ?, quoted_subtotal_egp = ?, quoted_discount_egp = ?, "
                "quoted_shipping_egp = ?, quoted_total_egp = ?, agent_outcome = 'ON_HOLD', "
                "outcome_reason = 'AWAITING_CONFIRMATION', updated_at = ? WHERE order_id = ?",
                (o.version, quote.subtotal_egp, quote.discount_egp, quote.shipping_egp, quote.total_egp,
                 ctx.now(), order_id),
            )
            _set_lifecycle(ctx, order_id, o.lifecycle_state, "VERIFIED")
            ctx.audit("TOOL", "CONFIRMATION_REQUESTED", order_id,
                      {"confirmation_request_id": cr_id, "version": o.version, "total_egp": quote.total_egp})
            return _ok("REQUESTED", confirmation_request_id=cr_id, order_version=o.version,
                       total_egp=quote.total_egp, previous_total_egp=d.details.get("previous_total_egp"),
                       summary_hash=digest, message=text, delivery="SIMULATED")
    except UnknownOrder:
        return _refused("UNKNOWN_ORDER", order_id=order_id)


def _request_seq(ctx: ToolContext, cr_id: str) -> int | None:
    row = ctx.conn.execute("SELECT seq FROM messages WHERE confirmation_request_id = ? AND kind = 'CONFIRMATION_REQUEST'",
                           (cr_id,)).fetchone()
    return row["seq"] if row else None


def _inbound_after_request(ctx: ToolContext, order_id: str, cr_id: str) -> list:
    seq = _request_seq(ctx, cr_id)
    return ctx.conn.execute(
        "SELECT seq, event_id, body FROM messages WHERE order_id = ? AND direction = 'INBOUND' AND seq > ? ORDER BY seq",
        (order_id, seq if seq is not None else -1),
    ).fetchall()


def record_confirmation(ctx: ToolContext, order_id: str, event_id: str) -> dict:
    """Accept a reply as confirmation ONLY when it is provably bound to the latest request (BR-04, SA-09).

    No caller-supplied interpretation is accepted: the decision is purely deterministic.
    """
    try:
        with transaction(ctx.conn):
            msg = ctx.conn.execute(
                "SELECT seq, body FROM messages WHERE event_id = ? AND order_id = ? AND direction = 'INBOUND'",
                (event_id, order_id)).fetchone()
            if msg is None:
                return _refused("UNKNOWN_EVENT", event_id=event_id)
            already = ctx.conn.execute(
                "SELECT confirmation_request_id, order_version FROM confirmation_requests "
                "WHERE order_id = ? AND status = 'ACCEPTED' AND accepted_event_id = ?", (order_id, event_id)).fetchone()
            if already:
                return _ok("ALREADY_ACCEPTED", confirmation_request_id=already["confirmation_request_id"],
                           order_version=already["order_version"])
            o = load_order(ctx.conn, order_id)
            if o.lifecycle_state not in EDITABLE_STATES:
                return _refused("NOT_CONFIRMABLE", lifecycle_state=o.lifecycle_state)
            cr = ctx.conn.execute("SELECT * FROM confirmation_requests WHERE order_id = ? AND status = 'OPEN'",
                                  (order_id,)).fetchone()
            if cr is None:
                return _refused("NO_OPEN_REQUEST")
            if cr["order_version"] != o.version:
                _invalidate_confirmations(ctx, order_id, "request bound to an older version")
                return _refused("STALE_REQUEST", request_version=cr["order_version"], current_version=o.version)
            pricing = compute_quote(ctx.conn, ctx.settings, o)
            if pricing.quote is None or summary_hash(o, pricing.quote) != cr["summary_hash"]:
                _invalidate_confirmations(ctx, order_id, "order content or prices changed since request")
                return _refused("CONTENT_CHANGED")
            inbound = _inbound_after_request(ctx, order_id, cr["confirmation_request_id"])
            if [r["event_id"] for r in inbound] != [event_id]:
                return _refused("NOT_DIRECT_REPLY",
                                hint="reply must be the only customer message after the latest confirmation request")
            if not is_unambiguous_affirmative(ctx.settings, msg["body"]):
                ctx.audit("POLICY", "CONFIRMATION_REJECTED", order_id, {"event_id": event_id, "body": msg["body"]})
                return _refused("AMBIGUOUS_REPLY", hint="ask the customer to confirm the latest summary explicitly")
            ctx.conn.execute(
                "UPDATE confirmation_requests SET status = 'ACCEPTED', accepted_event_id = ?, resolved_at = ? "
                "WHERE confirmation_request_id = ? AND status = 'OPEN'",
                (event_id, ctx.now(), cr["confirmation_request_id"]))
            ctx.audit("POLICY", "CONFIRMATION_ACCEPTED", order_id,
                      {"confirmation_request_id": cr["confirmation_request_id"], "version": o.version})
            return _ok("ACCEPTED", confirmation_request_id=cr["confirmation_request_id"], order_version=o.version)
    except UnknownOrder:
        return _refused("UNKNOWN_ORDER", order_id=order_id)
    except ExternalSourceError as e:
        return _refused("SOURCE_UNAVAILABLE", source=e.source, error_class="TOOL_ERROR")


# ---------------------------------------------------------------- duplicates (BR-05)

def flag_duplicates(ctx: ToolContext, order_id: str) -> dict:
    """Persist possible-duplicate flags and hold every editable order involved. Never cancels or merges."""
    try:
        with transaction(ctx.conn):
            o = load_order(ctx.conn, order_id)
            candidates = find_duplicate_candidates(ctx.conn, ctx.settings, o)
            if not candidates:
                return _ok("NO_DUPLICATES")
            _flag_pairs(ctx, order_id, candidates)
            return _ok("FLAGGED", order_id=order_id, duplicates=candidates)
    except UnknownOrder:
        return _refused("UNKNOWN_ORDER", order_id=order_id)


def request_duplicate_intent(ctx: ToolContext, order_id: str) -> dict:
    """Ask, with deterministic text naming both order IDs, whether the customer intended both orders.

    Binds the question (message seq + the order whose conversation carries it) to each open flag,
    so a later reply can only resolve the pair it was asked about.
    """
    try:
        with transaction(ctx.conn):
            load_order(ctx.conn, order_id)
            flags = ctx.conn.execute(
                "SELECT * FROM duplicate_flags WHERE (order_id_a = ? OR order_id_b = ?) AND status = 'OPEN' "
                "ORDER BY order_id_a, order_id_b", (order_id, order_id)).fetchall()
            if not flags:
                return _refused("NO_OPEN_FLAG", hint="call flag_duplicates first")
            pending = [f for f in flags if f["intent_order_id"] == order_id and f["intent_request_seq"] is not None]
            if len(pending) == len(flags) and not ctx.conn.execute(
                    "SELECT 1 FROM messages WHERE order_id = ? AND direction = 'INBOUND' AND seq > ?",
                    (order_id, min(f["intent_request_seq"] for f in flags))).fetchone():
                return _ok("ALREADY_REQUESTED")
            others = [f["order_id_b"] if f["order_id_a"] == order_id else f["order_id_a"] for f in flags]
            ids = " و ".join([order_id, *others])
            text = (f"لاحظنا إن فيه طلبين بنفس الرقم ونفس المنتجات بالظبط ({ids}). "
                    "هل حضرتك عايز الطلبين الاتنين؟ لو عايزهم الاتنين رد بـ (أيوه الاتنين). "
                    "لو عايز طلب واحد بس قولنا وزميلنا هيتواصل معاك. مش هنلغي أي طلب من غير ما نتأكد منك.")
            n = ctx.conn.execute("SELECT COUNT(*) FROM messages WHERE order_id = ? AND kind = 'DUPLICATE_INTENT_REQUEST'",
                                 (order_id,)).fetchone()[0] + 1
            cur = ctx.conn.execute(
                "INSERT INTO messages (order_id, direction, kind, body, idempotency_key, created_at) "
                "VALUES (?, 'OUTBOUND', 'DUPLICATE_INTENT_REQUEST', ?, ?, ?)",
                (order_id, text, f"dupq:{order_id}:{n}", ctx.now()))
            for f in flags:
                ctx.conn.execute(
                    "UPDATE duplicate_flags SET intent_order_id = ?, intent_request_seq = ? "
                    "WHERE order_id_a = ? AND order_id_b = ?", (order_id, cur.lastrowid, f["order_id_a"], f["order_id_b"]))
            ctx.audit("TOOL", "DUPLICATE_INTENT_REQUESTED", order_id, {"pairs": others})
            return _ok("REQUESTED", duplicates=others, message=text, delivery="SIMULATED")
    except UnknownOrder:
        return _refused("UNKNOWN_ORDER", order_id=order_id)


def clear_duplicate_flag(ctx: ToolContext, order_id: str, other_order_id: str, event_id: str) -> dict:
    """DT-08: clear ONLY the duplicate concern, and only on explicit, pair-bound evidence.

    Required (deterministic; a tool call alone proves nothing):
      - an OPEN flag for exactly this pair, with a duplicate-intent question sent on `order_id`'s conversation;
      - `event_id` is a customer message on that same conversation and the ONLY one since the question;
      - its text explicitly says both are intended (strict lexicon, no negation/condition/question).
    Each order still needs its own version-bound confirmation before it can become ready.
    """
    a, b = sorted((order_id, other_order_id))
    with transaction(ctx.conn):
        flag = ctx.conn.execute("SELECT * FROM duplicate_flags WHERE order_id_a = ? AND order_id_b = ?",
                                (a, b)).fetchone()
        if flag is None or flag["status"] != "OPEN":
            return _refused("NO_OPEN_FLAG")
        if flag["intent_order_id"] != order_id or flag["intent_request_seq"] is None:
            return _refused("NO_INTENT_QUESTION", hint="call request_duplicate_intent on this order first")
        msg = ctx.conn.execute(
            "SELECT seq, body FROM messages WHERE event_id = ? AND direction = 'INBOUND' AND order_id = ?",
            (event_id, order_id)).fetchone()
        if msg is None:
            return _refused("UNKNOWN_EVENT", event_id=event_id)
        after = [r["event_id"] for r in ctx.conn.execute(
            "SELECT event_id FROM messages WHERE order_id = ? AND direction = 'INBOUND' AND seq > ? ORDER BY seq",
            (order_id, flag["intent_request_seq"]))]
        if after != [event_id]:
            return _refused("NOT_DIRECT_REPLY", hint="reply must be the only customer message after the question")
        if not is_explicit_both_intended(ctx.settings, msg["body"]):
            ctx.audit("POLICY", "DUPLICATE_CLEAR_REJECTED", order_id, {"event_id": event_id, "body": msg["body"]})
            return _refused("NOT_EXPLICITLY_BOTH_INTENDED",
                            hint="keep both orders on hold; ask again or escalate to staff")
        ctx.conn.execute(
            "UPDATE duplicate_flags SET status = 'CLEARED_BOTH_INTENDED', resolved_at = ?, cleared_by_event_id = ? "
            "WHERE order_id_a = ? AND order_id_b = ?", (ctx.now(), event_id, a, b))
        for oid in (a, b):
            ctx.conn.execute("UPDATE orders SET outcome_reason = 'DUPLICATE_CLEARED_REEVALUATE', updated_at = ? "
                             "WHERE order_id = ?", (ctx.now(), oid))
        ctx.audit("POLICY", "DUPLICATE_CLEARED", order_id, {"pair": [a, b], "event_id": event_id})
        return _ok("CLEARED", reevaluate=[a, b])


# ---------------------------------------------------------------- readiness commit (DT-01, DT-13, AC-07)

class _ReservationFailed(Exception):
    pass


def commit_ready(ctx: ToolContext, order_id: str, expected_version: int) -> dict:
    """Atomically re-validate everything, reserve stock and mark READY_FOR_DISPATCH — at most once.

    op_id 'ready:{order}:v{version}' is the stable idempotency key: a retry returns the saved
    result and never reserves stock twice. Refusals reserve nothing.
    """
    op_id = f"ready:{order_id}:v{expected_version}"
    try:
        return _commit_ready(ctx, order_id, expected_version, op_id)
    except UnknownOrder:
        return _refused("UNKNOWN_ORDER", order_id=order_id)
    except ExternalSourceError as e:  # e.g. ledger unavailable: fail closed, nothing reserved
        return _refused("SOURCE_UNAVAILABLE", source=e.source, error_class="TOOL_ERROR")


def _commit_ready(ctx: ToolContext, order_id: str, expected_version: int, op_id: str) -> dict:
    saved = _lookup_operation(ctx, op_id)
    if saved:
        return {**saved, "status": "ALREADY_COMMITTED", "idempotent_replay": True}

    conn = ctx.conn
    conn.execute("BEGIN IMMEDIATE")
    try:
        saved = _lookup_operation(ctx, op_id)  # re-check under the write lock
        if saved:
            conn.execute("COMMIT")
            return {**saved, "status": "ALREADY_COMMITTED", "idempotent_replay": True}
        o = load_order(conn, order_id)
        if o.version != expected_version:
            conn.execute("ROLLBACK")
            return _refused("STALE_VERSION", current_version=o.version)
        if o.lifecycle_state not in EDITABLE_STATES:
            conn.execute("ROLLBACK")
            return _refused("NOT_COMMITTABLE", lifecycle_state=o.lifecycle_state)

        d = evaluate(ctx, order_id)
        if d.next_action != "COMMIT_READY":
            refusal = _persist_commit_refusal(ctx, o, d)
            conn.execute("COMMIT")
            return refusal

        reserved = []
        needed: dict[str, int] = {}
        for it in o.items:
            needed[it.sku] = needed.get(it.sku, 0) + it.quantity
        for sku, qty in sorted(needed.items()):
            cur = conn.execute(
                "UPDATE inventory SET available = available - ?, updated_at = ? WHERE sku = ? AND available >= ?",
                (qty, ctx.now(), sku, qty))
            if cur.rowcount != 1:
                raise _ReservationFailed(sku)
            reserved.append({"sku": sku, "quantity": qty})
        _set_lifecycle(ctx, order_id, o.lifecycle_state, READY)
        conn.execute("UPDATE orders SET agent_outcome = ?, outcome_reason = 'COMMITTED', updated_at = ? "
                     "WHERE order_id = ?", (READY, ctx.now(), order_id))
        result = _ok("COMMITTED", op_id=op_id, order_id=order_id, version=o.version, outcome=READY,
                     reserved=reserved, total_egp=d.details["quote"]["total_egp"],
                     confirmation_request_id=d.details["confirmation_request_id"])
        _record_operation(ctx, op_id, order_id, "COMMIT_READY", {"expected_version": expected_version}, result)
        for r in reserved:  # same transaction: ledger, reservations, stock and state commit together
            conn.execute("INSERT INTO stock_reservations VALUES (?, ?, ?, ?)", (op_id, order_id, r["sku"], r["quantity"]))
        ctx.audit("TOOL", "READY_COMMITTED", order_id, result)
        conn.execute("COMMIT")
    except _ReservationFailed as e:
        conn.execute("ROLLBACK")
        with transaction(conn):
            _set_outcome(ctx, order_id, ON_HOLD, "STOCK_CHANGED")
            ctx.audit("TOOL", "COMMIT_REFUSED", order_id, {"reason": "STOCK_CHANGED", "sku": str(e)})
        return _refused("REFUSED", reasons=["STOCK_CHANGED"], outcome=ON_HOLD)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    if ctx.faults.commit_timeout_after_success:
        raise CommitTimeout(op_id)  # simulated lost response AFTER a durable commit
    return result


def _persist_commit_refusal(ctx: ToolContext, o, d: Decision) -> dict:
    reasons = list(d.reasons)
    if "OUT_OF_STOCK" in reasons:
        reasons.insert(0, "STOCK_CHANGED")  # DT-13
    if "DUPLICATE_SUSPECTED" in reasons:
        _flag_pairs(ctx, o.order_id, d.details.get("duplicates", []))
    if "CONFIRMATION_REQUIRED" in reasons:
        # SA-06: an accepted confirmation no longer matching current version/content/prices is void.
        _invalidate_confirmations(ctx, o.order_id, "confirmation no longer matches order at commit")
    outcome = d.outcome if d.outcome in (ON_HOLD, ESCALATE) else ON_HOLD
    _set_outcome(ctx, o.order_id, outcome, ",".join(reasons))
    ctx.audit("TOOL", "COMMIT_REFUSED", o.order_id, {"reasons": reasons})
    return _refused("REFUSED", reasons=reasons, outcome=outcome, decision=d.to_dict())


def resolve_commit_outcome(ctx: ToolContext, order_id: str, op_id: str) -> dict:
    """After a CommitTimeout: establish what happened via the ledger. Never retry blindly (AC-07)."""
    try:
        saved = _lookup_operation(ctx, op_id)
    except (ExternalSourceError, sqlite3.Error) as e:
        res = escalate(ctx, order_id, "COMMIT_OUTCOME_UNKNOWN", f"ledger lookup failed for {op_id}: {e}")
        return _refused("UNKNOWN_ESCALATED", escalation=res, error_class="TOOL_ERROR")
    if saved:
        return _ok("COMMITTED", result=saved, safe_to_retry=False)
    o = load_order(ctx.conn, order_id)
    if o.lifecycle_state == READY:  # ready without a ledger entry is inconsistent → humans decide
        res = escalate(ctx, order_id, "COMMIT_OUTCOME_UNKNOWN", f"{op_id}: order READY but no ledger entry")
        return _refused("UNKNOWN_ESCALATED", escalation=res)
    # Ledger write and state change are one transaction, so no entry means nothing was applied.
    return _ok("NOT_COMMITTED", safe_to_retry=True)
