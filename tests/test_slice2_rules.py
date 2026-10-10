"""Slice 2: business rules BR-01..BR-06 through the policy engine and guarded tools.

Test names carry BR/DT/AC/TC identifiers (see docs/TRACEABILITY.md). These run the
deterministic layer only; the LLM agent loop is not involved (REPLAY/LIVE status unaffected).
"""

import sqlite3

import pytest

from cod_rescue.context import ToolContext
from cod_rescue.errors import CommitTimeout
from cod_rescue.policy import evaluate
from cod_rescue import tools
from cod_rescue.tools import (
    apply_customer_change, clear_duplicate_flag, commit_ready, flag_duplicates, ingest_event, record_confirmation,
    request_confirmation, resolve_commit_outcome, save_event_result, send_message,
)
from tests.conftest import FIXED_NOW, with_faults
from tests.helpers import confirm, count, insert_order, order_row, stock


def faulty(ctx, **faults):
    return ToolContext(ctx.conn, with_faults(ctx.settings, **faults), clock=lambda: FIXED_NOW)


# ======================================================================= DT-01 / TC-01

def test_TC01_DT01_complete_order_ready_exactly_once(ctx):
    d = evaluate(ctx, "ORD-1001")
    assert (d.outcome, d.reasons, d.next_action) == ("ON_HOLD", ["CONFIRMATION_REQUIRED"], "REQUEST_CONFIRMATION")

    req, acc = confirm(ctx, "ORD-1001")
    assert acc["status"] == "ACCEPTED" and acc["order_version"] == 1
    assert order_row(ctx.conn, "ORD-1001")["lifecycle_state"] == "VERIFIED"
    assert evaluate(ctx, "ORD-1001").next_action == "COMMIT_READY"

    res = commit_ready(ctx, "ORD-1001", 1)
    assert res["status"] == "COMMITTED" and res["reserved"] == [{"sku": "HOODIE-BLK-L", "quantity": 1}]
    row = order_row(ctx.conn, "ORD-1001")
    assert (row["lifecycle_state"], row["agent_outcome"]) == ("READY_FOR_DISPATCH", "READY_FOR_DISPATCH")
    assert stock(ctx.conn, "HOODIE-BLK-L") == 4

    again = commit_ready(ctx, "ORD-1001", 1)
    assert again["status"] == "ALREADY_COMMITTED" and again["idempotent_replay"]
    assert stock(ctx.conn, "HOODIE-BLK-L") == 4
    assert count(ctx.conn, "stock_reservations") == 1 and count(ctx.conn, "operations", "op_type='COMMIT_READY'") == 1


def test_DT06_commit_without_confirmation_is_refused(ctx):
    res = commit_ready(ctx, "ORD-1001", 1)
    assert not res["ok"] and "CONFIRMATION_REQUIRED" in res["reasons"]
    assert stock(ctx.conn, "HOODIE-BLK-L") == 5
    assert order_row(ctx.conn, "ORD-1001")["lifecycle_state"] == "PENDING"


def test_commit_with_stale_version_is_refused(ctx):
    confirm(ctx, "ORD-1001")
    assert commit_ready(ctx, "ORD-1001", 7)["status"] == "STALE_VERSION"


# ======================================================================= BR-01

def test_TC02_AC01_DT03_out_of_stock_holds_and_offers_only_verified_options(ctx):
    d = evaluate(ctx, "ORD-1002")
    assert (d.outcome, d.reasons, d.next_action) == ("ON_HOLD", ["OUT_OF_STOCK"], "OFFER_ALTERNATIVES")
    assert [a["sku"] for a in d.details["alternatives"]["HOODIE-BLK-XL"]] == ["HOODIE-BLK-L", "HOODIE-BLK-M"]
    assert request_confirmation(ctx, "ORD-1002", 1)["status"] == "NOT_ELIGIBLE"
    assert not commit_ready(ctx, "ORD-1002", 1)["ok"]
    # never substituted automatically
    assert ctx.conn.execute("SELECT sku FROM order_items WHERE order_id='ORD-1002'").fetchone()[0] == "HOODIE-BLK-XL"


