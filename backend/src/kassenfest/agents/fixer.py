"""The fixer agent: Muse Spark works out what has to happen before a patient's bills can go
out, and drafts it (AGT-01..04).

Per patient with open findings, a tool loop. The tools are its only way to the data and to
the outcome: they hand it facts under short refs (F1 a finding, D1 a document, A1 a doctor,
K1 a Kasse, T1 a deadline, L1 a draft) and check what comes back. A draft with a date,
amount, time or number that is in no tool result goes back to the model, and so does an
action without a computed deadline, a checked draft, or a recipient that fits its kind.
Amounts are summed from the findings, never written by the model. The tools add the address
block, the greeting and the sign-off. Nothing is sent: actions are drafts for a person.

A patient is drafted once per state of what the fixer sees (`Brief.fingerprint`); a new
upload that changes the findings makes it due again. Every step of the loop is stored, so the
Actions screen can show how each letter came about.
"""

import asyncio
import datetime as dt
import hashlib
import json
import re
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any, get_args

from sqlalchemy import Engine
from sqlmodel import col, select

from kassenfest.agents.auditor import checked_findings, current_audits, fields_read
from kassenfest.db import Fix, session_scope
from kassenfest.llm.client import MetaModelClient
from kassenfest.llm.prompts import DOC_NAMES, FIX_SYSTEM, FIX_VERSION, fix_user
from kassenfest.pipeline.month import SEVERITY_RANK, Month, StoredDoc, evaluate_month
from kassenfest.rules.calendar import WorkingDayCalendar, calendar_for
from kassenfest.rules.engine import pack_for
from kassenfest.rules.reference import load_reference
from kassenfest.schemas.actions import Action, ActionKind, Letter
from kassenfest.schemas.domain import CaseFile, Claim, ClaimLine
from kassenfest.schemas.findings import Finding
from kassenfest.schemas.labels import field_label
from kassenfest.schemas.records import MasterData

MAX_TURNS = 16
RECIPIENTS: dict[ActionKind, tuple[str, ...]] = {
    "folgeverordnung_request": ("doctor",),
    "stamp_request": ("doctor",),
    "prescription_change": ("doctor",),
    "kasse_letter": ("kasse",),
    "signature_request": ("patient",),
    "eigenanteil_notice": ("patient",),
    "claim_correction": ("office",),
    "staff_followup": ("office", "staff"),
}
"""Who each kind of action may go to."""
CHANNEL = {
    "doctor": "fax",
    "kasse": "post",
    "patient": "handover",
    "office": "internal",
    "staff": "internal",
}
PAPERWORK = ("muster12", "approval_letter", "visit_log_sgbv", "visit_log_sgbxi", "hospital_letter")
MONTHS = "Januar Februar März April Mai Juni Juli August September Oktober November Dezember"
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
DOMAIN = {"sgbv": "häusliche Krankenpflege (SGB V)", "sgbxi": "Pflegesachleistungen (SGB XI)"}
DEADLINES = ("billing_run", "rx_submission", "folge_window", "reply")


def _de(day: dt.date | dt.datetime) -> str:
    return day.strftime("%d.%m.%Y")


