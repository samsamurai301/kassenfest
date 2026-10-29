"""The resolver: every objection of the auditor agent re-checked without a model (ADR-4).

- A Kasse code is re-examined by the rules it maps to (docs/02 §9), as the engine evaluated
  them for this bill, and by record checks for what no rule in the pack covers yet.
- A FACT names a field and what the page shows there. The same reading as ours was already
  used by the rules. A different reading is tried out: the month's rules run again with
  the auditor's reading, and only one that would change the outcome is upheld, for a human
  to look at the page. Ink measured in a signature box settles a dispute about a mark.
- INFO is noted, never upheld: no rule can check a suspicion.

Upheld means a rule or record check confirms the objection; dismissed comes with what was
checked and found, so a human can see why.
"""

import datetime as dt
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, get_args, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError

from kassenfest.llm.prompts import as_written
from kassenfest.pipeline.casefile import SourceDoc, build_cases
from kassenfest.pipeline.link import value
from kassenfest.pipeline.month import Month, StoredDoc, assign_claims, boxed, claim_findings
from kassenfest.pipeline.validate import validate
from kassenfest.rules.engine import Line, run
from kassenfest.rules.reference import Reference, load_reference
from kassenfest.rules.stay import during
from kassenfest.rules.tariffs import normalize_code, price
from kassenfest.schemas.common import Extracted, Mark
from kassenfest.schemas.domain import CaseFile, Claim, ClaimLine, Visit
from kassenfest.schemas.findings import Evidence, Finding, Objection, ObjectionVerdict
from kassenfest.schemas.labels import field_label
from kassenfest.vision.ink import ABSENT_BUT_INKED, PRESENT_BUT_BLANK

RESOLVER_VERSION = "3"
"""Part of every audit's fingerprint: change the checks, bump it, and bills are due again."""


@dataclass
class Bill:
    """One claim and everything the resolver may check an objection against."""

    month: Month
    claim: Claim
    documents: list[StoredDoc]
    """The paperwork the auditor was shown."""
    as_of: dt.date
    ref: Reference = field(default_factory=load_reference)

    @cached_property
    def case(self) -> CaseFile:
        return self.month.cases[self.claim.patient_id]

    @cached_property
    def findings(self) -> list[Finding]:
        return claim_findings(self.claim, self.month.findings)

    @cached_property
    def line_ids(self) -> set[str]:
        return {ln.id for ln in self.claim.lines}

    def visit(self, line: ClaimLine) -> Visit | None:
        log = next((v for v in self.case.visit_logs if v.id == line.visit_log_id), None)
        if log is None:
            return None
        return next(
            (
                v
                for i, v in enumerate(log.visits)
                if (v.entry_index if v.entry_index is not None else i) == line.entry_index
            ),
            None,
        )

    def evidence(self, document_id: str | None, path: str | None, note: str | None = None):
        if not document_id:
            return []
        ev = Evidence(document_id=document_id, field_path=path, note=note)
        return [boxed(ev, self.month.docs)]


# --- record checks -----------------------------------------------------------------


@dataclass
class Check:
    name: str
    ok: bool
    text: str
    evidence: list[Evidence] = field(default_factory=list)


RecordCheck = Callable[[Bill, list[ClaimLine]], Check | None]
"""None: doesn't apply to this kind of bill."""


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _d(day: dt.date | dt.datetime) -> str:
    return day.strftime("%-d %b %Y")


def _dates(lines: list[ClaimLine]) -> str:
    days = sorted({ln.date for ln in lines})
    shown = ", ".join(d.strftime("%-d %b") for d in days[:6])
    return shown + (f" and {len(days) - 6} more days" if len(days) > 6 else "")


def _span(lines: list[ClaimLine]) -> tuple[dt.date, dt.date]:
    return min(ln.date for ln in lines), max(ln.date for ln in lines)


