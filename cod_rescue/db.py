"""SQLite connection, initialization and transactions.

Connections run in autocommit mode; writes go through `transaction()`, which takes
SQLite's write lock up front (BEGIN IMMEDIATE) so concurrent writers serialize.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 4
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class SchemaVersionError(RuntimeError):
    pass


def connect(db_path: Path | str) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def init_db(conn: sqlite3.Connection) -> bool:
    """Create the schema if the database is empty. Returns True if it was created."""
    version = schema_version(conn)
    if version == SCHEMA_VERSION:
        return False
    if version != 0:
        raise SchemaVersionError(
            f"database schema version {version} != expected {SCHEMA_VERSION}; "
            "re-create it with `python -m cod_rescue seed --reset`"
        )
    script = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
    return True


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [r["name"] for r in rows]