def test_TC03_customer_chosen_alternative_applied_once_then_reconfirmed(ctx):
    ingest_event(ctx, "ORD-1002", "EVT-1002-1", "خلاص خليها L بدل XL")
    change = {"items": [{"sku": "HOODIE-BLK-L", "quantity": 1}]}
    res = apply_customer_change(ctx, "ORD-1002", 1, change, "EVT-1002-1")
    assert res["status"] == "APPLIED" and res["new_version"] == 2
    again = apply_customer_change(ctx, "ORD-1002", 1, change, "EVT-1002-1")
    assert again["status"] == "DUPLICATE_OPERATION"
    assert order_row(ctx.conn, "ORD-1002")["version"] == 2
    assert evaluate(ctx, "ORD-1002").reasons == ["CONFIRMATION_REQUIRED"]
    confirm(ctx, "ORD-1002")
    assert commit_ready(ctx, "ORD-1002", 2)["status"] == "COMMITTED"


@pytest.mark.parametrize("items, status", [
    ([{"sku": "HOODIE-BLK-XL", "quantity": 1}], "ITEM_NOT_AVAILABLE"),   # re-requesting the unavailable size
    ([{"sku": "JEANS-BLU-34", "quantity": 1}], "OUT_OF_SCOPE_ITEM"),
    ([{"sku": "HOODIE-BLK-L", "quantity": 6}], "ITEM_NOT_AVAILABLE"),
    ([{"sku": "NO-SUCH", "quantity": 1}], "UNKNOWN_SKU"),
    ([{"sku": "HOODIE-BLK-L", "quantity": 0}], "INVALID_QUANTITY"),
])
def test_BR01_item_changes_only_to_verified_available_variants(ctx, items, status):
    ingest_event(ctx, "ORD-1002", "EVT-1002-X", "غير المقاس")
    res = apply_customer_change(ctx, "ORD-1002", 1, {"items": items}, "EVT-1002-X")
    assert res["status"] == status
    assert order_row(ctx.conn, "ORD-1002")["version"] == 1


def test_AC01_DT05_material_change_invalidates_prior_confirmation(ctx):
    confirm(ctx, "ORD-1001")
    ingest_event(ctx, "ORD-1001", "EVT-1001-CHG", "ممكن M بدل L")
    res = apply_customer_change(ctx, "ORD-1001", 1, {"items": [{"sku": "HOODIE-BLK-M", "quantity": 1}]}, "EVT-1001-CHG")
    assert res["invalidated_confirmations"] == 1
    assert count(ctx.conn, "confirmation_requests", "order_id='ORD-1001' AND status='ACCEPTED'") == 0
    assert order_row(ctx.conn, "ORD-1001")["lifecycle_state"] == "PENDING"
    assert commit_ready(ctx, "ORD-1001", 1)["status"] == "STALE_VERSION"
    assert "CONFIRMATION_REQUIRED" in commit_ready(ctx, "ORD-1001", 2)["reasons"]


def test_TC04_DT13_stock_change_before_commit_stops_readiness(ctx):
    confirm(ctx, "ORD-1003")
    ctx.conn.execute("UPDATE inventory SET available = 0 WHERE sku = 'TSHIRT-WHT-L'")  # sold elsewhere
    res = commit_ready(ctx, "ORD-1003", 1)
    assert not res["ok"] and res["reasons"][0] == "STOCK_CHANGED"
    assert stock(ctx.conn, "TSHIRT-WHT-L") == 0 and count(ctx.conn, "stock_reservations") == 0
    row = order_row(ctx.conn, "ORD-1003")
    assert (row["lifecycle_state"], row["agent_outcome"]) == ("VERIFIED", "ON_HOLD")


def test_DT11_inventory_outage_holds_without_assuming_stock(ctx):
    d = evaluate(faulty(ctx, inventory_unavailable=True), "ORD-1001")
    assert (d.outcome, d.error_class, d.next_action) == ("ON_HOLD", "TOOL_ERROR", "HOLD_FOR_SOURCE")
    assert "INVENTORY_UNAVAILABLE" in d.reasons


