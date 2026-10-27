"""Defect injection (docs/01 §4) and the patient casts of the demo, dev and test sets.

Each Tier-A defect maps to the rules that must catch it (docs/05 §3). A defect edits
a clean timeline, then records a `DefectLabel` naming the documents that show it and,
where it is about billed services, the exact lines. Labels end up in the documents'
`GroundTruth.defects` and in the per-patient-month manifest.

Co-labels are deliberate: a lapsed or late Folgeverordnung (D08) leaves visits without
a Verordnung, so it always brings D01 with it.
"""

import datetime as dt
import random
from collections import Counter
from collections.abc import Callable

from kassenfest.schemas.common import Frequency
from kassenfest.schemas.ground_truth import DefectId
from kassenfest.synth import catalog, identifiers
from kassenfest.synth.paperwork import doc_keys
from kassenfest.synth.world import (
    MONTH_END,
    MONTH_START,
    YEAR,
    DefectLabel,
    EinsatzPlan,
    PatientSpec,
    Rec,
    ServicePlan,
    Timeline,
    World,
    _jitter,
    add_stay,
    days,
    extend_chain,
    make_approval,
    set_death,
    simulate,
    stay_window,
    xi_month_cost,
)

TIER_A: list[DefectId] = [
    "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09",
    "D10", "D11", "D12", "D15", "D16", "D18", "D19", "D20",
]  # fmt: skip

RULES: dict[DefectId, list[str]] = {
    "D01": ["HKP-RX-REQUIRED"],
    "D02": ["HKP-APPROVAL-EXISTS"],
    "D03": ["HKP-APPROVAL-SCOPE"],
    "D04": ["HKP-LN-SIGNATURE", "XI-LN-SIGNATURE"],
    "D05": ["HKP-STAFF-INITIALS"],
    "D06": ["STAY-HKP", "STAY-XI-SACH"],
    "D07": ["HKP-SUBMIT-4WD"],
    "D08": ["HKP-FOLGE-WINDOW"],
    "D09": ["HKP-RX-SIGNED"],
    "D10": ["HKP-FREQ-RX"],
    "D11": ["HKP-ERST-14D"],
    "D12": ["XI-36-BUDGET"],
    "D15": ["MD-DECEASED"],
    "D16": ["MD-KVNR-CHECK"],
    "D18": ["HKP-DUPLICATE"],
    "D19": ["DOC-READABLE"],
    "D20": [],
}

HKP_ONLY = {"D01", "D02", "D03", "D05", "D07", "D08", "D09", "D10", "D11", "D18"}
CONFLICTS = [
    {"D02", "D03"}, {"D03", "D10"}, {"D10", "D18"}, {"D04", "D15"}, {"D06", "D15"},
    {"D08", "D11"}, {"D08", "D01"}, {"D11", "D01"}, {"D15", "D01"}, {"D15", "D08"},
]  # fmt: skip
CHAIN_FOR = {"D08": "switch", "D11": "new_late", "D01": "new_late"}
# Structural edits first, then edits that pick among the remaining visits.
ORDER: list[DefectId] = [
    "D11", "D08", "D01", "D06", "D15", "D12", "D02", "D03", "D10",
    "D07", "D09", "D18", "D05", "D16", "D04", "D19",
]  # fmt: skip


def _main_rx(tl: Timeline):
    """The Verordnung covering most of October."""

    def overlap(rx) -> int:
        start, end = max(rx.period_from, MONTH_START), min(rx.period_to, MONTH_END)
        return (end - start).days

    return max(tl.in_month(tl.prescriptions), key=overlap)


def _home(tl: Timeline, when: dt.datetime) -> bool:
    """Patient alive and not in hospital at that moment."""
    margin = dt.timedelta(hours=1)
    if tl.record.deceased_at and when >= tl.record.deceased_at:
        return False
    end_of_month = dt.datetime.combine(MONTH_END, dt.time.max)
    return not any(
        s.admitted_at - margin < when < (s.discharged_at or end_of_month) + margin for s in tl.stays
    )


