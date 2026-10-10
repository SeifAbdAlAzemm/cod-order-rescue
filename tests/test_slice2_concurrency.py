"""Slice 2: concurrent commits on separate connections (simulated parallel workers).

Single-machine SQLite only; this demonstrates the locking design, not production-scale concurrency.
"""

import threading

from tests.conftest import make_ctx
from tests.helpers import confirm, count, force_accepted_confirmation, insert_order, order_row, stock
from cod_rescue.tools import commit_ready


def _race(db_path, settings, calls):
    """Run commit_ready calls simultaneously, each on its own connection."""
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)
    errors = []

    def worker(i, order_id, version):
        c = make_ctx(db_path, settings)
        try:
            barrier.wait()
            results[i] = commit_ready(c, order_id, version)
        except Exception as e:  # surfaced to the test, never swallowed
            errors.append(e)
        finally:
            c.conn.close()

    threads = [threading.Thread(target=worker, args=(i, *call)) for i, call in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    return results


def test_last_unit_is_never_double_allocated(ctx, db_path, settings):
    insert_order(ctx.conn, "ORD-2003", "01200000099", [("TSHIRT-WHT-L", 1)])
    confirm(ctx, "ORD-1003")
    confirm(ctx, "ORD-2003")
    results = _race(db_path, settings, [("ORD-1003", 1), ("ORD-2003", 1)])
    statuses = sorted(r["status"] for r in results)
    assert statuses == ["COMMITTED", "REFUSED"]
    refused = next(r for r in results if r["status"] == "REFUSED")
    assert refused["reasons"][0] == "STOCK_CHANGED"
    assert stock(ctx.conn, "TSHIRT-WHT-L") == 0 and count(ctx.conn, "stock_reservations") == 1


def test_same_operation_retried_concurrently_commits_once(ctx, db_path, settings):
    results = _race(db_path, settings, [("ORD-1015", 2)] * 3)
    assert sorted(r["status"] for r in results) == ["ALREADY_COMMITTED", "ALREADY_COMMITTED", "COMMITTED"]
    assert stock(ctx.conn, "TSHIRT-WHT-XL") == 3 and count(ctx.conn, "stock_reservations") == 1


def test_concurrent_duplicates_are_both_held(ctx, db_path, settings):
    confirm(ctx, "ORD-1001")
    insert_order(ctx.conn, "ORD-2004", "01000000001", [("HOODIE-BLK-L", 1)])
    force_accepted_confirmation(ctx.conn, settings, "ORD-2004")  # both confirmed before the race
    results = _race(db_path, settings, [("ORD-1001", 1), ("ORD-2004", 1)])
    assert all(r["status"] == "REFUSED" and r["reasons"] == ["DUPLICATE_SUSPECTED"] for r in results)
    for oid in ("ORD-1001", "ORD-2004"):
        assert order_row(ctx.conn, oid)["lifecycle_state"] == "VERIFIED"
    assert count(ctx.conn, "duplicate_flags", "status='OPEN'") == 1
    assert stock(ctx.conn, "HOODIE-BLK-L") == 5