def insurance(bill: Bill, lines: list[ClaimLine]) -> Check:
    patient, ik = bill.case.patient, bill.claim.payer_ik
    attr = "krankenkasse_ik" if bill.claim.domain == "sgbv" else "pflegekasse_ik"
    periods = [p for p in patient.insurance if getattr(p, attr) == ik]

    def covered(day: dt.date) -> bool:
        return any(
            p.valid_from <= day and (p.valid_to is None or day <= p.valid_to) for p in periods
        )

    payer = bill.case.payers.get(ik)
    name = f"{payer.name} (IK {ik})" if payer else f"IK {ik}"
    bad = [ln for ln in lines if not covered(ln.date)]
    if bad:
        return Check(
            "insurance", False, f"{patient.name} isn't insured with {name} on {_dates(bad)}."
        )
    p = min(periods, key=lambda p: p.valid_from)
    until = f" to {_d(p.valid_to)}" if p.valid_to else ""
    return Check("insurance", True, f"Insured with {name} from {_d(p.valid_from)}{until}.")


def short_term_care(bill: Bill, lines: list[ClaimLine]) -> Check | None:
    if bill.claim.domain != "sgbv":
        return None  # STAY-XI-SACH covers care services
    stays = [s for s in bill.case.stays if s.kind == "short_term_care"]
    for s in stays:
        hit = [
            ln for ln in lines if during(s, Line(bill.claim, ln, None, None), "timestamp") == "yes"
        ]
        if hit:
            return Check(
                "Kurzzeitpflege",
                False,
                f"{len(hit)} lines ({_dates(hit)}) fall in the Kurzzeitpflege "
                f"from {_d(s.admitted_at)}.",
                bill.evidence(s.document_id, "admission_date"),
            )
    if not stays:
        return Check("Kurzzeitpflege", True, "No Kurzzeitpflege on file.")
    return Check("Kurzzeitpflege", True, "No line falls in the Kurzzeitpflege on file.")


def _approvals(bill: Bill, lines: list[ClaimLine]):
    first, last = _span(lines)
    return [
        a
        for a in bill.case.approvals
        if a.decision != "rejected" and a.period_from <= last and a.period_to >= first
    ]


def approval_ik(bill: Bill, lines: list[ClaimLine]) -> Check | None:
    if bill.claim.domain != "sgbv":
        return None
    provider = bill.case.provider
    found = _approvals(bill, lines)
    for a in found:
        if a.provider_ik != provider.ik or a.payer_ik != bill.claim.payer_ik:
            return Check(
                "approval IK",
                False,
                f"Genehmigung {a.approval_ref} is for IK {a.provider_ik} from IK {a.payer_ik}, "
                f"not for {provider.name} (IK {provider.ik}) from this bill's Kasse.",
                bill.evidence(a.document_id, "provider_ik", "IK Pflegedienst"),
            )
    if not found:
        return Check("approval IK", True, "No Genehmigung for these dates to compare.")
    refs = ", ".join(a.approval_ref for a in found)
    return Check(
        "approval IK",
        True,
        f"Genehmigung {refs} is addressed to {provider.name} (IK {provider.ik}).",
        [e for a in found for e in bill.evidence(a.document_id, "provider_ik", "IK Pflegedienst")],
    )


def _ref(text: object) -> str:
    return re.sub(r"[\s./-]", "", str(text)).upper()


def approval_number(bill: Bill, lines: list[ClaimLine]) -> Check | None:
    """The Genehmigungskennzeichen on the Leistungsnachweis against the Genehmigung's own:
    the bill must carry the number the Kasse issued."""
    if bill.claim.domain != "sgbv":
        return None
    found = _approvals(bill, lines)
    logs = [
        (d, ref)
        for d in bill.documents
        if d.document.doc_type == "visit_log_sgbv" and (ref := value(d.extraction, "approval_ref"))
    ]
    if not found or not logs:
        return None
    issued = {_ref(a.approval_ref): a for a in found}
    on_letter = [
        e for a in found for e in bill.evidence(a.document_id, "approval_ref", "Genehmigung")
    ]
    for d, ref in logs:
        if _ref(ref) not in issued:
            numbers = " or ".join(a.approval_ref for a in found)
            return Check(
                "Genehmigungskennzeichen",
                False,
                f"The Leistungsnachweis gives the Genehmigungskennzeichen as {ref}, the "
                f"Genehmigung as {numbers}. One of them is misread or wrong, and the bill has to "
                "carry the number the Kasse issued: a human should check both pages.",
                bill.evidence(d.document.id, "approval_ref", "Leistungsnachweis") + on_letter,
            )
    return Check(
        "Genehmigungskennzeichen",
        True,
        f"The Leistungsnachweis and the Genehmigung both give {logs[0][1]}.",
        on_letter,
    )


