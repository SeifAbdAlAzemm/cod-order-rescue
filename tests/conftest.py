import pytest

from cod_rescue.config import load_settings
from cod_rescue.db import connect, init_db
from cod_rescue.seed import seed


@pytest.fixture
def settings():
    return load_settings(env={})


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite3")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def seeded(conn, settings):
    seed(conn, settings.fixtures_dir)
    return conn
