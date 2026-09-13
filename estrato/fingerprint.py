"""Row count and content hash of every mart.

Two replays over the same extracts must print the same lines. Run it, run
the replay again, run it again: if any line differs, something in the
pipeline depends on the wall clock, on row order, or on how many times it
has been run, and the README's claim is false.
"""

import psycopg2

from estrato.config import Postgres

MARTS = ["dim_insured", "dim_policy", "dim_diagnosis", "dim_date", "fct_claim", "quarantine_claim"]


def fingerprint(pg: Postgres) -> dict[str, tuple[int, str]]:
    out = {}
    with psycopg2.connect(pg.dsn()) as con, con.cursor() as cur:
        for table in MARTS:
            # The row's text form, sorted, hashed: independent of physical
            # order and of the column list being read back in any order.
            cur.execute(
                f"select count(*), coalesce(md5(string_agg(t::text, '|' order by t::text)), '-') "
                f"from marts.{table} as t"
            )
            out[table] = cur.fetchone()
    return out


def print_fingerprint(pg: Postgres):
    for table, (rows, digest) in fingerprint(pg).items():
        print(f"{table:<18} {rows:>9} rows  {digest}")