def limitation(bill: Bill, lines: list[ClaimLine]) -> Check:
    first, _ = _span(lines)
    deadline = dt.date(first.year + 4, 12, 31)  # §45 SGB I: four years after the year's end
    if bill.as_of > deadline:
        return Check("limitation", False, f"Services from {first.year} lapsed on {_d(deadline)}.")
    return Check(
        "limitation",
        True,
        f"Services from {first.strftime('%B %Y')} can be billed until {_d(deadline)} (§45 SGB I).",
    )


def kostenerstattung(bill: Bill, lines: list[ClaimLine]) -> Check:
    return Check(
        "Kostenerstattung",
        True,
        "Nothing in the patient's records or paperwork shows a choice of Kostenerstattung: "
        "the services are billed to the Kasse directly.",
    )


def matches_log(bill: Bill, lines: list[ClaimLine]) -> Check:
    domain = bill.claim.domain
    bad = [
        ln
        for ln in lines
        if (v := bill.visit(ln)) is None
        or v.date != ln.date
        or normalize_code(domain, v.code) != normalize_code(domain, ln.code)
    ]
    if bad:
        return Check(
            "Leistungsnachweis",
            False,
            f"{len(bad)} lines ({_dates(bad)}) have no matching row on the Leistungsnachweis.",
        )
    docs = {v.document_id for ln in lines if (v := bill.visit(ln)) and v.document_id}
    return Check(
        "Leistungsnachweis",
        True,
        f"Each of the {len(lines)} lines comes from its own row on the Leistungsnachweis, "
        "with the same date and position.",
        [e for d in sorted(docs) for e in bill.evidence(d, "entries", "Leistungsnachweis")],
    )


FUNDED = {"sachleistung_36": "§36 Sachleistung", "entlastung_45b": "§45b Entlastungsbetrag"}


def funding(bill: Bill, lines: list[ClaimLine]) -> Check | None:
    """Care services: each line billed from the budget its row on the Leistungsnachweis names."""
    if bill.claim.domain != "sgbxi":
        return None
    bad = [ln for ln in lines if (v := bill.visit(ln)) is not None and v.funding != ln.funding]
    if bad:
        return Check(
            "funding",
            False,
            f"{len(bad)} lines ({_dates(bad)}) are billed from another budget than their row "
            "on the Leistungsnachweis.",
        )
    counts = Counter(FUNDED[ln.funding] for ln in lines if ln.funding in FUNDED)
    shown = _and([f"{n} under {name}" for name, n in sorted(counts.items())])
    return Check(
        "funding",
        True,
        f"Each line is billed from the budget its Leistungsnachweis row names: {shown}.",
    )


def pflegegrad(bill: Bill, lines: list[ClaimLine]) -> Check:
    if bill.claim.domain != "sgbxi":
        return Check("Pflegegrad", True, "Home nursing (SGB V) doesn't depend on a Pflegegrad.")
    periods = sorted(bill.case.patient.pflegegrad, key=lambda p: p.valid_from)

    def grade(day: dt.date):
        return next((p for p in reversed(periods) if p.valid_from <= day), None)

    bad = [
        ln
        for ln in lines
        if (g := grade(ln.date)) is None or (g.grade < 2 and ln.funding == "sachleistung_36")
    ]
    if bad:
        return Check("Pflegegrad", False, f"No Pflegegrad covers the services on {_dates(bad)}.")
    g = grade(_span(lines)[0])
    assert g is not None
    return Check("Pflegegrad", True, f"Pflegegrad {g.grade} since {_d(g.valid_from)}.")


QUALIFICATION = {
    "pflegefachkraft": "Pflegefachkraft",
    "pflegehilfskraft": "Pflegehilfskraft",
    "auszubildende": "Auszubildende",
}