def _hkp_oct(tl: Timeline) -> list[Rec]:
    return tl.october_of("sgbv")


def _label(tl: Timeline, defect: DefectId, docs: list[str], note: str, lines=()) -> None:
    tl.labels.append(DefectLabel(defect, docs, note, list(lines)))


def _reapprove(tl: Timeline, rx, rng: random.Random) -> None:
    """Keep an approval in step with an edited Verordnung's period."""
    ap = tl.approval_for(rx)
    if ap is None:
        return
    ap.period_from, ap.period_to = rx.period_from, rx.period_to
    for item in ap.approved:
        item.valid_from, item.valid_to = rx.period_from, rx.period_to
    ap.letter_date = catalog.add_working_days(
        rx.submitted_to_payer_at or rx.issue_date, rng.choice([2, 3, 5])
    )


# --- Injectors -------------------------------------------------------------------------


def d01_early_start(tl: Timeline, rng: random.Random) -> None:
    """Care started before the Erstverordnung's period: the first days are uncovered."""
    erst = tl.prescriptions[0]
    shift = tl.spec.params.get("d01_shift") or rng.randint(2, 4)
    erst.period_from = erst.issue_date = tl.record.care_start + dt.timedelta(days=shift)
    erst.submitted_to_payer_at = catalog.add_working_days(erst.issue_date, 1)
    _reapprove(tl, erst, rng)
    lines = [r for r in _hkp_oct(tl) if r.date < erst.period_from]
    _label(
        tl, "D01", [f"muster12:{erst.id}", "visit_log_sgbv"],
        f"Visits from {tl.record.care_start} but the Erstverordnung starts {erst.period_from}",
        lines,
    )  # fmt: skip


def d08_folge(tl: Timeline, rng: random.Random) -> None:
    """The Folgeverordnung came late (gap) or never came (lapsed); visits went on."""
    a, b = tl.prescriptions[0], tl.prescriptions[1]
    mode = tl.spec.params.get("d08") or rng.choice(["lapsed", "late"])
    if mode == "lapsed":
        tl.prescriptions = [a]
        tl.approvals = [ap for ap in tl.approvals if ap.prescription_id == a.id]
        lines = [r for r in _hkp_oct(tl) if r.date > a.period_to]
        _label(
            tl, "D08", [f"muster12:{a.id}"], f"Verordnung ended {a.period_to}, no Folgeverordnung"
        )
        _label(
            tl,
            "D01",
            [f"muster12:{a.id}", "visit_log_sgbv"],
            f"Visits after {a.period_to} without Verordnung",
            lines,
        )
        return
    b.issue_date = b.period_from = a.period_to + dt.timedelta(days=rng.randint(3, 6))
    b.submitted_to_payer_at = catalog.add_working_days(b.issue_date, 1)
    _reapprove(tl, b, rng)
    lines = [r for r in _hkp_oct(tl) if a.period_to < r.date < b.period_from]
    _label(
        tl,
        "D08",
        [f"muster12:{a.id}", f"muster12:{b.id}"],
        f"Folgeverordnung issued {b.issue_date}, after the previous one ended {a.period_to}",
    )
    _label(
        tl,
        "D01",
        [f"muster12:{b.id}", "visit_log_sgbv"],
        f"Visits {a.period_to + dt.timedelta(days=1)}–{b.period_from - dt.timedelta(days=1)} "
        "without Verordnung",
        lines,
    )


def d11_long_erst(tl: Timeline, rng: random.Random) -> None:
    """Erstverordnung for 3–4 weeks instead of at most 14 days."""
    erst = tl.prescriptions[0]
    erst.period_to = erst.period_from + dt.timedelta(days=rng.randint(20, 27))
    provider_ik = tl.approvals[0].provider_ik
    tl.prescriptions = [erst]
    tl.approvals = [ap for ap in tl.approvals if ap.prescription_id == erst.id]
    _reapprove(tl, erst, rng)
    extend_chain(tl.record, tl.prescriptions, rng)
    tl.approvals += [make_approval(tl.record, rx, provider_ik, rng) for rx in tl.prescriptions[1:]]
    days_ = (erst.period_to - erst.period_from).days + 1
    _label(tl, "D11", [f"muster12:{erst.id}"], f"Erstverordnung covers {days_} days")