def test_commit_rolls_back_everything_on_unexpected_failure(ctx, monkeypatch):
    confirm(ctx, "ORD-1001")

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(tools, "_record_operation", boom)
    with pytest.raises(RuntimeError):
        commit_ready(ctx, "ORD-1001", 1)
    assert stock(ctx.conn, "HOODIE-BLK-L") == 5 and count(ctx.conn, "stock_reservations") == 0
    assert order_row(ctx.conn, "ORD-1001")["lifecycle_state"] == "VERIFIED"


# ======================================================================= BR-02

def test_TC05_AC02_DT02_incomplete_address_holds_with_precise_fields(ctx):
    d = evaluate(ctx, "ORD-1004")
    assert (d.outcome, d.next_action) == ("ON_HOLD", "ASK_CLARIFICATION")
    assert d.reasons == ["ADDRESS_INCOMPLETE"]
    assert d.details["missing_fields"] == ["building", "city", "governorate", "street"]


def test_AC02_extract_only_supplied_fields_never_fabricate(ctx):
    fabricated = apply_customer_change(ctx, "ORD-1004", 1, {"governorate": "الشرقية", "street": "شارع الجلاء"})
    assert fabricated["status"] == "UNGROUNDED_VALUE" and fabricated["fields"] == ["street"]
    res = apply_customer_change(ctx, "ORD-1004", 1, {"governorate": "الشرقية", "city": "الزقازيق",
                                                      "landmark": "مسجد الفتح"})
    assert res["status"] == "APPLIED"
    row = order_row(ctx.conn, "ORD-1004")
    assert (row["governorate"], row["city"], row["landmark"], row["street"]) == ("sharqia", "الزقازيق", "مسجد الفتح", None)
    assert evaluate(ctx, "ORD-1004").details["missing_fields"] == ["building", "street"]


def test_TC06_valid_address_from_customer_reply_passes(ctx):
    apply_customer_change(ctx, "ORD-1004", 1, {"governorate": "الشرقية", "city": "الزقازيق", "landmark": "مسجد الفتح"})
    ingest_event(ctx, "ORD-1004", "EVT-1004-1", "العنوان شارع الجلاء عمارة 5 جنب مسجد الفتح")
    res = apply_customer_change(ctx, "ORD-1004", 2, {"street": "شارع الجلاء", "building": "5"}, "EVT-1004-1")
    assert res["status"] == "APPLIED"
    d = evaluate(ctx, "ORD-1004")
    assert d.reasons == ["CONFIRMATION_REQUIRED"] and d.details["quote"]["shipping_egp"] == 75


def test_BR02_non_address_change_requires_customer_message(ctx):
    assert apply_customer_change(ctx, "ORD-1004", 1, {"phone_raw": "01000000099"})["status"] == "EVENT_REQUIRED"
    ingest_event(ctx, "ORD-1004", "EVT-1004-P", "رقمي الجديد 0100 000 0099")
    assert apply_customer_change(ctx, "ORD-1004", 1, {"phone_raw": "01000000098"}, "EVT-1004-P")["status"] == "UNGROUNDED_VALUE"
    assert apply_customer_change(ctx, "ORD-1004", 1, {"phone_raw": "01000000099"}, "EVT-1004-P")["status"] == "APPLIED"


def test_SA05_clarification_limit_escalates(ctx):
    for i in range(3):
        assert send_message(ctx, "ORD-1004", "CLARIFICATION", f"محتاجين اسم الشارع ورقم العمارة ({i})", f"clar-{i}")["ok"]
    send_message(ctx, "ORD-1004", "CLARIFICATION", "تكرار", "clar-2")  # same key: not counted again
    assert order_row(ctx.conn, "ORD-1004")["clarification_attempts"] == 3
    d = evaluate(ctx, "ORD-1004")
    assert (d.outcome, d.reasons) == ("ESCALATE_TO_HUMAN", ["CLARIFICATION_LIMIT"])