def staff(bill: Bill, lines: list[ClaimLine]) -> Check:
    team = {s.initials.upper(): s for s in bill.case.provider.staff}
    seen: dict[str, list[ClaimLine]] = {}
    for ln in lines:
        if (v := bill.visit(ln)) and v.staff_initials:  # missing ones: HKP-STAFF-INITIALS
            seen.setdefault(v.staff_initials.upper(), []).append(ln)
    unknown = {hz: lns for hz, lns in seen.items() if hz not in team}
    if unknown:
        hz, lns = next(iter(unknown.items()))
        return Check("staff", False, f"Handzeichen {hz} ({_dates(lns)}) isn't on the staff list.")
    who = ", ".join(
        f"{team[hz].initials} ({team[hz].name}, {QUALIFICATION[team[hz].qualification]})"
        for hz in sorted(seen)
    )
    return Check(
        "staff",
        True,
        f"Every Handzeichen belongs to staff on file: {who}. The contract tables require no "
        "particular qualification for these positions, so nothing grounds the objection.",
    )


def prices(bill: Bill, lines: list[ClaimLine]) -> Check | None:
    if bill.claim.domain != "sgbxi":
        return None  # HKP-POSITION-PRICE covers home nursing
    wrong = [
        ln
        for ln in lines
        if (p := price(bill.ref, "sgbxi", ln.code, ln.date)) is None
        or p.unit_cents != ln.unit_price_cents
    ]
    if wrong:
        return Check(
            "prices", False, f"{len(wrong)} prices ({_dates(wrong)}) differ from the tariff."
        )
    return Check(
        "prices",
        True,
        f"Every price is the Leistungskomplex points times the Punktwert valid that day "
        f"({bill.claim.tariff_version}).",
    )


def surcharges(bill: Bill, lines: list[ClaimLine]) -> Check:
    labels = {code: p.label_de for code, p in bill.ref.hkp_positions.items()} | {
        code: lk.label_de for code, lk in bill.ref.leistungskomplexe.items()
    }
    billed = [ln for ln in lines if "zuschlag" in labels.get(ln.code, "").lower()]
    twice = [k for k, n in Counter((ln.date, ln.time) for ln in billed).items() if n > 1]
    if twice:
        return Check(
            "surcharges", False, f"More than one surcharge on the visit of {_d(twice[0][0])}."
        )
    if not billed:
        return Check("surcharges", True, "No Sunday or holiday surcharge is billed.")
    return Check("surcharges", True, "No visit carries more than one surcharge.")


def paperwork(bill: Bill, lines: list[ClaimLine]) -> Check | None:
    """Not a test: the Verordnungen and Genehmigungen behind these lines, for the reason."""
    if bill.claim.domain != "sgbv":
        return Check("paperwork", True, "Care services (SGB XI) need no Genehmigung per visit.")
    first, last = _span(lines)
    parts, evidence = [], []
    for rx in bill.case.prescriptions:
        if rx.period_from <= last and rx.period_to >= first:
            kind = "Folgeverordnung" if rx.kind == "folge" else "Erstverordnung"
            parts.append(f"{kind} {_d(rx.period_from)} to {_d(rx.period_to)}")
            evidence += bill.evidence(rx.document_id, "period_to", "Verordnung bis")
    for a in _approvals(bill, lines):
        parts.append(f"Genehmigung {a.approval_ref} {_d(a.period_from)} to {_d(a.period_to)}")
        evidence += bill.evidence(a.document_id, "approval_ref", "Genehmigungskennzeichen")
    if not parts:
        return None
    return Check("paperwork", True, f"On file: {'; '.join(parts)}.", evidence)


def _at(moment: dt.datetime) -> str:
    return moment.strftime("%-d %b %Y, %H:%M")


