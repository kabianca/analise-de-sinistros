"""A source system that changes over time, and the truth about how.

Public claims datasets almost never carry what a Type 2 dimension needs:
attributes that change on known dates. So this module plays the source
system. It simulates insured persons, their policies and their claims month
by month, and writes two things:

* the extracts a warehouse would actually receive: a full picture of the
  insured and policy tables at the end of every month, plus one file of
  claims per month of *reception*, with the defects real feeds have
  (late claims, rows sent twice, references to people who do not exist);

* the truth the extracts were cut from: every version of every insured and
  policy with the exact instant it started, and for every claim which
  version was in force when it happened. The warehouse never reads this.
  The test suite does, to hold the dimensions to it.

Everything is drawn from one seeded generator in a fixed order, so the same
seed writes the same bytes.

Cadence matters. An extract at the end of a month sees at most one state per
key, so a key that changed twice inside a month would lose a version between
the truth and the warehouse. The simulation changes each key at most once
per month by construction, and the README says so: this is the known blind
spot of snapshot-based history, and the honest fix is change data capture,
not a cleverer snapshot.
"""

import calendar
import csv
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from estrato import catalog

# --- Rates, all per month unless stated. Chosen to look like the legacy CSV
# (a quarter of the book chronic, programme members claiming 7-10 times a
# year, 5 % of marital status missing) while leaving enough changes for the
# history to matter.
JOIN_RATE = 0.004  # of the initial population
CANCEL_RATE = 0.003  # of the active population
MARITAL_CHANGE_RATE = 0.004
REGION_CHANGE_RATE = 0.002
PRODUCT_CHANGE_RATE = 0.0015
ENROL_RATE = 0.03  # of chronic insureds not yet in the programme
LEAVE_RATE = 0.003  # of programme members
CHRONIC_SHARE = 0.25
CHRONIC_HTA_SHARE = 0.65  # the rest is diabetes
ENROLLED_AT_START = 0.40  # the programme opened at the end of 2015
PAY_PER_SERVICE_SHARE = 0.02

CLAIMS_PER_YEAR = {"regular": 1.8, "chronic": 4.5, "programme": 8.5}
CHRONIC_DIAGNOSIS_SHARE = 0.70  # of a chronic insured's claims
COVERAGE = {"EPS": 0.85, "AMC": 0.75, "AMI": 0.65}
MEAN_COST = {"PROGRAMA": 300.0, "AMBULATORIO": 120.0, "FARMACIA": 60.0, "HOSPITALARIO": 2500.0}
COST_SIGMA = {"PROGRAMA": 0.6, "AMBULATORIO": 0.6, "FARMACIA": 0.5, "HOSPITALARIO": 0.9}

# Deliberate defects, as a share of claim rows.
DUPLICATE_ROW_RATE = 0.005
UNKNOWN_INSURED_RATE = 0.002
# ...and as a share of the insureds each event touches.
CLAIM_BEFORE_CREATION_SHARE = 0.10  # of new joiners: a claim dated before they existed
CLAIM_AFTER_CANCELLATION_SHARE = 0.20  # of cancelled: a claim dated the month after

FIRST_INSURED_ID = 10_000
FIRST_POLICY_ID = 500_000
UNKNOWN_INSURED_BASE = 9_000_000

TS = "%Y-%m-%d %H:%M:%S"


@dataclass
class Version:
    valid_from: datetime
    attrs: dict


@dataclass
class Policy:
    cod_apolice: int
    versions: list[Version] = field(default_factory=list)

    @property
    def current(self):
        return self.versions[-1].attrs


@dataclass
class Insured:
    num_afiliado: int
    sexo: str
    data_nascimento: date
    chronic: str | None  # HTA, DM or None; a latent trait, never exported
    created_at: datetime
    policy: Policy
    versions: list[Version] = field(default_factory=list)
    cancelled_at: datetime | None = None
    changed_this_month: bool = False

    @property
    def current(self):
        return self.versions[-1].attrs

    @property
    def active(self):
        return self.cancelled_at is None


