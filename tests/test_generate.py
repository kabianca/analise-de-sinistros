"""The synthetic source has the shape the model needs, and says so.

These run without Postgres: they hold the generator to its own promises
(same seed, same bytes; every version observable; every defect present),
so that when an integration test fails, the source is not the suspect.
"""

import csv
import hashlib
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from estrato import catalog, generate

SEED_CSV = Path(__file__).parent.parent / "dbt" / "seeds" / "cid10.csv"


def read(path: Path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def digest(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.rglob("*.csv"))
    }


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    root = tmp_path_factory.mktemp("source")
    report = generate.write_source(
        root / "raw", root / "truth", seed=7, scale=400, start="2016-01", end="2017-06"
    )
    return root, report


def test_same_seed_same_bytes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate.write_source(a / "raw", a / "truth", seed=3, scale=50, start="2016-01", end="2016-04")
    generate.write_source(b / "raw", b / "truth", seed=3, scale=50, start="2016-01", end="2016-04")
    assert digest(a) == digest(b)


def test_different_seed_different_bytes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate.write_source(a / "raw", a / "truth", seed=3, scale=50, start="2016-01", end="2016-04")
    generate.write_source(b / "raw", b / "truth", seed=4, scale=50, start="2016-01", end="2016-04")
    assert digest(a) != digest(b)


def test_history_exists(source):
    root, _ = source
    versions = Counter(r["num_afiliado"] for r in read(root / "truth" / "insured_versions.csv"))
    assert max(versions.values()) >= 2
    assert sum(1 for n in versions.values() if n >= 2) > 10


def test_at_most_one_change_per_key_per_month(source):
    # The extract cadence is monthly; a second change inside a month would
    # be a version the warehouse could never see, and the truth would be
    # unfair to hold it to.
    root, _ = source
    seen = Counter()
    for r in read(root / "truth" / "insured_versions.csv"):
        if r["is_deleted"] == "0" and r["valid_from"] >= "2016-01-01":
            seen[(r["num_afiliado"], r["valid_from"][:7])] += 1
    assert seen and max(seen.values()) == 1
    seen = Counter()
    for r in read(root / "truth" / "policy_versions.csv"):
        if r["is_deleted"] == "0" and r["valid_from"] >= "2016-01-01":
            seen[(r["cod_apolice"], r["valid_from"][:7])] += 1
    assert seen and max(seen.values()) == 1


def test_every_version_is_observed_by_exactly_the_extracts(source):
    # Each (key, updated_at) pair in the extracts is one truth version, and
    # every non-deleted truth version shows up in at least one extract. This
    # is the contract that lets a test compare the snapshot to the truth.
    root, _ = source
    truth = {
        (r["num_afiliado"], r["valid_from"])
        for r in read(root / "truth" / "insured_versions.csv")
        if r["is_deleted"] == "0"
    }
    observed = set()
    for extract in sorted((root / "raw").glob("segurados_*.csv")):
        observed |= {(r["num_afiliado"], r["updated_at"]) for r in read(extract)}
    assert observed == truth


def test_cancelled_keys_disappear_and_are_marked_deleted(source):
    root, report = source
    assert report["insured_cancelled"] > 0
    deleted = {
        r["num_afiliado"]
        for r in read(root / "truth" / "insured_versions.csv")
        if r["is_deleted"] == "1"
    }
    assert len(deleted) == report["insured_cancelled"]
    last = read(max((root / "raw").glob("segurados_*.csv")))
    assert deleted.isdisjoint(r["num_afiliado"] for r in last)


def test_extract_exposes_no_derived_age(source):
    # Age is a function of the claim date and the birth date. Storing it on
    # the insured, as the legacy CSV did, is the first step towards reporting
    # a 2016 claim at a 2018 age.
    root, _ = source
    header = next(iter(read(min((root / "raw").glob("segurados_*.csv")))))
    assert "edad" not in header and "age" not in header
    assert "data_nascimento" in header


def test_claims_carry_every_defect_the_report_counts(source):
    root, report = source
    rows = []
    for f in sorted((root / "raw").glob("sinistros_*.csv")):
        rows += read(f)
    ids = Counter(r["cod_sinistro"] for r in rows)

    assert report["defects"]["duplicate_rows"] > 0
    assert sum(n - 1 for n in ids.values()) == report["defects"]["duplicate_rows"]

    unknown = {
        r["num_afiliado"] for r in rows if int(r["num_afiliado"]) >= generate.UNKNOWN_INSURED_BASE
    }
    assert len(unknown) == report["defects"]["unknown_insured"] > 0

    late = sum(1 for r in rows if r["fec_recepcao"][:7] != r["fec_ocurrencia"][:7])
    assert late > 0
    assert all(r["fec_recepcao"] >= r["fec_ocurrencia"] for r in rows)

    truth = read(root / "truth" / "claims.csv")
    assert set(ids) == {r["cod_sinistro"] for r in truth}
    dispositions = Counter(r["disposition"] for r in truth)
    assert dispositions["quarantine:unknown_insured"] == report["defects"]["unknown_insured"]
    assert (
        dispositions["quarantine:no_version_at_occurrence"]
        == report["defects"]["claim_before_creation"]
    )
    assert (
        dispositions["quarantine:insured_cancelled"]
        == report["defects"]["claim_after_cancellation"]
    )
    assert dispositions["fact"] > 0.95 * len(truth)


def test_programme_claims_follow_enrolment_at_the_time(source):
    # A chronic diagnosis is a programme claim only while the policy was
    # enrolled on the day it happened, not whenever it was enrolled at all.
    root, _ = source
    truth = {r["cod_sinistro"]: r for r in read(root / "truth" / "claims.csv")}
    rows = []
    for f in sorted((root / "raw").glob("sinistros_*.csv")):
        rows += read(f)
    programme = [r for r in rows if r["agrupbenef"] == catalog.BENEFIT_PROGRAMME]
    assert programme
    assert all(truth[r["cod_sinistro"]]["flag_programa"] == "1" for r in programme)


def test_seed_matches_catalog():
    seed = {(r["diagnosis_code"], r["chronic_group"] or None) for r in read(SEED_CSV)}
    assert seed == {(code, group) for code, _, _, group in catalog.CID10}


def test_one_file_per_reception_month(source):
    root, _ = source
    by_file = defaultdict(set)
    for f in sorted((root / "raw").glob("sinistros_*.csv")):
        by_file[f.stem[-7:]] = {r["fec_recepcao"][:7] for r in read(f)}
    assert all(months == {name} for name, months in by_file.items())