@pytest.mark.parametrize("kind, body, status", [
    ("CLARIFICATION", "الإجمالي 810 جنيه", "AMOUNTS_NOT_ALLOWED_IN_FREE_TEXT"),
    ("INFO", "total is EGP 900", "AMOUNTS_NOT_ALLOWED_IN_FREE_TEXT"),
    ("CONFIRMATION_REQUEST", "تمام؟", "KIND_NOT_ALLOWED"),
    ("INFO", "", "INVALID_BODY"),
])
def test_send_message_guards(ctx, kind, body, status):
    assert send_message(ctx, "ORD-1004", kind, body, "k1")["status"] == status
    assert count(ctx.conn, "messages", "order_id='ORD-1004'") == 0


# ======================================================================= BR-03

def test_TC07_AC03_DT05_destination_change_recomputes_and_reconfirms(ctx):
    assert evaluate(ctx, "ORD-1005").next_action == "COMMIT_READY"  # 810 accepted for v2
    ingest_event(ctx, "ORD-1005", "EVT-1005-2", "غيروا العنوان: الشرقية، الزقازيق، شارع الجلاء، عمارة 5")
    res = apply_customer_change(ctx, "ORD-1005", 2, {"governorate": "الشرقية", "city": "الزقازيق",
                                                      "street": "شارع الجلاء", "building": "5"}, "EVT-1005-2")
    assert res["status"] == "APPLIED" and res["invalidated_confirmations"] == 1
    d = evaluate(ctx, "ORD-1005")
    assert d.reasons == ["CONFIRMATION_REQUIRED", "QUOTE_CHANGED"]
    assert (d.details["previous_total_egp"], d.details["quote"]["total_egp"]) == (810, 825)
    assert not commit_ready(ctx, "ORD-1005", 3)["ok"]
    req = request_confirmation(ctx, "ORD-1005", 3)
    assert (req["total_egp"], req["previous_total_egp"]) == (825, 810) and "825" in req["message"]


def test_AC03_rate_lookup_failure_holds_without_guessing(ctx):
    f = faulty(ctx, shipping_rates_unavailable=True)
    d = evaluate(f, "ORD-1005")
    assert (d.outcome, d.error_class) == ("ON_HOLD", "TOOL_ERROR") and "SHIPPING_SOURCE_UNAVAILABLE" in d.reasons
    assert not commit_ready(f, "ORD-1005", 2)["ok"]
    assert stock(ctx.conn, "HOODIE-BLK-M") == 3


def test_TC08_DT04_missing_rate_or_price_outage_never_estimated(ctx):
    d = evaluate(ctx, "ORD-1006")
    assert (d.outcome, d.next_action, d.reasons) == ("ON_HOLD", "HOLD_FOR_SOURCE", ["SHIPPING_RATE_MISSING"])
    assert request_confirmation(ctx, "ORD-1006", 1)["status"] == "NOT_ELIGIBLE"
    d2 = evaluate(faulty(ctx, price_source_unavailable=True), "ORD-1001")
    assert "PRICE_SOURCE_UNAVAILABLE" in d2.reasons and d2.error_class == "TOOL_ERROR"
    assert order_row(ctx.conn, "ORD-1006")["quoted_total_egp"] is None


def test_SA06_price_change_after_acceptance_invalidates_at_commit(ctx):
    confirm(ctx, "ORD-1001")
    ctx.conn.execute("UPDATE variants SET unit_price_egp = 790 WHERE sku = 'HOODIE-BLK-L'")
    res = commit_ready(ctx, "ORD-1001", 1)
    assert not res["ok"] and "QUOTE_CHANGED" in res["reasons"]
    assert count(ctx.conn, "confirmation_requests", "order_id='ORD-1001' AND status='ACCEPTED'") == 0
    assert stock(ctx.conn, "HOODIE-BLK-L") == 5


def test_BR03_unauthorized_discount_holds(ctx):
    ingest_event(ctx, "ORD-1001", "EVT-1001-D", "عندي كود OLD50")
    assert apply_customer_change(ctx, "ORD-1001", 1, {"discount_code": "OLD50"}, "EVT-1001-D")["status"] == "APPLIED"
    assert "DISCOUNT_NOT_AUTHORIZED" in evaluate(ctx, "ORD-1001").reasons