@dataclass
class Claim:
    cod_sinistro: int
    num_afiliado: int
    cod_apolice: int
    fec_ocurrencia: date
    fec_recepcao: date
    cod_diagnostico: str
    agrupbenef: str
    gasto_presentado: float
    beneficio_pagado: float
    # Truth, never written to the extracts.
    disposition: str
    at_occurrence: dict


# --- Calendar helpers -------------------------------------------------------


def month_range(start: str, end: str):
    y, m = (int(p) for p in start.split("-"))
    ye, me = (int(p) for p in end.split("-"))
    while (y, m) <= (ye, me):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def next_month_start(y: int, m: int) -> datetime:
    return datetime.combine(month_end(y, m) + timedelta(days=1), datetime.min.time())


def random_day(rng, y: int, m: int, not_before: date | None = None) -> date:
    first = date(y, m, 1)
    last = month_end(y, m)
    lo = max(first, not_before) if not_before else first
    return lo + timedelta(days=int(rng.integers(0, (last - lo).days + 1)))


def random_instant(rng, day: date) -> datetime:
    # Office hours, as a source system would stamp them. The time of day
    # never decides anything: see version_at.
    return datetime.combine(day, datetime.min.time()) + timedelta(
        hours=8 + int(rng.integers(0, 10)),
        minutes=int(rng.integers(0, 60)),
        seconds=int(rng.integers(0, 60)),
    )


def version_at(versions: list[Version], day: date) -> Version | None:
    """The version in force on `day`.

    Claims carry a date, not an instant, so the day is the finest grain an
    attribution can honestly have: a change stamped anywhere on day d counts
    for the whole of day d. The warehouse applies the same rule
    (valid_from::date <= day < valid_to::date), and a claim on the day an
    insured joined belongs to that first version, not to quarantine.
    """
    hit = None
    for v in versions:
        if v.valid_from.date() <= day:
            hit = v
        else:
            break
    return hit


# --- Simulation -------------------------------------------------------------


