"""The synthetic world: Pflegedienst Sonnenschein in Deggendorf, October 2026.

`build_world(seed)` makes the cast (provider, nurses, doctors, hospital). `simulate()`
turns one `PatientSpec` into a clean `Timeline`: prescription chain, approvals, visits
for September (history, already billed) and October (the billing month), hospital
stays, death, Kassenwechsel and Pflegegrad change. `scenarios.py` then edits the
timeline to inject defects, and `case_file()` exports the truth the rules evaluate.

Every random choice draws from an RNG seeded by (world seed, patient key), so changing
one patient never reshuffles another.
"""

import datetime as dt
import random
from dataclasses import dataclass, field
from typing import Literal

from kassenfest.schemas.common import Frequency
from kassenfest.schemas.domain import (
    Approval,
    ApprovedService,
    CaseFile,
    Claim,
    ClaimLine,
    Domain,
    InsurancePeriod,
    Patient,
    Payer,
    PflegegradPeriod,
    Physician,
    PrescribedService,
    Prescription,
    Provider,
    Staff,
    Stay,
    Visit,
    VisitLog,
)
from kassenfest.schemas.ground_truth import DefectId, Variant
from kassenfest.synth import catalog, identifiers
from kassenfest.synth.catalog import KASSEN, LK, Kasse

YEAR, MONTH = 2026, 10
MONTH_STR = f"{YEAR}-{MONTH:02d}"
MONTH_START = dt.date(YEAR, MONTH, 1)
MONTH_END = dt.date(YEAR, MONTH, 31)
HISTORY_START = dt.date(2026, 9, 1)
HISTORY_MONTH = "2026-09"

Kind = Literal["hkp", "both", "xi"]
Chain = Literal["single", "switch", "new_early", "new_late"]
Event = Literal["stay", "death", "kassenwechsel", "pg_change"]
Slot = Literal["morning", "noon", "evening"]

SLOT_BASE = {"morning": (7, 25), "noon": (11, 30), "evening": (18, 10)}
FACHKRAFT = "pflegefachkraft"


def days(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def sub_working_days(d: dt.date, n: int) -> dt.date:
    return catalog.add_working_days(d, -n)


# --- Cast --------------------------------------------------------------------------


@dataclass
class Doctor:
    name: str
    specialty: str
    street: str
    zip_town: tuple[str, str]
    lanr: str
    bsnr: str

    @property
    def stamp_lines(self) -> list[str]:
        return [
            self.name,
            self.specialty,
            f"{self.street}, {self.zip_town[0]} {self.zip_town[1]}",
            f"BSNR {self.bsnr}  LANR {self.lanr}",
        ]

    def domain(self) -> Physician:
        return Physician(
            name=self.name,
            lanr=self.lanr,
            bsnr=self.bsnr,
            address=[f"Praxis {self.name}", self.street, " ".join(self.zip_town)],
        )


@dataclass
class World:
    seed: int
    provider: Provider
    doctors: list[Doctor]
    hospital_id: str

    @property
    def staff(self) -> list[Staff]:
        return self.provider.staff

    def doctor(self, lanr: str) -> Doctor:
        return next(d for d in self.doctors if d.lanr == lanr)


def build_world(seed: int) -> World:
    rng = random.Random(f"{seed}:world")
    staff = [
        Staff(
            employee_no=identifiers.generate_employee_no(rng),
            initials=initials,
            name=name,
            qualification=qual,  # type: ignore[arg-type]
        )
        for name, initials, qual in catalog.NURSES
    ]
    provider = Provider(
        name=catalog.PROVIDER_NAME,
        ik=identifiers.generate_ik(rng, "46", "99"),
        municipality="Deggendorf",
        address=list(catalog.PROVIDER_ADDRESS),
        staff=staff,
    )
    doctors = [
        Doctor(
            name=name,
            specialty=specialty,
            street=street,
            zip_town=zip_town,
            lanr=identifiers.generate_lanr(rng, fachgruppe),
            bsnr=identifiers.generate_bsnr(rng),
        )
        for name, specialty, street, zip_town, fachgruppe in catalog.DOCTORS
    ]
    return World(seed, provider, doctors, identifiers.generate_location_code(rng))


# --- Plans ---------------------------------------------------------------------------


@dataclass
class ServicePlan:
    """One HKP measure as the nurses deliver it."""

    position_no: str
    count: int
    per: Literal["day", "week"]
    slots: list[Slot]  # per day: one slot per visit; per week: the single slot used
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    details: str | None = None

    @property
    def category(self) -> str:
        return catalog.HKP_SERVICES[self.position_no].category


@dataclass
class EinsatzPlan:
    """One SGB XI visit type: a time of day, a funding source, a bundle of LK."""

    label: str
    funding: Literal["sachleistung_36", "entlastung_45b"]
    base: tuple[int, int]
    lk: list[str]
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)


