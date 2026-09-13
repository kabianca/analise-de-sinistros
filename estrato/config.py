"""Every knob in one place, all overridable from the environment.

Postgres is addressed through the libpq variable names (PGHOST, PGUSER, ...)
so that psql, psycopg2 and dbt's profiles.yml read the same five values and
there is no second vocabulary to keep in sync.
"""

import os
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(os.environ.get("ESTRATO_DATA_DIR", "data"))
DBT_PROJECT_DIR = Path(os.environ.get("DBT_PROJECT_DIR", "dbt"))

# The source system's extracts land here, one file per table per extract
# date; the ground truth the generator knows lands next to them so that a
# test can hold the warehouse to it.
RAW_DIR = DATA_DIR / "raw"
TRUTH_DIR = DATA_DIR / "truth"
IMG_DIR = Path("docs") / "img"

# The schema the loader owns. dbt never writes here; it only reads.
RAW_SCHEMA = "raw"

# Defaults of the synthetic source. Three calendar years of monthly extracts
# is enough history for a claim to be attributed under attributes that have
# since changed, which is the whole point.
DEFAULT_SEED = 2016
DEFAULT_SCALE = 10_000  # insured persons at the start of the history
DEFAULT_START = "2016-01"  # first extract month, inclusive
DEFAULT_END = "2018-12"  # last extract month, inclusive


@dataclass(frozen=True)
class Postgres:
    host: str = os.environ.get("PGHOST", "localhost")
    port: int = int(os.environ.get("PGPORT", "5432"))
    user: str = os.environ.get("PGUSER", "estrato")
    password: str = os.environ.get("PGPASSWORD", "estrato")
    database: str = os.environ.get("PGDATABASE", "estrato")

    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} user={self.user} "
            f"password={self.password} dbname={self.database}"
        )
