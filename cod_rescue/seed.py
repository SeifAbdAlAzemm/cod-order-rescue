"""Load synthetic fixtures into the database.

Safety: seeding only writes into an empty database or one recognised as the synthetic demo
store, and replacing existing data requires an explicit `replace_existing=True` (CLI: --reset).
Seeding is deterministic: the same fixtures always produce an identical database.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path

from cod_rescue.config import Settings
from cod_rescue.db import SCHEMA_VERSION, init_db, schema_version, table_names, transaction
from cod_rescue.normalize import normalize_text
from cod_rescue.services import compute_quote, load_order, summary_hash

DB_PURPOSE = "SYNTHETIC_DEMO"

# Children before parents, so drops respect foreign keys.
_TABLES = [
    "audit_log", "agent_steps", "agent_runs", "escalations", "stock_reservations", "operations",
    "duplicate_flags", "event_results", "messages", "confirmation_requests",
    "order_items", "orders", "discounts", "shipping_rates", "governorate_aliases",
    "governorates", "inventory", "variants", "products", "db_meta",
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


def is_synthetic_demo_db(conn: sqlite3.Connection) -> bool:
    tables = set(table_names(conn))
    if "db_meta" in tables:
        row = conn.execute("SELECT value FROM db_meta WHERE key = 'purpose'").fetchone()
        return row is not None and row[0] == DB_PURPOSE
    # Schema v1 (before db_meta) only ever held synthetic orders (CHECK synthetic = 1).
    return "orders" in tables and schema_version(conn) == 1


def seed(conn: sqlite3.Connection, settings: Settings, *, replace_existing: bool = False) -> dict[str, int]:
    tables = table_names(conn)
    has_rows = any(conn.execute(f'SELECT 1 FROM "{t}" LIMIT 1').fetchone() for t in tables)
    if has_rows:
        if not is_synthetic_demo_db(conn):
            raise SeedError("refusing to seed: database is not marked as the synthetic demo store")
        if not replace_existing:
            raise SeedError("database already contains data; re-seed explicitly with "
                            "`python -m cod_rescue seed --reset`")
        _drop_all(conn)
    elif tables and schema_version(conn) != SCHEMA_VERSION:
        _drop_all(conn)  # empty tables from an older schema: nothing to lose
    init_db(conn)

    fixtures_dir = settings.fixtures_dir
    catalog = _load(fixtures_dir, "catalog.json")
    geography = _load(fixtures_dir, "geography.json")
    discounts = _load(fixtures_dir, "discounts.json")
    orders = _load(fixtures_dir, "orders.json")
    clean = dataclasses.replace(settings, simulation=dataclasses.replace(
        settings.simulation, fault_injection=dataclasses.replace(
            settings.simulation.fault_injection, inventory_unavailable=False, shipping_rates_unavailable=False,
            price_source_unavailable=False, commit_timeout_after_success=False, ledger_unavailable=False)))

    with transaction(conn):
        conn.execute("INSERT INTO db_meta VALUES ('purpose', ?)", (DB_PURPOSE,))
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
            for alias in sorted({normalize_text(a) for a in (g["name_ar"], g["name_en"], g["governorate"], *g["aliases"])}):
                conn.execute("INSERT INTO governorate_aliases VALUES (?, ?)", (alias, g["governorate"]))
            if g["fee_egp"] is not None:
                conn.execute(
                    "INSERT INTO shipping_rates VALUES (?, ?, ?)",
                    (g["governorate"], g["fee_egp"], geography["rates_updated_at"]),
                )

        for d in discounts["discounts"]:
            conn.execute("INSERT INTO discounts VALUES (:code, :kind, :value, :active)", d)

        for o in orders["orders"]:
            _insert_order(conn, clean, o)

    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in reversed(_TABLES)}


def _drop_all(conn: sqlite3.Connection) -> None:
    # DROP TABLE fires no triggers, so lifecycle guards cannot block an explicit synthetic reset.
    with transaction(conn):
        for t in _TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.execute("PRAGMA user_version = 0")


def _insert_order(conn: sqlite3.Connection, settings: Settings, o: dict) -> None:
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
        # Bind seeded confirmations to the real canonical content hash, exactly as the tools do.
        order = load_order(conn, o["order_id"])
        pricing = compute_quote(conn, settings, order)
        if pricing.quote is None or cr["order_version"] != order.version:
            raise SeedError(f"{cr['confirmation_request_id']}: fixture cannot be bound to current order content")
        if pricing.quote.total_egp != cr["total_egp"]:
            raise SeedError(f"{cr['confirmation_request_id']}: fixture total {cr['total_egp']} "
                            f"!= computed {pricing.quote.total_egp}")
        conn.execute(
            "INSERT INTO confirmation_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cr["confirmation_request_id"], o["order_id"], cr["order_version"],
                summary_hash(order, pricing.quote),
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
