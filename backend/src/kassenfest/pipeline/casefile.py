"""Extractions + the Pflegedienst's records → one CaseFile per patient for the month.

The rules engine evaluates CaseFiles whoever built them: the synthetic world builds
the truth, this module builds what was read off the paper. What wasn't read is never
guessed. A row without a date is left out and noted; a document without its key
dates is noted and skipped. Missing data then shows up as a gap the rules can see.

Two judgement calls, both in the patient's favour. Rules must not block on what the
reader couldn't make out:
- a mark (signature, stamp, Handzeichen) read as "unclear" counts as present. DOC-READABLE
  flags it for a human instead.
- unknown times: admission at the start of its day, discharge at the end of its day.
"""

import datetime as dt
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from types import UnionType

from pydantic import BaseModel

from kassenfest.pipeline.link import value
from kassenfest.rules.reference import Reference, load_reference
from kassenfest.rules.tariffs import normalize_lk
from kassenfest.schemas.common import Mark
from kassenfest.schemas.domain import (
    Approval,
    ApprovedService,
    CaseFile,
    Domain,
    PrescribedService,
    Prescription,
    Stay,
    Visit,
    VisitLog,
)
from kassenfest.schemas.extraction import (
    ApprovalLetter,
    HospitalLetter,
    Muster12,
    VisitEntry,
    VisitLogSGBV,
    VisitLogSGBXI,
)
from kassenfest.schemas.records import MasterData

UNCLEAR_INITIALS = "?"
"""Handzeichen there but unreadable: counts as signed off; DOC-READABLE flags the cell."""


@dataclass
class SourceDoc:
    document_id: str
    extraction: BaseModel
    patient_id: str


@dataclass
class Built:
    cases: dict[str, CaseFile]
    issues: dict[str, list[str]] = field(default_factory=dict)
    """document id → what could not be used from it."""


