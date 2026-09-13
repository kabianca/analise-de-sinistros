"""The dbt / Postgres pair actually works together.

Version pins are only a claim until dbt parses the project and opens a
connection. This is the test that fails first if the adapter and core drift
apart, or if the compose file points at a Postgres the adapter does not
speak to.
"""

import psycopg2
from dbt.cli.main import dbtRunner

from estrato.config import Postgres


def test_postgres_is_16():
    with psycopg2.connect(Postgres().dsn()) as con, con.cursor() as cur:
        cur.execute("show server_version")
        (version,) = cur.fetchone()
    assert version.startswith("16."), version


def test_dbt_connects_and_parses():
    # `dbt debug` without flags also wants git on the PATH, which the image
    # deliberately lacks: no package is fetched from a repository.
    connection = dbtRunner().invoke(["debug", "--connection"])
    assert connection.success, connection.exception

    parsed = dbtRunner().invoke(["parse"])
    assert parsed.success, parsed.exception