@dataclass
class PatientSpec:
    """What a scenario asks for; everything left None is drawn at random."""

    key: str
    kind: Kind
    chain: Chain = "single"
    defects: list[DefectId] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    sex: Literal["f", "m"] | None = None
    last_name: str | None = None
    first_name: str | None = None
    kasse: str | None = None  # Kasse.short
    pflegegrad: int | None = None
    hkp: list[ServicePlan] | None = None
    blank: bool = False  # Blankoverordnung (wound care only)
    hero: str | None = None
    params: dict = field(default_factory=dict)  # scenario knobs, e.g. stay dates
    variants: dict[str, Variant] = field(default_factory=dict)  # doc key -> variant


@dataclass
class Record:
    """Patient master data plus what the paperwork needs (address, eGK number, doctor)."""

    id: str
    sex: Literal["f", "m"]
    first_name: str
    last_name: str
    dob: dt.date
    street: str
    zip_town: tuple[str, str]
    card_kvnr: str  # on the eGK: what doctors, Kassen and hospitals print
    kvnr: str  # in the provider's software (differs only for D16)
    insurance: list[InsurancePeriod]
    pflegegrad: list[PflegegradPeriod]
    copay_exempt: bool
    doctor_lanr: str
    icd_codes: list[str]
    limitations: str
    care_start: dt.date
    hkp: list[ServicePlan]
    xi: list[EinsatzPlan]
    team: list[int]  # staff indexes, Fachkräfte first
    deceased_at: dt.datetime | None = None

    @property
    def name(self) -> str:
        return f"{self.last_name}, {self.first_name}"

    def kasse_at(self, d: dt.date) -> Kasse:
        for p in self.insurance:
            if p.valid_from <= d and (p.valid_to is None or d <= p.valid_to):
                return catalog.KASSE_BY_IK[p.krankenkasse_ik]
        return catalog.KASSE_BY_IK[self.insurance[-1].krankenkasse_ik]

    def pflegegrad_at(self, d: dt.date) -> int | None:
        grade = None
        for p in sorted(self.pflegegrad, key=lambda p: p.valid_from):
            if p.valid_from <= d:
                grade = p.grade
        return grade

    def domain(self) -> Patient:
        return Patient(
            id=self.id,
            name=self.name,
            dob=self.dob,
            kvnr=self.kvnr,
            insurance=self.insurance,
            pflegegrad=self.pflegegrad,
            deceased_at=self.deceased_at,
            copay_exempt=self.copay_exempt,
        )


@dataclass
class Rec:
    """One delivered service: an HKP position on a visit, or one LK of an SGB XI Einsatz."""

    when: dt.datetime
    domain: Domain
    code: str
    staff: int | None  # index into world.staff; None = no Handzeichen
    slot: Slot | None = None  # HKP
    einsatz: int | None = None  # SGB XI, index into record.xi
    xi_funding: Literal["sachleistung_36", "entlastung_45b"] = "sachleistung_36"

    @property
    def date(self) -> dt.date:
        return self.when.date()

    @property
    def funding(self) -> Literal["hkp", "sachleistung_36", "entlastung_45b"]:
        return "hkp" if self.domain == "sgbv" else self.xi_funding


@dataclass
class StayInfo:
    """What the Entlassbrief says beyond the stay itself."""

    diagnoses: list[str]
    physician: str
    hkp_recommended: bool
    hkp_days: int | None
    medication: list[str]
    signed: bool = True


@dataclass
class DefectLabel:
    defect: DefectId
    docs: list[str]  # doc keys, resolved to doc ids by the set generator
    note: str
    lines: list[Rec] = field(default_factory=list)  # affected billed services, if any