# ======================================================================= BR-04

def test_TC09_AC04_direct_tamam_accepted_for_latest_version_only(ctx):
    ingest_event(ctx, "ORD-1007", "EVT-1007-A", "تمام")
    acc = record_confirmation(ctx, "ORD-1007", "EVT-1007-A")
    assert (acc["status"], acc["confirmation_request_id"], acc["order_version"]) == ("ACCEPTED", "CR-1007-V3", 3)
    assert record_confirmation(ctx, "ORD-1007", "EVT-1007-A")["status"] == "ALREADY_ACCEPTED"
    # never reused on version 4
    ingest_event(ctx, "ORD-1007", "EVT-1007-B", "خليها الدور 6")
    assert apply_customer_change(ctx, "ORD-1007", 3, {"floor": "6"}, "EVT-1007-B")["new_version"] == 4
    assert "CONFIRMATION_REQUIRED" in commit_ready(ctx, "ORD-1007", 4)["reasons"]
    assert record_confirmation(ctx, "ORD-1007", "EVT-1007-A")["status"] == "NO_OPEN_REQUEST"


@pytest.mark.parametrize("reply", ["تمام بس عايزة أغير المقاس", "تمام؟", "مش تمام", "هشوف وأرد عليك"])
def test_TC10_DT12_ambiguous_reply_is_not_confirmation(ctx, reply):
    ingest_event(ctx, "ORD-1007", "EVT-1007-Q", reply)
    assert record_confirmation(ctx, "ORD-1007", "EVT-1007-Q")["status"] == "AMBIGUOUS_REPLY"
    assert evaluate(ctx, "ORD-1007").next_action == "AWAIT_CONFIRMATION"
    again = request_confirmation(ctx, "ORD-1007", 3)  # ask again with a fresh request
    assert again["status"] == "REQUESTED"
    assert count(ctx.conn, "confirmation_requests", "confirmation_request_id='CR-1007-V3' AND status='SUPERSEDED'") == 1


def test_TC10_tamam_not_directly_after_request_is_rejected(ctx):
    ingest_event(ctx, "ORD-1007", "EVT-1007-1", "استنى ثانية")
    ingest_event(ctx, "ORD-1007", "EVT-1007-2", "تمام")
    assert record_confirmation(ctx, "ORD-1007", "EVT-1007-2")["status"] == "NOT_DIRECT_REPLY"


def test_TC10_tamam_before_request_is_rejected(ctx):
    ingest_event(ctx, "ORD-1001", "EVT-1001-EARLY", "تمام")
    request_confirmation(ctx, "ORD-1001", 1)
    assert record_confirmation(ctx, "ORD-1001", "EVT-1001-EARLY")["status"] == "NOT_DIRECT_REPLY"


def test_TC10_tamam_after_order_edit_is_rejected(ctx):
    ingest_event(ctx, "ORD-1007", "EVT-1007-E", "الدور 6 مش 5")
    apply_customer_change(ctx, "ORD-1007", 3, {"floor": "6"}, "EVT-1007-E")
    ingest_event(ctx, "ORD-1007", "EVT-1007-T", "تمام")
    assert record_confirmation(ctx, "ORD-1007", "EVT-1007-T")["status"] == "NO_OPEN_REQUEST"


def test_TC10_tamam_after_price_change_is_rejected(ctx):
    ctx.conn.execute("UPDATE variants SET unit_price_egp = 950 WHERE sku = 'DRESS-RED-M'")
    ingest_event(ctx, "ORD-1007", "EVT-1007-P", "تمام")
    assert record_confirmation(ctx, "ORD-1007", "EVT-1007-P")["status"] == "CONTENT_CHANGED"
    assert count(ctx.conn, "confirmation_requests", "order_id='ORD-1007' AND status='OPEN'") == 0


