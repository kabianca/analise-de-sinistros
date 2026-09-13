"""Replay the extracts through dbt, one extract date at a time.

The snapshot only ever sees one extract: the one dated `as_of`. Running it
once per extract date, in order, is what a production schedule would have
done month after month, and it is the only way a snapshot accumulates
history. The fact follows each snapshot, so a claim is attributed against
versions that were already known when it arrived.

A snapshot is a one-way street. It answers "what does the source say now",
so feeding it an extract older than the last one it saw is a lie with
consequences: a key cancelled in March is present again in January's
extract, and dbt, correctly, brings it back to life with a version that
overlaps the ones it already has. So the replay keeps a log of what it has
done, resumes from the first extract not yet seen, refuses to go backwards,
and offers `--rebuild` for the case where starting over is the intent.

What does converge, and what `python -m estrato fingerprint` is for:
re-running the latest step, rebuilding from scratch, and re-merging any
month of the fact all leave every mart byte-for-byte the same.
"""

import json
import sys
import time

import psycopg2
from dbt.cli.main import dbtRunner

from estrato.config import RAW_SCHEMA, Postgres

LOG_DDL = """
create schema if not exists meta;
create table if not exists meta.replay_log (
    as_of date primary key,
    replayed_at timestamp not null default now()
);
"""

# Everything dbt writes. Dropping these and replaying is a rebuild; the
# raw schema is the loader's and stays.
DBT_SCHEMAS = ["staging", "snapshots", "marts"]


def extract_dates(pg: Postgres) -> list[str]:
    with psycopg2.connect(pg.dsn()) as con, con.cursor() as cur:
        cur.execute(f"select distinct extract_date from {RAW_SCHEMA}.segurados_extract order by 1")
        return [d.isoformat() for (d,) in cur.fetchall()]


def last_replayed(pg: Postgres) -> str | None:
    with psycopg2.connect(pg.dsn()) as con, con.cursor() as cur:
        cur.execute(LOG_DDL)
        cur.execute("select max(as_of) from meta.replay_log")
        (latest,) = cur.fetchone()
        return latest.isoformat() if latest else None


def invoke(args: list[str], as_of: str | None = None):
    if as_of:
        args = [*args, "--vars", json.dumps({"as_of": as_of})]
    # dbt is chatty; the summary line per step below is what a person needs.
    result = dbtRunner().invoke([*args, "--quiet"])
    if not result.success:
        raise RuntimeError(f"dbt {' '.join(args)} failed: {result.exception}")
    return result


def step(pg: Postgres, as_of: str):
    """Snapshot the extract dated `as_of`, then build the marts up to it."""
    latest = last_replayed(pg)
    if latest and as_of < latest:
        raise RuntimeError(
            f"the snapshot has already seen {latest}; replaying {as_of} would resurrect "
            "keys that were deleted in between. Use --rebuild to start over."
        )
    started = time.monotonic()
    # One invocation per step: `build` orders the staging views, the
    # snapshots and the marts by dependency, so the snapshot of this
    # extract is complete before the fact reads it. Tests wait for the
    # end; they describe the finished history, not every step of it.
    invoke(["build", "--exclude", "resource_type:test", "resource_type:seed"], as_of)
    with psycopg2.connect(pg.dsn()) as con, con.cursor() as cur:
        cur.execute(
            "insert into meta.replay_log (as_of) values (%s) "
            "on conflict (as_of) do update set replayed_at = now()",
            (as_of,),
        )
    print(f"as of {as_of}: built in {time.monotonic() - started:4.1f}s")


def rebuild(pg: Postgres):
    with psycopg2.connect(pg.dsn()) as con, con.cursor() as cur:
        for schema in DBT_SCHEMAS:
            cur.execute(f"drop schema if exists {schema} cascade")
        cur.execute(LOG_DDL)
        cur.execute("truncate meta.replay_log")


def replay(pg: Postgres, from_scratch: bool = False, test: bool = True) -> int:
    """Replay every extract not yet seen, in order; then run the dbt tests."""
    if from_scratch:
        rebuild(pg)
    dates = extract_dates(pg)
    if not dates:
        print("nothing to replay: raw is empty (run `load` first)", file=sys.stderr)
        return 1

    latest = last_replayed(pg)
    pending = [d for d in dates if latest is None or d > latest]
    if not pending:
        print(f"up to date: the snapshot has seen every extract through {latest}")
    else:
        started = time.monotonic()
        invoke(["seed"])
        for as_of in pending:
            step(pg, as_of)
        print(f"replayed {len(pending)} extracts in {time.monotonic() - started:.0f}s")

    if test:
        # Left unset, `as_of` means the latest extract, which is the state
        # every assertion should hold on once the replay is complete.
        invoke(["test"])
        print("dbt test: passed")
    return 0
