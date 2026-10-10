"""Slice 2: deterministic services (no LLM, no writes)."""

import dataclasses

import pytest

from cod_rescue.errors import ExternalSourceError
from cod_rescue.normalize import is_grounded, normalize_phone, normalize_text
from cod_rescue.services import (
    check_stock, compute_quote, find_duplicate_candidates, is_unambiguous_affirmative, item_signature,
    list_alternatives, load_order, resolve_governorate, summary_hash, validate_customer, validate_phone,
)
from tests.conftest import with_faults


# ---------- normalization ----------

@pytest.mark.parametrize("raw", ["01000000008", "+20 100 000 0008", "00201000000008", "٠١٠٠٠٠٠٠٠٠٨", "0100-000-0008"])
def test_phone_normalization(raw):
    assert normalize_phone(raw) == "01000000008"


@pytest.mark.parametrize("raw, valid", [("01012345678", True), ("+201512345678", True),
                                        ("0101234567", False), ("01312345678", False), ("", False)])
def test_phone_validation(settings, raw, valid):
    assert validate_phone(settings, raw)[0] is valid


def test_arabic_text_normalization():
    assert normalize_text("الإسكندرية،  سموحة!") == normalize_text("الاسكندريه سموحه")
    assert normalize_text("عمارة ١٢") == "عماره 12"


def test_grounding_requires_literal_presence():
    source = "الشرقية، الزقازيق، عند مسجد الفتح"
    assert is_grounded("الزقازيق", source)
    assert is_grounded("مسجد الفتح", source)
    assert not is_grounded("شارع الجلاء", source)   # never supplied -> fabricated
    assert not is_grounded("12", "عمارة 125")         # token-aligned, no partial digits
    assert not is_grounded("", source)


@pytest.mark.parametrize("text, gov", [("القاهرة", "cairo"), ("القاهره", "cairo"), ("محافظة الشرقية", "sharqia"),
                                       ("Alex", "alexandria"), ("مطروح", "matrouh"), ("مصر", None), ("xyz", None)])
def test_governorate_resolution(seeded, text, gov):
    assert resolve_governorate(seeded, text) == gov


# ---------- BR-04 strict affirmative gate (SA-09) ----------

@pytest.mark.parametrize("text", ["تمام", "تمام كده", "تمام يا فندم", "ايوه أكد الطلب", "ماشي شكرا", "OK", "confirmed"])
def test_unambiguous_affirmatives_pass(settings, text):
    assert is_unambiguous_affirmative(settings, text)


@pytest.mark.parametrize("text", ["تمام؟", "تمام بس غير المقاس XL", "مش تمام", "لا", "تمام هشوف وارد عليك",
                                  "كده", "", "ok?", "تمام 2"])
def test_ambiguous_or_conditional_replies_fail(settings, text):
    assert not is_unambiguous_affirmative(settings, text)


# ---------- BR-01 stock ----------

def test_stock_and_verified_alternatives(seeded, settings):
    o = load_order(seeded, "ORD-1002")
    [line] = check_stock(seeded, settings, o.items)
    assert (line.sku, line.ok, line.reason) == ("HOODIE-BLK-XL", False, "OUT_OF_STOCK")
    alts = list_alternatives(seeded, settings, "HOODIE-BLK-XL", 1)
    assert [a["sku"] for a in alts] == ["HOODIE-BLK-L", "HOODIE-BLK-M"]
    assert all(a["available"] >= 1 for a in alts)


def test_alternatives_exclude_insufficient_stock(seeded, settings):
    assert [a["sku"] for a in list_alternatives(seeded, settings, "HOODIE-BLK-XL", 4)] == ["HOODIE-BLK-L"]


def test_DT11_inventory_outage_raises_not_guesses(seeded, settings):
    o = load_order(seeded, "ORD-1001")
    with pytest.raises(ExternalSourceError):
        check_stock(seeded, with_faults(settings, inventory_unavailable=True), o.items)


# ---------- BR-02 customer ----------

def test_AC02_landmark_only_address_reports_missing_fields(seeded, settings):
    issues = validate_customer(seeded, settings, load_order(seeded, "ORD-1004"))
    assert issues == [{"code": "ADDRESS_INCOMPLETE", "fields": ["governorate", "city", "street", "building"]}]


