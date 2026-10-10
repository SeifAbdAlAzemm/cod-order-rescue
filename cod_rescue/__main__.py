"""CLI: python -m cod_rescue {init-db,seed,status} [--db PATH]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cod_rescue.config import load_settings
from cod_rescue.db import connect, init_db, schema_version
from cod_rescue.seed import seed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cod_rescue", description="COD Order Rescue (local MVP, synthetic data)")
    parser.add_argument("--db", help="SQLite path (default from config/settings.toml)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create the schema if missing")
    seed_p = sub.add_parser("seed", help="(re)load synthetic fixtures; deterministic and repeatable")
    seed_p.add_argument("--reset", action="store_true", help="delete the database file first (e.g. after a schema change)")
    sub.add_parser("status", help="show schema version, row counts and orders")
    args = parser.parse_args(argv)

    settings = load_settings()
    db_path = args.db or settings.db_path

    if args.command == "seed" and args.reset and str(db_path) != ":memory:":
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)

    conn = connect(db_path)
    try:
        if args.command == "init-db":
            created = init_db(conn)
            print(f"{'Created' if created else 'Already initialized'}: {db_path} (schema v{schema_version(conn)})")
        elif args.command == "seed":
            counts = seed(conn, settings.fixtures_dir)
            print(f"Seeded SYNTHETIC data into {db_path}")
            for table, n in counts.items():
                if n:
                    print(f"  {table:<22} {n}")
        elif args.command == "status":
            init_db(conn)
            print(f"DB: {db_path} | schema v{schema_version(conn)} | model: {settings.llm.model} | messaging: SIMULATED")
            for r in conn.execute(
                "SELECT order_id, lifecycle_state, version, agent_outcome FROM orders ORDER BY order_id"
            ):
                print(f"  {r['order_id']}  {r['lifecycle_state']:<19} v{r['version']}  outcome={r['agent_outcome'] or '-'}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