@dataclass
class Timeline:
    spec: PatientSpec
    record: Record
    prescriptions: list[Prescription]
    approvals: list[Approval]
    recs: list[Rec]  # September + October, both domains
    stays: list[Stay] = field(default_factory=list)
    stay_info: dict[str, StayInfo] = field(default_factory=dict)
    signed: dict[str, bool] = field(default_factory=dict)  # domain -> LN signed by patient
    missing_reason: dict[str, Literal[1, 2, 3, 4] | None] = field(default_factory=dict)
    labels: list[DefectLabel] = field(default_factory=list)
    # Rejected items appear on the approval letter only: approval id -> [(position, reason)]
    rejected: dict[str, list[tuple[str, str]]] = field(default_factory=dict)

    @property
    def october(self) -> list[Rec]:
        return [r for r in self.recs if r.date >= MONTH_START]

    def october_of(self, domain: Domain) -> list[Rec]:
        return sorted(
            (r for r in self.october if r.domain == domain), key=lambda r: (r.when, r.code)
        )

    def in_month(self, items: list) -> list:
        return [x for x in items if x.period_from <= MONTH_END and x.period_to >= MONTH_START]

    @property
    def domains(self) -> list[Domain]:
        return [d for d in ("sgbv", "sgbxi") if any(r.domain == d for r in self.october)]

    def approval_for(self, rx: Prescription) -> Approval | None:
        return next((a for a in self.approvals if a.prescription_id == rx.id), None)


# --- Simulation ------------------------------------------------------------------------


def _random_hkp(rng: random.Random) -> list[ServicePlan]:
    """1–3 measures that make sense together."""
    choice = rng.choices(
        ["med2", "med1", "diabetes", "komp", "wound", "med_komp", "diab_med", "wound_komp"],
        weights=[4, 2, 3, 2, 2, 3, 2, 1],
    )[0]
    med2 = ServicePlan("032101", 2, "day", ["morning", "evening"])
    med1 = ServicePlan("032101", 1, "day", ["morning"])
    inj = ServicePlan("032110", 1, "day", ["morning"])
    bz = ServicePlan("032120", 1, "day", ["morning"])
    komp = ServicePlan("032130", 1, "day", ["morning"])
    wound = ServicePlan("032151", 3, "week", ["noon"], weekdays=(0, 2, 4))
    plans = {
        "med2": [med2],
        "med1": [med1],
        "diabetes": [inj, bz],
        "komp": [ServicePlan("032140", 1, "day", ["morning"])],
        "wound": [wound],
        "med_komp": [med1, komp],
        "diab_med": [med2, inj, bz],
        "wound_komp": [komp, wound],
    }
    return plans[choice]


def _xi_plan(rng: random.Random, grade: int) -> list[EinsatzPlan]:
    early = (6, 50)
    plans = {
        2: [EinsatzPlan("Früh", "sachleistung_36", early, ["LK02", "LK07"])],
        3: [
            EinsatzPlan("Früh", "sachleistung_36", early, ["LK01", "LK07"]),
            EinsatzPlan("Abend", "sachleistung_36", (19, 0), ["LK05"], (0, 2, 4)),
        ],
        4: [
            EinsatzPlan("Früh", "sachleistung_36", early, ["LK01", "LK03", "LK07"]),
            EinsatzPlan("Abend", "sachleistung_36", (19, 0), ["LK02", "LK07"]),
        ],
        5: [
            EinsatzPlan("Früh", "sachleistung_36", early, ["LK01", "LK03", "LK07"]),
            EinsatzPlan("Abend", "sachleistung_36", (19, 0), ["LK02", "LK05", "LK07"]),
        ],
    }
    out = [EinsatzPlan(e.label, e.funding, e.base, list(e.lk), e.weekdays) for e in plans[grade]]
    if rng.random() < 0.6:  # §45b help with shopping, once a week
        out.append(
            EinsatzPlan(
                "Hauswirtschaft", "entlastung_45b", (10, 15), ["LK12"], (rng.randint(0, 4),)
            )
        )
    return out


def xi_month_cost(recs: list[Rec]) -> int:
    return sum(
        LK[r.code].price_cents
        for r in recs
        if r.domain == "sgbxi" and r.xi_funding == "sachleistung_36" and r.date >= MONTH_START
    )


