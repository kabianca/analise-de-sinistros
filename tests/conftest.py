"""Shared fixtures.

One synthetic source, one load and one replay per test session, in a
database of their own (`estrato_test`, dropped and recreated) so that the
suite never clobbers what `make run` built and never inherits it either.
Every integration assertion is a pure function of that replay, so sharing
it cannot leak state between tests.
"""

import os
from types import SimpleNamespace

import psycopg2
import pytest

from estrato import generate, load, replay
from estrato.config import Postgres

TEST_DB = "estrato_test"

# Small, but long enough for changes, cancellations, late claims and every
# defect to occur, and for a claim to be attributed under a version that
# has since been closed.
SEED, SCALE, START, END = 11, 300, "2016-01", "2016-12"


@pytest.fixture(scope="session")
def test_pg():
    admin = Postgres()
    con = psycopg2.connect(admin.dsn())
    con.autocommit = True
    with con.cursor() as cur:
        cur.execute(f"drop database if exists {TEST_DB}")
        cur.execute(f"create database {TEST_DB}")
    con.close()
    # dbt reads the profile from the environment on every invocation, so
    # this is how the replay is pointed at the test database.
    previous = os.environ.get("PGDATABASE")
    os.environ["PGDATABASE"] = TEST_DB
    yield Postgres(database=TEST_DB)
    if previous is None:
        del os.environ["PGDATABASE"]
    else:
        os.environ["PGDATABASE"] = previous


@pytest.fixture(scope="session")
def run(test_pg, tmp_path_factory):
    root = tmp_path_factory.mktemp("source")
    raw, truth = root / "raw", root / "truth"
    report = generate.write_source(raw, truth, seed=SEED, scale=SCALE, start=START, end=END)
    load.load_raw(raw, test_pg)
    assert replay.replay(test_pg) == 0
    return SimpleNamespace(pg=test_pg, raw=raw, truth=truth, report=report)


@pytest.fixture
def query(test_pg):
    def _query(sql: str):
        with psycopg2.connect(test_pg.dsn()) as con, con.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    return _query