def test_request_confirmation_is_idempotent_while_awaiting_reply(ctx):
    first = request_confirmation(ctx, "ORD-1001", 1)
    second = request_confirmation(ctx, "ORD-1001", 1)
    assert second["status"] == "ALREADY_REQUESTED"
    assert second["confirmation_request_id"] == first["confirmation_request_id"]
    assert count(ctx.conn, "messages", "order_id='ORD-1001' AND kind='CONFIRMATION_REQUEST'") == 1


# ======================================================================= BR-05

def test_TC11_AC05_DT07_both_duplicates_held_none_cancelled(ctx):
    for oid, other in (("ORD-1008", "ORD-1009"), ("ORD-1009", "ORD-1008")):
        d = evaluate(ctx, oid)
        assert (d.outcome, d.reasons, d.next_action) == ("ON_HOLD", ["DUPLICATE_SUSPECTED"], "ASK_DUPLICATE_INTENT")
        assert d.details["duplicates"] == [other]
    assert flag_duplicates(ctx, "ORD-1008")["status"] == "FLAGGED"
    flag_duplicates(ctx, "ORD-1009")
    assert count(ctx.conn, "duplicate_flags") == 1
    for oid in ("ORD-1008", "ORD-1009"):
        row = order_row(ctx.conn, oid)
        assert (row["lifecycle_state"], row["agent_outcome"]) == ("PENDING", "ON_HOLD")
        assert request_confirmation(ctx, oid, 1)["status"] == "NOT_ELIGIBLE"
    assert count(ctx.conn, "orders", "lifecycle_state='CANCELLED'") == 1  # only the seeded ORD-1014
    assert evaluate(ctx, "ORD-1010").reasons == ["CONFIRMATION_REQUIRED"]  # negative control


def test_TC12_DT08_both_intended_clears_flag_and_each_reevaluated_independently(ctx):
    flag_duplicates(ctx, "ORD-1008")
    assert clear_duplicate_flag(ctx, "ORD-1008", "ORD-1009", "EVT-NONE")["status"] == "UNKNOWN_EVENT"
    ingest_event(ctx, "ORD-1008", "EVT-1008-1", "أيوه الاتنين طلبات منفصلة، واحد ليا وواحد لأختي")
    res = clear_duplicate_flag(ctx, "ORD-1009", "ORD-1008", "EVT-1008-1")
    assert res["status"] == "CLEARED" and res["reevaluate"] == ["ORD-1008", "ORD-1009"]
    for oid in ("ORD-1008", "ORD-1009"):
        assert evaluate(ctx, oid).reasons == ["CONFIRMATION_REQUIRED"]  # not auto-ready
    confirm(ctx, "ORD-1008")
    assert commit_ready(ctx, "ORD-1008", 1)["status"] == "COMMITTED"
    assert "CONFIRMATION_REQUIRED" in commit_ready(ctx, "ORD-1009", 1)["reasons"]


def test_BR05_duplicate_arriving_after_confirmation_blocks_commit_persistently(ctx):
    confirm(ctx, "ORD-1001")
    insert_order(ctx.conn, "ORD-2001", "+20 100 000 0001", [("HOODIE-BLK-L", 1)])
    res = commit_ready(ctx, "ORD-1001", 1)
    assert not res["ok"] and res["reasons"] == ["DUPLICATE_SUSPECTED"]
    assert count(ctx.conn, "duplicate_flags", "status='OPEN'") == 1
    assert order_row(ctx.conn, "ORD-1001")["lifecycle_state"] == "VERIFIED"
    assert stock(ctx.conn, "HOODIE-BLK-L") == 5


def test_BR05_duplicate_of_ready_order_escalates_without_touching_it(ctx):
    insert_order(ctx.conn, "ORD-2002", "01100000011", [("HOODIE-BLK-M", 1)], created_at="2026-10-09T18:00:00+03:00")
    assert flag_duplicates(ctx, "ORD-2002")["duplicates"] == ["ORD-1011"]
    ready = order_row(ctx.conn, "ORD-1011")
    assert (ready["lifecycle_state"], ready["version"]) == ("READY_FOR_DISPATCH", 4)
    assert count(ctx.conn, "escalations", "order_id='ORD-1011' AND reason_code='DUPLICATE_OF_NON_EDITABLE_ORDER'") == 1
    assert order_row(ctx.conn, "ORD-2002")["agent_outcome"] == "ON_HOLD"