class Simulation:
    def __init__(self, seed: int, scale: int, start: str, end: str):
        self.rng = np.random.default_rng(seed)
        self.scale = scale
        self.months = list(month_range(start, end))
        self.start = date(self.months[0][0], self.months[0][1], 1)
        self.insureds: list[Insured] = []
        self.claims: list[Claim] = []
        self.next_insured_id = FIRST_INSURED_ID
        self.next_policy_id = FIRST_POLICY_ID
        self.next_claim_id = 1
        self.next_unknown_id = UNKNOWN_INSURED_BASE
        self.report = {
            "seed": seed,
            "scale": scale,
            "start": start,
            "end": end,
            "insured_joined": 0,
            "insured_cancelled": 0,
            "changes": {
                "estado_civil": 0,
                "ind_capital_provincia": 0,
                "product": 0,
                "enrol": 0,
                "leave": 0,
            },
            "claims_generated": 0,
            "claims_late": 0,
            "claims_received_after_horizon": 0,
            "defects": {
                "duplicate_rows": 0,
                "unknown_insured": 0,
                "claim_before_creation": 0,
                "claim_after_cancellation": 0,
            },
        }

    # -- population

    def _new_insured(self, created_at: datetime, age_mean: float, age_sd: float) -> Insured:
        rng = self.rng
        age = float(np.clip(rng.normal(age_mean, age_sd), 18, 95))
        born = created_at.date() - timedelta(days=int(age * 365.25) + int(rng.integers(0, 365)))
        chronic = None
        if rng.random() < CHRONIC_SHARE:
            chronic = "HTA" if rng.random() < CHRONIC_HTA_SHARE else "DM"
        product = catalog.PRODUCTS[rng.choice(3, p=[0.78, 0.15, 0.07])]
        contract = (
            catalog.CONTRACT_PAY_PER_SERVICE
            if rng.random() < PAY_PER_SERVICE_SHARE
            else catalog.CONTRACT_REGULAR
        )
        policy = Policy(self.next_policy_id)
        self.next_policy_id += 1
        policy.versions.append(
            Version(
                created_at,
                {
                    "desc_producto_agrupado": product,
                    "desc_tipo_contrat": contract,
                    "flag_programa": 0,
                    "fecha_ingreso": None,
                },
            )
        )
        insured = Insured(
            num_afiliado=self.next_insured_id,
            sexo=catalog.SEXES[rng.choice(2, p=[0.55, 0.45])],
            data_nascimento=born,
            chronic=chronic,
            created_at=created_at,
            policy=policy,
        )
        self.next_insured_id += 1
        insured.versions.append(
            Version(
                created_at,
                {
                    "estado_civil": catalog.MARITAL[
                        rng.choice(6, p=[0.57, 0.20, 0.08, 0.07, 0.03, 0.05])
                    ],
                    "ind_capital_provincia": catalog.REGIONS[rng.choice(3, p=[0.86, 0.13, 0.01])],
                },
            )
        )
        return insured

    def _enrol(self, insured: Insured, when: datetime):
        variants = catalog.CONTRACT_PROGRAMME[insured.chronic]
        contract = variants[int(self.rng.random() < 0.45)]
        insured.policy.versions.append(
            Version(
                when,
                {
                    **insured.policy.current,
                    "desc_tipo_contrat": contract,
                    "flag_programa": 1,
                    "fecha_ingreso": when.date(),
                },
            )
        )

    def initial_population(self):
        rng = self.rng
        start = datetime.combine(self.start, datetime.min.time())
        for _ in range(self.scale):
            created = start - timedelta(days=int(rng.integers(1, 8 * 365)))
            created = random_instant(rng, created.date())
            insured = self._new_insured(created, age_mean=63, age_sd=14)
            # The programme opened at the end of 2015; some chronic insureds
            # are already in when the history starts. Their enrolment is
            # part of the same initial version: it predates the warehouse.
            if insured.chronic and rng.random() < ENROLLED_AT_START:
                variants = catalog.CONTRACT_PROGRAMME[insured.chronic]
                v = insured.policy.versions[0]
                v.attrs["desc_tipo_contrat"] = variants[int(rng.random() < 0.45)]
                v.attrs["flag_programa"] = 1
                v.attrs["fecha_ingreso"] = self.start - timedelta(days=int(rng.integers(1, 60)))
            self.insureds.append(insured)

    # -- one month

    def _sample(self, candidates: list[Insured], rate: float) -> list[Insured]:
        if not candidates:
            return []
        n = int(self.rng.binomial(len(candidates), rate))
        if n == 0:
            return []
        idx = self.rng.choice(len(candidates), size=n, replace=False)
        return [candidates[i] for i in sorted(idx)]

    def simulate_month(self, y: int, m: int):
        rng = self.rng
        for ins in self.insureds:
            ins.changed_this_month = False

        # Joiners. They get no change this month, so that their first
        # version is the one the month-end extract sees.
        joined = []
        for _ in range(int(rng.poisson(JOIN_RATE * self.scale))):
            created = random_instant(rng, random_day(rng, y, m))
            ins = self._new_insured(created, age_mean=45, age_sd=15)
            ins.changed_this_month = True
            joined.append(ins)
        self.insureds.extend(joined)
        self.report["insured_joined"] += len(joined)

        active = [i for i in self.insureds if i.active and not i.changed_this_month]

        # Cancellations: the row simply stops appearing. Also excluded from
        # changes this month: a change nobody will ever extract is not a
        # version the warehouse can be held to.
        for ins in self._sample(active, CANCEL_RATE):
            ins.cancelled_at = random_instant(
                rng, random_day(rng, y, m, not_before=ins.created_at.date())
            )
            ins.changed_this_month = True
        active = [i for i in active if i.active]
        self.report["insured_cancelled"] += sum(
            1
            for i in self.insureds
            if i.cancelled_at and i.cancelled_at.year == y and i.cancelled_at.month == m
        )

        # Insured-level changes: one attribute per key per month.
        for ins in self._sample(active, MARITAL_CHANGE_RATE):
            self._change_insured(ins, y, m, "estado_civil")
        for ins in self._sample(
            [i for i in active if not i.changed_this_month], REGION_CHANGE_RATE
        ):
            self._change_insured(ins, y, m, "ind_capital_provincia")

        # Policy-level changes, independent of the insured-level ones (a
        # different table, a different snapshot), but again one per month.
        policy_touched = set()
        for ins in self._sample(active, PRODUCT_CHANGE_RATE):
            self._change_product(ins, y, m)
            policy_touched.add(ins.num_afiliado)
        eligible = [
            i
            for i in active
            if i.chronic
            and not i.policy.current["flag_programa"]
            and i.num_afiliado not in policy_touched
        ]
        for ins in self._sample(eligible, ENROL_RATE):
            self._enrol(ins, random_instant(rng, random_day(rng, y, m)))
            policy_touched.add(ins.num_afiliado)
            self.report["changes"]["enrol"] += 1
        members = [
            i
            for i in active
            if i.policy.current["flag_programa"] and i.num_afiliado not in policy_touched
        ]
        for ins in self._sample(members, LEAVE_RATE):
            ins.policy.versions.append(
                Version(
                    random_instant(rng, random_day(rng, y, m)),
                    {
                        **ins.policy.current,
                        "desc_tipo_contrat": catalog.CONTRACT_REGULAR,
                        "flag_programa": 0,
                        "fecha_ingreso": None,
                    },
                )
            )
            self.report["changes"]["leave"] += 1

        self._claims_for_month(y, m, joined)

    def _change_insured(self, ins: Insured, y: int, m: int, attr: str):
        rng = self.rng
        current = ins.current[attr]
        if attr == "estado_civil":
            # Missing values get filled in; everyone else moves to another state.
            options = [v for v in catalog.MARITAL if v is not None and v != current]
        else:
            options = [v for v in catalog.REGIONS if v != current]
        new = options[int(rng.integers(0, len(options)))]
        ins.versions.append(
            Version(random_instant(rng, random_day(rng, y, m)), {**ins.current, attr: new})
        )
        ins.changed_this_month = True
        self.report["changes"][attr] += 1

    def _change_product(self, ins: Insured, y: int, m: int):
        rng = self.rng
        current = ins.policy.current["desc_producto_agrupado"]
        options = [p for p in catalog.PRODUCTS if p != current]
        new = options[int(rng.integers(0, len(options)))]
        ins.policy.versions.append(
            Version(
                random_instant(rng, random_day(rng, y, m)),
                {**ins.policy.current, "desc_producto_agrupado": new},
            )
        )
        self.report["changes"]["product"] += 1

    # -- claims

    def _claims_for_month(self, y: int, m: int, joined: list[Insured]):
        rng = self.rng
        month_start = date(y, m, 1)
        end = month_end(y, m)
        horizon = month_end(*self.months[-1])

        # One Poisson draw per insured, vectorised; the rate depends on the
        # programme status at the start of the month, which is close enough
        # for a rate and keeps the draw independent of the day of each claim.
        population = [
            i
            for i in self.insureds
            if i.cancelled_at is None or i.cancelled_at.date() >= month_start
        ]
        rates = np.array(
            [
                CLAIMS_PER_YEAR[
                    "programme"
                    if i.policy.current["flag_programa"]
                    else "chronic"
                    if i.chronic
                    else "regular"
                ]
                / 12.0
                for i in population
            ]
        )
        counts = rng.poisson(rates)

        for ins, n in zip(population, counts):
            for _ in range(int(n)):
                occurred = random_day(rng, y, m, not_before=ins.created_at.date())
                if ins.cancelled_at and occurred > ins.cancelled_at.date():
                    occurred = ins.cancelled_at.date()
                self._emit_claim(ins, occurred, horizon)

        # Defect: a claim dated before the insured existed (retroactive
        # billing on a fresh record). Nothing in the warehouse can attribute
        # it; it must land in quarantine, not vanish and not be forced onto
        # the first version.
        for ins in joined:
            if rng.random() < CLAIM_BEFORE_CREATION_SHARE and ins.created_at.date() > month_start:
                occurred = month_start + timedelta(
                    days=int(rng.integers(0, (ins.created_at.date() - month_start).days))
                )
                received = ins.created_at.date() + timedelta(days=int(rng.integers(0, 10)))
                if self._emit_claim(ins, occurred, horizon, received=received):
                    self.report["defects"]["claim_before_creation"] += 1

        # Defect: a claim dated after the insured left, in the following
        # month. The extract that month no longer lists them.
        cancelled_now = [
            i
            for i in self.insureds
            if i.cancelled_at and (i.cancelled_at.year, i.cancelled_at.month) == (y, m)
        ]
        for ins in cancelled_now:
            if rng.random() < CLAIM_AFTER_CANCELLATION_SHARE and end < horizon:
                ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
                occurred = random_day(rng, ny, nm)
                if self._emit_claim(ins, occurred, horizon):
                    self.report["defects"]["claim_after_cancellation"] += 1

    def _emit_claim(
        self, ins: Insured, occurred: date, horizon: date, received: date | None = None
    ) -> bool:
        """Append one claim; False if it would only arrive after the horizon."""
        rng = self.rng
        if received is None:
            bucket = rng.choice(4, p=[0.55, 0.30, 0.12, 0.03])
            delay = [
                0,
                int(rng.integers(1, 16)),
                int(rng.integers(16, 46)),
                int(rng.integers(46, 76)),
            ][bucket]
            received = occurred + timedelta(days=delay)
        if received > horizon:
            self.report["claims_received_after_horizon"] += 1
            return False
        if received.month != occurred.month or received.year != occurred.year:
            self.report["claims_late"] += 1

        insured_v = version_at(ins.versions, occurred)
        policy_v = version_at(ins.policy.versions, occurred)

        # Diagnosis and benefit group follow the truth at the time: a chronic
        # diagnosis is a programme claim only while the policy is enrolled.
        if ins.chronic and rng.random() < CHRONIC_DIAGNOSIS_SHARE:
            codes = catalog.CHRONIC_CODES[ins.chronic]
            diagnosis = codes[int(rng.integers(0, len(codes)))]
        else:
            diagnosis = catalog.GENERAL_CODES[int(rng.integers(0, len(catalog.GENERAL_CODES)))]
        enrolled = bool(policy_v and policy_v.attrs["flag_programa"])
        if diagnosis in catalog.CHRONIC_CODES.get(ins.chronic or "", []) and enrolled:
            benefit, cost_key = catalog.BENEFIT_PROGRAMME, "PROGRAMA"
        else:
            benefit = catalog.BENEFIT_GENERAL[rng.choice(3, p=[0.60, 0.10, 0.30])]
            cost_key = benefit
        mean, sigma = MEAN_COST[cost_key], COST_SIGMA[cost_key]
        submitted = round(float(rng.lognormal(math.log(mean) - sigma**2 / 2, sigma)), 2)
        product = (policy_v or ins.policy.versions[0]).attrs["desc_producto_agrupado"]
        coverage = min(1.0, max(0.0, COVERAGE[product] + float(rng.normal(0, 0.05))))
        paid = round(min(submitted, submitted * coverage), 2)

        # Disposition, as the warehouse must decide it from the extracts.
        deleted_from = (
            next_month_start(ins.cancelled_at.year, ins.cancelled_at.month)
            if ins.cancelled_at
            else None
        )
        if insured_v is None:
            disposition = "quarantine:no_version_at_occurrence"
        elif deleted_from and occurred >= deleted_from.date():
            disposition = "quarantine:insured_cancelled"
        else:
            disposition = "fact"
        at_occurrence = {
            "estado_civil": insured_v.attrs["estado_civil"] if insured_v else None,
            "ind_capital_provincia": insured_v.attrs["ind_capital_provincia"]
            if insured_v
            else None,
            "desc_producto_agrupado": policy_v.attrs["desc_producto_agrupado"]
            if policy_v
            else None,
            "flag_programa": policy_v.attrs["flag_programa"] if policy_v else None,
            "age": age_on(ins.data_nascimento, occurred),
        }

        self.claims.append(
            Claim(
                cod_sinistro=self.next_claim_id,
                num_afiliado=ins.num_afiliado,
                cod_apolice=ins.policy.cod_apolice,
                fec_ocurrencia=occurred,
                fec_recepcao=received,
                cod_diagnostico=diagnosis,
                agrupbenef=benefit,
                gasto_presentado=submitted,
                beneficio_pagado=paid,
                disposition=disposition,
                at_occurrence=at_occurrence,
            )
        )
        self.next_claim_id += 1
        self.report["claims_generated"] += 1
        return True