def _fit_xi_budget(record: Record, grade: int) -> None:
    """Thin out the Abend Einsatz until a clean month stays below 92 % of the §36 cap."""
    cap = catalog.SACHLEISTUNG_CAP_CENTS[grade] * 0.92

    def cost() -> int:
        total = 0
        for d in days(MONTH_START, MONTH_END):
            for e in record.xi:
                if e.funding == "sachleistung_36" and d.weekday() in e.weekdays:
                    total += sum(LK[c].price_cents for c in e.lk)
        return total

    while cost() > cap:
        evening = [e for e in record.xi if e.label == "Abend"]
        target = evening[0] if evening else record.xi[0]
        if len(target.weekdays) > 1:
            target.weekdays = target.weekdays[:-1]
        elif len(target.lk) > 1:
            target.lk.pop()
        else:
            record.xi.remove(target)


def make_record(world: World, spec: PatientSpec) -> Record:
    rng = random.Random(f"{world.seed}:{spec.key}:record")
    sex = spec.sex or rng.choice(["f", "f", "m"])
    first = spec.first_name or rng.choice(catalog.FEMALE if sex == "f" else catalog.MALE)
    last = spec.last_name or rng.choice(catalog.SURNAMES)
    age = rng.randint(64, 94)
    dob = dt.date(YEAR - age, rng.randint(1, 12), rng.randint(1, 28))
    kasse = next(k for k in KASSEN if k.short == spec.kasse) if spec.kasse else None
    kasse = kasse or rng.choices(KASSEN, weights=[5, 2, 2, 2, 1, 1, 1])[0]
    insured_since = dt.date(rng.randint(1995, 2020), 1, 1)
    insurance = [InsurancePeriod(
        krankenkasse_ik=kasse.krankenkasse_ik,
        pflegekasse_ik=kasse.pflegekasse_ik,
        valid_from=insured_since,
    )]  # fmt: skip
    if "kassenwechsel" in spec.events:
        old = rng.choice([k for k in KASSEN if k is not kasse])
        insurance = [
            InsurancePeriod(
                krankenkasse_ik=old.krankenkasse_ik,
                pflegekasse_ik=old.pflegekasse_ik,
                valid_from=insured_since,
                valid_to=MONTH_START - dt.timedelta(days=1),
            ),
            InsurancePeriod(
                krankenkasse_ik=kasse.krankenkasse_ik,
                pflegekasse_ik=kasse.pflegekasse_ik,
                valid_from=MONTH_START,
            ),
        ]

    grade = spec.pflegegrad or (
        rng.choice([2, 2, 3, 3, 4, 5]) if spec.kind != "hkp" else rng.choice([None, 1, 2, 2, 3])
    )
    pflegegrad = []
    if grade:
        pflegegrad = [
            PflegegradPeriod(
                grade=grade, valid_from=dt.date(rng.randint(2019, 2025), rng.randint(1, 12), 1)
            )
        ]
        if "pg_change" in spec.events and spec.kind != "hkp":
            pflegegrad = [
                PflegegradPeriod(grade=max(2, grade - 1), valid_from=pflegegrad[0].valid_from),
                PflegegradPeriod(grade=grade, valid_from=MONTH_START),
            ]

    hkp = spec.hkp if spec.hkp is not None else ([] if spec.kind == "xi" else _random_hkp(rng))
    for s in hkp:
        if s.details is None:
            s.details = rng.choice(catalog.MEASURE_DETAILS[s.position_no])
    if spec.blank:
        hkp = [s for s in hkp if s.position_no == "032151"] or [
            ServicePlan("032151", 3, "week", ["noon"], weekdays=(0, 2, 4))
        ]
        hkp[0].details = hkp[0].details or catalog.MEASURE_DETAILS["032151"][0]
    xi = _xi_plan(rng, grade) if spec.kind != "hkp" and grade and grade >= 2 else []

    icd: list[str] = []
    for s in hkp:
        for code in catalog.SERVICE_ICD[s.position_no][:2]:
            if code not in icd:
                icd.append(code)
    if not icd:
        icd = [rng.choice(["F03", "I50.9", "M17.1"])]

    if spec.chain == "new_early":
        care_start = dt.date(2026, 9, rng.randint(14, 25))
    elif spec.chain == "new_late":
        care_start = spec.params.get("care_start") or dt.date(2026, 10, rng.randint(5, 19))
    else:
        care_start = dt.date(rng.randint(2022, 2026), rng.randint(1, 6), 1)

    fachkraefte = [i for i, s in enumerate(world.staff) if s.qualification == FACHKRAFT]
    helpers = [i for i, s in enumerate(world.staff) if s.qualification != FACHKRAFT]
    team = rng.sample(fachkraefte, 3) + rng.sample(helpers, 1)

    zip_code, town = rng.choice(catalog.TOWNS)
    card_kvnr = identifiers.generate_kvnr(rng)
    record = Record(
        id=spec.key,
        sex=sex,
        first_name=first,
        last_name=last,
        dob=dob,
        street=f"{rng.choice(catalog.STREETS)} {rng.randint(1, 48)}",
        zip_town=(zip_code, town),
        card_kvnr=card_kvnr,
        kvnr=card_kvnr,
        insurance=insurance,
        pflegegrad=pflegegrad,
        copay_exempt=rng.random() < 0.25,
        doctor_lanr=rng.choice(world.doctors).lanr,
        icd_codes=icd[:3],
        limitations=rng.choice(catalog.LIMITATIONS),
        care_start=care_start,
        hkp=hkp,
        xi=xi,
        team=team,
    )
    if xi and grade:
        _fit_xi_budget(record, record.pflegegrad_at(MONTH_START) or grade)
    return record