def d06_stay(tl: Timeline, rng: random.Random) -> None:
    """Hospital stay with an Entlassbrief, but the visit log goes on as if at home."""
    admitted, discharged = tl.spec.params.get("stay") or stay_window(tl, rng)
    stay = add_stay(tl, admitted, discharged, rng, clean=False)
    lines = [r for r in tl.october if admitted < r.when < discharged]
    docs = [f"hospital_letter:{stay.id}", *sorted({f"visit_log_{r.domain}" for r in lines})]
    _label(
        tl,
        "D06",
        docs,
        f"Visits billed during the stay {admitted:%d.%m. %H:%M}–{discharged:%d.%m. %H:%M}",
        lines,
    )


def d15_deceased(tl: Timeline, rng: random.Random) -> None:
    """Patient died; the visit log still lists visits for a few days after."""
    day = dt.date(YEAR, 10, rng.randint(17, 25))
    when = dt.datetime.combine(day, dt.time(rng.randint(9, 15), rng.choice([5, 20, 40])))
    set_death(tl, when, clean=False)
    stop = when + dt.timedelta(days=rng.randint(2, 4))
    tl.recs = [r for r in tl.recs if r.when < stop]
    lines = [r for r in tl.october if r.when >= when]
    docs = sorted({f"visit_log_{r.domain}" for r in lines})
    _label(tl, "D15", docs, f"Died {when:%d.%m.%Y %H:%M}; visits billed afterwards", lines)


def d12_budget(tl: Timeline, rng: random.Random) -> None:
    """SGB XI services worth more than the §36 Sachleistung cap for the Pflegegrad."""
    grade = tl.record.pflegegrad_at(MONTH_END) or 2
    cap = catalog.SACHLEISTUNG_CAP_CENTS[grade]
    target = cap * rng.uniform(1.08, 1.25)
    extra = EinsatzPlan("Mittag", "sachleistung_36", (11, 45), ["LK04"])
    tl.record.xi.append(extra)
    ei = len(tl.record.xi) - 1
    pool = ["LK13", "LK06", "LK03", "LK05", "LK01"]

    def deliver() -> None:
        tl.recs = [r for r in tl.recs if not (r.domain == "sgbxi" and r.einsatz == ei)]
        for d in days(max(MONTH_START, tl.record.care_start), MONTH_END):
            when = dt.datetime.combine(d, _jitter(extra.base, rng))
            if _home(tl, when):
                nurse = rng.choice(tl.record.team)
                tl.recs += [Rec(when, "sgbxi", c, nurse, einsatz=ei) for c in extra.lk]

    deliver()
    while xi_month_cost(tl.recs) < target and pool:
        extra.lk.append(pool.pop(0))
        deliver()
    total = xi_month_cost(tl.recs)
    if total <= cap:
        raise ValueError(f"{tl.record.id}: could not push SGB XI services over the cap")
    lines, running = [], 0
    for r in sorted(tl.october_of("sgbxi"), key=lambda r: r.when):
        if r.xi_funding != "sachleistung_36":
            continue
        running += catalog.LK[r.code].price_cents
        if running > cap:
            lines.append(r)
    _label(
        tl,
        "D12",
        ["visit_log_sgbxi"],
        f"§36 services {total / 100:.2f} € > cap {cap / 100:.2f} € (PG {grade})",
        lines,
    )


def d02_no_approval(tl: Timeline, rng: random.Random) -> None:
    rx = _main_rx(tl)
    tl.approvals = [a for a in tl.approvals if a.prescription_id != rx.id]
    lines = [r for r in _hkp_oct(tl) if rx.period_from <= r.date <= rx.period_to]
    _label(
        tl,
        "D02",
        [f"muster12:{rx.id}", "visit_log_sgbv"],
        f"No Genehmigung for the Verordnung of {rx.issue_date}",
        lines,
    )