def _day(day: dt.date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {_de(day)}"


def _eur(cents: int) -> str:
    return f"{cents / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _month(ym: str) -> str:
    year, month = ym.split("-")
    return f"{MONTHS.split()[int(month) - 1]} {year}"


def full_name(listed: str) -> str:
    """'Albers, Erika' -> 'Erika Albers'."""
    last, _, first = listed.partition(",")
    return f"{first.strip()} {last.strip()}".strip()


# --- what the fixer works from --------------------------------------------------------------


@dataclass
class Recipient:
    ref: str
    kind: str
    """doctor | kasse | patient | office | staff"""
    address: list[str]
    greeting: str | None
    """None for an internal note: no greeting, no sign-off."""
    who: str


@dataclass
class Brief:
    month: Month
    case: CaseFile
    findings: list[Finding]
    """The patient's open findings, worst first: F1, F2, …"""
    docs: list[StoredDoc]
    """D1, D2, …"""
    recipients: dict[str, Recipient]
    doctors: dict[str, str]
    """LANR → A-ref."""
    kassen: dict[str, str]
    """IK → K-ref."""
    as_of: dt.date
    calendar: WorkingDayCalendar
    fingerprint: str = ""

    @property
    def patient_id(self) -> str:
        return self.case.patient.id

    @property
    def claims(self) -> list[Claim]:
        return [c for c in self.month.claims.values() if c.patient_id == self.patient_id]

    def doc_ref(self, document_id: str | None) -> str | None:
        refs = {d.document.id: f"D{i}" for i, d in enumerate(self.docs, 1)}
        return refs.get(document_id or "")

    def refs(self) -> dict[str, str]:
        """Ref → id, for the screen: findings and documents."""
        out = {f"F{i}": f.id for i, f in enumerate(self.findings, 1)}
        return out | {f"D{i}": d.document.id for i, d in enumerate(self.docs, 1)}


def open_findings(findings: list[Finding], patient_id: str) -> list[Finding]:
    mine = [f for f in findings if f.patient_id == patient_id and f.severity != "info"]
    return sorted(mine, key=lambda f: (SEVERITY_RANK[f.severity], -f.amount_at_risk_cents, f.id))


def brief(month: Month, patient_id: str, findings: list[Finding], as_of: dt.date) -> Brief:
    case = month.cases[patient_id]
    patient, provider = case.patient, case.provider
    docs = sorted(
        (
            d
            for d in month.docs.values()
            if d.patient_id == patient_id
            and d.extraction is not None
            and d.document.doc_type in PAPERWORK
        ),
        key=lambda d: (PAPERWORK.index(d.document.doc_type or ""), d.document.created_at),
    )
    lanrs = [rx.physician_lanr for rx in case.prescriptions] + list(case.physicians)
    doctors = {lanr: f"A{i}" for i, lanr in enumerate(dict.fromkeys(lanrs), 1)}
    iks = [i for p in patient.insurance for i in (p.krankenkasse_ik, p.pflegekasse_ik)]
    iks += [c.payer_ik for c in month.claims.values() if c.patient_id == patient_id]
    kassen = {ik: f"K{i}" for i, ik in enumerate(dict.fromkeys(iks), 1) if ik in case.payers}

    name = full_name(patient.name)
    recipients = {}
    for lanr, ref in doctors.items():
        doc = case.physicians.get(lanr)
        if doc is None:
            continue
        addressed = doc.name.replace("Dr. med. ", "Dr. ")
        recipients[ref] = Recipient(
            ref, "doctor", doc.address or [doc.name], f"Guten Tag {addressed},", doc.name
        )
    for ik, ref in kassen.items():
        payer = case.payers[ik]
        dept = "Leistungsabteilung Pflege" if payer.kind == "pflegekasse" else "Leistungsabteilung"
        recipients[ref] = Recipient(
            ref, "kasse", [payer.name, dept], "Sehr geehrte Damen und Herren,", payer.name
        )
    recipients["patient"] = Recipient("patient", "patient", [name], f"Guten Tag {name},", name)
    recipients["office"] = Recipient(
        "office", "office", ["Abrechnung", provider.name], None, "the billing office"
    )
    for s in provider.staff:
        ref = f"staff:{s.initials}"
        recipients[ref] = Recipient(ref, "staff", [s.name, provider.name], None, s.name)

    b = Brief(
        month,
        case,
        open_findings(findings, patient_id),
        docs,
        recipients,
        doctors,
        kassen,
        as_of,
        calendar_for(provider.bundesland, provider.municipality),
    )
    seen = [
        FIX_VERSION,
        FIX_SYSTEM,
        fix_user(name, _month(month.month)),
        json.dumps(TOOLS),
        json.dumps(findings_result(b), ensure_ascii=False),
        json.dumps(context_result(b), ensure_ascii=False),
        *(json.dumps(document_result(b, d), ensure_ascii=False) for d in docs),
        *sorted(f.id for f in b.findings),
        *(d.document.id for d in docs),  # a new upload of the same pages is due again
    ]
    b.fingerprint = hashlib.sha256("\n".join(seen).encode()).hexdigest()
    return b


# --- what the read tools return ------------------------------------------------------------


def _labels() -> dict[str, str]:
    ref = load_reference()
    return {c: p.label_de for c, p in ref.hkp_positions.items()} | {
        c: lk.label_de for c, lk in ref.leistungskomplexe.items()
    }


def _bill(claim: Claim | None) -> str:
    if claim is None:
        return "no bill"
    return f"{DOMAIN[claim.domain]}, {_month(claim.month)}"


def _line(ln: ClaimLine, labels: dict[str, str]) -> str:
    time = f" {ln.time:%H:%M}" if ln.time else ""
    qty = f" x{ln.quantity}" if ln.quantity > 1 else ""
    label = labels.get(ln.code, "?")
    return f"{_day(ln.date)}{time} {ln.code} {label}{qty} {_eur(ln.amount_cents)}"


def _lines(b: Brief, ids: list[str], labels: dict[str, str]) -> dict[str, Any]:
    wanted = set(ids)
    lines = sorted(
        (ln for c in b.claims for ln in c.lines if ln.id in wanted),
        key=lambda ln: (ln.date, ln.time or dt.time()),
    )
    if not lines:
        return {"count": 0}
    if len(lines) <= 12:
        return {"count": len(lines), "each": [_line(ln, labels) for ln in lines]}
    codes = Counter(ln.code for ln in lines)
    return {
        "count": len(lines),
        "from": _day(lines[0].date),
        "to": _day(lines[-1].date),
        "positions": [f"{c} {labels.get(c, '?')}: {n}" for c, n in codes.items()],
        "total": _eur(sum(ln.amount_cents for ln in lines)),
    }


def _evidence(b: Brief, f: Finding) -> list[dict[str, Any]]:
    """Where the finding shows on the paper, per document: the first few fields."""
    fields: dict[str, list[str]] = {}
    for ev in f.evidence:
        if ref := b.doc_ref(ev.document_id):
            label = field_label(ev.field_path or "") or "page"
            fields.setdefault(ref, []).append(f"{label}: {ev.note}" if ev.note else label)
    out = []
    for ref, labels in fields.items():
        item: dict[str, Any] = {"document": ref, "fields": labels[:4]}
        if len(labels) > 4:
            item["more_fields"] = len(labels) - 4
        out.append(item)
    return out


def findings_result(b: Brief) -> dict[str, Any]:
    """get_claim_findings without today's date (the fingerprint must not change daily)."""
    labels, codes = _labels(), load_reference().kasse_codes
    out = []
    for i, f in enumerate(b.findings, 1):
        claim = b.month.claims.get(f.claim_id or "")
        item: dict[str, Any] = {
            "ref": f"F{i}",
            "rule": f.rule_id,
            "severity": f.severity,
            "bill": _bill(claim),
            "at_risk": _eur(f.amount_at_risk_cents),
            "says": f.message_de,
            "in_english": f.message_en,
            "sources": f.sources,
        }
        if f.kasse_codes:
            item["kasse_codes"] = [
                f"{c} {codes[c].label_de}" if c in codes else c for c in f.kasse_codes
            ]
        if f.claim_line_ids:
            item["lines"] = _lines(b, f.claim_line_ids, labels)
        if evidence := _evidence(b, f):
            item["evidence"] = evidence
        out.append(item)
    bills = [
        {
            "bill": _bill(c),
            "kasse": b.kassen.get(c.payer_ik, c.payer_ik),
            "lines": len(c.lines),
            "total": _eur(c.total_cents),
        }
        for c in b.claims
    ]
    return {"billing_month": _month(b.month.month), "bills": bills, "findings": out}


def context_result(b: Brief) -> dict[str, Any]:
    case, p = b.case, b.case.patient
    labels = _labels()
    patient: dict[str, Any] = {
        "name": full_name(p.name),
        "listed_as": p.name,
        "born": _de(p.dob),
        "versicherten_nr": p.kvnr,
    }
    if p.pflegegrad:
        patient["pflegegrad"] = [f"{g.grade} from {_de(g.valid_from)}" for g in p.pflegegrad]
    if p.deceased_at:
        patient["died"] = f"{p.deceased_at:%d.%m.%Y %H:%M}"
    kassen = [
        {
            "ref": ref,
            "name": case.payers[ik].name,
            "ik": ik,
            "kind": case.payers[ik].kind,
        }
        for ik, ref in b.kassen.items()
    ]
    doctors = [
        {
            "ref": ref,
            "name": d.name,
            "lanr": d.lanr,
            "bsnr": d.bsnr,
            "address": ", ".join(d.address[1:]) if d.address else "unknown",
        }
        for lanr, ref in b.doctors.items()
        if (d := case.physicians.get(lanr))
    ]

    def service(s) -> str:
        what = labels.get(s.position_no or "", s.category)
        freq = f" {s.frequency.count}x per {s.frequency.per}" if s.frequency else ""
        details = f": {s.details}" if s.details else ""
        return f"{what}{f' ({s.position_no})' if s.position_no else ''}{freq}{details}"

    prescriptions = [
        {
            "document": b.doc_ref(rx.document_id) or "not in the paperwork",
            "kind": {"erst": "Erstverordnung", "folge": "Folgeverordnung"}[rx.kind],
            "doctor": b.doctors.get(rx.physician_lanr, rx.physician_lanr),
            "issued": _de(rx.issue_date),
            "period": f"{_de(rx.period_from)} to {_de(rx.period_to)}",
            "services": [service(s) for s in rx.services],
            "doctor_signed": rx.doctor_signed,
            "practice_stamp": rx.stamp_present,
            "reached_kasse": _de(rx.submitted_to_payer_at)
            if rx.submitted_to_payer_at
            else "no fax report",
        }
        for rx in case.prescriptions
    ]
    approvals = [
        {
            "document": b.doc_ref(a.document_id) or "not in the paperwork",
            "kasse": b.kassen.get(a.payer_ik, a.payer_ik),
            "approval_ref": a.approval_ref,
            "letter_date": _de(a.letter_date),
            "decision": a.decision,
            "period": f"{_de(a.period_from)} to {_de(a.period_to)}",
            "approved": [
                f"{s.position_no} {labels.get(s.position_no, '?')}"
                + (f" {s.frequency.count}x per {s.frequency.per}" if s.frequency else "")
                + f", {_de(s.valid_from)} to {_de(s.valid_to)}"
                for s in a.approved
            ],
        }
        for a in case.approvals
    ]
    stays = [
        {
            "document": b.doc_ref(s.document_id) or "not in the paperwork",
            "kind": s.kind,
            "admitted": f"{s.admitted_at:%d.%m.%Y %H:%M}",
            "discharged": f"{s.discharged_at:%d.%m.%Y %H:%M}" if s.discharged_at else "not yet",
        }
        for s in case.stays
    ]
    logs = [
        {
            "document": b.doc_ref(v.document_id) or "not in the paperwork",
            "month": _month(v.month),
            "kind": DOMAIN[v.domain],
            "visits": len(v.visits),
            "patient_signed": v.patient_signed,
            "missing_signature_reason": v.missing_signature_reason,
        }
        for v in case.visit_logs
    ]
    staff = [
        {"ref": f"staff:{s.initials}", "name": s.name, "qualification": s.qualification}
        for s in case.provider.staff
    ]
    recipients = {
        r.ref: f"{r.who} ({CHANNEL[r.kind]})" for r in b.recipients.values() if r.kind != "staff"
    }
    recipients["staff:XY"] = "a nurse by Handzeichen, see staff (internal)"
    return {
        "patient": patient,
        "kassen": kassen,
        "doctors": doctors,
        "prescriptions": prescriptions,
        "approvals": approvals,
        "stays": stays,
        "visit_logs": logs,
        "staff": staff,
        "provider": {"name": case.provider.name, "ik": case.provider.ik},
        "recipients": recipients,
    }


def document_result(b: Brief, doc: StoredDoc) -> dict[str, Any]:
    note = "get_claim_findings lists the rows each finding concerns"
    return {
        "document": b.doc_ref(doc.document.id),
        "type": DOC_NAMES.get(doc.document.doc_type or "", "other"),
        "received": _de(doc.document.created_at),
        "pages": len(doc.pages),
        "fields": fields_read(doc, entries=note, indent=""),
    }


# --- the tools -------------------------------------------------------------------------------


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None):
    params = {"type": "object", "properties": properties, "required": required or []}
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": params},
    }