def _prescription(
    record: Record,
    n: int,
    kind: Literal["erst", "folge"],
    issue: dt.date,
    start: dt.date,
    end: dt.date,
    rng: random.Random,
    blank: bool = False,
) -> Prescription:
    return Prescription(
        id=f"{record.id}-rx{n}",
        patient_id=record.id,
        physician_lanr=record.doctor_lanr,
        kind=kind,
        issue_date=issue,
        period_from=start,
        period_to=end,
        blank=blank,
        services=[
            PrescribedService(
                category=s.category,
                position_no=s.position_no,
                frequency=None if blank else Frequency(count=s.count, per=s.per),
                details=s.details,
            )
            for s in record.hkp
        ],
        icd_codes=record.icd_codes,
        doctor_signed=True,
        stamp_present=True,
        submitted_to_payer_at=catalog.add_working_days(issue, rng.choice([1, 1, 2, 2, 3])),
    )


def _chain(
    record: Record, chain: Chain, rng: random.Random, blank: bool, params: dict
) -> list[Prescription]:
    """Verordnungen from care start until past the billing month, no gaps."""
    out: list[Prescription] = []
    if chain in ("new_early", "new_late"):
        start = record.care_start
        end = start + dt.timedelta(days=13)
        out.append(_prescription(record, 1, "erst", start, start, end, rng))
    elif chain == "switch":
        end = params.get("rx_end") or dt.date(YEAR, MONTH, rng.randint(9, 22))
        start = end - dt.timedelta(days=rng.choice([59, 61, 90]))
        issue = sub_working_days(start - dt.timedelta(days=1), rng.choice([1, 2]))
        out.append(_prescription(record, 1, "folge", issue, start, end, rng, blank))
    else:
        start = dt.date(2026, 9, rng.randint(1, 30))
        if rng.random() < 0.5:
            start = MONTH_START
        end = start + dt.timedelta(days=rng.choice([60, 75, 90]))
        issue = sub_working_days(start - dt.timedelta(days=1), rng.choice([1, 2]))
        out.append(_prescription(record, 1, "folge", issue, start, end, rng, blank))
    extend_chain(record, out, rng, blank)
    return out


def extend_chain(
    record: Record, out: list[Prescription], rng: random.Random, blank: bool = False
) -> None:
    """Append Folgeverordnungen, each issued in time, until the month is covered."""
    while out[-1].period_to < MONTH_END:
        prev = out[-1]
        start = prev.period_to + dt.timedelta(days=1)
        end = start + dt.timedelta(days=rng.choice([60, 75, 90]))
        issue = sub_working_days(prev.period_to, rng.choice([1, 2]))
        n = int(prev.id.rsplit("rx", 1)[1]) + 1
        out.append(_prescription(record, n, "folge", issue, start, end, rng, blank))


