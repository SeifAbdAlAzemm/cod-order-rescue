"""Shared test helpers (synthetic setup only)."""

from cod_rescue.services import compute_quote, load_order, summary_hash
from cod_rescue.tools import ingest_event, record_confirmation, request_confirmation


def stock(conn, sku):
    return conn.execute("SELECT available FROM inventory WHERE sku = ?", (sku,)).fetchone()[0]


def count(conn, table, where="1=1", params=()):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]


def order_row(conn, order_id):
    return conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()


def confirm(ctx, order_id, reply="تمام", event_id=None):
    """Drive the real tools: request summary -> customer reply -> deterministic acceptance."""
    version = load_order(ctx.conn, order_id).version
    req = request_confirmation(ctx, order_id, version)
    assert req["ok"], req
    eid = event_id or f"EVT-{req['confirmation_request_id']}"
    assert ingest_event(ctx, order_id, eid, reply)["ok"]
    return req, record_confirmation(ctx, order_id, eid)


def insert_order(conn, order_id, phone, items, created_at="2026-10-10T11:30:00+03:00", state="PENDING"):
    """Simulate intake of a new synthetic order (bypasses tools on purpose: it is source data)."""
    conn.execute(
        "INSERT INTO orders (order_id, channel, lifecycle_state, version, customer_name, phone_raw, address_raw, "
        "governorate, city, street, building, created_at, updated_at) "
        "VALUES (?, 'whatsapp', ?, 1, 'عميل تجريبي اختبار', ?, 'القاهرة، مدينة نصر، شارع عباس العقاد، عمارة 9', "
        "'cairo', 'مدينة نصر', 'شارع عباس العقاد', '9', ?, ?)",
        (order_id, state, phone, created_at, created_at),
    )
    for n, (sku, qty) in enumerate(items, start=1):
        conn.execute("INSERT INTO order_items VALUES (?, ?, ?, ?)", (order_id, n, sku, qty))


def force_accepted_confirmation(conn, settings, order_id):
    """Test-only: simulate an order that was already validly confirmed before a race began."""
    o = load_order(conn, order_id)
    q = compute_quote(conn, settings, o).quote
    conn.execute("UPDATE orders SET lifecycle_state = 'VERIFIED' WHERE order_id = ?", (order_id,))
    conn.execute(
        "INSERT INTO confirmation_requests (confirmation_request_id, order_id, order_version, summary_hash, total_egp, "
        "status, created_at) VALUES (?, ?, ?, ?, ?, 'ACCEPTED', '2026-10-10T11:40:00+03:00')",
        (f"CR-FORCED-{order_id}", order_id, o.version, summary_hash(o, q), q.total_egp),
    )