def d03_partial(tl: Timeline, rng: random.Random) -> None:
    """The Kasse approved less than prescribed; the nurses billed the prescription."""
    rx = _main_rx(tl)
    ap = tl.approval_for(rx)
    assert ap is not None
    ap.decision = "partial"
    twice = [
        a
        for a in ap.approved
        if a.frequency and a.frequency.per == "day" and a.frequency.count >= 2
    ]
    in_period = [r for r in _hkp_oct(tl) if ap.period_from <= r.date <= ap.period_to]
    if twice and (len(ap.approved) == 1 or rng.random() < 0.5):
        item = twice[0]
        item.frequency = Frequency(count=item.frequency.count - 1, per="day")  # type: ignore[union-attr]
        seen: Counter = Counter()
        lines = []
        for r in sorted(in_period, key=lambda r: r.when):
            if r.code == item.position_no:
                seen[r.date] += 1
                if seen[r.date] > item.frequency.count:
                    lines.append(r)
        note = f"Approved {item.position_no} {item.frequency.count}x/day, billed more"
    else:
        item = ap.approved[-1]
        ap.approved.remove(item)
        tl.rejected[ap.id] = [(item.position_no, rng.choice([
            "Medizinische Notwendigkeit nicht ausreichend begründet",
            "Leistung kann durch Angehörige erbracht werden",
            "Keine Angaben zur Wundgröße und -art",
        ]))]  # fmt: skip
        lines = [r for r in in_period if r.code == item.position_no]
        note = f"Approval rejects {item.position_no}, billed anyway"
    _label(tl, "D03", [f"approval_letter:{ap.id}", "visit_log_sgbv"], note, lines)


def d10_frequency(tl: Timeline, rng: random.Random) -> None:
    """Billed more often than the Verordnung says (the approval just says 'lt. VO')."""
    rx = _main_rx(tl)
    ap = tl.approval_for(rx)
    daily = [s for s in rx.services if s.frequency and s.frequency.per == "day"]
    twice = [s for s in daily if s.frequency and s.frequency.count >= 2]
    in_period = [r for r in _hkp_oct(tl) if rx.period_from <= r.date <= rx.period_to]
    if twice:
        svc = twice[0]
        svc.frequency = Frequency(count=1, per="day")
        seen: Counter = Counter()
        lines = []
        for r in sorted(in_period, key=lambda r: r.when):
            if r.code == svc.position_no:
                seen[r.date] += 1
                if seen[r.date] > 1:
                    lines.append(r)
    else:
        svc = daily[0]
        lines = []
        for r in [r for r in in_period if r.code == svc.position_no]:
            when = dt.datetime.combine(r.date, _jitter((18, 20), rng))
            if _home(tl, when):
                extra = Rec(when, "sgbv", svc.position_no, r.staff, slot="evening")
                tl.recs.append(extra)
                lines.append(extra)
    if ap:
        for item in ap.approved:
            if item.position_no == svc.position_no:
                item.frequency = None
    _label(
        tl,
        "D10",
        [f"muster12:{rx.id}", "visit_log_sgbv"],
        f"Verordnung {svc.position_no} 1x/day, billed 2x/day",
        lines,
    )


def d07_late_submission(tl: Timeline, rng: random.Random) -> None:
    """Verordnung reached the Kasse after the 4th working day after issue."""
    rx = tl.prescriptions[0] if tl.spec.params.get("d07_first") else _main_rx(tl)
    late = tl.spec.params.get("d07_wd") or rng.choice([5, 6, 7, 9])
    rx.submitted_to_payer_at = catalog.add_working_days(rx.issue_date, late)
    ap = tl.approval_for(rx)
    if ap:
        ap.letter_date = catalog.add_working_days(rx.submitted_to_payer_at, rng.choice([3, 4, 6]))
    until = ap.letter_date if ap else MONTH_END
    lines = [r for r in _hkp_oct(tl) if rx.period_from <= r.date < until and r.date <= rx.period_to]
    _label(
        tl,
        "D07",
        [f"muster12:{rx.id}"],
        f"Issued {rx.issue_date}, reached the Kasse {rx.submitted_to_payer_at} "
        f"({late}th working day)",
        lines,
    )