# ======================================================================= BR-06

def test_TC13_AC06_DT09_ready_order_change_escalated_not_applied(ctx):
    ingest_event(ctx, "ORD-1011", "EVT-1011-1", "عايز أغير المقاس L")
    for _ in range(2):
        res = apply_customer_change(ctx, "ORD-1011", 4, {"items": [{"sku": "HOODIE-BLK-L", "quantity": 1}]}, "EVT-1011-1")
        assert (res["ok"], res["status"], res["blocked"]) == (False, "ESCALATED_NOT_APPLIED", True)
    row = order_row(ctx.conn, "ORD-1011")
    assert (row["lifecycle_state"], row["version"], row["agent_outcome"]) == ("READY_FOR_DISPATCH", 4, "ESCALATE_TO_HUMAN")
    assert ctx.conn.execute("SELECT sku FROM order_items WHERE order_id='ORD-1011'").fetchone()[0] == "HOODIE-BLK-M"
    assert count(ctx.conn, "escalations", "order_id='ORD-1011'") == 1
    d = evaluate(ctx, "ORD-1011", change_requested=True)
    assert (d.outcome, d.blocked, d.reasons) == ("ESCALATE_TO_HUMAN", True, ["READY_CHANGE_REQUIRES_HUMAN"])


@pytest.mark.parametrize("order_id, state", [("ORD-1012", "SHIPPED"), ("ORD-1013", "DELIVERED"), ("ORD-1014", "CANCELLED")])
def test_TC14_AC06_DT10_locked_orders_never_modified(ctx, order_id, state):
    ingest_event(ctx, order_id, f"EVT-{order_id}", "غيروا العنوان للجيزة")
    res = apply_customer_change(ctx, order_id, 1, {"governorate": "الجيزة"}, f"EVT-{order_id}")
    assert (res["ok"], res["status"], res["blocked"]) == (False, "BLOCKED_LIFECYCLE_LOCKED", True)
    row = order_row(ctx.conn, order_id)
    assert row["lifecycle_state"] == state and row["governorate"] != "giza"
    assert count(ctx.conn, "escalations", "order_id=? AND reason_code='LOCKED_ORDER_CHANGE_REQUESTED'", (order_id,)) == 1
    assert evaluate(ctx, order_id, change_requested=True).blocked


@pytest.mark.parametrize("sql", [
    "UPDATE orders SET lifecycle_state = 'PENDING' WHERE order_id = 'ORD-1014'",           # CANCELLED -> PENDING
    "UPDATE orders SET lifecycle_state = 'PENDING' WHERE order_id = 'ORD-1011'",           # READY -> PENDING
    "UPDATE orders SET lifecycle_state = 'SHIPPED' WHERE order_id = 'ORD-1001'",           # PENDING -> SHIPPED
    "UPDATE orders SET lifecycle_state = 'CANCELLED' WHERE order_id = 'ORD-1001'",         # no auto-cancel
    "UPDATE orders SET building = '99' WHERE order_id = 'ORD-1011'",                       # READY content
    "UPDATE order_items SET quantity = 2 WHERE order_id = 'ORD-1012'",                     # SHIPPED items
    "DELETE FROM order_items WHERE order_id = 'ORD-1013'",                                 # DELIVERED items
])
def test_BR06_database_triggers_block_unauthorized_transitions(seeded, sql):
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(sql)


def test_agent_outcome_cannot_be_set_ready_outside_commit(ctx):
    with pytest.raises(PermissionError):
        tools._set_outcome(ctx, "ORD-1001", "READY_FOR_DISPATCH", "x")
    with pytest.raises(PermissionError):
        tools._set_lifecycle(ctx, "ORD-1001", "PENDING", "SHIPPED")


def test_agent_outcome_is_separate_from_lifecycle(ctx):
    tools.escalate(ctx, "ORD-1011", "TEST", "staff review")
    row = order_row(ctx.conn, "ORD-1011")
    assert (row["agent_outcome"], row["lifecycle_state"]) == ("ESCALATE_TO_HUMAN", "READY_FOR_DISPATCH")