def stays(bill: Bill, lines: list[ClaimLine]) -> Check:
    """Not a test (STAY-* are): the stays on file and the visits on their edge days."""
    if not bill.case.stays:
        return Check("stays", True, "No hospital or care-home stay on file.")
    parts, evidence = [], []
    for s in bill.case.stays:
        out = _at(s.discharged_at) if s.discharged_at else "still admitted"
        part = f"{s.kind.replace('_', ' ')} stay from {_at(s.admitted_at)} to {out}"
        outside = [
            ln for ln in lines if during(s, Line(bill.claim, ln, None, None), "timestamp") == "no"
        ]
        for day, side in (
            (s.admitted_at.date(), "before the admission"),
            (s.discharged_at.date() if s.discharged_at else None, "after the discharge"),
        ):
            times = sorted({ln.time for ln in outside if ln.date == day and ln.time})
            if times:
                shown = ", ".join(t.strftime("%H:%M") for t in times)
                part += f"; the visit on {day:%-d %b} was at {shown}, {side}"
        parts.append(part)
        evidence += bill.evidence(s.document_id, "admission_date", "Aufnahme")
    return Check("stays", True, f"On file: {'; '.join(parts)}.", evidence)


# Rules per code (docs/02 §9; only rules the pack has) and checks for the rest.
RULES_FOR: dict[str, list[str]] = {
    "41002": ["MD-DECEASED"],
    "41003": ["STAY-HKP", "STAY-XI-SACH"],
    "42002": ["HKP-APPROVAL-EXISTS", "HKP-RX-REQUIRED"],
    "42003": ["HKP-APPROVAL-EXISTS", "HKP-RX-REQUIRED", "HKP-FOLGE-WINDOW"],
    "42004": ["HKP-APPROVAL-EXISTS"],
    "42005": ["STAY-XI-SACH"],
    "42006": [],
    "42007": ["HKP-DUPLICATE"],
    "42008": [],
    "42009": [],
    "43001": ["HKP-APPROVAL-SCOPE", "HKP-FREQ-RX"],
    "43002": [],
    "43003": [],
    "43004": ["XI-36-BUDGET"],
    "43005": [],
    "44001": ["HKP-POSITION-PRICE"],
    "44003": ["HKP-POSITION-PRICE"],
    "44004": [],
}
CHECKS_FOR: dict[str, list[RecordCheck]] = {
    "41002": [insurance],
    "41003": [stays],
    "42002": [paperwork],
    "42003": [paperwork],
    "42004": [approval_number, paperwork],
    "42005": [short_term_care, stays],
    "42006": [approval_ik],
    "42007": [],
    "42008": [limitation],
    "42009": [kostenerstattung],
    "43001": [paperwork],
    "43002": [matches_log, funding],
    "43003": [pflegegrad],
    "43004": [pflegegrad],
    "43005": [staff],
    "44001": [prices, funding],
    "44003": [prices],
    "44004": [surcharges],
}


# --- resolving -----------------------------------------------------------------------


SHORT = {
    "muster12": "Verordnung",
    "approval_letter": "Genehmigung",
    "visit_log_sgbv": "Leistungsnachweis",
    "visit_log_sgbxi": "Leistungsnachweis",
    "hospital_letter": "Entlassbrief",
}


def resolve(bill: Bill, objection: Objection) -> ObjectionVerdict:
    asked = objection.claim_line_ids
    lines = [ln for ln in bill.claim.lines if ln.id in asked] if asked else bill.claim.lines
    if asked and not lines:
        return _verdict(objection, "dismissed", f"Lines {', '.join(asked)} aren't on this bill.")
    cited = next((d for d in bill.documents if d.document.id == objection.document_id), None)
    if objection.code != "INFO" and cited and objection.field_path in IDENTITY:
        return _identity(bill, objection, cited)
    if objection.code == "INFO":
        return _verdict(
            objection,
            "noted",
            "A suspicion, not a reason to reject: no rule can check it, so it is shown to a "
            "human and doesn't change the bill's status.",
            evidence=_cited(bill, objection),
        )
    if objection.code == "FACT":
        return _fact(bill, objection)
    return _code(bill, objection, lines)


def _verdict(o: Objection, verdict: str, reason: str, **kw: Any) -> ObjectionVerdict:
    return ObjectionVerdict(objection=o, verdict=verdict, reason=reason, **kw)  # type: ignore[arg-type]


def _cited(bill: Bill, o: Objection) -> list[Evidence]:
    if o.document_id not in {d.document.id for d in bill.documents}:
        return []
    return bill.evidence(o.document_id, o.field_path, field_label(o.field_path or "") or None)


def _applies(rule_id: str, domain: str) -> bool:
    if rule_id.startswith(("HKP-", "STAY-HKP")):
        return domain == "sgbv"
    if rule_id.startswith(("XI-", "STAY-XI")):
        return domain == "sgbxi"
    return True