def d09_unsigned(tl: Timeline, rng: random.Random) -> None:
    rx = tl.prescriptions[0] if tl.spec.params.get("d09_first") else _main_rx(tl)
    what = tl.spec.params.get("d09") or rng.choice(["signature", "stamp"])
    if what == "signature":
        rx.doctor_signed = False
    else:
        rx.stamp_present = False
    _label(tl, "D09", [f"muster12:{rx.id}"], f"Muster 12 without doctor {what}")


def d18_duplicate(tl: Timeline, rng: random.Random) -> None:
    """The second visit of a twice-daily service written with the first one's time."""
    by_day: dict[tuple[dt.date, str], list[Rec]] = {}
    for r in _hkp_oct(tl):
        by_day.setdefault((r.date, r.code), []).append(r)
    pairs = [v for v in by_day.values() if len(v) == 2]
    lines = []
    for first, second in rng.sample(pairs, min(len(pairs), rng.randint(1, 3))):
        second.when, second.staff = first.when, first.staff
        lines += [first, second]
    _label(tl, "D18", ["visit_log_sgbv"], "Same position, day and time billed twice", lines)


def d05_initials(tl: Timeline, rng: random.Random) -> None:
    candidates = [r for r in _hkp_oct(tl) if r.staff is not None]
    by_day = {}
    for r in rng.sample(candidates, len(candidates)):
        by_day.setdefault(r.date, r)
    lines = list(by_day.values())[: rng.randint(2, 5)]
    for r in lines:
        r.staff = None
    _label(tl, "D05", ["visit_log_sgbv"], "Visit entries without Handzeichen", lines)


def d16_kvnr(tl: Timeline, rng: random.Random) -> None:
    tl.record.kvnr = identifiers.corrupt_kvnr(tl.record.card_kvnr, rng)
    docs = [f"visit_log_{d}" for d in tl.domains]
    _label(
        tl,
        "D16",
        docs,
        f"Provider has KVNR {tl.record.kvnr} on file, card says {tl.record.card_kvnr}",
    )


def d04_signature(tl: Timeline, rng: random.Random) -> None:
    domain = tl.spec.params.get("d04") or rng.choice(tl.domains)
    tl.signed[domain] = False
    tl.missing_reason[domain] = None
    _label(
        tl, "D04", [f"visit_log_{domain}"], "Leistungsnachweis not signed by the patient, no reason"
    )


def d19_unreadable(tl: Timeline, rng: random.Random) -> None:
    keys = doc_keys(tl)
    used = {k for lab in tl.labels for k in lab.docs}
    key = tl.spec.params.get("d19") or rng.choice([k for k in keys if k not in used] or keys)
    tl.spec.variants[key] = "bad_photo"
    _label(tl, "D19", [key], "Photo too blurred to read")


INJECT: dict[DefectId, Callable[[Timeline, random.Random], None]] = {
    "D01": d01_early_start,
    "D02": d02_no_approval,
    "D03": d03_partial,
    "D04": d04_signature,
    "D05": d05_initials,
    "D06": d06_stay,
    "D07": d07_late_submission,
    "D08": d08_folge,
    "D09": d09_unsigned,
    "D10": d10_frequency,
    "D11": d11_long_erst,
    "D12": d12_budget,
    "D15": d15_deceased,
    "D16": d16_kvnr,
    "D18": d18_duplicate,
    "D19": d19_unreadable,
}


def build_timeline(world: World, spec: PatientSpec) -> Timeline:
    """Simulate a clean month, then inject the spec's defects in dependency order."""
    tl = simulate(world, spec)
    for defect in ORDER:
        if defect in spec.defects:
            INJECT[defect](tl, random.Random(f"{world.seed}:{spec.key}:{defect}"))
    if not tl.labels:
        _label(tl, "D20", doc_keys(tl), "Clean patient-month")
    return tl


