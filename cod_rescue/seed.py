"""Load synthetic fixtures into the database.

Seeding is deterministic and repeatable: it clears every table and reloads all
fixtures in one transaction, so running it twice yields an identical database.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from cod_rescue.db import init_db, transaction

# Children before parents, so deletes respect foreign keys.
_CLEAR_ORDER = [
    "audit_log", "agent_runs", "escalations", "stock_reservations", "operations",
    "duplicate_flags", "event_results", "messages", "confirmation_requests",
    "order_items", "orders", "discounts", "shipping_rates", "governorate_aliases",
    "governorates", "inventory", "variants", "products",
]

_ORDER_FIELDS = {
    "order_id", "channel", "lifecycle_state", "version", "customer_name", "phone_raw", "address_raw",
    "governorate", "city", "district", "street", "building", "floor", "apartment", "landmark",
    "discount_code", "agent_outcome", "created_at",
}
_ORDER_META = {"test_cases", "acceptance", "purpose", "items", "quote", "confirmation_requests", "messages"}


class SeedError(ValueError):
    pass


def _load(fixtures_dir: Path, name: str) -> dict:
    with open(fixtures_dir / name, encoding="utf-8") as f:
        return json.load(f)


def seed(conn: sqlite3.Connection, fixtures_dir: Path) -> dict[str, int]:
    init_db(conn)
    catalog = _load(fixtures_dir, "catalog.json")
    geography = _load(fixtures_dir, "geography.json")
    discounts = _load(fixtures_dir, "discounts.json")
    orders = _load(fixtures_dir, "orders.json")

    with transaction(conn):
        for table in _CLEAR_ORDER:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence")

        for p in catalog["products"]:
            conn.execute("INSERT INTO products VALUES (:product_id, :name_ar, :name_en)", p)
        for v in catalog["variants"]:
            conn.execute(
                "INSERT INTO variants (sku, product_id, size, color, unit_price_egp, price_updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (v["sku"], v["product_id"], v["size"], v["color"], v["unit_price_egp"], catalog["price_updated_at"]),
            )
            conn.execute(
                "INSERT INTO inventory VALUES (?, ?, ?)", (v["sku"], v["available"], catalog["stock_updated_at"])
            )

        for g in geography["governorates"]:
            conn.execute("INSERT INTO governorates VALUES (:governorate, :name_ar, :name_en)", g)
            for alias in sorted({a.lower() for a in (g["name_ar"], g["name_en"], g["governorate"], *g["aliases"])}):
                conn.execute("INSERT INTO governorate_aliases VALUES (?, ?)", (alias, g["governorate"]))
            if g["fee_egp"] is not None:
                conn.execute(
                    "INSERT INTO shipping_rates VALUES (?, ?, ?)",
                    (g["governorate"], g["fee_egp"], geography["rates_updated_at"]),
                )

        for d in discounts["discounts"]:
            conn.execute("INSERT INTO discounts VALUES (:code, :kind, :value, :active)", d)

        for o in orders["orders"]:
            _insert_order(conn, o)

    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in reversed(_CLEAR_ORDER)}


def _insert_order(conn: sqlite3.Connection, o: dict) -> None:
    unknown = set(o) - _ORDER_FIELDS - _ORDER_META
    if unknown:
        raise SeedError(f"{o.get('order_id')}: unknown fixture keys {sorted(unknown)}")
    if not o.get("items"):
        raise SeedError(f"{o['order_id']}: an order needs at least one item")

    row = {k: o.get(k) for k in _ORDER_FIELDS}
    quote = o.get("quote") or {}
    row.update(
        quoted_version=quote.get("version"),
        quoted_subtotal_egp=quote.get("subtotal_egp"),
        quoted_discount_egp=quote.get("discount_egp"),
        quoted_shipping_egp=quote.get("shipping_egp"),
        quoted_total_egp=quote.get("total_egp"),
        updated_at=o["created_at"],
    )
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO orders ({cols}) VALUES ({', '.join(':' + c for c in row)})", row)

    for line_no, item in enumerate(o["items"], start=1):
        conn.execute(
            "INSERT INTO order_items VALUES (?, ?, ?, ?)", (o["order_id"], line_no, item["sku"], item["quantity"])
        )

    for cr in o.get("confirmation_requests", []):
        conn.execute(
            "INSERT INTO confirmation_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cr["confirmation_request_id"], o["order_id"], cr["order_version"],
                # Placeholder until Slice 2 defines the canonical summary hash.
                f"fixture:{cr['confirmation_request_id']}",
                cr["total_egp"], cr["status"], cr.get("accepted_event_id"), cr["created_at"], cr.get("resolved_at"),
            ),
        )

    for m in o.get("messages", []):
        conn.execute(
            "INSERT INTO messages (order_id, direction, kind, body, event_id, idempotency_key, "
            "confirmation_request_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                o["order_id"], m["direction"], m["kind"], m["body"], m.get("event_id"),
                m.get("idempotency_key"), m.get("confirmation_request_id"), m["created_at"],
            ),
        )