def age_on(born: date, day: date) -> int:
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


# --- Writers ----------------------------------------------------------------


def fmt(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime(TS)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def write_csv(path: Path, header: list[str], rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        for row in rows:
            w.writerow([fmt(v) for v in row])


def write_extract(sim: Simulation, raw_dir: Path, as_of: date):
    """The insured and policy tables as the source shows them at the end of `as_of`."""
    insured_rows, policy_rows = [], []
    for ins in sorted(sim.insureds, key=lambda i: i.num_afiliado):
        if ins.created_at.date() > as_of or (ins.cancelled_at and ins.cancelled_at.date() <= as_of):
            continue
        v = version_at(ins.versions, as_of)
        insured_rows.append(
            [
                ins.num_afiliado,
                ins.sexo,
                ins.data_nascimento,
                v.attrs["estado_civil"],
                v.attrs["ind_capital_provincia"],
                ins.created_at,
                v.valid_from,
            ]
        )
        p = version_at(ins.policy.versions, as_of)
        policy_rows.append(
            [
                ins.policy.cod_apolice,
                ins.num_afiliado,
                p.attrs["desc_producto_agrupado"],
                p.attrs["desc_tipo_contrat"],
                p.attrs["flag_programa"],
                p.attrs["fecha_ingreso"],
                ins.created_at,
                p.valid_from,
            ]
        )
    stamp = as_of.isoformat()
    write_csv(raw_dir / f"segurados_{stamp}.csv", catalog.INSURED_COLUMNS, insured_rows)
    write_csv(raw_dir / f"apolices_{stamp}.csv", catalog.POLICY_COLUMNS, policy_rows)


def write_claims(sim: Simulation, raw_dir: Path):
    """One file per month of reception, with the defects mixed in."""
    rng = sim.rng
    by_month: dict[tuple[int, int], list[Claim]] = {}
    for c in sim.claims:
        by_month.setdefault((c.fec_recepcao.year, c.fec_recepcao.month), []).append(c)

    for y, m in sorted(by_month):
        rows = []
        for c in sorted(by_month[(y, m)], key=lambda c: (c.fec_recepcao, c.cod_sinistro)):
            num_afiliado = c.num_afiliado
            # Defect: the feed points at an insured that never existed.
            if c.disposition == "fact" and rng.random() < UNKNOWN_INSURED_RATE:
                num_afiliado = sim.next_unknown_id
                sim.next_unknown_id += 1
                c.disposition = "quarantine:unknown_insured"
                sim.report["defects"]["unknown_insured"] += 1
            rows.append(
                [
                    c.cod_sinistro,
                    num_afiliado,
                    c.cod_apolice,
                    c.fec_ocurrencia,
                    c.fec_recepcao,
                    c.cod_diagnostico,
                    c.agrupbenef,
                    c.gasto_presentado,
                    c.beneficio_pagado,
                ]
            )
        # Defect: the same row sent twice, somewhere else in the file.
        n_dup = int(rng.binomial(len(rows), DUPLICATE_ROW_RATE))
        for i in sorted(rng.choice(len(rows), size=n_dup, replace=False)) if n_dup else []:
            rows.insert(int(rng.integers(0, len(rows) + 1)), list(rows[i]))
        sim.report["defects"]["duplicate_rows"] += n_dup
        write_csv(raw_dir / f"sinistros_{y:04d}-{m:02d}.csv", catalog.CLAIM_COLUMNS, rows)


def write_truth(sim: Simulation, truth_dir: Path):
    horizon_end = next_month_start(*sim.months[-1])
    insured_rows, policy_rows = [], []
    for ins in sorted(sim.insureds, key=lambda i: i.num_afiliado):
        if ins.created_at >= horizon_end:
            continue
        deleted_from = (
            next_month_start(ins.cancelled_at.year, ins.cancelled_at.month)
            if ins.cancelled_at
            else None
        )
        # A cancelled key's last real version closes at the first extract
        # that no longer lists it, then a deleted marker opens, carrying the
        # last attributes seen: the same shape dbt's `hard_deletes:
        # new_record` writes.
        versions = ins.versions + ([Version(deleted_from, ins.current)] if deleted_from else [])
        for i, v in enumerate(versions):
            valid_to = versions[i + 1].valid_from if i + 1 < len(versions) else None
            insured_rows.append(
                [
                    ins.num_afiliado,
                    v.valid_from,
                    valid_to,
                    ins.sexo,
                    ins.data_nascimento,
                    v.attrs["estado_civil"],
                    v.attrs["ind_capital_provincia"],
                    int(v.valid_from == deleted_from),
                ]
            )
        pversions = ins.policy.versions + (
            [Version(deleted_from, ins.policy.current)] if deleted_from else []
        )
        for i, v in enumerate(pversions):
            valid_to = pversions[i + 1].valid_from if i + 1 < len(pversions) else None
            policy_rows.append(
                [
                    ins.policy.cod_apolice,
                    ins.num_afiliado,
                    v.valid_from,
                    valid_to,
                    v.attrs["desc_producto_agrupado"],
                    v.attrs["desc_tipo_contrat"],
                    v.attrs["flag_programa"],
                    v.attrs["fecha_ingreso"],
                    int(v.valid_from == deleted_from),
                ]
            )
    write_csv(
        truth_dir / "insured_versions.csv",
        [
            "num_afiliado",
            "valid_from",
            "valid_to",
            "sexo",
            "data_nascimento",
            "estado_civil",
            "ind_capital_provincia",
            "is_deleted",
        ],
        insured_rows,
    )
    write_csv(
        truth_dir / "policy_versions.csv",
        [
            "cod_apolice",
            "num_afiliado",
            "valid_from",
            "valid_to",
            "desc_producto_agrupado",
            "desc_tipo_contrat",
            "flag_programa",
            "fecha_ingreso",
            "is_deleted",
        ],
        policy_rows,
    )
    write_csv(
        truth_dir / "claims.csv",
        [
            "cod_sinistro",
            "disposition",
            "estado_civil",
            "ind_capital_provincia",
            "desc_producto_agrupado",
            "flag_programa",
            "age",
        ],
        (
            [
                c.cod_sinistro,
                c.disposition,
                c.at_occurrence["estado_civil"],
                c.at_occurrence["ind_capital_provincia"],
                c.at_occurrence["desc_producto_agrupado"],
                c.at_occurrence["flag_programa"],
                c.at_occurrence["age"],
            ]
            for c in sorted(sim.claims, key=lambda c: c.cod_sinistro)
        ),
    )


def write_source(
    raw_dir: Path, truth_dir: Path, seed: int, scale: int, start: str, end: str
) -> dict:
    """Simulate, then write the extracts and the truth. Returns the report."""
    sim = Simulation(seed, scale, start, end)
    sim.initial_population()

    # The initial load: the tables as they stood the day before the history
    # starts, before any change the extracts will later observe. Without it,
    # a key that changes in the first month would show up with its second
    # version only.
    write_extract(sim, raw_dir, sim.start - timedelta(days=1))
    for y, m in sim.months:
        sim.simulate_month(y, m)
        write_extract(sim, raw_dir, month_end(y, m))

    write_claims(sim, raw_dir)
    write_truth(sim, truth_dir)

    sim.report["extracts"] = len(sim.months) + 1
    sim.report["insured_initial"] = scale
    (truth_dir / "report.json").write_text(json.dumps(sim.report, indent=2) + "\n")
    return sim.report
