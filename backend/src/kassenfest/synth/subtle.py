"""Subtle defects for the auditor eval (docs/01 AUD-05): what no rule in the pack checks.

Each one leaves the bill green on the rules, so the auditor agent attacks it. Some edit what
happened (a Verordnung issued after its period began, visit times copied for a whole month),
others what one document shows (a digit of the Genehmigungskennzeichen on the
Leistungsnachweis, the whole log in one hand). `inject` makes the timeline edits and labels
every defect while the timeline is built; `on_paper` makes the document edits once the pile is
planned. `eval.auditor` decides what counts as catching each one.
"""

import datetime as dt
import random

from kassenfest.schemas.ground_truth import DefectId
from kassenfest.synth import catalog, identifiers
from kassenfest.synth.documents import LNStaff, Muster12Content, VisitLogContent, VisitLogXIContent
from kassenfest.synth.paperwork import DocPlan
from kassenfest.synth.world import (
    MONTH_END,
    MONTH_START,
    DefectLabel,
    Rec,
    Timeline,
    World,
    visit_order,
)

SUBTLE: dict[DefectId, str] = {
    "S01": "Genehmigungskennzeichen on the Leistungsnachweis one digit off the Genehmigung",
    "S02": "Verordnung carries another person's valid Versicherten-Nr.",
    "S03": "Verordnung carries a wrong date of birth",
    "S04": "Erstverordnung issued days after its period began: retroactive",
    "S05": "Medikamentengabe prescribed without naming the Präparate",
    "S06": "Entries signed with the Handzeichen of somebody not on the staff",
    "S07": "Leistungsnachweis signed by the patient mid-month, before the later services",
    "S08": "Every visit of the month at the same minute",
    "S09": "Evening dose logged minutes after the morning dose",
    "S10": "Whole Leistungsnachweis in one hand and one pen, under several Handzeichen",
}
HKP_ONLY = {"S01", "S02", "S03", "S04", "S05", "S09"}
STRANGERS = ["KR", "HB", "SW", "EM", "RG"]
"""Handzeichen for S06: whichever the provider's staff doesn't use."""


def _main_rx(tl: Timeline):
    def overlap(rx) -> int:
        return (min(rx.period_to, MONTH_END) - max(rx.period_from, MONTH_START)).days

    return max(tl.in_month(tl.prescriptions), key=overlap)


def _domain(tl: Timeline, defect: DefectId) -> str:
    return "sgbv" if defect in HKP_ONLY or "sgbv" in tl.domains else "sgbxi"


def _label(tl: Timeline, defect: DefectId, docs: list[str], lines: list[Rec] | None = None) -> None:
    tl.labels.append(DefectLabel(defect, docs, SUBTLE[defect], lines or []))


def inject(tl: Timeline, defect: DefectId, rng: random.Random) -> None:
    """Edit what happened where the defect needs it, and label the defect."""
    domain = _domain(tl, defect)
    log = f"visit_log_{domain}"
    if defect in ("S01", "S02", "S03", "S05"):
        rx = _main_rx(tl)
        if defect == "S01":
            ap = tl.approval_for(rx)
            assert ap is not None
            _label(tl, defect, [log, f"approval_letter:{ap.id}"])
            return
        if defect == "S05":
            med = [s for s in rx.services if s.category == "medikamentengabe"]
            assert med, "S05 needs a Medikamentengabe"
            for s in med:
                s.details = None
        _label(tl, defect, [f"muster12:{rx.id}"])
    elif defect == "S04":
        erst = tl.prescriptions[0]
        assert erst.kind == "erst", "S04 needs a care start in the month (chain new_late)"
        erst.issue_date = catalog.add_working_days(erst.period_from, rng.choice([2, 3]))
        erst.submitted_to_payer_at = catalog.add_working_days(erst.issue_date, 1)
        ap = tl.approval_for(erst)
        if ap is not None:
            ap.letter_date = catalog.add_working_days(erst.submitted_to_payer_at, 3)
        before = [r for r in tl.october_of("sgbv") if r.date < erst.issue_date]
        _label(tl, defect, [f"muster12:{erst.id}", log], before)
    elif defect == "S06":
        recs = tl.october_of(domain)  # type: ignore[arg-type]
        by_day: dict[dt.date, Rec] = {}
        for r in rng.sample(recs, len(recs)):
            by_day.setdefault(r.date, r)
        chosen = list(by_day.values())[: rng.randint(3, 5)]
        if domain == "sgbxi":  # one Handzeichen per Einsatz: all its LK
            visits = {(r.date, r.einsatz) for r in chosen}
            chosen = [r for r in recs if (r.date, r.einsatz) in visits]
        _label(tl, defect, [log], chosen)
    elif defect == "S08":
        first: dict[tuple, dt.time] = {}
        for r in tl.october_of(domain):  # type: ignore[arg-type]
            key = (r.code, r.slot) if domain == "sgbv" else (r.einsatz,)
            first.setdefault(key, r.when.time())
            r.when = dt.datetime.combine(r.date, first[key])
        _label(tl, defect, [log])
    elif defect == "S09":
        pairs: dict[dt.date, list[Rec]] = {}
        for r in tl.october_of("sgbv"):
            if r.code == "032101":
                pairs.setdefault(r.date, []).append(r)
        twice = [v for v in pairs.values() if len(v) == 2]
        assert twice, "S09 needs a twice-daily Medikamentengabe"
        moved = []
        for morning, evening in rng.sample(twice, min(len(twice), rng.randint(6, 9))):
            evening.when = morning.when + dt.timedelta(minutes=rng.randint(4, 14))
            moved.append(evening)
        _label(tl, defect, [log], moved)
    else:  # S07, S10: only the paper changes
        _label(tl, defect, [log])


