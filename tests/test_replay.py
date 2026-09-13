"""The warehouse agrees with the truth the extracts were cut from.

The generator knows every version and the exact day each one started; the
warehouse only ever saw month-end extracts. These tests hold the second to
the first, row by row, and then run the whole replay again to show that
nothing depends on how many times it has been run.
"""

import csv
import json

import pytest

from estrato import fingerprint, replay

TS = "%Y-%m-%d %H:%M:%S"


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def stamp(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime(TS) if hasattr(value, "hour") else value.isoformat()
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def test_insured_dimension_matches_truth(run, query):
    truth = {
        (
            r["num_afiliado"],
            r["valid_from"],
            r["valid_to"],
            r["sexo"],
            r["data_nascimento"],
            r["estado_civil"],
            r["ind_capital_provincia"],
            r["is_deleted"],
        )
        for r in read_csv(run.truth / "insured_versions.csv")
    }
    warehouse = {
        tuple(stamp(v) for v in row)
        for row in query(
            "select insured_id, valid_from, valid_to, sex, birth_date, marital_status, region,"
            " is_deleted from marts.dim_insured"
        )
    }
    assert warehouse == truth


def test_policy_dimension_matches_truth(run, query):
    truth = {
        (
            r["cod_apolice"],
            r["valid_from"],
            r["valid_to"],
            r["desc_producto_agrupado"],
            r["desc_tipo_contrat"],
            r["flag_programa"],
            r["fecha_ingreso"],
            r["is_deleted"],
        )
        for r in read_csv(run.truth / "policy_versions.csv")
    }
    warehouse = {
        tuple(stamp(v) for v in row)
        for row in query(
            "select policy_id, valid_from, valid_to, product, contract_type, in_programme,"
            " programme_entry_date, is_deleted from marts.dim_policy"
        )
    }
    assert warehouse == truth


def test_every_claim_is_attributed_as_the_truth_says(run, query):
    truth = {r["cod_sinistro"]: r for r in read_csv(run.truth / "claims.csv")}
    placed = {
        str(claim_id): (marital, region, product, stamp(in_programme), str(age))
        for claim_id, marital, region, product, in_programme, age in query(
            "select f.claim_id, i.marital_status, i.region, p.product, p.in_programme,"
            " f.age_at_occurrence"
            " from marts.fct_claim f"
            " join marts.dim_insured i using (insured_sk)"
            " join marts.dim_policy p using (policy_sk)"
        )
    }
    expected = {
        k: (
            r["estado_civil"] or None,
            r["ind_capital_provincia"],
            r["desc_producto_agrupado"],
            r["flag_programa"],
            r["age"],
        )
        for k, r in truth.items()
        if r["disposition"] == "fact"
    }
    assert placed == expected


def test_quarantine_reasons_match_truth(run, query):
    truth = {
        r["cod_sinistro"]: r["disposition"].removeprefix("quarantine:")
        for r in read_csv(run.truth / "claims.csv")
        if r["disposition"] != "fact"
    }
    warehouse = {
        str(k): reason for k, reason in query("select claim_id, reason from marts.quarantine_claim")
    }
    assert warehouse == truth
    assert set(truth.values()) == {
        "unknown_insured",
        "no_version_at_occurrence",
        "insured_cancelled",
    }


def test_duplicates_are_dropped_in_staging_and_counted_in_raw(run, query):
    ((raw_rows, staged),) = query(
        "select (select count(*) from raw.sinistros), (select count(*) from staging.stg_claim)"
    )
    assert raw_rows - staged == run.report["defects"]["duplicate_rows"] > 0


def test_history_changed_the_answer_for_some_claims(run, query):
    # The reason the model exists: claims whose insured looks different
    # today than on the day of the claim. Under "keep the last record"
    # every one of these would be reported with the wrong attributes.
    ((total, under_closed_version, attribute_differs),) = query(
        """
        select
            count(*),
            count(*) filter (where not i.is_current),
            count(*) filter (where (i.marital_status, i.region) is distinct from (c.marital_status, c.region))
        from marts.fct_claim f
        join marts.dim_insured i on i.insured_sk = f.insured_sk
        join marts.dim_insured c on c.insured_id = i.insured_id and c.is_current
        """
    )
    assert total > 0
    assert 0 < under_closed_version < total
    assert 0 < attribute_differs <= under_closed_version


def test_late_claims_exist_and_are_attributed_by_occurrence(run, query):
    # A claim received two months after it happened is still placed on the
    # version in force when it happened, even if a change came between.
    ((late, late_under_closed),) = query(
        """
        select
            count(*),
            count(*) filter (where f.occurrence_date < i.valid_to::date and not i.is_current)
        from marts.fct_claim f
        join marts.dim_insured i on i.insured_sk = f.insured_sk
        where date_trunc('month', f.reception_date) > date_trunc('month', f.occurrence_date)
        """
    )
    assert late > 0
    assert late_under_closed > 0


def test_rerunning_the_latest_step_changes_nothing(run):
    # The production re-run: the same extract, snapshotted again. Every key
    # is found in its current version; every claim is merged onto itself.
    before = fingerprint.fingerprint(run.pg)
    replay.step(run.pg, "2016-12-31")
    assert fingerprint.fingerprint(run.pg) == before


def test_replay_is_a_no_op_once_up_to_date(run, capsys):
    before = fingerprint.fingerprint(run.pg)
    assert replay.replay(run.pg, test=False) == 0
    assert "up to date" in capsys.readouterr().out
    assert fingerprint.fingerprint(run.pg) == before


def test_replay_refuses_to_go_backwards(run):
    # An old extract fed to a snapshot that has moved on would bring
    # cancelled keys back to life. The guard is the point; the message
    # says why.
    with pytest.raises(RuntimeError, match="resurrect"):
        replay.step(run.pg, "2016-03-31")


def test_remerging_one_month_of_the_fact_changes_nothing(run):
    before = fingerprint.fingerprint(run.pg)
    replay.invoke(["build", "--select", "fct_claim"], "2016-06-30")
    assert fingerprint.fingerprint(run.pg) == before


def test_rebuilding_from_scratch_gives_the_same_bytes(run):
    # Surrogate keys included: they are a hash of (business key, source
    # timestamp), not a sequence, so a rebuild does not renumber history.
    before = fingerprint.fingerprint(run.pg)
    assert replay.replay(run.pg, from_scratch=True, test=False) == 0
    assert fingerprint.fingerprint(run.pg) == before


def test_report_is_written(run):
    report = json.loads((run.truth / "report.json").read_text())
    assert report["extracts"] == 13
    assert report["claims_generated"] == sum(1 for _ in read_csv(run.truth / "claims.csv"))