# ======================================================================= DT-14 / TC-15 (tool level)

def test_TC15_DT14_repeated_event_has_no_repeated_side_effects(ctx):
    first = ingest_event(ctx, "ORD-1001", "EVT-DUP", "تمام")
    save_event_result(ctx, "EVT-DUP", {"outcome": "ON_HOLD"})
    second = ingest_event(ctx, "ORD-1001", "EVT-DUP", "تمام")
    assert (first["status"], second["status"]) == ("RECORDED", "DUPLICATE_EVENT")
    assert second["saved_result"] == {"outcome": "ON_HOLD"}
    assert count(ctx.conn, "messages", "event_id='EVT-DUP'") == 1
    assert ingest_event(ctx, "ORD-1002", "EVT-DUP", "تمام")["status"] == "EVENT_ORDER_MISMATCH"
    send_message(ctx, "ORD-1001", "INFO", "تم استلام رسالتك", "out:EVT-DUP")
    assert send_message(ctx, "ORD-1001", "INFO", "تم استلام رسالتك", "out:EVT-DUP")["status"] == "DUPLICATE_MESSAGE"
    assert count(ctx.conn, "messages", "direction='OUTBOUND' AND order_id='ORD-1001'") == 1


# ======================================================================= AC-07 / TC-16

def test_TC16_AC07_timeout_after_success_resolved_by_op_id_without_double_allocation(ctx):
    f = faulty(ctx, commit_timeout_after_success=True)
    with pytest.raises(CommitTimeout) as exc:
        commit_ready(f, "ORD-1015", 2)
    op_id = exc.value.op_id
    assert op_id == "ready:ORD-1015:v2" and stock(ctx.conn, "TSHIRT-WHT-XL") == 3
    status = resolve_commit_outcome(f, "ORD-1015", op_id)
    assert (status["status"], status["safe_to_retry"]) == ("COMMITTED", False)
    retry = commit_ready(f, "ORD-1015", 2)
    assert retry["status"] == "ALREADY_COMMITTED"
    assert stock(ctx.conn, "TSHIRT-WHT-XL") == 3 and count(ctx.conn, "stock_reservations") == 1


def test_AC07_unknown_outcome_stops_and_escalates(ctx):
    with pytest.raises(CommitTimeout):
        commit_ready(faulty(ctx, commit_timeout_after_success=True), "ORD-1015", 2)
    res = resolve_commit_outcome(faulty(ctx, ledger_unavailable=True), "ORD-1015", "ready:ORD-1015:v2")
    assert res["status"] == "UNKNOWN_ESCALATED"
    assert count(ctx.conn, "escalations", "order_id='ORD-1015' AND reason_code='COMMIT_OUTCOME_UNKNOWN'") == 1
    assert order_row(ctx.conn, "ORD-1015")["agent_outcome"] == "ESCALATE_TO_HUMAN"


def test_AC07_not_committed_is_safe_to_retry_and_ledger_outage_fails_closed(ctx):
    assert resolve_commit_outcome(ctx, "ORD-1015", "ready:ORD-1015:v2")["safe_to_retry"] is True
    res = commit_ready(faulty(ctx, ledger_unavailable=True), "ORD-1015", 2)
    assert (res["status"], res["error_class"]) == ("SOURCE_UNAVAILABLE", "TOOL_ERROR")
    assert stock(ctx.conn, "TSHIRT-WHT-XL") == 4 and order_row(ctx.conn, "ORD-1015")["lifecycle_state"] == "VERIFIED"


# ======================================================================= observability

def test_audit_log_is_pii_redacted(ctx):
    ingest_event(ctx, "ORD-1001", "EVT-PII", "رقمي 01000000001 والعنوان شارع مصطفى النحاس")
    rows = [r[0] for r in ctx.conn.execute("SELECT detail_json FROM audit_log")]
    assert rows and not any("01000000001" in r or "مصطفى" in r for r in rows)