TOOLS = [
    _tool(
        "get_claim_findings",
        "The patient's open findings on this month's bills, worst first: each with its ref "
        "(F1, F2, ...), the rule, the money at risk, the lines it concerns and the evidence.",
        {},
    ),
    _tool(
        "get_patient_context",
        "The patient's records: Kassen (K1, ...), doctors (A1, ...), Verordnungen, "
        "Genehmigungen, stays, Leistungsnachweise, staff, and who can receive a letter.",
        {},
    ),
    _tool(
        "get_document",
        "Every field as read on one document of the paperwork.",
        {"document": {"type": "string", "description": "D1, D2, ..."}},
        ["document"],
    ),
    _tool(
        "compute_deadline",
        "A due date on the provider's working-day calendar (Mon-Fri without the holidays of "
        "its municipality). billing_run: when this month's bills go out. rx_submission: by "
        "when a Verordnung must reach the Kasse (needs document). folge_window: when the "
        "Folgeverordnung for a Verordnung is due (needs document). reply: working_days from "
        "today, for an answer you ask for.",
        {
            "kind": {"type": "string", "enum": list(DEADLINES)},
            "document": {"type": "string", "description": "The Verordnung, D1, D2, ..."},
            "working_days": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        ["kind"],
    ),
    _tool(
        "draft_letter",
        "Check and keep a letter or internal note. Adds the address block, greeting and "
        "sign-off. Returns its ref (L1, ...) or the problems to fix.",
        {
            "recipient": {"type": "string", "description": "A1, K1, patient, office, staff:XY"},
            "subject": {"type": "string", "description": "German"},
            "body": {"type": "string", "description": "German, without greeting or sign-off"},
        },
        ["recipient", "subject", "body"],
    ),
    _tool(
        "create_action",
        "File an action for a person at the Pflegedienst to check and carry out.",
        {
            "kind": {"type": "string", "enum": list(get_args(ActionKind))},
            "title": {"type": "string", "description": "English, what to do, under 70 chars"},
            "why": {"type": "string", "description": "English, one sentence"},
            "findings": {"type": "array", "items": {"type": "string"}, "description": "F1, ..."},
            "deadline": {"type": "string", "description": "T1, ... from compute_deadline"},
            "letter": {"type": "string", "description": "L1, ... from draft_letter"},
        },
        ["kind", "title", "why", "findings", "deadline", "letter"],
    ),
]

DATE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})?(?!\d)")
MONEY = re.compile(
    r"(\d{1,3}(?:\.\d{3})*,\d{2})\s?(?:€|EUR|Euro)|(?:€|EUR)\s?(\d{1,3}(?:\.\d{3})*,\d{2})"
)
TIME = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9]")
GREETING = re.compile(r"^(Sehr geehrte|Guten Tag|Liebe|Hallo)", re.IGNORECASE)
REF = re.compile(r"\b[ADFKLTX]\d{1,2}\b")
ADDRESSED = re.compile(r"\b(Herrn?|Frau)\s+(Dr\.\s+)?[A-ZÄÖÜ]")
SIGN_OFF = "Mit freundlichen Grüßen\n\nPflegedienstleitung\n{provider}"