def test_complete_customer_has_no_issues(seeded, settings):
    assert validate_customer(seeded, settings, load_order(seeded, "ORD-1001")) == []


# ---------- BR-03 pricing ----------

def test_AC03_quote_from_trusted_tables(seeded, settings):
    q = compute_quote(seeded, settings, load_order(seeded, "ORD-1005")).quote
    assert (q.subtotal_egp, q.discount_egp, q.shipping_egp, q.total_egp) == (750, 0, 60, 810)


def test_AC03_destination_change_recomputes_total(seeded, settings):
    o = dataclasses.replace(load_order(seeded, "ORD-1005"), governorate="sharqia")
    assert compute_quote(seeded, settings, o).quote.total_egp == 825


def test_DT04_missing_shipping_rate_is_an_issue_not_a_guess(seeded, settings):
    r = compute_quote(seeded, settings, load_order(seeded, "ORD-1006"))
    assert r.quote is None and r.issues == [{"code": "SHIPPING_RATE_MISSING", "governorate": "matrouh"}]


@pytest.mark.parametrize("fault", ["price_source_unavailable", "shipping_rates_unavailable"])
def test_DT04_source_outage_raises(seeded, settings, fault):
    with pytest.raises(ExternalSourceError):
        compute_quote(seeded, with_faults(settings, **{fault: True}), load_order(seeded, "ORD-1001"))


def test_discounts_only_when_authorized(seeded, settings):
    o = load_order(seeded, "ORD-1001")
    q = compute_quote(seeded, settings, dataclasses.replace(o, discount_code="welcome10")).quote
    assert (q.discount_egp, q.total_egp) == (75, 750 - 75 + 60)
    r = compute_quote(seeded, settings, dataclasses.replace(o, discount_code="OLD50"))
    assert r.quote is None and r.issues[0]["code"] == "DISCOUNT_NOT_AUTHORIZED"


# ---------- BR-04 summary hash ----------

def test_summary_hash_is_deterministic_and_content_bound(seeded, settings):
    o = load_order(seeded, "ORD-1007")
    q = compute_quote(seeded, settings, o).quote
    h = summary_hash(o, q)
    assert len(h) == 64 and h == summary_hash(load_order(seeded, "ORD-1007"), q)
    assert summary_hash(dataclasses.replace(o, version=4), q) != h                       # version-bound
    assert summary_hash(dataclasses.replace(o, building="34"), q) != h                   # address-bound
    assert summary_hash(o, dataclasses.replace(q, total_egp=961)) != h                   # amount-bound


def test_seeded_confirmations_use_real_hashes(seeded, settings):
    rows = seeded.execute("SELECT order_id, summary_hash FROM confirmation_requests").fetchall()
    assert len(rows) == 3
    for r in rows:
        o = load_order(seeded, r["order_id"])
        assert r["summary_hash"] == summary_hash(o, compute_quote(seeded, settings, o).quote)


# ---------- BR-05 duplicate detection ----------

def test_item_signature_ignores_line_order(seeded):
    assert item_signature(load_order(seeded, "ORD-1008")) == item_signature(load_order(seeded, "ORD-1009"))


def test_AC05_duplicates_need_same_identity_and_full_signature(seeded, settings):
    assert find_duplicate_candidates(seeded, settings, load_order(seeded, "ORD-1008")) == ["ORD-1009"]
    assert find_duplicate_candidates(seeded, settings, load_order(seeded, "ORD-1009")) == ["ORD-1008"]
    # ORD-1010: same customer, overlapping SKU, different signature -> not a duplicate
    assert find_duplicate_candidates(seeded, settings, load_order(seeded, "ORD-1010")) == []


def test_duplicate_window_is_configurable(seeded, settings):
    s = dataclasses.replace(settings, simulation=dataclasses.replace(
        settings.simulation, duplicates=dataclasses.replace(settings.simulation.duplicates, window_hours=1)))
    assert find_duplicate_candidates(seeded, s, load_order(seeded, "ORD-1008")) == []  # 90 min apart
