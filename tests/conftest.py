import dataclasses
from datetime import datetime

import pytest

from cod_rescue.config import load_settings
from cod_rescue.context import CAIRO_TZ, ToolContext
from cod_rescue.db import connect, init_db
from cod_rescue.seed import seed

FIXED_NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=CAIRO_TZ)


@pytest.fixture
def settings():
    return load_settings(env={})


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.sqlite3"


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def seeded(conn, settings):
    seed(conn, settings)
    return conn


@pytest.fixture
def ctx(seeded, settings):
    return ToolContext(seeded, settings, clock=lambda: FIXED_NOW)


def with_faults(settings, **faults):
    """Return settings with selected test-only fault switches enabled."""
    fi = dataclasses.replace(settings.simulation.fault_injection, **faults)
    return dataclasses.replace(settings, simulation=dataclasses.replace(settings.simulation, fault_injection=fi))


def make_ctx(db_path, settings):
    """A context on its own connection (for concurrency tests)."""
    return ToolContext(connect(db_path), settings, clock=lambda: FIXED_NOW)
