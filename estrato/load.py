"""COPY the extracts into the raw schema, every column as text.

Raw is the warehouse's copy of what the source sent: one row per row
received, nothing dropped, nothing typed, nothing deduplicated. Every
extract is kept, tagged with its extract date and file name, so the
snapshots can be replayed in order from the database alone, and so an
argument about "what did the source say on 2017-03-31" has somewhere to go.

Typing happens in staging, where a bad value fails a model with a message,
not a COPY with a line number. A load is a full reload of raw from data/,
which is what makes it repeatable; everything dbt built from the previous
raw is dropped with it, because a snapshot of extracts that no longer exist
is not history, it is a leftover.
"""

import re
from pathlib import Path

import psycopg2

from estrato import replay
from estrato.catalog import CLAIM_COLUMNS, INSURED_COLUMNS, POLICY_COLUMNS
from estrato.config import RAW_SCHEMA, Postgres

# (file prefix, raw table, columns)
EXTRACTS = [
    ("segurados", "segurados_extract", INSURED_COLUMNS),
    ("apolices", "apolices_extract", POLICY_COLUMNS),
]

DDL = f"""
create schema if not exists {RAW_SCHEMA};

drop table if exists {RAW_SCHEMA}.segurados_extract;
create table {RAW_SCHEMA}.segurados_extract (
    extract_date date not null,
    {", ".join(f"{c} text" for c in INSURED_COLUMNS)},
    source_file text not null,
    loaded_at timestamp not null default now()
);

drop table if exists {RAW_SCHEMA}.apolices_extract;
create table {RAW_SCHEMA}.apolices_extract (
    extract_date date not null,
    {", ".join(f"{c} text" for c in POLICY_COLUMNS)},
    source_file text not null,
    loaded_at timestamp not null default now()
);

-- row_no is the order the rows arrived in, across files. When the source
-- sends the same claim twice, staging keeps the first and this is how it
-- knows which one that was.
drop table if exists {RAW_SCHEMA}.sinistros;
create table {RAW_SCHEMA}.sinistros (
    row_no bigint generated always as identity,
    {", ".join(f"{c} text" for c in CLAIM_COLUMNS)},
    source_file text not null,
    loaded_at timestamp not null default now()
);
"""


def copy_file(cur, path: Path, table: str, columns: list[str], extra: dict[str, str]):
    """COPY one CSV into `table`, stamping the constant `extra` columns.

    COPY cannot add columns, so the file goes through a temporary table
    shaped like the file and one INSERT ... SELECT adds the stamps.
    """
    cur.execute(
        f"create temp table incoming ({', '.join(f'{c} text' for c in columns)}) on commit drop"
    )
    with path.open() as f:
        cur.copy_expert(
            f"copy incoming ({', '.join(columns)}) from stdin with (format csv, header true)", f
        )
    stamps = ", ".join(f"%({k})s" for k in extra)
    cur.execute(
        f"insert into {RAW_SCHEMA}.{table} ({', '.join(extra)}, {', '.join(columns)}) "
        f"select {stamps}, {', '.join(columns)} from incoming",
        extra,
    )
    rows = cur.rowcount
    cur.execute("drop table incoming")
    return rows


def load_raw(raw_dir: Path, pg: Postgres) -> dict[str, int]:
    """Reload raw from every file in `raw_dir`. Returns rows loaded per table."""
    loaded = {"segurados_extract": 0, "apolices_extract": 0, "sinistros": 0}
    replay.rebuild(pg)
    with psycopg2.connect(pg.dsn()) as con, con.cursor() as cur:
        cur.execute(DDL)
        for prefix, table, columns in EXTRACTS:
            for path in sorted(raw_dir.glob(f"{prefix}_*.csv")):
                stamp = re.fullmatch(rf"{prefix}_(\d{{4}}-\d{{2}}-\d{{2}})", path.stem).group(1)
                n = copy_file(
                    cur, path, table, columns, {"extract_date": stamp, "source_file": path.name}
                )
                loaded[table] += n
                print(f"raw.{table:<18} {path.name:<28} {n:>8} rows")
        for path in sorted(raw_dir.glob("sinistros_*.csv")):
            n = copy_file(cur, path, "sinistros", CLAIM_COLUMNS, {"source_file": path.name})
            loaded["sinistros"] += n
            print(f"raw.{'sinistros':<18} {path.name:<28} {n:>8} rows")
    return loaded
