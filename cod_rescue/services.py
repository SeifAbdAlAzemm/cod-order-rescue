"""Deterministic read-side services over the simulated authoritative sources.

No function here writes to the database or calls an LLM. Unavailable sources raise
ExternalSourceError; missing data is reported, never filled in.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime

from cod_rescue.config import Settings
from cod_rescue.errors import ExternalSourceError, UnknownOrder
from cod_rescue.normalize import normalize_phone, normalize_text

ADDRESS_FIELDS = ("governorate", "city", "district", "street", "building", "floor", "apartment", "landmark")
EDITABLE_STATES = ("PENDING", "VERIFIED")
LOCKED_STATES = ("SHIPPED", "DELIVERED", "CANCELLED")


# ---------- order snapshot ----------

@dataclass(frozen=True)
class Item:
    line_no: int
    sku: str
    quantity: int
    product_id: str | None
    size: str | None
    color: str | None
    active: bool


@dataclass(frozen=True)
class Order:
    order_id: str
    channel: str
    lifecycle_state: str
    version: int
    customer_name: str | None
    phone_raw: str | None
    address_raw: str | None
    governorate: str | None
    city: str | None
    district: str | None
    street: str | None
    building: str | None
    floor: str | None
    apartment: str | None
    landmark: str | None
    discount_code: str | None
    quoted_version: int | None
    quoted_subtotal_egp: int | None
    quoted_discount_egp: int | None
    quoted_shipping_egp: int | None
    quoted_total_egp: int | None
    agent_outcome: str | None
    outcome_reason: str | None
    clarification_attempts: int
    synthetic: int
    created_at: str
    updated_at: str
    items: tuple[Item, ...] = ()

    @property
    def phone_normalized(self) -> str:
        return normalize_phone(self.phone_raw)

    def address(self) -> dict:
        return {f: getattr(self, f) for f in ADDRESS_FIELDS}


def load_order(conn: sqlite3.Connection, order_id: str) -> Order:
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise UnknownOrder(order_id)
    items = tuple(
        Item(r["line_no"], r["sku"], r["quantity"], r["product_id"], r["size"], r["color"], bool(r["active"]))
        for r in conn.execute(
            "SELECT i.line_no, i.sku, i.quantity, v.product_id, v.size, v.color, COALESCE(v.active, 0) AS active "
            "FROM order_items i LEFT JOIN variants v ON v.sku = i.sku WHERE i.order_id = ? ORDER BY i.line_no",
            (order_id,),
        )
    )
    return Order(**dict(row), items=items)


# ---------- BR-01 inventory ----------

@dataclass(frozen=True)
class StockLine:
    sku: str
    requested: int
    available: int | None
    ok: bool
    reason: str | None  # OUT_OF_STOCK | UNKNOWN_SKU


def check_stock(conn: sqlite3.Connection, settings: Settings, items) -> list[StockLine]:
    if settings.simulation.fault_injection.inventory_unavailable:
        raise ExternalSourceError("inventory")
    needed: dict[str, int] = {}
    for it in items:
        needed[it.sku] = needed.get(it.sku, 0) + it.quantity
    lines = []
    for sku, qty in needed.items():
        row = conn.execute(
            "SELECT inv.available, v.active FROM variants v JOIN inventory inv ON inv.sku = v.sku WHERE v.sku = ?",
            (sku,),
        ).fetchone()
        if row is None or not row["active"]:
            lines.append(StockLine(sku, qty, None, False, "UNKNOWN_SKU"))
        else:
            ok = row["available"] >= qty
            lines.append(StockLine(sku, qty, row["available"], ok, None if ok else "OUT_OF_STOCK"))
    return lines


def list_alternatives(conn: sqlite3.Connection, settings: Settings, sku: str, quantity: int) -> list[dict]:
    """Verified in-stock variants of the same product. Only these may be offered (BR-01)."""
    if settings.simulation.fault_injection.inventory_unavailable:
        raise ExternalSourceError("inventory")
    rows = conn.execute(
        "SELECT v.sku, v.size, v.color, v.unit_price_egp, inv.available FROM variants v "
        "JOIN inventory inv ON inv.sku = v.sku "
        "WHERE v.product_id = (SELECT product_id FROM variants WHERE sku = ?) "
        "AND v.sku <> ? AND v.active = 1 AND inv.available >= ? ORDER BY v.sku",
        (sku, sku, quantity),
    )
    return [dict(r) for r in rows]


# ---------- BR-02 customer / address ----------

def resolve_governorate(conn: sqlite3.Connection, text: str | None) -> str | None:
    key = normalize_text(text)
    key = re.sub(r"^محافظه ", "", key)
    if not key:
        return None
    if conn.execute("SELECT 1 FROM governorates WHERE governorate = ?", (key,)).fetchone():
        return key
    row = conn.execute("SELECT governorate FROM governorate_aliases WHERE alias = ?", (key,)).fetchone()
    return row["governorate"] if row else None


def validate_phone(settings: Settings, raw: str | None) -> tuple[bool, str]:
    normalized = normalize_phone(raw)
    return bool(re.fullmatch(settings.simulation.phone.pattern, normalized)), normalized


def validate_customer(conn: sqlite3.Connection, settings: Settings, order: Order) -> list[dict]:
    """Return a list of issues {code, fields}. Empty list = sufficient for delivery (SA-03/SA-04)."""
    issues = []
    if not (order.customer_name or "").strip():
        issues.append({"code": "CUSTOMER_NAME_MISSING", "fields": ["customer_name"]})
    if not validate_phone(settings, order.phone_raw)[0]:
        issues.append({"code": "PHONE_INVALID", "fields": ["phone"]})
    missing = [f for f in settings.simulation.address.required_fields if not (getattr(order, f) or "").strip()]
    if missing:
        issues.append({"code": "ADDRESS_INCOMPLETE", "fields": missing})
    if order.governorate and resolve_governorate(conn, order.governorate) != order.governorate:
        issues.append({"code": "GOVERNORATE_UNKNOWN", "fields": ["governorate"]})
    return issues


# ---------- BR-03 pricing ----------

@dataclass(frozen=True)
class Quote:
    lines: tuple[dict, ...]
    subtotal_egp: int
    discount_egp: int
    shipping_egp: int
    total_egp: int
    governorate: str


@dataclass(frozen=True)
class PricingResult:
    quote: Quote | None
    issues: list[dict] = field(default_factory=list)


def compute_quote(conn: sqlite3.Connection, settings: Settings, order: Order) -> PricingResult:
    """Price strictly from the trusted synthetic tables; any gap -> issue, never an estimate."""
    faults = settings.simulation.fault_injection
    if faults.price_source_unavailable:
        raise ExternalSourceError("prices")
    if faults.shipping_rates_unavailable:
        raise ExternalSourceError("shipping_rates")

    issues = []
    lines = []
    for it in order.items:
        row = conn.execute("SELECT unit_price_egp, active FROM variants WHERE sku = ?", (it.sku,)).fetchone()
        if row is None or not row["active"]:
            issues.append({"code": "PRICE_MISSING", "sku": it.sku})
            continue
        lines.append({"sku": it.sku, "quantity": it.quantity, "unit_price_egp": row["unit_price_egp"],
                      "line_total_egp": row["unit_price_egp"] * it.quantity})
    subtotal = sum(l["line_total_egp"] for l in lines)

    discount = 0
    if order.discount_code:
        d = conn.execute("SELECT * FROM discounts WHERE code = ?", (order.discount_code.strip().upper(),)).fetchone()
        if d is None or not d["active"]:
            issues.append({"code": "DISCOUNT_NOT_AUTHORIZED", "discount_code": order.discount_code})
        elif d["kind"] == "PERCENT":
            discount = subtotal * d["value"] // 100  # whole EGP; fractional discount rounded down (SA-07)
        else:
            discount = min(d["value"], subtotal)

    if not order.governorate or resolve_governorate(conn, order.governorate) != order.governorate:
        issues.append({"code": "SHIPPING_DESTINATION_UNKNOWN"})
        shipping = None
    else:
        rate = conn.execute("SELECT fee_egp FROM shipping_rates WHERE governorate = ?", (order.governorate,)).fetchone()
        shipping = rate["fee_egp"] if rate else None
        if rate is None:
            issues.append({"code": "SHIPPING_RATE_MISSING", "governorate": order.governorate})

    if issues:
        return PricingResult(None, issues)
    return PricingResult(Quote(tuple(lines), subtotal, discount, shipping, subtotal - discount + shipping,
                               order.governorate))


# ---------- BR-04 confirmation binding ----------

def summary_payload(order: Order, quote: Quote) -> dict:
    """Canonical content a customer confirms. Any change here changes the hash."""
    sizes = {it.sku: (it.size, it.color) for it in order.items}
    return {
        "order_id": order.order_id,
        "version": order.version,
        "customer_name": (order.customer_name or "").strip(),
        "phone": order.phone_normalized,
        "address": {f: (getattr(order, f) or "").strip() for f in ADDRESS_FIELDS},
        "items": sorted(
            ({"sku": l["sku"], "size": sizes[l["sku"]][0], "color": sizes[l["sku"]][1], "quantity": l["quantity"],
              "unit_price_egp": l["unit_price_egp"]} for l in quote.lines),
            key=lambda x: x["sku"],
        ),
        "discount_code": (order.discount_code or "").strip().upper(),
        "subtotal_egp": quote.subtotal_egp,
        "discount_egp": quote.discount_egp,
        "shipping_egp": quote.shipping_egp,
        "total_egp": quote.total_egp,
        "currency": "EGP",
        "payment": "COD",
    }


def summary_hash(order: Order, quote: Quote) -> str:
    canonical = json.dumps(summary_payload(order, quote), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_summary(conn: sqlite3.Connection, order: Order, quote: Quote) -> str:
    """Deterministic Arabic confirmation text (amounts come from the quote, never from the LLM)."""
    names = {r["sku"]: r["name_ar"] for r in conn.execute(
        "SELECT v.sku, p.name_ar FROM variants v JOIN products p ON p.product_id = v.product_id")}
    gov = conn.execute("SELECT name_ar FROM governorates WHERE governorate = ?", (quote.governorate,)).fetchone()
    sizes = {it.sku: it.size for it in order.items}
    parts = [f"{names[l['sku']]} مقاس {sizes[l['sku']]} × {l['quantity']} = {l['line_total_egp']} جنيه" for l in quote.lines]
    text = f"ملخص طلبك {order.order_id} (نسخة {order.version}): " + "، ".join(parts)
    if quote.discount_egp:
        text += f" - خصم {quote.discount_egp} جنيه"
    text += (f" + شحن {gov['name_ar']} {quote.shipping_egp} جنيه = الإجمالي {quote.total_egp} جنيه دفع عند الاستلام. "
             f"العنوان: {order.city}، {order.street}، عمارة {order.building}. ترد بـ (تمام) للتأكيد؟")
    return text


def is_unambiguous_affirmative(settings: Settings, text: str | None) -> bool:
    """Strict lexical gate for BR-04 (SA-09). A question or any non-affirmative word fails."""
    if not text or "?" in text or "؟" in text:
        return False
    rules = settings.simulation.confirmation
    core = {normalize_text(w) for w in rules.short_affirmatives}
    allowed = core | {normalize_text(w) for w in rules.filler_words}
    words = normalize_text(text).split()
    return bool(words) and all(w in allowed for w in words) and any(w in core for w in words)


# Free-text outbound policy (SA-21): the agent may not make operational commitments it cannot verify.
_DAYS = r"(السبت|الاحد|الاتنين|التلات|التلاتاء|الاربع|الاربعاء|الخميس|الجمعه|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_COMMITMENT_PATTERNS = {
    "DELIVERY_PROMISE": [
        r"(هيوصل|هتوصل|هيوصلك|هتستلم|هتستلمه|هيتسلم|هيجيلك|التوصيل|الاستلام|هيكون عندك|deliver\w*|arriv\w*)"
        r"\W+(\w+\W+){0,4}(بكره|بكرا|النهارده|انهارده|بعد بكره|خلال|يوم|ايام|ساعه|ساعات|الاسبوع|" + _DAYS[1:-1]
        + r"|today|tomorrow|within|\d)",
        r"(خلال|في خلال|within)\s+\d+\s*(يوم|ايام|ساعه|ساعات|days?|hours?)",
    ],
    "REFUND_OR_COMPENSATION": [r"(استرداد|استرجاع فلوس|فلوسك هترجع|تعويض|refund|compensat\w*)"],
    "FREE_OR_GUARANTEE": [r"(مجان\w*|ببلاش|شحن مجاني|free|مضمون|اضمنلك|ضمان|guarantee\w*|بوعدك|اوعدك|promise)"],
    "CANCELLATION_CLAIM": [r"(اتلغي|تم الغاء|تم إلغاء|لغينا|الغينا|cancell?ed)"],
}
_STATE_CLAIMS = {  # allowed only when the authoritative lifecycle supports them
    "CONFIRMATION_CLAIM": (r"(\bاتاكد\b|تم تاكيد|اتاكد طلبك|طلبك اتاكد|confirmed)", {"READY_FOR_DISPATCH", "SHIPPED", "DELIVERED"}),
    "SHIPPING_CLAIM": (r"(اتشحن|تم الشحن|في الطريق|shipped|on the way)", {"SHIPPED", "DELIVERED"}),
}


def outbound_violations(text: str, lifecycle_state: str) -> list[str]:
    t = normalize_text(text)
    found = [code for code, pats in _COMMITMENT_PATTERNS.items() if any(re.search(p, t) for p in pats)]
    found += [code for code, (pat, ok_states) in _STATE_CLAIMS.items()
              if re.search(pat, t) and lifecycle_state not in ok_states]
    return found


def is_explicit_both_intended(settings: Settings, text: str | None) -> bool:
    """Strict lexical gate for DT-08: explicit 'yes, both orders'. Questions, negations,
    conditions or any unlisted word fail (e.g. 'لا واحد بس', 'الاتنين؟', 'اه بس الغي واحد')."""
    if not text or "?" in text or "؟" in text:
        return False
    conf, dup = settings.simulation.confirmation, settings.simulation.duplicates
    core = {normalize_text(w) for w in conf.short_affirmatives}
    markers = {normalize_text(w) for w in dup.both_markers}
    allowed = core | markers | {normalize_text(w) for w in (*conf.filler_words, *dup.both_intended_words)}
    words = normalize_text(text).split()
    return (bool(words) and all(w in allowed for w in words)
            and any(w in core for w in words) and any(w in markers for w in words))


# ---------- BR-05 duplicates ----------

def item_signature(order: Order) -> tuple:
    agg: dict[tuple, int] = {}
    for it in order.items:
        key = (it.sku, it.size)
        agg[key] = agg.get(key, 0) + it.quantity
    return tuple(sorted((sku, size, qty) for (sku, size), qty in agg.items()))


def find_duplicate_candidates(conn: sqlite3.Connection, settings: Settings, order: Order) -> list[str]:
    """Distinct orders with same normalized phone AND identical item signature within the window (SA-01/02).

    Pairs a customer already cleared as 'both intended' are excluded.
    """
    rules = settings.simulation.duplicates
    phone = order.phone_normalized
    if not phone:
        return []
    created = datetime.fromisoformat(order.created_at)
    signature = item_signature(order)
    placeholders = ",".join("?" for _ in rules.ignore_lifecycle_states) or "''"
    candidates = []
    for row in conn.execute(
        f"SELECT order_id FROM orders WHERE order_id <> ? AND lifecycle_state NOT IN ({placeholders})",
        (order.order_id, *rules.ignore_lifecycle_states),
    ):
        other = load_order(conn, row["order_id"])
        if other.phone_normalized != phone or item_signature(other) != signature:
            continue
        if abs((datetime.fromisoformat(other.created_at) - created).total_seconds()) > rules.window_hours * 3600:
            continue
        a, b = sorted((order.order_id, other.order_id))
        cleared = conn.execute(
            "SELECT 1 FROM duplicate_flags WHERE order_id_a = ? AND order_id_b = ? AND status = 'CLEARED_BOTH_INTENDED'",
            (a, b),
        ).fetchone()
        if not cleared:
            candidates.append(other.order_id)
    return sorted(candidates)


def open_duplicate_flags(conn: sqlite3.Connection, order_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT CASE WHEN order_id_a = ? THEN order_id_b ELSE order_id_a END AS other FROM duplicate_flags "
        "WHERE (order_id_a = ? OR order_id_b = ?) AND status IN ('OPEN', 'ESCALATED')",
        (order_id, order_id, order_id),
    )
    return sorted(r["other"] for r in rows)


def to_dict(obj) -> dict:
    return asdict(obj)