# --- Casts --------------------------------------------------------------------------------

MED2 = ServicePlan("032101", 2, "day", ["morning", "evening"])
MED1 = ServicePlan("032101", 1, "day", ["morning"])
KOMP = ServicePlan("032130", 1, "day", ["morning"])
INJ = ServicePlan("032110", 1, "day", ["morning"])
BZ = ServicePlan("032120", 1, "day", ["morning"])
WOUND = ServicePlan("032151", 3, "week", ["noon"], weekdays=(0, 2, 4))


def _plan(*services: ServicePlan) -> list[ServicePlan]:
    """Fresh copies: timelines edit their plans."""
    return [ServicePlan(s.position_no, s.count, s.per, list(s.slots), s.weekdays) for s in services]


def _oct(day: int, hour: int, minute: int) -> dt.datetime:
    return dt.datetime(YEAR, 10, day, hour, minute)


def demo_specs() -> list[PatientSpec]:
    """5 hero patients (docs/05 §4.4) and their background, October 2026."""
    return [
        # Heroes
        PatientSpec(
            "p01", "hkp", "switch", ["D08"], hero="Frau Albers",
            sex="f", last_name="Albers", first_name="Erika", kasse="AOK", hkp=_plan(MED1, KOMP),
            params={"rx_end": dt.date(YEAR, 10, 14), "d08": "lapsed"},
            variants={"visit_log_sgbv": "scan"},
        ),
        PatientSpec(
            "p02", "hkp", "single", ["D06"], hero="Herr Brandl",
            sex="m", last_name="Brandl", first_name="Josef", kasse="TK", hkp=_plan(MED2),
            params={"stay": (_oct(12, 10, 30), _oct(16, 11, 15))},
            variants={"hospital_letter:p02-st1": "photo", "visit_log_sgbv": "photo"},
        ),
        PatientSpec(
            "p03", "hkp", "single", ["D04"], hero="Frau Christl",
            sex="f", last_name="Christl", first_name="Maria", kasse="BARMER", hkp=_plan(INJ, BZ),
            params={"d04": "sgbv"},
            variants={"visit_log_sgbv": "photo"},
        ),
        PatientSpec(
            "p04", "hkp", "new_late", ["D07", "D09"], hero="Herr Dengler",
            sex="m", last_name="Dengler", first_name="Franz", kasse="AOK", hkp=_plan(MED2),
            params={
                "care_start": dt.date(YEAR, 10, 1),
                "d07_wd": 5, "d07_first": True, "d09": "stamp", "d09_first": True,
            },
            variants={"muster12:p04-rx1": "photo"},
        ),
        PatientSpec(
            "p05", "both", "single", [], hero="Frau Eder",
            sex="f", last_name="Eder", first_name="Theresia", kasse="DAK", pflegegrad=3,
            hkp=_plan(MED1, KOMP), events=["pg_change", "stay"],
            variants={"visit_log_sgbv": "scan", "visit_log_sgbxi": "scan"},
        ),
        # Background
        PatientSpec(
            "p06", "xi", defects=["D12"], hero="Herr Fischer (second SGB XI patient)",
            sex="m", last_name="Fischer", first_name="Helmut", pflegegrad=2,
        ),
        PatientSpec("p07", "hkp", hkp=_plan(MED2), events=["kassenwechsel", "stay"]),
        PatientSpec("p08", "hkp", blank=True, hkp=_plan(WOUND)),
        PatientSpec("p09", "hkp", defects=["D03", "D05", "D18"], hkp=_plan(MED2, INJ, BZ)),
        PatientSpec("p10", "xi", events=["stay"], pflegegrad=4),
        PatientSpec("p11", "xi", defects=["D15"], pflegegrad=3),
        PatientSpec(
            "p12", "hkp", defects=["D10", "D19"], hkp=_plan(MED1),
            params={"d19": "approval_letter:p12-ap1"},
        ),
        PatientSpec("p13", "xi", defects=["D16"], pflegegrad=2),
        PatientSpec(
            "p14", "hkp", "new_late", ["D11", "D02"], hkp=_plan(KOMP),
            params={"care_start": dt.date(YEAR, 10, 8)},
        ),
    ]  # fmt: skip