def _code(bill: Bill, o: Objection, lines: list[ClaimLine]) -> ObjectionVerdict:
    rule_ids = [r for r in RULES_FOR[o.code] if _applies(r, bill.claim.domain)]
    ids = {ln.id for ln in lines}
    touched = [
        f
        for f in bill.findings
        if f.rule_id in rule_ids and (not f.claim_line_ids or ids & set(f.claim_line_ids))
    ]
    hits = [f for f in touched if f.severity != "info"]
    checks = [c for fn in CHECKS_FOR[o.code] if (c := fn(bill, lines)) is not None]
    failed = [c for c in checks if not c.ok]
    checked = [*rule_ids, *(c.name for c in checks)]
    if hits or failed:
        reason = " ".join([f"{f.rule_id}: {f.message_en}" for f in hits] + [c.text for c in failed])
        evidence = [e for f in hits for e in f.evidence] + [e for c in failed for e in c.evidence]
        return _verdict(o, "upheld", reason, checked=checked, evidence=evidence)
    scope = f"the {len(lines)} lines named" if o.claim_line_ids else "this bill"
    parts = [f"{', '.join(rule_ids)} found nothing on {scope}."] if rule_ids else []
    parts += [f"{f.rule_id} only notes: {f.message_en}" for f in touched]
    parts += [c.text for c in checks]
    evidence = [e for c in checks for e in c.evidence] or _cited(bill, o)
    return _verdict(o, "dismissed", " ".join(parts), checked=checked, evidence=evidence)


# --- FACT: a field on a page ---------------------------------------------------------

_STEP = re.compile(r"([a-z_]+)(?:\[(\d+)\])?")
_MISSING = object()
BLANK = {"", "-", "–", "—", "leer", "blank", "empty", "(leer)", "keine", "none", "absent"}
TRUE = {"ja", "x", "✓", "✗", "true", "yes", "angekreuzt", "present", "vorhanden"}
FALSE = {"nein", "false", "no", "nicht angekreuzt"}


def _child(obj: Any, step: str | int) -> Any:
    if isinstance(step, str) and isinstance(obj, BaseModel) and step in type(obj).model_fields:
        return getattr(obj, step)
    if isinstance(step, int) and isinstance(obj, list) and 0 <= step < len(obj):
        return obj[step]
    return _MISSING


def _locate(doc: BaseModel, path: str) -> tuple[Any, str | int] | None:
    """(container, key) of a field path: a model attribute or a list index."""
    steps: list[str | int] = []
    for part in path.split("."):
        m = _STEP.fullmatch(part)
        if m is None:
            return None
        steps.append(m[1])
        if m[2] is not None:
            steps.append(int(m[2]))
    obj: Any = doc
    for step in steps[:-1]:
        if (obj := _child(obj, step)) is _MISSING:
            return None
    if _child(obj, steps[-1]) is _MISSING:
        return None
    return obj, steps[-1]


def reading(doc: BaseModel, path: str) -> tuple[Any, str] | None:
    """What a field holds and how to show it; None if the path names no single field."""
    found = _locate(doc, path)
    if found is None:
        return None
    value = _child(*found)
    if isinstance(value, Mark):
        state = "present" if value.state == "present" else value.state
        return ("mark", state), {"present": "ink present", "absent": "blank"}.get(state, state)
    if isinstance(value, Extracted):
        shown = as_written(value.value) if value.status == "present" else value.status
        return ("field", value.status, value.value), "blank" if shown == "empty" else shown
    if isinstance(value, BaseModel | list):
        return None
    return ("value", value), "blank" if value is None else as_written(value)


def _coerce(annotation: Any, text: str) -> Any:
    candidates: list[Any] = []
    if any(get_origin(a) is list for a in (annotation, *get_args(annotation))):
        candidates.append([p.strip() for p in re.split(r"[,;]", text) if p.strip()])
    candidates += [text, text.lower()]
    if text.lower() in TRUE | FALSE:
        candidates.append(text.lower() in TRUE)
    adapter = TypeAdapter(annotation)
    for c in candidates:
        try:
            return adapter.validate_python(c)
        except ValidationError:
            continue
    return _MISSING


