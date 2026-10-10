"""Slice 1 smoke tests: configuration, schema, constraints, fixtures and the seed command.

These verify foundations only. Business-rule behaviour (BR-01..BR-06) is tested from Slice 2.
"""

import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from cod_rescue import PROJECT_ROOT
from cod_rescue.config import DEFAULT_SETTINGS_PATH, SIMULATION_STATUS, ConfigError, load_settings
from cod_rescue.db import SCHEMA_VERSION, connect, init_db, schema_version, table_names, transaction
from cod_rescue.seed import SeedError, seed

EXPECTED_TABLES = {
    "db_meta", "products", "variants", "inventory", "governorates", "governorate_aliases", "shipping_rates", "discounts",
    "orders", "order_items", "confirmation_requests", "messages", "event_results", "duplicate_flags",
    "operations", "stock_reservations", "escalations", "agent_runs", "audit_log",
}


def _write_settings(tmp_path, transform):
    text = transform(DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _db_fingerprint(conn):
    h = hashlib.sha256()
    for table in sorted(EXPECTED_TABLES):
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2"):
            h.update(repr(tuple(row)).encode())
    return h.hexdigest()


# ---------- configuration ----------

def test_settings_load_with_approved_model_and_simulated_messaging(settings):
    assert settings.llm.model == "claude-haiku-5-5"
    assert settings.simulation.messaging.mode == "SIMULATED_OUTBOX"
    assert settings.simulation.duplicates.window_hours == 24
    assert settings.simulation.duplicates.item_match == "exact_signature"
    assert "claude-haiku-5-5" in settings.llm.pricing_usd_per_mtok


def test_every_simulation_section_is_labelled_as_assumption(settings):
    for name in settings.simulation.__dataclass_fields__:
        assert getattr(settings.simulation, name).status == SIMULATION_STATUS, name


def test_fault_injection_disabled_by_default(settings):
    fi = settings.simulation.fault_injection
    assert not any([fi.inventory_unavailable, fi.shipping_rates_unavailable,
                    fi.price_source_unavailable, fi.commit_timeout_after_success])


def test_env_overrides_model_and_db_path(tmp_path):
    s = load_settings(env={"COD_RESCUE_MODEL": "claude-sonnet-5-5", "COD_RESCUE_DB_PATH": str(tmp_path / "x.db")})
    assert s.llm.model == "claude-sonnet-5-5"
    assert s.db_path == tmp_path / "x.db"


@pytest.mark.parametrize(
    "transform, message",
    [
        (lambda t: t.replace('mode = "SIMULATED_OUTBOX"', 'mode = "WHATSAPP_LIVE"'), "SIMULATED_OUTBOX"),
        (lambda t: t.replace("window_hours = 24", "window_hours = 24\nunexpected_key = 1"), "unexpected_key"),
        (lambda t: t.replace('[simulation.phone]\nstatus = "SIMULATION_ASSUMPTION"', "[simulation.phone]"), "status"),
        (lambda t: t.replace("max_tool_calls = 8", "max_tool_calls = 0"), "agent_budget"),
        (lambda t: t.replace('provider = "anthropic"', 'provider = "anthropic"\napi_key = "x"'), "secrets"),
    ],
    ids=["live-messaging", "unknown-key", "unlabelled-assumption", "unbounded-budget", "secret-in-file"],
)
def test_invalid_settings_are_rejected(tmp_path, transform, message):
    with pytest.raises(ConfigError, match=message):
        load_settings(_write_settings(tmp_path, transform), env={})


def test_no_credentials_committed():
    text = DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8") + (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "sk-ant-" not in text
    assert "ANTHROPIC_API_KEY=\n" in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")


# ---------- schema ----------

def test_init_creates_all_tables_with_version(conn):
    assert set(table_names(conn)) >= EXPECTED_TABLES
    assert schema_version(conn) == SCHEMA_VERSION
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_init_is_idempotent(conn):
    assert init_db(conn) is False
    assert set(table_names(conn)) >= EXPECTED_TABLES


def test_transaction_rolls_back_on_error(seeded):
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(seeded):
            seeded.execute("UPDATE inventory SET available = available - 1 WHERE sku = 'TSHIRT-WHT-L'")
            seeded.execute("UPDATE inventory SET available = available - 1 WHERE sku = 'HOODIE-BLK-XL'")  # 0 -> -1
    assert seeded.execute("SELECT available FROM inventory WHERE sku = 'TSHIRT-WHT-L'").fetchone()[0] == 1


CONSTRAINT_VIOLATIONS = {
    "negative-stock": "UPDATE inventory SET available = -1 WHERE sku = 'HOODIE-BLK-L'",
    "unknown-lifecycle": "UPDATE orders SET lifecycle_state = 'RETURNED' WHERE order_id = 'ORD-1001'",
    "unknown-outcome": "UPDATE orders SET agent_outcome = 'AUTO_CANCELLED' WHERE order_id = 'ORD-1001'",
    "non-synthetic-order": "UPDATE orders SET synthetic = 0 WHERE order_id = 'ORD-1001'",
    "unknown-sku-fk": "INSERT INTO order_items VALUES ('ORD-1001', 9, 'NO-SUCH-SKU', 1)",
    "zero-quantity": "INSERT INTO order_items VALUES ('ORD-1001', 9, 'HOODIE-BLK-L', 0)",
    "second-open-confirmation": (
        "INSERT INTO confirmation_requests (confirmation_request_id, order_id, order_version, summary_hash, "
        "total_egp, status, created_at) VALUES ('CR-X', 'ORD-1007', 3, 'h', 960, 'OPEN', 't')"
    ),
    "duplicate-event-id": (
        "INSERT INTO messages (order_id, direction, kind, body, event_id, created_at) "
        "VALUES ('ORD-1005', 'INBOUND', 'CUSTOMER', 'تمام', 'EVT-1005-001', 't')"
    ),
    "inbound-without-event-id": (
        "INSERT INTO messages (order_id, direction, kind, body, created_at) "
        "VALUES ('ORD-1001', 'INBOUND', 'CUSTOMER', 'hi', 't')"
    ),
    "live-delivery": (
        "INSERT INTO messages (order_id, direction, kind, body, delivery, created_at) "
        "VALUES ('ORD-1001', 'OUTBOUND', 'INFO', 'hi', 'WHATSAPP', 't')"
    ),
    "unordered-duplicate-pair": (
        "INSERT INTO duplicate_flags (order_id_a, order_id_b, match_basis, status, created_at) "
        "VALUES ('ORD-1009', 'ORD-1008', 'x', 'OPEN', 't')"
    ),
    "unknown-run-mode": ("INSERT INTO agent_runs (run_id, mode, status, cost_basis, started_at) "
                         "VALUES ('r', 'MIXED', 'RUNNING', 'NOT_APPLICABLE_REPLAY', 't')"),
    "replay-run-with-model-cost": ("INSERT INTO agent_runs (run_id, mode, status, cost_basis, started_at) "
                                   "VALUES ('r', 'REPLAY', 'RUNNING', 'ESTIMATED_FROM_TOKEN_USAGE', 't')"),
    "live-run-labelled-replay-cost": ("INSERT INTO agent_runs (run_id, mode, status, cost_basis, started_at) "
                                      "VALUES ('r', 'LIVE', 'RUNNING', 'NOT_APPLICABLE_REPLAY', 't')"),
}


@pytest.mark.parametrize("sql", CONSTRAINT_VIOLATIONS.values(), ids=CONSTRAINT_VIOLATIONS.keys())
def test_schema_rejects_invalid_state(seeded, sql):
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(sql)


def test_operation_ids_are_unique(seeded):
    sql = ("INSERT INTO operations (op_id, order_id, op_type, status, request_json, created_at) "
           "VALUES ('ready:ORD-1015:v2', 'ORD-1015', 'COMMIT_READY', 'SUCCEEDED', '{}', 't')")
    seeded.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(sql)


# ---------- seed ----------

def test_seed_loads_expected_counts(seeded):
    counts = {t: seeded.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("products", "variants", "inventory", "governorates", "shipping_rates", "orders")}
    assert counts == {"products": 4, "variants": 12, "inventory": 12, "governorates": 9,
                      "shipping_rates": 8, "orders": 15}


def test_seed_is_deterministic_and_repeatable(seeded, settings):
    first = _db_fingerprint(seeded)
    seeded.execute("UPDATE inventory SET available = 99 WHERE sku = 'HOODIE-BLK-L'")
    seed(seeded, settings, replace_existing=True)
    assert _db_fingerprint(seeded) == first


def test_seed_refuses_to_overwrite_without_explicit_reset(seeded, settings):
    with pytest.raises(SeedError, match="--reset"):
        seed(seeded, settings)
    assert seeded.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 15


def test_seed_refuses_non_synthetic_database_even_with_reset(tmp_path, settings):
    foreign = connect(tmp_path / "foreign.sqlite3")
    foreign.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
    foreign.execute("INSERT INTO customers (name) VALUES ('real data')")
    with pytest.raises(SeedError, match="not marked as the synthetic demo"):
        seed(foreign, settings, replace_existing=True)
    assert foreign.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 1
    foreign.close()


def test_seeded_db_is_marked_synthetic(seeded):
    assert seeded.execute("SELECT value FROM db_meta WHERE key = 'purpose'").fetchone()[0] == "SYNTHETIC_DEMO"


def test_seed_starts_with_no_runtime_side_effects(seeded):
    for table in ("operations", "stock_reservations", "escalations", "event_results",
                  "duplicate_flags", "agent_runs", "audit_log"):
        assert seeded.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


# ---------- fixtures support the planned scenarios (data only, no business logic) ----------

def _orders_fixture():
    return json.loads((PROJECT_ROOT / "data/fixtures/orders.json").read_text(encoding="utf-8"))["orders"]


def test_fixtures_cover_every_test_case():
    tagged = {tc for o in _orders_fixture() for tc in o["test_cases"]}
    assert tagged == {f"TC-{i:02d}" for i in range(1, 17)}


def test_all_orders_are_synthetic(seeded):
    assert seeded.execute("SELECT COUNT(*) FROM orders WHERE synthetic <> 1").fetchone()[0] == 0
    names = [r[0] for r in seeded.execute("SELECT DISTINCT customer_name FROM orders")]
    assert all(n.startswith("عميل تجريبي") for n in names)  # "test customer" placeholders


def test_ac01_fixture_xl_out_of_stock_l_available(seeded):
    stock = dict(seeded.execute("SELECT sku, available FROM inventory WHERE sku LIKE 'HOODIE-BLK-%'").fetchall())
    assert stock["HOODIE-BLK-XL"] == 0 and stock["HOODIE-BLK-L"] > 0
    assert seeded.execute("SELECT sku FROM order_items WHERE order_id = 'ORD-1002'").fetchone()[0] == "HOODIE-BLK-XL"


def test_ac02_fixture_address_has_only_supplied_fields(seeded):
    o = seeded.execute("SELECT * FROM orders WHERE order_id = 'ORD-1004'").fetchone()
    assert o["address_raw"] == "الشرقية، الزقازيق، عند مسجد الفتح"
    assert all(o[f] is None for f in ("governorate", "city", "street", "building", "landmark"))


def test_ac03_fixture_810_total_matches_authoritative_sources(seeded):
    o = seeded.execute("SELECT * FROM orders WHERE order_id = 'ORD-1005'").fetchone()
    price = seeded.execute("SELECT unit_price_egp FROM variants WHERE sku = 'HOODIE-BLK-M'").fetchone()[0]
    fee = seeded.execute("SELECT fee_egp FROM shipping_rates WHERE governorate = 'cairo'").fetchone()[0]
    assert o["quoted_total_egp"] == 810 == price + fee
    assert o["quoted_version"] == o["version"] == 2


def test_ac04_fixture_open_request_bound_to_current_version(seeded):
    cr = seeded.execute("SELECT * FROM confirmation_requests WHERE order_id = 'ORD-1007'").fetchall()
    assert len(cr) == 1 and cr[0]["status"] == "OPEN" and cr[0]["order_version"] == 3
    last = seeded.execute("SELECT * FROM messages WHERE order_id = 'ORD-1007' ORDER BY seq DESC LIMIT 1").fetchone()
    assert last["kind"] == "CONFIRMATION_REQUEST" and last["confirmation_request_id"] == "CR-1007-V3"


def test_tc08_fixture_matrouh_has_no_trusted_rate(seeded):
    assert seeded.execute("SELECT COUNT(*) FROM governorates WHERE governorate = 'matrouh'").fetchone()[0] == 1
    assert seeded.execute("SELECT COUNT(*) FROM shipping_rates WHERE governorate = 'matrouh'").fetchone()[0] == 0


def test_lifecycle_fixtures_present(seeded):
    states = dict(seeded.execute(
        "SELECT order_id, lifecycle_state FROM orders WHERE order_id IN ('ORD-1011','ORD-1012','ORD-1013','ORD-1014')"
    ).fetchall())
    assert states == {"ORD-1011": "READY_FOR_DISPATCH", "ORD-1012": "SHIPPED",
                      "ORD-1013": "DELIVERED", "ORD-1014": "CANCELLED"}


# ---------- CLI ----------

def test_cli_seed_and_status(tmp_path):
    db = tmp_path / "cli.sqlite3"
    run = lambda *a: subprocess.run([sys.executable, "-m", "cod_rescue", "--db", str(db), *a],
                                    cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
    seeded = run("seed")
    assert seeded.returncode == 0, seeded.stderr
    assert "SYNTHETIC" in seeded.stdout
    again = run("seed")
    assert again.returncode == 2 and "--reset" in again.stderr
    assert run("seed", "--reset").returncode == 0
    status = run("status")
    assert status.returncode == 0, status.stderr
    assert "ORD-1015" in status.stdout and "SIMULATED" in status.stdout