def _iso(text: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _time(text: str | None) -> dt.time | None:
    try:
        return dt.time.fromisoformat(text) if text else None
    except ValueError:
        return None


def _digits(text: str | None) -> str | None:
    return re.sub(r"\s", "", text) if text else None


def _signed(mark: Mark) -> bool:
    return mark.state != "absent"


def _of(docs: list[SourceDoc], kind: type | UnionType) -> list[SourceDoc]:
    return [s for s in docs if isinstance(s.extraction, kind)]


def _label_key(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


class _Builder:
    def __init__(self, month: str, records: MasterData, ref: Reference):
        self.month, self.records, self.ref = month, records, ref
        self.issues: dict[str, list[str]] = defaultdict(list)
        self.month_start = dt.date.fromisoformat(f"{month}-01")
        self.staff = {s.initials.upper(): s for s in records.provider.staff}
        self.payers = {p.ik: p for p in records.payers}
        self.patients = {p.id: p for p in records.patients}

    def note(self, src: SourceDoc, message: str) -> None:
        self.issues[src.document_id].append(message)

    # --- lookups ------------------------------------------------------------------

    def hkp_position(self, label: str | None) -> str | None:
        """Positionsnummer for a service label as printed, when the number itself wasn't read."""
        if not label:
            return None
        key = _label_key(label)
        for code, pos in self.ref.hkp_positions.items():
            if _label_key(pos.label_de) in key or key in _label_key(pos.label_de):
                return code
        return None

    def lk_code(self, code: str | None, label: str | None) -> str | None:
        if code and (norm := normalize_lk(code)) in self.ref.leistungskomplexe:
            return norm
        if label:
            key = _label_key(label)
            for lk, info in self.ref.leistungskomplexe.items():
                if _label_key(info.label_de) == key:
                    return lk
        return normalize_lk(code) if code else None

    def payer_ik(self, doc: BaseModel, kind: str, patient_id: str, day: dt.date) -> str:
        """The IK as printed if the records know it, else by name, else the patient's Kasse."""
        ik = _digits(value(doc, "payer_ik"))
        if ik in self.payers and self.payers[ik].kind == kind:
            return ik
        name = value(doc, "payer_name")
        if name:
            key = _label_key(name)
            named = [p for p in self.records.payers if p.kind == kind and _label_key(p.name) == key]
            if len(named) == 1:
                return named[0].ik
        patient = self.patients[patient_id]
        live = [i for i in patient.insurance if i.valid_from <= day] or patient.insurance
        period = max(live, key=lambda i: i.valid_from)
        return period.krankenkasse_ik if kind == "krankenkasse" else period.pflegekasse_ik

    # --- per document type --------------------------------------------------------

    def prescription(self, src: SourceDoc) -> Prescription | None:
        m = src.extraction
        assert isinstance(m, Muster12)
        starts = [d for x in m.measures if (d := _iso(x.duration_from))]
        ends = [d for x in m.measures if (d := _iso(x.duration_to))]
        start = _iso(value(m, "period_from")) or min(starts, default=None)
        end = _iso(value(m, "period_to")) or max(ends, default=None)
        issued = _iso(value(m, "issue_date")) or start
        if not (start and end and issued):
            self.note(src, "Verordnungszeitraum unreadable: not used as a Verordnung")
            return None
        kind = value(m, "prescription_kind")
        if kind is None:
            self.note(src, "Erst-/Folgeverordnung tick unreadable: taken as Erstverordnung")
        blank = bool(value(m, "blank_prescription"))
        fax = next(
            (
                f
                for f in self.records.fax_reports
                if f.patient_id == src.patient_id and f.issue_date == issued
            ),
            None,
        )
        return Prescription(
            id=f"rx-{src.document_id}",
            patient_id=src.patient_id,
            physician_lanr=_digits(value(m, "lanr")) or "",
            kind=kind or "erst",
            issue_date=issued,
            period_from=start,
            period_to=end,
            blank=blank,
            services=[
                PrescribedService(
                    category=x.category,
                    frequency=None if blank else x.frequency,
                    details=x.details,
                )
                for x in m.measures
            ],
            icd_codes=value(m, "icd_codes") or [],
            doctor_signed=_signed(m.doctor_signature),
            stamp_present=_signed(m.practice_stamp),
            corrections_present=m.corrections_present,
            corrections_initialled=_signed(m.corrections_initialled),
            submitted_to_payer_at=fax.sent_on if fax else None,
            document_id=src.document_id,
        )

    def approval(self, src: SourceDoc, prescriptions: list[Prescription]) -> Approval | None:
        a = src.extraction
        assert isinstance(a, ApprovalLetter)
        start, end = _iso(value(a, "period_from")), _iso(value(a, "period_to"))
        items: list[ApprovedService] = []
        for i, item in enumerate(a.approved_items):
            code = _digits(item.position_no) or self.hkp_position(item.description)
            valid_from, valid_to = _iso(item.valid_from) or start, _iso(item.valid_to) or end
            if not code:
                self.note(src, f"approved_items[{i}]: no Positionsnummer for {item.description!r}")
            elif not (valid_from and valid_to):
                self.note(src, f"approved_items[{i}]: validity unreadable")
            else:
                items.append(
                    ApprovedService(
                        position_no=code,
                        frequency=item.frequency,
                        valid_from=valid_from,
                        valid_to=valid_to,
                    )
                )
        start = start or min((x.valid_from for x in items), default=None)
        end = end or max((x.valid_to for x in items), default=None)
        letter_date = _iso(value(a, "letter_date"))
        if not (start and end and letter_date):
            self.note(src, "letter date or approval period unreadable: not used as a Genehmigung")
            return None
        decision = value(a, "decision") or (
            "rejected" if not items else "partial" if a.rejected_items else "approved"
        )
        rx_issued = _iso(value(a, "prescription_issue_date"))
        rx = next((p for p in prescriptions if p.issue_date == rx_issued), None) or next(
            (p for p in prescriptions if p.period_from <= start <= p.period_to), None
        )
        provider_ik = _digits(value(a, "provider_ik"))
        return Approval(
            id=f"ap-{src.document_id}",
            patient_id=src.patient_id,
            payer_ik=self.payer_ik(a, "krankenkasse", src.patient_id, start),
            provider_ik=provider_ik
            if provider_ik and len(provider_ik) == 9
            else self.records.provider.ik,
            approval_ref=value(a, "approval_ref") or "",
            letter_date=letter_date,
            decision=decision,
            period_from=start,
            period_to=end,
            approved=items,
            prescription_id=rx.id if rx else None,
            document_id=src.document_id,
        )

    def _month_of(self, src: SourceDoc, written: str | None, dates: list[dt.date]) -> str | None:
        if written:
            return written
        months = Counter(d.strftime("%Y-%m") for d in dates)
        if months:
            self.note(src, "billing month unreadable: taken from the visit dates")
            return months.most_common(1)[0][0]
        self.note(src, "billing month and visit dates unreadable: not used")
        return None

    def _staff(self, initials: str | None, state: str) -> tuple[str | None, str | None]:
        """(Handzeichen, Beschäftigtennummer) for one cell."""
        if state == "absent":
            return None, None
        if state == "unclear":
            return initials or UNCLEAR_INITIALS, None
        staff = self.staff.get((initials or "").upper())
        return initials, staff.employee_no if staff else None

    def visit_log(self, src: SourceDoc) -> VisitLog | None:
        d = src.extraction
        assert isinstance(d, VisitLogSGBV | VisitLogSGBXI)
        domain: Domain = "sgbv" if isinstance(d, VisitLogSGBV) else "sgbxi"
        visits: list[Visit] = []
        for i, e in enumerate(d.entries):
            day = _iso(e.date)
            if isinstance(e, VisitEntry):
                code = _digits(e.position_no) or self.hkp_position(e.service)
                start, end, quantity, funding = (
                    _time(e.start_time),
                    _time(e.end_time),
                    e.quantity,
                    "hkp",
                )
            else:
                code = self.lk_code(e.lk_code, e.lk_label)
                start, end, quantity, funding = _time(e.time), None, e.count, e.funding
            if not day:
                self.note(src, f"entries[{i}]: date unreadable, line left out")
                continue
            if not code:
                self.note(src, f"entries[{i}]: service unreadable, line left out")
                continue
            initials, employee_no = self._staff(e.staff_initials, e.initials_state)
            visits.append(
                Visit(
                    date=day,
                    start=start,
                    end=end,
                    code=code,
                    quantity=quantity or 1,
                    funding=funding,
                    employee_no=getattr(e, "employee_no", None) or employee_no,
                    staff_initials=initials,
                    document_id=src.document_id,
                    entry_index=i,
                )
            )
        month = self._month_of(src, value(d, "month"), [v.date for v in visits])
        if month is None:
            return None
        kind = "krankenkasse" if domain == "sgbv" else "pflegekasse"
        start_day = dt.date.fromisoformat(f"{month}-01")
        reason = value(d, "missing_signature_reason") if domain == "sgbv" else None
        died = self.patients[src.patient_id].deceased_at
        if not reason and not _signed(d.patient_signature) and died and f"{died:%Y-%m}" <= month:
            reason = 1  # Kennzeichen "verstorben", from the records (the SGB XI form has no box)
        return VisitLog(
            id=f"{src.patient_id}-{month}-{domain}",
            patient_id=src.patient_id,
            payer_ik=self.payer_ik(d, kind, src.patient_id, start_day),
            month=month,
            domain=domain,
            visits=visits,
            patient_signed=_signed(d.patient_signature),
            missing_signature_reason=int(reason) if reason else None,
            provider_signed=_signed(d.provider_signature),
            document_id=src.document_id,
        )

    def stay(self, src: SourceDoc) -> Stay | None:
        h = src.extraction
        assert isinstance(h, HospitalLetter)
        admitted = _iso(value(h, "admission_date"))
        if admitted is None:
            self.note(src, "admission date unreadable: not used as a hospital stay")
            return None
        discharged = _iso(value(h, "discharge_date"))
        in_time = _time(value(h, "admission_time")) or dt.time.min
        out_time = _time(value(h, "discharge_time")) or dt.time(23, 59)
        return Stay(
            id=f"stay-{src.document_id}",
            patient_id=src.patient_id,
            kind="hospital",
            admitted_at=dt.datetime.combine(admitted, in_time),
            discharged_at=dt.datetime.combine(discharged, out_time) if discharged else None,
            document_id=src.document_id,
        )

    # --- one patient --------------------------------------------------------------

    def case(self, patient_id: str, docs: list[SourceDoc]) -> CaseFile:
        prescriptions = [rx for s in _of(docs, Muster12) if (rx := self.prescription(s))]
        approvals = [
            ap for s in _of(docs, ApprovalLetter) if (ap := self.approval(s, prescriptions))
        ]
        logs: list[VisitLog] = []
        for s in _of(docs, VisitLogSGBV | VisitLogSGBXI):
            if log := self.visit_log(s):
                if any(other.id == log.id for other in logs):
                    log.id = f"{log.id}-{s.document_id}"
                logs.append(log)
        patient = self.patients[patient_id]
        iks = {i.krankenkasse_ik for i in patient.insurance} | {
            i.pflegekasse_ik for i in patient.insurance
        }
        lanrs = {rx.physician_lanr for rx in prescriptions}
        return CaseFile(
            month=self.month,
            provider=self.records.provider,
            patient=patient,
            payers={ik: p for ik, p in self.payers.items() if ik in iks},
            physicians={p.lanr: p for p in self.records.physicians if p.lanr in lanrs},
            prescriptions=prescriptions,
            approvals=approvals,
            visit_logs=logs,
            stays=[st for s in _of(docs, HospitalLetter) if (st := self.stay(s))],
            prior_claims=[c for c in self.records.billed if c.patient_id == patient_id],
        )


def build_cases(
    month: str, records: MasterData, docs: list[SourceDoc], ref: Reference | None = None
) -> Built:
    builder = _Builder(month, records, ref or load_reference())
    by_patient: dict[str, list[SourceDoc]] = defaultdict(list)
    for doc in docs:
        by_patient[doc.patient_id].append(doc)
    cases = {pid: builder.case(pid, group) for pid, group in sorted(by_patient.items())}
    return Built(cases, dict(builder.issues))