def _other_digit(ref: str, rng: random.Random) -> str:
    """One digit of the reference's number changed."""
    digits = [i for i, ch in enumerate(ref) if ch.isdigit()][-6:]
    i = rng.choice(digits)
    new = rng.choice([d for d in "0123456789" if d != ref[i]])
    return ref[:i] + new + ref[i + 1 :]


def _other_dob(dob: dt.date, rng: random.Random) -> dt.date:
    """Day digits swapped where that gives another valid date, else a year off."""
    swapped = f"{dob.day:02d}"[::-1]
    try:
        if swapped[0] != swapped[1]:
            return dob.replace(day=int(swapped))
    except ValueError:
        pass
    return dob.replace(year=dob.year + rng.choice([-1, 1]))


def on_paper(plans: list[DocPlan], tl: Timeline, world: World) -> None:
    """Make the document edits of the timeline's subtle defects."""
    by_key = {p.key: p.content for p in plans}
    for label in tl.labels:
        if label.defect not in SUBTLE:
            continue
        rng = random.Random(f"{world.seed}:{tl.record.id}:{label.defect}:paper")
        doc = by_key[label.docs[0]]
        match label.defect:
            case "S01":
                assert isinstance(doc, VisitLogContent) and doc.approval_ref
                doc.approval_ref = _other_digit(doc.approval_ref, rng)
            case "S02":
                assert isinstance(doc, Muster12Content)
                doc.kvnr = identifiers.generate_kvnr(rng)
            case "S03":
                assert isinstance(doc, Muster12Content)
                doc.patient_dob = _other_dob(doc.patient_dob, rng)
            case "S06":
                assert isinstance(doc, VisitLogContent | VisitLogXIContent)
                taken = {s.initials for s in world.staff}
                stranger = next(i for i in STRANGERS if i not in taken)
                doc.staff.append(
                    LNStaff(initials=stranger, employee_no=identifiers.generate_employee_no(rng))
                )
                _sign_as(doc, tl, label.lines, len(doc.staff) - 1)
            case "S07":
                assert isinstance(doc, VisitLogContent | VisitLogXIContent)
                doc.patient_signature_date = MONTH_START + dt.timedelta(days=rng.randint(10, 16))
            case "S10":
                assert isinstance(doc, VisitLogContent | VisitLogXIContent)
                doc.one_hand = True


def _sign_as(
    doc: VisitLogContent | VisitLogXIContent, tl: Timeline, lines: list[Rec], staff: int
) -> None:
    """Point the visits of these services at another Handzeichen."""
    if isinstance(doc, VisitLogContent):
        order = visit_order(tl, "sgbv")
        wanted = {id(r) for r in lines}
        for visit, r in zip(doc.visits, order, strict=True):
            if id(r) in wanted:
                visit.staff = staff
        return
    keys = {(r.date.day, r.einsatz or 0) for r in lines}
    for visit in doc.visits:
        if (visit.day, visit.einsatz) in keys:
            visit.staff = staff
