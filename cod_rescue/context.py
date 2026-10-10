"""Execution context passed to services and tools."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from cod_rescue.config import Settings

CAIRO_TZ = timezone(timedelta(hours=3))  # simulation: fixed UTC+3

_PII_KEYS = {"customer_name", "phone", "phone_raw", "address_raw", "street", "building", "floor",
             "apartment", "landmark", "district", "body", "text"}
_PHONE_RE = re.compile(r"(?:\+?20|0)1\d[\d\s-]{7,}")


def redact(value):
    """Mask PII-bearing keys and phone-like strings before anything is logged."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k in _PII_KEYS and v is not None else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _PHONE_RE.sub("[PHONE]", value)
    return value


@dataclass
class ToolContext:
    conn: sqlite3.Connection
    settings: Settings
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(CAIRO_TZ))
    run_id: str | None = None

    def now(self) -> str:
        return self.clock().isoformat(timespec="seconds")

    @property
    def faults(self):
        return self.settings.simulation.fault_injection

    def audit(self, actor: str, event_type: str, order_id: str | None, detail: dict) -> None:
        self.conn.execute(
            "INSERT INTO audit_log (ts, run_id, order_id, actor, event_type, detail_json) VALUES (?, ?, ?, ?, ?, ?)",
            (self.now(), self.run_id, order_id, actor, event_type,
             json.dumps(redact(detail), ensure_ascii=False, sort_keys=True, default=str)),
        )