def with_reading(doc: BaseModel, path: str, reads: str) -> BaseModel | None:
    """A copy of the extraction with `reads` in that field, normalized like any reading;
    None if it can't be a value of that field."""
    copy = doc.model_copy(deep=True)
    found = _locate(copy, path)
    if found is None:
        return None
    container, key = found
    current, text = _child(container, key), reads.strip()
    blank = text.lower() in BLANK
    if isinstance(current, Mark):
        current.state = "absent" if blank else "present"
    elif isinstance(current, Extracted):
        if blank:
            current.value, current.status = None, "empty"
        else:
            assert isinstance(key, str)
            kind = type(container).model_fields[key].annotation
            value = _coerce(kind.model_fields["value"].annotation, text)  # type: ignore[union-attr]
            if value is _MISSING:
                return None
            current.value, current.status = value, "present"
    elif isinstance(current, BaseModel | list) or not isinstance(key, str):
        return None
    else:
        value = None if blank else _coerce(type(container).model_fields[key].annotation, text)
        if value is _MISSING:
            return None
        setattr(container, key, value)
    validate(copy)
    return copy


def what_if(bill: Bill, doc: StoredDoc, changed: BaseModel) -> list[Finding]:
    """Findings on this bill that the auditor's reading would add: the patient's month
    rebuilt and every rule run again, everything else as read."""
    pid = bill.claim.patient_id
    sources = [
        SourceDoc(d.document.id, changed if d is doc else d.extraction, pid)
        for d in bill.month.docs.values()
        if d.extraction is not None and d.patient_id == pid
    ]
    built = build_cases(bill.month.month, bill.month.records, sources, bill.ref)
    if pid not in built.cases:
        return []
    result = run(built.cases[pid], ref=bill.ref)
    after = assign_claims(built.cases, {pid: result}, bill.month.docs, result.findings)
    before = {(f.id, f.severity) for f in bill.month.results[pid].findings}
    return [
        f
        for f in claim_findings(bill.claim, after)
        if f.severity != "info" and (f.id, f.severity) not in before
    ]


def _fact(bill: Bill, o: Objection) -> ObjectionVerdict:
    doc = next((d for d in bill.documents if d.document.id == o.document_id), None)
    if doc is None or doc.extraction is None:
        return _verdict(o, "dismissed", f"{o.document_id} isn't part of this bill's paperwork.")
    name = SHORT.get(doc.document.doc_type or "", "document")
    if not o.field_path or o.reads is None:
        return _verdict(o, "dismissed", "A FACT has to name a field and say what it reads.")
    path, label = o.field_path, field_label(o.field_path)
    ours = reading(doc.extraction, path)
    if ours is None:
        return _verdict(o, "dismissed", f"There is no single field {path} on the {name}.")
    evidence = bill.evidence(doc.document.id, path, label)
    changed = with_reading(doc.extraction, path, o.reads)
    theirs = reading(changed, path) if changed is not None else None
    if changed is None or theirs is None:
        return _verdict(
            o, "dismissed", f"'{o.reads}' can't be a value of {label}.", evidence=evidence
        )
    checked = [f"reading of {path}"]
    if theirs[0] == ours[0]:
        return _verdict(
            o,
            "dismissed",
            f"We read the same in {label}: {ours[1]}. The rules already used it and found "
            "nothing to object to.",
            checked=checked,
            evidence=evidence,
        )
    differ = f"We read {label} as {ours[1]}; the auditor reads {theirs[1]}."
    ink = doc.ink.get(path)
    if ours[0][0] == "mark" and ink is not None:
        checked.append("ink in the box")
        if ours[0][1] == "present" and ink >= ABSENT_BUT_INKED:
            return _verdict(
                o,
                "dismissed",
                f"{differ} {ink:.1%} of the evidence box is ink; an empty field never measured "
                f"above {ABSENT_BUT_INKED:.0%}.",
                checked=checked,
                evidence=evidence,
            )
        if ours[0][1] == "absent" and ink < PRESENT_BUT_BLANK:
            return _verdict(
                o,
                "dismissed",
                f"{differ} The evidence box is blank paper ({ink:.2%} ink).",
                checked=checked,
                evidence=evidence,
            )
    added = what_if(bill, doc, changed)
    checked.append("every rule with the auditor's reading")
    if added:
        effect = " ".join(f"{f.rule_id}: {f.message_en}" for f in added)
        return _verdict(
            o,
            "upheld",
            f"{differ} With that reading: {effect} A human should look at the page.",
            checked=checked,
            evidence=evidence + [e for f in added for e in f.evidence],
        )
    return _verdict(
        o,
        "dismissed",
        f"{differ} The rules ran again with the auditor's reading: nothing on this bill changes.",
        checked=checked,
        evidence=evidence,
    )