def _feasible(spec: PatientSpec, defect: DefectId) -> bool:
    if defect in HKP_ONLY and spec.kind == "xi":
        return False
    if defect == "D12" and spec.kind == "hkp":
        return False
    if defect == "D19" and spec.kind == "xi":  # needs a document without other evidence
        return False
    if any({defect, d} in CONFLICTS for d in spec.defects):
        return False
    chain = CHAIN_FOR.get(defect)
    if chain and any(CHAIN_FOR.get(d, chain) != chain for d in spec.defects):
        return False
    return len(spec.defects) < MAX_DEFECTS


MAX_DEFECTS = 5


def random_specs(seed: int, n: int, quota: int, clean: int) -> list[PatientSpec]:
    """A cast of n patients where every Tier-A defect appears in at least `quota` of them.

    Greedy, most constrained defect first. Defects any patient can carry go preferably
    to SGB XI-only patients, which keeps the HKP patients free for the HKP-only ones.
    """
    rng = random.Random(f"{seed}:cast")
    n_xi, n_both = round(n * 0.22), round(n * 0.2)
    kinds = ["xi"] * n_xi + ["both"] * n_both + ["hkp"] * (n - n_xi - n_both)
    rng.shuffle(kinds)
    specs = [PatientSpec(f"p{i + 1:02d}", kind) for i, kind in enumerate(kinds)]  # type: ignore[arg-type]
    by_kind = {k: [s for s in specs if s.kind == k] for k in ("xi", "both", "hkp")}
    clean_pool = [by_kind["xi"][0], by_kind["hkp"][0], by_kind["hkp"][1], by_kind["both"][0]]
    clean_pool = clean_pool[:clean]
    by_kind["hkp"][1].blank = True  # one clean Blankoverordnung (wound care)
    by_kind["hkp"][1].hkp = _plan(WOUND)

    counts: Counter = Counter()
    for defect in ORDER:
        need = quota - counts[defect]
        candidates = [s for s in specs if s not in clean_pool and _feasible(s, defect)]
        rng.shuffle(candidates)
        bonus = 0 if defect in HKP_ONLY else 2  # load SGB XI-only patients first
        candidates.sort(key=lambda s: len(s.defects) - (bonus if s.kind == "xi" else 0))
        if len(candidates) < need:
            raise ValueError(f"cannot place {defect} {quota}x in a cast of {n}")
        for s in candidates[: max(need, 0)]:
            s.defects.append(defect)
            if chain := CHAIN_FOR.get(defect):
                s.chain = chain  # type: ignore[assignment]
            counts[defect] += 1
            if defect == "D08":
                counts["D01"] += 1
            if defect == "D10":
                s.hkp = _plan(MED1, KOMP)
            if defect in ("D18", "D03"):
                s.hkp = _plan(MED2, KOMP)

    # World events, on patients whose defects they don't disturb.
    calm = [s for s in specs if not {"D06", "D15", "D04", "D01", "D08", "D12"} & set(s.defects)]
    rng.shuffle(calm)
    next(s for s in calm if s.kind != "xi").events.append("kassenwechsel")
    next(s for s in calm if s.kind != "hkp").events.append("pg_change")
    next(s for s in calm if s.kind == "xi").events.append("death")
    for s in [s for s in calm if "death" not in s.events][:2]:
        s.events.append("stay")
    for s in by_kind["xi"]:
        s.pflegegrad = rng.choice([2, 3, 3, 4])
    return specs


def assign_names(specs: list[PatientSpec], seed: int) -> None:
    """Unique surnames per world: heroes keep theirs, everyone else draws without repeats."""
    rng = random.Random(f"{seed}:names")
    taken = {s.last_name for s in specs if s.last_name}
    pool = [n for n in catalog.SURNAMES if n not in taken]
    rng.shuffle(pool)
    for s in specs:
        if not s.last_name:
            s.last_name = pool.pop()
