"""CLI: python -m cod_rescue {init-db,seed,status} [--db PATH]"""

from __future__ import annotations

import argparse
import sys

from cod_rescue.config import load_settings
from cod_rescue.db import SchemaVersionError, connect, init_db, schema_version
from cod_rescue.seed import SeedError, seed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cod_rescue", description="COD Order Rescue (local MVP, synthetic data)")
    parser.add_argument("--db", help="SQLite path (default from config/settings.toml)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create the schema if missing")
    seed_p = sub.add_parser("seed", help="load synthetic fixtures into an empty database")
    seed_p.add_argument("--reset", action="store_true",
                        help="replace an existing SYNTHETIC demo database (refused for any other database)")
    sub.add_parser("status", help="show schema version and orders")
    args = parser.parse_args(argv)

    settings = load_settings()
    db_path = args.db or settings.db_path

    conn = connect(db_path)
    try:
        if args.command == "init-db":
            created = init_db(conn)
            print(f"{'Created' if created else 'Already initialized'}: {db_path} (schema v{schema_version(conn)})")
        elif args.command == "seed":
            counts = seed(conn, settings, replace_existing=args.reset)
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
    except (SeedError, SchemaVersionError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