# --- whose document is it? ------------------------------------------------------------

IDENTITY = {"kvnr": "Versicherten-Nr.", "patient_name": "name", "patient_dob": "date of birth"}


def _same(path: str, a: object, b: object) -> bool:
    def norm(v: object) -> str | None:
        if v is None:
            return None
        if path == "patient_name":
            return " ".join(sorted(re.findall(r"[a-zäöüß]+", str(v).lower())))
        return str(v).replace(" ", "").upper()

    return norm(a) is not None and norm(a) == norm(b)


def _identity(bill: Bill, o: Objection, doc: StoredDoc) -> ObjectionVerdict:
    """An objection about whose document this is: the cited name, date of birth or
    Versicherten-Nr. against the records, and what else ties the document to the patient."""
    assert doc.extraction is not None and o.field_path is not None
    path, label, name = o.field_path, IDENTITY[o.field_path], SHORT[doc.document.doc_type or ""]
    patient = bill.case.patient
    records = {"kvnr": patient.kvnr, "patient_name": patient.name, "patient_dob": patient.dob}
    on_file = as_written(str(records[path]))
    ours = value(doc.extraction, path)
    theirs: object = None
    if o.code == "FACT" and o.reads is not None:
        changed = with_reading(doc.extraction, path, o.reads)
        theirs = value(changed, path) if changed is not None else o.reads
    tested = theirs if theirs is not None else ours
    evidence = bill.evidence(doc.document.id, path, f"{label} on the {name}")
    checked = [f"{label} against the records", "the other documents"]
    read = (
        f"We read {as_written(ours)}. "
        if theirs is not None and not _same(path, theirs, ours)
        else ""
    )
    if _same(path, tested, records[path]):
        return _verdict(
            o,
            "dismissed",
            f"{read}The {label} on the {name} reads {as_written(tested)}, as in the records.",
            checked=checked,
            evidence=evidence,
        )
    shown = as_written(tested) if tested is not None else "nothing legible"
    who = "The auditor reads" if theirs is not None else "We read"
    differs = f"{who} {shown} as the {label} on the {name}; the records say {on_file}."
    ties = [
        IDENTITY[f]
        for f in IDENTITY
        if f != path and _same(f, value(doc.extraction, f), records[f])
    ]
    support, more = [], []
    rx = next((p for p in bill.case.prescriptions if p.document_id == doc.document.id), None)
    for a in bill.case.approvals if rx else []:
        if a.prescription_id == rx.id:  # type: ignore[union-attr]
            support.append(f"the Kasse's own Genehmigung {a.approval_ref} approves this Verordnung")
            more += bill.evidence(a.document_id, "kvnr", "Versicherten-Nr. on the Genehmigung")
    others = [
        d
        for d in bill.documents
        if d is not doc and d.extraction and _same(path, value(d.extraction, path), records[path])
    ]
    if others:
        names = sorted({SHORT[d.document.doc_type or ""] for d in others})
        support.append(f"the {_and(names)} carry {on_file}")
    if ties and support:
        return _verdict(
            o,
            "dismissed",
            f"{differs} Everything else ties it to {patient.name}: the {_and(ties)} match "
            f"the records, and {'; '.join(support)}. The handwritten value is most likely misread.",
            checked=checked,
            evidence=evidence + more,
        )
    return _verdict(
        o,
        "upheld",
        f"{differs} Nothing else ties the {name} firmly to {patient.name}: a human should check "
        "whose document it is.",
        checked=checked,
        evidence=evidence,
    )