CLERKS = ["Frau Gschwendtner", "Herr Lallinger", "Frau Weinzierl", "Herr Schmidbauer", "Frau Ertl"]


def make_approval(
    record: Record, rx: Prescription, provider_ik: str, rng: random.Random
) -> Approval:
    kasse = record.kasse_at(rx.period_from)
    ref = kasse.ref_prefix.format(y=YEAR, n=rng.randint(10**5, 10**6 - 1))
    submitted = rx.submitted_to_payer_at or rx.issue_date
    stated = rng.random() < 0.8 or rx.blank  # otherwise the letter says "lt. Verordnung"
    blank_freq = Frequency(count=3, per="week")
    return Approval(
        id=f"{record.id}-ap{rx.id.rsplit('rx', 1)[1]}",
        patient_id=record.id,
        payer_ik=kasse.krankenkasse_ik,
        provider_ik=provider_ik,
        approval_ref=ref,
        letter_date=catalog.add_working_days(submitted, rng.choice([2, 3, 4, 6, 9])),
        decision="approved",
        period_from=rx.period_from,
        period_to=rx.period_to,
        approved=[
            ApprovedService(
                position_no=s.position_no or "",
                frequency=(s.frequency or blank_freq) if stated else None,
                valid_from=rx.period_from,
                valid_to=rx.period_to,
            )
            for s in rx.services
        ],
        prescription_id=rx.id,
    )