def _dates(text: str) -> list[tuple[str, int, int, int | None]]:
    out = []
    for m in DATE.finditer(text):
        day, month = int(m[1]), int(m[2])
        if 1 <= day <= 31 and 1 <= month <= 12:
            out.append((m[0], day, month, int(m[3]) if m[3] else None))
    return out


def _cents(text: str) -> set[int]:
    return {int((m[1] or m[2]).replace(".", "").replace(",", "")) for m in MONEY.finditer(text)}


def _times(text: str) -> set[str]:
    return {f"{int(m[1]):02d}:{m[2]}" for m in TIME.finditer(text)}


@dataclass
class Deadline:
    date: dt.date
    kind: str


@dataclass
class Draft:
    recipient: Recipient
    letter: Letter
    filed: str | None = None


@dataclass
class Desk:
    """The fixer's workspace for one patient: what it was told, computed and filed."""

    brief: Brief
    seen: list[str] = field(default_factory=list)
    """Every tool result so far, as sent: what a letter may quote."""
    deadlines: dict[str, Deadline] = field(default_factory=dict)
    drafts: dict[str, Draft] = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)
    covered: set[str] = field(default_factory=set)

    def call(self, name: str, arguments: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """(arguments as parsed, result) of one tool call; mistakes come back as problems."""
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("not an object")
        except ValueError:
            return {"_raw": arguments}, {"ok": False, "problems": ["arguments are not valid JSON"]}
        tools = {
            "get_claim_findings": self.get_claim_findings,
            "get_patient_context": self.get_patient_context,
            "get_document": self.get_document,
            "compute_deadline": self.compute_deadline,
            "draft_letter": self.draft_letter,
            "create_action": self.create_action,
        }
        if name not in tools:
            result = {"ok": False, "problems": [f"no tool {name!r}; use {', '.join(tools)}"]}
        else:
            try:
                result = tools[name](**args)
            except (TypeError, AttributeError) as exc:  # missing, extra or mistyped
                result = {"ok": False, "problems": [f"wrong arguments: {exc}"]}
        self.seen.append(json.dumps(result, ensure_ascii=False))
        return args, result

    # read

    def get_claim_findings(self) -> dict[str, Any]:
        return {"today": _day(self.brief.as_of)} | findings_result(self.brief)

    def get_patient_context(self) -> dict[str, Any]:
        return context_result(self.brief)

    def get_document(self, document: str) -> dict[str, Any]:
        doc = self._doc(document)
        if doc is None:
            return {"ok": False, "problems": [f"no document {document!r}"]}
        return document_result(self.brief, doc)

    def _doc(self, ref: str | None) -> StoredDoc | None:
        refs = {f"D{i}": d for i, d in enumerate(self.brief.docs, 1)}
        return refs.get((ref or "").strip())

    # compute

    def compute_deadline(
        self, kind: str, document: str | None = None, working_days: int | None = None
    ) -> dict[str, Any]:
        b, cal = self.brief, self.brief.calendar
        out: dict[str, Any] = {}
        if isinstance(working_days, str) and working_days.strip().isdigit():
            working_days = int(working_days)
        if kind == "billing_run":
            first = dt.date.fromisoformat(f"{b.month.month}-01")
            last = (first + dt.timedelta(days=31)).replace(day=1) - dt.timedelta(days=1)
            n = b.case.provider.billing_working_day
            date = cal.add_working_days(last, n)
            basis = f"{n}. Arbeitstag im {MONTHS.split()[date.month - 1]}: Abrechnungslauf"
        elif kind in ("rx_submission", "folge_window"):
            doc = self._doc(document)
            rx = next(
                (r for r in b.case.prescriptions if doc and r.document_id == doc.document.id),
                None,
            )
            if rx is None:
                return {"ok": False, "problems": [f"{kind} needs a Verordnung: document D1, ..."]}
            if kind == "rx_submission":
                spec = pack_for(rx.issue_date).rule("HKP-SUBMIT-4WD")
                n = spec.params["working_days_after_issue"]
                date = cal.add_working_days(rx.issue_date, n)
                basis = f"{n}. Arbeitstag nach Ausstellung am {_de(rx.issue_date)}"
                out["source"] = spec.sources[0]
            else:
                spec = pack_for(rx.period_to).rule("HKP-FOLGE-WINDOW")
                window = cal.last_working_days(rx.period_to, spec.params["window_working_days"])
                date = window[-1]
                out["window_from"] = _day(window[0])
                basis = (
                    f"letzte {len(window)} Arbeitstage vor Ablauf der Verordnung am "
                    f"{_de(rx.period_to)}"
                )
                out["source"] = spec.sources[0]
        elif kind == "reply":
            if not isinstance(working_days, int) or not 1 <= working_days <= 10:
                return {"ok": False, "problems": ["reply needs working_days from 1 to 10"]}
            date = cal.add_working_days(b.as_of, working_days)
            basis = f"{working_days} Arbeitstage ab heute, {_de(b.as_of)}"
        else:
            return {"ok": False, "problems": [f"kind is one of {', '.join(DEADLINES)}"]}
        ref = f"T{len(self.deadlines) + 1}"
        self.deadlines[ref] = Deadline(date, kind)
        days = (date - b.as_of).days
        result = {"deadline": ref, "date": _day(date), "days_from_today": days, "basis": basis}
        return result | out | ({"passed": True} if days < 0 else {})

    # write

    def draft_letter(self, recipient: str, subject: str, body: str) -> dict[str, Any]:
        r = self.brief.recipients.get(recipient.strip())
        if r is None:
            names = ", ".join(self.brief.recipients)
            return {"ok": False, "problems": [f"no recipient {recipient!r}; use one of {names}"]}
        subject, body = subject.strip(), body.strip()
        problems = []
        if not subject or len(subject) > 160:
            problems.append("the subject needs 1 to 160 characters")
        if len(body) < 60 or len(body) > 2500:
            problems.append("the body needs 60 to 2500 characters")
        if GREETING.match(body):
            problems.append("leave out the greeting: draft_letter adds it")
        if re.search(r"freundlichen Gr(ü|ue)(ß|ss)en", body):
            problems.append("leave out the sign-off: draft_letter adds it")
        if refs := sorted(set(REF.findall(f"{subject}\n{body}"))):
            problems.append(
                f"{', '.join(refs)} are refs for you, not for the reader: name the document, "
                "finding or date instead"
            )
        if ADDRESSED.search(f"{subject}\n{body}"):
            problems.append(
                "name people with first and last name, without Herr or Frau: the records do "
                "not say how they are addressed"
            )
        if r.greeting is not None and body[-1:] not in ".!?":
            problems.append("end the body with a full sentence")
        problems += self.ungrounded(f"{subject}\n{body}")
        if problems:
            return {"ok": False, "problems": problems}
        if r.greeting is not None:
            sign_off = SIGN_OFF.format(provider=self.brief.case.provider.name)
            body = f"{r.greeting}\n\n{body}\n\n{sign_off}"
        letter = Letter(channel=CHANNEL[r.kind], recipient=r.address, subject=subject, body=body)
        ref = f"L{len(self.drafts) + 1}"
        self.drafts[ref] = Draft(r, letter)
        return {"ok": True, "letter": ref, "to": r.address, "channel": letter.channel}

    def ungrounded(self, text: str) -> list[str]:
        """Dates, amounts, times and long numbers in `text` that no tool result contains."""
        seen = "\n".join(self.seen)
        full = {(d, m, y) for _, d, m, y in _dates(seen) if y}
        today = self.brief.as_of
        full.add((today.day, today.month, today.year))
        problems = []
        for raw, d, m, y in _dates(text):
            ok = (d, m, y) in full if y else any((d, m) == (fd, fm) for fd, fm, _ in full)
            if not ok:
                problems.append(
                    f"the date {raw} is in no tool result: use only dates the tools gave you, "
                    "and compute_deadline for a new one"
                )
        known = _cents(seen)
        for cents in sorted(_cents(text) - known):
            problems.append(
                f"the amount {_eur(cents)} is in no tool result: take amounts from "
                "get_claim_findings as they are"
            )
        for t in sorted(_times(text) - _times(seen)):
            problems.append(f"the time {t} is in no tool result")
        for token in dict.fromkeys(TOKEN.findall(text)):
            if sum(ch.isdigit() for ch in token) >= 5 and token not in seen:
                problems.append(f"{token} is in no tool result: copy numbers exactly")
        return problems

    def create_action(
        self,
        kind: str,
        title: str,
        why: str,
        findings: list[str],
        deadline: str,
        letter: str,
    ) -> dict[str, Any]:
        b = self.brief
        refs = {f"F{i}": f for i, f in enumerate(b.findings, 1)}
        if isinstance(findings, str):  # "F1, F2" or "['F1', 'F2']"
            findings = re.findall(r"F\d+", findings)
        problems = []
        if kind not in RECIPIENTS:
            problems.append(f"kind is one of {', '.join(RECIPIENTS)}")
        if not findings:
            problems.append("name the findings this action answers: F1, ...")
        unknown = [f for f in findings if f.strip() not in refs]
        if unknown:
            problems.append(f"no finding {', '.join(unknown)}")
        due = self.deadlines.get(deadline.strip())
        if due is None:
            problems.append(f"no deadline {deadline!r}: compute_deadline returns one")
        draft = self.drafts.get(letter.strip())
        if draft is None:
            problems.append(f"no letter {letter!r}: draft_letter returns one when it accepts it")
        elif draft.filed:
            problems.append(f"{letter} is already filed with {draft.filed}: draft a new one")
        elif kind in RECIPIENTS and draft.recipient.kind not in RECIPIENTS[kind]:  # type: ignore[index]
            allowed = " or ".join(RECIPIENTS[kind])  # type: ignore[index]
            problems.append(
                f"a {kind} goes to the {allowed}; {letter} is addressed to {draft.recipient.ref}"
            )
        if not title.strip() or len(title) > 90:
            problems.append("the title needs 1 to 90 characters")
        if not why.strip():
            problems.append("say why in one sentence")
        if problems:
            return {"ok": False, "problems": problems}
        assert due is not None and draft is not None
        answered = [refs[f.strip()] for f in dict.fromkeys(findings)]
        n = len(self.actions) + 1
        action = Action(
            id=f"act-{b.patient_id}-{n}",
            kind=kind,  # type: ignore[arg-type]
            title=title.strip(),
            why=why.strip(),
            patient_id=b.patient_id,
            patient_name=b.case.patient.name,
            claim_id=next((f.claim_id for f in answered if f.claim_id), None),
            finding_ids=[f.id for f in answered],
            due_date=due.date,
            amount_cents=amount_of(b, answered),
            status="open" if draft.letter.channel == "internal" else "draft",
            letter=draft.letter,
        )
        self.actions.append(action)
        draft.filed = f"X{n}"
        self.covered |= {f.strip() for f in findings}
        return {
            "ok": True,
            "action": f"X{n}",
            "due": _day(due.date),
            "money_on_it": _eur(action.amount_cents),
        }

    def uncovered(self) -> list[str]:
        return [
            f"F{i}" for i in range(1, len(self.brief.findings) + 1) if f"F{i}" not in self.covered
        ]


def amount_of(b: Brief, findings: list[Finding]) -> int:
    """The money on these findings, never counted twice: findings on the same lines share it
    (each at most its own amount at risk), whole-bill ones add theirs, and the total never
    exceeds the bills they are on."""
    amounts = {ln.id: ln.amount_cents for c in b.claims for ln in c.lines}
    on_lines = [f for f in findings if f.claim_line_ids]
    lines = {i for f in on_lines for i in f.claim_line_ids if i in amounts}
    total = min(sum(f.amount_at_risk_cents for f in on_lines), sum(amounts[i] for i in lines))
    total += sum(f.amount_at_risk_cents for f in findings if not f.claim_line_ids)
    bills = {f.claim_id for f in findings if f.claim_id}
    cap = sum(c.total_cents for c in b.claims if c.id in bills) or total
    return min(total, cap)


# --- the loop --------------------------------------------------------------------------------


@dataclass
class Drafted:
    steps: list[dict[str, Any]]
    actions: list[Action]
    note: str
    cost_usd: float


async def draft(client: MetaModelClient, b: Brief) -> Drafted:
    desk = Desk(b)
    name = full_name(b.case.patient.name)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": FIX_SYSTEM},
        {"role": "user", "content": fix_user(name, _month(b.month.month))},
    ]
    steps: list[dict[str, Any]] = []
    cost, note, nudged = 0.0, "", False
    for turn in range(1, MAX_TURNS + 1):
        reply = await client.chat_tools(
            prompt_id=f"fix.turn{turn}.{FIX_VERSION}",
            messages=messages,
            tools=TOOLS,
            reasoning_effort="medium",
        )
        cost += reply.meta.cost_usd
        messages.append(reply.message())
        if reply.content.strip():
            steps.append({"turn": turn, "kind": "say", "text": reply.content.strip()})
        if not reply.calls:
            missing = desk.uncovered()
            if missing and not nudged:  # once: it may have a reason
                nudged = True
                text = (
                    f"No action covers {', '.join(missing)} yet. Create one for each, or say "
                    "in one sentence why it needs none."
                )
                messages.append({"role": "user", "content": text})
                steps.append({"turn": turn, "kind": "nudge", "text": text})
                continue
            note = reply.content.strip()
            break
        for call in reply.calls:
            args, result = desk.call(call.name, call.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            steps.append(
                {
                    "turn": turn,
                    "kind": "call",
                    "tool": call.name,
                    "args": args,
                    "result": result,
                    "ok": result.get("ok", True),
                }
            )
    else:
        note = f"Stopped after {MAX_TURNS} turns."
    return Drafted(steps, desk.actions, note, cost)


# --- which patients, and what came of it --------------------------------------------------


def latest_fixes(engine: Engine) -> dict[str, Fix]:
    """The newest run of every patient."""
    with session_scope(engine) as s:
        rows = s.exec(select(Fix).order_by(col(Fix.created_at))).all()
    return {f.patient_id: f for f in rows}


def briefs(month: Month, findings: list[Finding], as_of: dt.date) -> dict[str, Brief]:
    """Every patient with open findings."""
    patients = {f.patient_id for f in findings if f.severity != "info"} & set(month.cases)
    return {pid: brief(month, pid, findings, as_of) for pid in sorted(patients)}


def due(
    month: Month,
    engine: Engine,
    as_of: dt.date,
    patient_ids: Collection[str] | None = None,
) -> list[Brief]:
    """Patients with open findings and no run on what the fixer would see now (or a failed one)."""
    findings = checked_findings(month, current_audits(month, engine, as_of))
    latest = latest_fixes(engine)
    out = []
    for pid, b in briefs(month, findings, as_of).items():
        if patient_ids is not None and pid not in patient_ids:
            continue
        done = latest.get(pid)
        if done is None or done.fingerprint != b.fingerprint or done.error is not None:
            out.append(b)
    return out


@dataclass
class FixSummary:
    patients: int = 0
    actions: int = 0
    failed: int = 0
    cost_usd: float = 0.0


async def fix_month(
    client: MetaModelClient,
    engine: Engine,
    records: MasterData,
    *,
    patient_ids: Collection[str] | None = None,
    as_of: dt.date | None = None,
    pending: list[Brief] | None = None,
) -> FixSummary:
    """Draft the actions of every patient who is due (or the given briefs) and store them."""
    if pending is None:
        month = evaluate_month(engine, records, records.month)
        pending = due(month, engine, as_of or client.settings.as_of(), patient_ids)
    results = await asyncio.gather(*(draft(client, b) for b in pending), return_exceptions=True)
    summary = FixSummary()
    with session_scope(engine) as s:
        for b, result in zip(pending, results, strict=True):
            fix = Fix(
                patient_id=b.patient_id,
                fingerprint=b.fingerprint,
                model=client.settings.muse_model,
                as_of=b.as_of,
                refs=b.refs(),
            )
            if isinstance(result, BaseException):
                fix.error = f"{type(result).__name__}: {result}"
                summary.failed += 1
            else:
                fix.steps, fix.note, fix.cost_usd = result.steps, result.note, result.cost_usd
                fix.actions = [
                    a.model_copy(update={"run_id": fix.id}).model_dump(mode="json")
                    for a in result.actions
                ]
                summary.patients += 1
                summary.actions += len(result.actions)
                summary.cost_usd += result.cost_usd
            s.add(fix)
    return summary


def actions(fix: Fix) -> list[Action]:
    return [Action.model_validate(a) for a in fix.actions]