def _jitter(base: tuple[int, int], rng: random.Random) -> dt.time:
    minutes = base[0] * 60 + base[1] + rng.randint(-15, 20)
    if rng.random() < 0.7:
        minutes = 5 * round(minutes / 5)
    return dt.time(minutes // 60, minutes % 60)


def _visits(world: World, record: Record, rng: random.Random) -> list[Rec]:
    recs: list[Rec] = []
    fach = [i for i in record.team if world.staff[i].qualification == FACHKRAFT]
    start = max(HISTORY_START, record.care_start)
    for d in days(start, MONTH_END):
        for slot in ("morning", "noon", "evening"):
            due = [
                s
                for s in record.hkp
                if slot in s.slots and (s.per == "day" or d.weekday() in s.weekdays)
            ]
            if not due:
                continue
            when = dt.datetime.combine(d, _jitter(SLOT_BASE[slot], rng))
            nurse = rng.choice(fach)
            recs += [Rec(when, "sgbv", s.position_no, nurse, slot=slot) for s in due]
        for ei, e in enumerate(record.xi):
            if d.weekday() not in e.weekdays:
                continue
            when = dt.datetime.combine(d, _jitter(e.base, rng))
            nurse = rng.choice(record.team)
            recs += [
                Rec(when, "sgbxi", code, nurse, einsatz=ei, xi_funding=e.funding) for code in e.lk
            ]
    return recs


def add_stay(
    tl: Timeline,
    admitted: dt.datetime,
    discharged: dt.datetime,
    rng: random.Random,
    *,
    clean: bool = True,
) -> Stay:
    """A hospital stay with its Entlassbrief. Clean: visits pause from an hour before
    admission to an hour after discharge (edge days keep the visits outside that)."""
    stay = Stay(
        id=f"{tl.record.id}-st{len(tl.stays) + 1}",
        patient_id=tl.record.id,
        kind="hospital",
        admitted_at=admitted,
        discharged_at=discharged,
    )
    tl.stays.append(stay)
    tl.stay_info[stay.id] = StayInfo(
        diagnoses=rng.choice(catalog.HOSPITAL_DIAGNOSES),
        physician=rng.choice(catalog.HOSPITAL_DOCTORS),
        hkp_recommended=bool(tl.record.hkp),
        hkp_days=None,
        medication=rng.sample(
            [
                "Torasemid 10 mg 1-0-0",
                "Apixaban 5 mg 1-0-1",
                "Ramipril 5 mg 1-0-0",
                "Metformin 1000 mg 1-0-1",
                "Pantoprazol 20 mg 1-0-0",
                "Amoxicillin 1000 mg 1-1-1 bis einschl. Folgetag",
                "Paracetamol 500 mg bei Bedarf, max. 4x tgl.",
            ],
            3,
        ),
    )
    if clean:
        margin = dt.timedelta(hours=1)
        tl.recs = [r for r in tl.recs if not (admitted - margin < r.when < discharged + margin)]
    return stay


def set_death(tl: Timeline, when: dt.datetime, *, clean: bool = True) -> None:
    tl.record.deceased_at = when
    if clean:
        tl.recs = [r for r in tl.recs if r.when < when]
    for domain in ("sgbv", "sgbxi"):
        tl.signed[domain] = False
        tl.missing_reason[domain] = 1


def stay_window(
    tl: Timeline, rng: random.Random, length: int | None = None
) -> tuple[dt.datetime, dt.datetime]:
    """Admission and discharge inside October, after care start, on days with visits."""
    length = length or rng.randint(3, 6)
    first = max(MONTH_START + dt.timedelta(days=2), tl.record.care_start + dt.timedelta(days=2))
    last = MONTH_END - dt.timedelta(days=length + 2)
    day = first + dt.timedelta(days=rng.randint(0, max(0, (last - first).days)))
    admitted = dt.datetime.combine(day, dt.time(rng.randint(9, 14), rng.choice([0, 15, 30, 45])))
    discharged = dt.datetime.combine(
        day + dt.timedelta(days=length), dt.time(rng.randint(10, 13), rng.choice([0, 15, 30, 45]))
    )
    return admitted, discharged


def simulate(world: World, spec: PatientSpec) -> Timeline:
    """A clean timeline for one patient; world events applied, no defects yet."""
    record = make_record(world, spec)
    rng = random.Random(f"{world.seed}:{spec.key}:timeline")
    prescriptions = _chain(record, spec.chain, rng, spec.blank, spec.params) if record.hkp else []
    approvals = [make_approval(record, rx, world.provider.ik, rng) for rx in prescriptions]
    tl = Timeline(spec, record, prescriptions, approvals, _visits(world, record, rng))
    for domain in tl.domains:
        tl.signed[domain] = True
        tl.missing_reason[domain] = None

    if "stay" in spec.events:
        admitted, discharged = spec.params.get("stay") or stay_window(tl, rng)
        add_stay(tl, admitted, discharged, rng, clean=True)
    if "death" in spec.events:
        day = dt.date(YEAR, MONTH, rng.randint(14, 26))
        set_death(tl, dt.datetime.combine(day, dt.time(rng.randint(9, 16), 20)), clean=True)
    return tl


# --- Export ---------------------------------------------------------------------------


def _payers(record: Record) -> dict[str, Payer]:
    out: dict[str, Payer] = {}
    for p in record.insurance:
        k = catalog.KASSE_BY_IK[p.krankenkasse_ik]
        out[k.krankenkasse_ik] = Payer(name=k.name, ik=k.krankenkasse_ik, kind="krankenkasse")
        out[k.pflegekasse_ik] = Payer(
            name=k.pflegekasse_name, ik=k.pflegekasse_ik, kind="pflegekasse"
        )
    return out


def payer_ik(record: Record, domain: Domain, d: dt.date) -> str:
    k = record.kasse_at(d)
    return k.krankenkasse_ik if domain == "sgbv" else k.pflegekasse_ik


def price_cents(rec: Rec) -> int:
    return (
        catalog.HKP_SERVICES[rec.code].price_cents
        if rec.domain == "sgbv"
        else LK[rec.code].price_cents
    )


def prior_claims(world: World, tl: Timeline) -> list[Claim]:
    claims = []
    for domain in ("sgbv", "sgbxi"):
        recs = sorted(
            (r for r in tl.recs if r.domain == domain and r.date < MONTH_START),
            key=lambda r: (r.when, r.code),
        )
        if not recs:
            continue
        claim_id = f"{tl.record.id}-{HISTORY_MONTH}-{domain}"
        claims.append(
            Claim(
                id=claim_id,
                patient_id=tl.record.id,
                payer_ik=payer_ik(tl.record, domain, recs[0].date),  # type: ignore[arg-type]
                month=HISTORY_MONTH,
                domain=domain,  # type: ignore[arg-type]
                lines=[
                    ClaimLine(
                        id=f"{claim_id}-{i:03d}",
                        date=r.date,
                        time=r.when.time(),
                        code=r.code,
                        quantity=1,
                        unit_price_cents=price_cents(r),
                        funding=r.funding,
                    )
                    for i, r in enumerate(recs)
                ],
                tariff_version=catalog.HKP_TARIFF if domain == "sgbv" else catalog.XI_TARIFF,
            )
        )
    return claims


def sheet_services(tl: Timeline) -> list[str]:
    """Columns of the SGB V sheet: care-plan order, then anything else billed."""
    billed = {r.code for r in tl.october_of("sgbv")}
    codes = [s.position_no for s in tl.record.hkp]
    codes += sorted(billed - set(codes))
    return [c for c in codes if c in billed]


def visit_order(tl: Timeline, domain: Domain) -> list[Rec]:
    """October services in the order the rendered sheet lists them as `entries[i]`.

    SGB V: day, sheet column, then time within the day (the slot). SGB XI: day,
    Einsatz, then the Einsatz's LK order. `paperwork` builds the sheets from this order.
    """
    recs = tl.october_of(domain)
    if domain == "sgbv":
        columns = sheet_services(tl)
        rank = slot_rank(tl)
        return sorted(recs, key=lambda r: (r.date, columns.index(r.code), rank[id(r)]))
    xi = tl.record.xi
    return sorted(recs, key=lambda r: (r.date, r.einsatz or 0, xi[r.einsatz or 0].lk.index(r.code)))


def slot_rank(tl: Timeline) -> dict[int, int]:
    """Per SGB V service: 0 for the first visit of the day, 1 for the second (by id(rec))."""
    rank: dict[int, int] = {}
    seen: dict[tuple[dt.date, str], int] = {}
    for r in tl.october_of("sgbv"):
        rank[id(r)] = seen.get((r.date, r.code), 0)
        seen[(r.date, r.code)] = rank[id(r)] + 1
    return rank


def visit_log_id(tl: Timeline, domain: Domain) -> str:
    return f"{tl.record.id}-{MONTH_STR}-{domain}"


def case_file(world: World, tl: Timeline, doc_ids: dict[str, str] | None = None) -> CaseFile:
    """The truth for one patient-month. `doc_ids` maps doc keys to rendered document ids;
    visit entry indexes match the `entries[i]` of the rendered Leistungsnachweis."""
    doc_ids = doc_ids or {}
    record = tl.record
    prescriptions = [
        rx.model_copy(update={"document_id": doc_ids.get(f"muster12:{rx.id}")})
        for rx in tl.in_month(tl.prescriptions)
    ]
    approvals = [
        a.model_copy(update={"document_id": doc_ids.get(f"approval_letter:{a.id}")})
        for a in tl.in_month(tl.approvals)
    ]
    logs = []
    for domain in tl.domains:
        doc_id = doc_ids.get(f"visit_log_{domain}")
        recs = visit_order(tl, domain)
        logs.append(
            VisitLog(
                id=visit_log_id(tl, domain),
                patient_id=record.id,
                payer_ik=payer_ik(record, domain, MONTH_END),
                month=MONTH_STR,
                domain=domain,
                visits=[
                    Visit(
                        date=r.date,
                        start=r.when.time(),
                        code=r.code,
                        quantity=1,
                        funding=r.funding,
                        employee_no=world.staff[r.staff].employee_no
                        if r.staff is not None
                        else None,
                        staff_initials=world.staff[r.staff].initials
                        if r.staff is not None
                        else None,
                        document_id=doc_id,
                        entry_index=i,
                    )
                    for i, r in enumerate(recs)
                ],
                patient_signed=tl.signed[domain],
                missing_signature_reason=tl.missing_reason[domain],
                provider_signed=True,
                document_id=doc_id,
            )
        )
    stays = [
        s.model_copy(update={"document_id": doc_ids.get(f"hospital_letter:{s.id}")})
        for s in tl.stays
    ]
    return CaseFile(
        month=MONTH_STR,
        provider=world.provider,
        patient=record.domain(),
        payers=_payers(record),
        physicians={
            rx.physician_lanr: world.doctor(rx.physician_lanr).domain() for rx in prescriptions
        },
        prescriptions=prescriptions,
        approvals=approvals,
        visit_logs=logs,
        stays=stays,
        prior_claims=prior_claims(world, tl),
    )
