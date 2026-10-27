"""Typed document content -> HTML -> rendered page + ground truth.

Each builder returns the template context plus `TruthSpec`: for every extraction
path, the true value, its status and whether it was handwritten. Boxes come from
the rendered DOM, keyed by the same paths `schemas.paths.flatten()` produces.
"""

import calendar
import datetime as dt
import random
from dataclasses import dataclass, field
from typing import Any, Literal

from markupsafe import Markup, escape
from pydantic import BaseModel

from kassenfest.schemas.common import FieldStatus, MarkState
from kassenfest.schemas.ground_truth import GroundTruth, GTField, GTPage, GTRegion, Variant
from kassenfest.synth.fonts import FontFace, load_fonts
from kassenfest.synth.markup import INKS, Hand, printed, printed_tick, signature, stamp
from kassenfest.synth.render import (
    A4_LANDSCAPE,
    A4_PORTRAIT,
    RenderedPage,
    Renderer,
    font_face_css,
    templates,
)

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
GERMAN_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]  # fmt: skip
PER_LABEL = {"day": "tgl.", "week": "wtl.", "month": "mtl."}


def de_date(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


# --- Content models (the truth to put on paper) ----------------------------------


class M12Measure(BaseModel):
    category: str
    label: str
    details: str | None = None
    count: int | None  # None on a Blankoverordnung: the nurse sets the frequency
    per: Literal["day", "week", "month"] | None
    duration_from: dt.date
    duration_to: dt.date


class Muster12Content(BaseModel):
    payer_name: str
    payer_ik: str
    patient_name: str
    patient_dob: dt.date
    kvnr: str
    status: str = "1000000"
    bsnr: str
    lanr: str
    issue_date: dt.date
    icd_codes: list[str]
    limitations: str
    kind: Literal["erst", "folge"]
    accident: bool = False
    blank: bool = False
    period_from: dt.date
    period_to: dt.date
    measures: list[M12Measure]
    further_notes: str | None = None
    doctor_name: str
    practice_lines: list[str]
    doctor_signed: bool = True
    stamp_present: bool = True


class LNService(BaseModel):
    position_no: str
    label: str
    slots: int = 1  # visits per day for this service (1 or 2)


class LNVisit(BaseModel):
    day: int
    service: int  # index into services
    slot: int
    time: dt.time
    staff: int | None  # index into staff; None = Handzeichen missing


class LNStaff(BaseModel):
    initials: str
    employee_no: str


class VisitLogContent(BaseModel):
    provider_name: str
    provider_ik: str
    patient_name: str
    kvnr: str
    payer_name: str
    year: int
    month: int
    approval_ref: str | None
    responsible_nurse: str
    services: list[LNService]
    staff: list[LNStaff]
    visits: list[LNVisit]
    patient_signed: bool = True
    patient_signature_date: dt.date | None = None
    missing_signature_reason: Literal["1", "2", "3", "4"] | None = None
    provider_signed: bool = True


class ApprovedLine(BaseModel):
    position_no: str | None
    description: str
    count: int | None = None  # None: "lt. Verordnung", the letter states no frequency
    per: Literal["day", "week", "month"] | None = None
    valid_from: dt.date
    valid_to: dt.date


class RejectedLine(BaseModel):
    description: str
    reason: str | None


class ApprovalLetterContent(BaseModel):
    style: Literal["a", "b"]  # two payer letter layouts
    payer_name: str
    payer_ik: str
    payer_address: list[str]
    letter_date: dt.date
    approval_ref: str
    patient_name: str
    patient_dob: dt.date
    kvnr: str
    provider_name: str
    provider_address: list[str]
    provider_ik: str
    prescription_issue_date: dt.date
    decision: Literal["approved", "partial", "rejected"]
    period_from: dt.date
    period_to: dt.date
    approved: list[ApprovedLine]
    rejected: list[RejectedLine] = []
    copay_exempt: bool = False
    clerk: str
    phone: str


class XIEinsatz(BaseModel):
    """One kind of visit on the SGB XI sheet: a time row plus one row per Leistungskomplex."""

    label: str
    funding: Literal["sachleistung_36", "entlastung_45b"]
    lk: list[tuple[str, str]]  # (code, label)


class XIVisit(BaseModel):
    day: int
    einsatz: int  # index into einsaetze
    time: dt.time
    staff: int | None  # index into staff; None = Handzeichen missing
    lk: list[str]  # codes delivered on this visit, a subset of the Einsatz's


class VisitLogXIContent(BaseModel):
    provider_name: str
    provider_ik: str
    patient_name: str
    kvnr: str
    payer_name: str
    pflegegrad: int
    year: int
    month: int
    einsaetze: list[XIEinsatz]
    staff: list[LNStaff]
    visits: list[XIVisit]
    patient_signed: bool = True
    patient_signature_date: dt.date | None = None
    provider_signed: bool = True


class HospitalLetterContent(BaseModel):
    hospital_name: str
    hospital_lines: list[str]
    hospital_id: str  # Standortkennzeichen 77…
    letter_date: dt.date
    recipient_lines: list[str]
    patient_name: str
    patient_sex: Literal["f", "m"]
    patient_dob: dt.date
    kvnr: str
    payer_name: str
    admitted_at: dt.datetime
    discharged_at: dt.datetime
    diagnoses: list[tuple[str, str]]  # (ICD code, text)
    hkp_recommended: bool
    hkp_text: str | None = None
    hkp_prescription_days: int | None = None
    medication: list[str] = []
    physician: str
    signed: bool = True


# --- Style: who writes what, with which pen ---------------------------------------


@dataclass
class Style:
    rng: random.Random
    hands: list[FontFace]
    signatures: list[FontFace]
    form_ink: str = "#a23a4a"
    shade: str = "#f6e9eb"
    paper: str = "#ffffff"

    def hand(self, ink: str | None = None) -> Hand:
        face = self.rng.choice(self.hands)
        return Hand(
            family=face.family,
            ink=ink or self.rng.choice(list(INKS.values())),
            size_pt=self.rng.uniform(12.5, 15.5),
            rng=self.rng,
            jitter=self.rng.uniform(0.6, 1.4),
            tilt=self.rng.gauss(0, 1.0),
            font_file=face.file,
        )

    def signature_font(self) -> str | None:
        """Half the signatures are a name in a signature font, half procedural scribbles."""
        return self.rng.choice(self.signatures).family if self.rng.random() < 0.5 else None


def default_style(seed: int, split: Literal["dev", "test"] = "dev") -> Style:
    return Style(
        rng=random.Random(seed),
        hands=load_fonts("hand_dev" if split == "dev" else "hand_test"),
        signatures=load_fonts("signature"),
    )


@dataclass
class TruthSpec:
    fields: dict[str, tuple[Any, FieldStatus, bool]] = field(default_factory=dict)
    marks: dict[str, MarkState] = field(default_factory=dict)

    def put(self, path: str, value: Any, *, hand: bool = False) -> None:
        empty = value is None or value == []
        self.fields[path] = (value, "empty" if empty else "present", hand)


# --- Muster 12 ------------------------------------------------------------------

M12_ROWS = [
    ("medikamentengabe", "Medikamentengabe"),
    ("injektion", "Injektionen"),
    ("blutzucker", "Blutzuckermessung"),
    ("kompression", "Kompressionsbehandlung"),
    ("wundversorgung", "Wundversorgung"),
    ("positionswechsel", "Positionswechsel"),
    ("sonstige", "Sonstige Maßnahmen"),
]


# Inner widths (mm) of the Muster 12 cells, from muster12.html.j2: handwriting that would
# not fit is written smaller instead of running into the next cell.
M12_CELL_MM = {
    "payer_name": 124, "patient_name": 97, "patient_dob": 23, "payer_ik": 47, "kvnr": 47,
    "bsnr": 47, "lanr": 47, "issue_date": 23, "period_from": 44, "period_to": 44,
    "icd_codes": 185, "limitations": 185, "further_notes": 185,
    "details": 66, "frequency": 19, "duration_from": 24, "duration_to": 24,
}  # fmt: skip


def build_muster12(c: Muster12Content, style: Style) -> tuple[dict[str, Any], TruthSpec]:
    rng = style.rng
    mode = rng.choices(["printed", "mixed", "handwritten"], weights=[0.35, 0.4, 0.25])[0]
    doctor = style.hand(INKS["blue"] if rng.random() < 0.7 else INKS["black"])
    truth = TruthSpec()

    def put(path: str, text: str | None, value: Any, by_hand: bool, min_mm: float = 18) -> Markup:
        truth.put(path, value, hand=by_hand and text is not None)
        if not by_hand:
            return printed(text, path, min_mm)
        return doctor.write(text, path, min_mm, M12_CELL_MM[path.rsplit(".", 1)[-1]])

    header_by_hand = mode == "handwritten"
    loose_by_hand = mode != "printed"  # dates, ticks, frequencies
    cells: dict[str, Markup] = {
        "payer_name": put("payer_name", c.payer_name, c.payer_name, header_by_hand),
        "patient_name": put("patient_name", c.patient_name, c.patient_name, header_by_hand),
        "patient_dob": put(
            "patient_dob", de_date(c.patient_dob), c.patient_dob.isoformat(), header_by_hand
        ),
        "payer_ik": put("payer_ik", c.payer_ik, c.payer_ik, header_by_hand),
        "kvnr": put("kvnr", c.kvnr, c.kvnr, header_by_hand),
        "status": printed(c.status),
        "bsnr": put("bsnr", c.bsnr, c.bsnr, header_by_hand),
        "lanr": put("lanr", c.lanr, c.lanr, header_by_hand),
        "issue_date": put(
            "issue_date", de_date(c.issue_date), c.issue_date.isoformat(), loose_by_hand
        ),
        "period_from": put(
            "period_from", de_date(c.period_from), c.period_from.isoformat(), loose_by_hand
        ),
        "period_to": put("period_to", de_date(c.period_to), c.period_to.isoformat(), loose_by_hand),
        "icd_codes": put("icd_codes", ", ".join(c.icd_codes), c.icd_codes, header_by_hand, 40),
        "limitations": doctor.write(c.limitations, max_mm=M12_CELL_MM["limitations"])
        if header_by_hand
        else printed(c.limitations),
        "further_notes": put("further_notes", c.further_notes, c.further_notes, loose_by_hand, 60),
    }

    tick = doctor.tick if loose_by_hand else printed_tick
    cells["kind_erst"] = tick(c.kind == "erst", "prescription_kind" if c.kind == "erst" else None)
    cells["kind_folge"] = tick(
        c.kind == "folge", "prescription_kind" if c.kind == "folge" else None
    )
    truth.put("prescription_kind", c.kind, hand=loose_by_hand)
    cells["accident"] = tick(c.accident, "accident")
    truth.put("accident", c.accident, hand=loose_by_hand)
    cells["blank"] = tick(c.blank, "blank_prescription")
    truth.put("blank_prescription", c.blank, hand=loose_by_hand)

    rows = []
    by_category = {m.category: m for m in c.measures}
    index = 0
    for category, label in M12_ROWS:
        m = by_category.get(category)
        if m is None:
            rows.append(
                {
                    "tick": tick(False),
                    "label": label,
                    "details": "",
                    "frequency": "",
                    "duration_from": "",
                    "duration_to": "",
                }
            )
            continue
        p = f"measures[{index}]"
        index += 1
        truth.put(f"{p}.category", m.category, hand=loose_by_hand)
        if m.count is None or m.per is None:
            freq_text, freq_field = None, f"{p}.frequency"
            truth.put(freq_field, None)
        else:
            freq_text = f"{m.count}x {PER_LABEL[m.per]}"
            truth.put(f"{p}.frequency.count", m.count, hand=loose_by_hand)
            truth.put(f"{p}.frequency.per", m.per, hand=loose_by_hand)
            freq_field = f"{p}.frequency.count {p}.frequency.per"
        rows.append(
            {
                "tick": tick(True, f"{p}.category"),
                "label": label,
                "details": put(f"{p}.details", m.details, m.details, header_by_hand, 40),
                "frequency": doctor.write(freq_text, freq_field, 12, M12_CELL_MM["frequency"])
                if loose_by_hand
                else printed(freq_text, freq_field, 12),
                "duration_from": put(
                    f"{p}.duration_from",
                    de_date(m.duration_from),
                    m.duration_from.isoformat(),
                    loose_by_hand,
                ),
                "duration_to": put(
                    f"{p}.duration_to",
                    de_date(m.duration_to),
                    m.duration_to.isoformat(),
                    loose_by_hand,
                ),
            }
        )
    truth.put("measures[#]", index)

    cells["practice_stamp"] = stamp(c.stamp_present, "practice_stamp", c.practice_lines, rng)
    cells["doctor_signature"] = signature(
        c.doctor_signed,
        "doctor_signature",
        rng,
        ink=doctor.ink,
        name=c.doctor_name.split()[-1],
        font=style.signature_font(),
    )
    truth.marks["practice_stamp"] = "present" if c.stamp_present else "absent"
    truth.marks["doctor_signature"] = "present" if c.doctor_signed else "absent"
    truth.marks["corrections_initialled"] = "absent"
    truth.put("corrections_present", False)
    truth.fields["doc_type"] = ("muster12", "present", False)

    context = {"c": cells, "rows": rows, "size_mm": A4_PORTRAIT, "margin_mm": 10, "mode": mode}
    return context, truth


# --- Leistungsnachweis SGB V ----------------------------------------------------


def build_visit_log_sgbv(c: VisitLogContent, style: Style) -> tuple[dict[str, Any], TruthSpec]:
    rng = style.rng
    office = style.hand(INKS["black"])
    nurses = [style.hand() for _ in c.staff]
    truth = TruthSpec()
    days = calendar.monthrange(c.year, c.month)[1]

    visits = sorted(c.visits, key=lambda v: (v.day, v.service, v.slot))
    index_of = {(v.day, v.service, v.slot): i for i, v in enumerate(visits)}
    for i, v in enumerate(visits):
        s = c.services[v.service]
        p = f"entries[{i}]"
        truth.put(f"{p}.date", dt.date(c.year, c.month, v.day).isoformat())
        truth.put(f"{p}.start_time", v.time.strftime("%H:%M"), hand=True)
        truth.put(f"{p}.end_time", None)
        truth.put(f"{p}.position_no", s.position_no)
        truth.put(f"{p}.service", s.label)
        truth.put(f"{p}.quantity", 1)
        initials = c.staff[v.staff].initials if v.staff is not None else None
        truth.put(f"{p}.staff_initials", initials, hand=True)
        truth.put(f"{p}.employee_no", None)
        truth.put(f"{p}.initials_state", "present" if initials else "absent")
    truth.put("entries[#]", len(visits))

    grid = []
    for day in range(1, days + 1):
        date = dt.date(c.year, c.month, day)
        day_paths = [f"entries[{index_of[k]}].date" for k in index_of if k[0] == day]
        cells = []
        for si, s in enumerate(c.services):
            for slot in range(s.slots):
                i = index_of.get((day, si, slot))
                if i is None:
                    cells.append({"time": "", "initials": ""})
                    continue
                v = visits[i]
                nurse = nurses[v.staff] if v.staff is not None else rng.choice(nurses)
                initials = c.staff[v.staff].initials if v.staff is not None else None
                cells.append(
                    {
                        "time": nurse.write(v.time.strftime("%H:%M"), f"entries[{i}].start_time"),
                        "initials": nurse.write(
                            initials, f"entries[{i}].staff_initials entries[{i}].initials_state", 6
                        ),
                    }
                )
        grid.append(
            {
                "label": Markup(
                    f'<span data-field="{" ".join(day_paths)}">'
                    f"{WEEKDAYS[date.weekday()]} {day:02d}.</span>"
                ),
                "weekend": date.weekday() >= 5,
                "cells": cells,
            }
        )

    services = []
    for si, s in enumerate(c.services):
        paths = [
            f"entries[{i}].position_no entries[{i}].service"
            for (d, svc, sl), i in index_of.items()
            if svc == si
        ]
        services.append(
            {
                "position_no": Markup(
                    f'<span data-field="{" ".join(paths)}">{s.position_no}</span>'
                ),
                "label": s.label,
                "slots": s.slots,
            }
        )

    month_text = f"{c.month:02d}/{c.year}"
    cells: dict[str, Markup] = {
        "provider_ik": printed(c.provider_ik, "provider_ik"),
        "month": printed(month_text, "month"),
        "approval_ref": printed(c.approval_ref, "approval_ref"),
        "patient_name": printed(c.patient_name, "patient_name"),
        "kvnr": printed(c.kvnr, "kvnr"),
        "payer_name": printed(c.payer_name, "payer_name"),
        "responsible_nurse": printed(c.responsible_nurse, "responsible_nurse"),
    }
    for key, value in (
        ("provider_ik", c.provider_ik),
        ("month", f"{c.year}-{c.month:02d}"),
        ("approval_ref", c.approval_ref),
        ("patient_name", c.patient_name),
        ("kvnr", c.kvnr),
        ("payer_name", c.payer_name),
        ("responsible_nurse", c.responsible_nurse),
    ):
        truth.put(key, value)

    family = style.hand(INKS["blue"])
    cells["patient_signature"] = signature(
        c.patient_signed,
        "patient_signature",
        rng,
        ink=family.ink,
        name=c.patient_name.split(",")[0],
        font=style.signature_font(),
    )
    sig_date = c.patient_signature_date
    cells["patient_signature_date"] = family.write(
        de_date(sig_date) if sig_date else None, "patient_signature_date", 20
    )
    truth.put("patient_signature_date", sig_date.isoformat() if sig_date else None, hand=True)
    cells["missing_signature_reason"] = office.write(
        c.missing_signature_reason, "missing_signature_reason", 8
    )
    truth.put("missing_signature_reason", c.missing_signature_reason, hand=True)
    cells["provider_signature"] = signature(
        c.provider_signed,
        "provider_signature",
        rng,
        ink=office.ink,
        font=style.signature_font(),
        name="Pflegedienst",
    )
    truth.marks["patient_signature"] = "present" if c.patient_signed else "absent"
    truth.marks["provider_signature"] = "present" if c.provider_signed else "absent"
    truth.fields["doc_type"] = ("visit_log_sgbv", "present", False)

    slots = sum(s.slots for s in c.services)
    usable = A4_LANDSCAPE[0] - 2 * 8
    day_mm = 16
    time_mm = min(30, (usable - day_mm) / slots * 0.6)
    hz_mm = min(20, (usable - day_mm) / slots * 0.4)
    context = {
        "c": cells,
        "services": services,
        "grid": grid,
        "provider_name": c.provider_name,
        "month_label": f"{GERMAN_MONTHS[c.month - 1]} {c.year}",
        "size_mm": A4_LANDSCAPE,
        "margin_mm": 8,
        "row_mm": 4.3,
        "cell_pt": 8.5 if slots > 4 else 9.0,
        "day_mm": day_mm,
        "time_mm": round(time_mm, 1),
        "hz_mm": round(hz_mm, 1),
        "table_mm": round(day_mm + slots * (time_mm + hz_mm), 1),
    }
    return context, truth


# --- Genehmigung (approval letter) ---------------------------------------------------

DECISION_DE = {"approved": "genehmigt", "partial": "teilweise genehmigt", "rejected": "abgelehnt"}
PER_DE = {"day": "täglich", "week": "wöchentlich", "month": "monatlich"}


def build_approval_letter(
    c: ApprovalLetterContent, style: Style
) -> tuple[dict[str, Any], TruthSpec]:
    truth = TruthSpec()

    def put(path: str, text: str | None, value: Any, min_mm: float = 18) -> Markup:
        truth.put(path, value)
        return printed(text, path, min_mm)

    def date(path: str, d: dt.date) -> Markup:
        return put(path, de_date(d), d.isoformat())

    cells: dict[str, Any] = {
        "payer_name": put("payer_name", c.payer_name, c.payer_name),
        "payer_ik": put("payer_ik", c.payer_ik, c.payer_ik),
        "letter_date": date("letter_date", c.letter_date),
        "approval_ref": put("approval_ref", c.approval_ref, c.approval_ref),
        "patient_name": put("patient_name", c.patient_name, c.patient_name),
        "patient_dob": printed(de_date(c.patient_dob)),
        "kvnr": put("kvnr", c.kvnr, c.kvnr),
        "provider_name": put("provider_name", c.provider_name, c.provider_name),
        "provider_ik": put("provider_ik", c.provider_ik, c.provider_ik),
        "prescription_issue_date": date("prescription_issue_date", c.prescription_issue_date),
        "decision": put("decision", DECISION_DE[c.decision], c.decision),
        "period_from": date("period_from", c.period_from),
        "period_to": date("period_to", c.period_to),
    }
    approved = []
    for i, a in enumerate(c.approved):
        p = f"approved_items[{i}]"
        if a.count is None or a.per is None:
            truth.put(f"{p}.frequency", None)
            freq = printed("lt. Verordnung", f"{p}.frequency")
        else:
            truth.put(f"{p}.frequency.count", a.count)
            truth.put(f"{p}.frequency.per", a.per)
            freq = printed(f"{a.count}x {PER_DE[a.per]}", f"{p}.frequency.count {p}.frequency.per")
        approved.append(
            {
                "position_no": put(f"{p}.position_no", a.position_no, a.position_no, 12),
                "description": put(f"{p}.description", a.description, a.description),
                "frequency": freq,
                "valid_from": date(f"{p}.valid_from", a.valid_from),
                "valid_to": date(f"{p}.valid_to", a.valid_to),
            }
        )
    truth.put("approved_items[#]", len(c.approved))
    rejected = []
    for i, r in enumerate(c.rejected):
        p = f"rejected_items[{i}]"
        rejected.append(
            {
                "description": put(f"{p}.description", r.description, r.description),
                "reason": put(f"{p}.reason", r.reason, r.reason),
            }
        )
    truth.put("rejected_items[#]", len(c.rejected))
    truth.fields["doc_type"] = ("approval_letter", "present", False)

    context = {
        "template": f"approval_letter_{c.style}.html.j2",
        "c": cells,
        "approved": approved,
        "rejected": rejected,
        "raw": c,
        "salutation": "Sehr geehrte Damen und Herren,",
        "copay": "von der gesetzlichen Zuzahlung befreit"
        if c.copay_exempt
        else "zuzahlungspflichtig (10 % der Kosten zzgl. 10 € je Verordnung, max. 28 Tage)",
        "size_mm": A4_PORTRAIT,
        "margin_mm": 18,
    }
    return context, truth


# --- Leistungsnachweis SGB XI ---------------------------------------------------------


def build_visit_log_sgbxi(c: VisitLogXIContent, style: Style) -> tuple[dict[str, Any], TruthSpec]:
    rng = style.rng
    nurses = [style.hand() for _ in c.staff]
    truth = TruthSpec()
    days = calendar.monthrange(c.year, c.month)[1]

    # Entry order: day, then Einsatz, then the Einsatz's LK order.
    visits = sorted(c.visits, key=lambda v: (v.day, v.einsatz))
    entries: list[tuple[XIVisit, str]] = []
    for v in visits:
        order = [code for code, _ in c.einsaetze[v.einsatz].lk]
        entries += [(v, code) for code in order if code in v.lk]
    labels = {code: label for e in c.einsaetze for code, label in e.lk}
    paths: dict[str, list[str]] = {}  # cell key -> paths, for data-field attributes

    def add(key: str, *names: str) -> None:
        paths.setdefault(key, []).extend(names)

    for i, (v, code) in enumerate(entries):
        p = f"entries[{i}]"
        e = c.einsaetze[v.einsatz]
        initials = c.staff[v.staff].initials if v.staff is not None else None
        truth.put(f"{p}.date", dt.date(c.year, c.month, v.day).isoformat())
        truth.put(f"{p}.time", v.time.strftime("%H:%M"), hand=True)
        truth.put(f"{p}.lk_code", code)
        truth.put(f"{p}.lk_label", labels[code])
        truth.put(f"{p}.count", 1, hand=True)
        truth.put(f"{p}.funding", e.funding)
        truth.put(f"{p}.staff_initials", initials, hand=True)
        truth.put(f"{p}.initials_state", "present" if initials else "absent")
        add(f"day:{v.day}", f"{p}.date")
        add(f"time:{v.einsatz}:{v.day}", f"{p}.time")
        add(f"row:{v.einsatz}:{code}", f"{p}.lk_code", f"{p}.lk_label")
        add(f"cell:{v.einsatz}:{code}:{v.day}", f"{p}.count", f"{p}.staff_initials")
        add(f"cell:{v.einsatz}:{code}:{v.day}", f"{p}.initials_state")
        add(f"funding:{e.funding}", f"{p}.funding")
    truth.put("entries[#]", len(entries))

    def field(key: str) -> str | None:
        return " ".join(paths[key]) if key in paths else None

    by_slot = {(v.einsatz, v.day): v for v in visits}
    sections = []
    for funding, title in (
        ("sachleistung_36", "Pflegesachleistung § 36 SGB XI"),
        ("entlastung_45b", "Entlastungsbetrag § 45b SGB XI"),
    ):
        rows = []
        for ei, e in enumerate(c.einsaetze):
            if e.funding != funding:
                continue
            times = []
            for day in range(1, days + 1):
                v = by_slot.get((ei, day))
                nurse = nurses[v.staff] if v and v.staff is not None else rng.choice(nurses)
                text = f"{v.time.hour}:{v.time.minute:02d}" if v else None
                times.append(nurse.write(text, field(f"time:{ei}:{day}"), 4) if v else "")
            rows.append({"kind": "time", "label": f"{e.label} · Uhrzeit", "cells": times})
            for code, label in e.lk:
                cells = []
                for day in range(1, days + 1):
                    v = by_slot.get((ei, day))
                    if v is None or code not in v.lk:
                        cells.append("")
                        continue
                    initials = c.staff[v.staff].initials if v.staff is not None else None
                    nurse = nurses[v.staff] if v.staff is not None else rng.choice(nurses)
                    cells.append(nurse.write(initials, field(f"cell:{ei}:{code}:{day}"), 4))
                rows.append(
                    {
                        "kind": "lk",
                        "label": Markup(
                            f'<span data-field="{field(f"row:{ei}:{code}") or ""}">'
                            f"{code} {escape(label)}</span>"
                        ),
                        "cells": cells,
                    }
                )
        if rows:
            sections.append(
                {
                    "title": Markup(
                        f'<span data-field="{field(f"funding:{funding}") or ""}">{title}</span>'
                    ),
                    "rows": rows,
                }
            )

    header_days = []
    for day in range(1, days + 1):
        date = dt.date(c.year, c.month, day)
        header_days.append(
            {
                "label": Markup(f'<span data-field="{field(f"day:{day}") or ""}">{day}</span>'),
                "weekday": WEEKDAYS[date.weekday()],
                "weekend": date.weekday() >= 5,
            }
        )

    cells: dict[str, Markup] = {}
    for key, text, value in (
        ("provider_ik", c.provider_ik, c.provider_ik),
        ("month", f"{c.month:02d}/{c.year}", f"{c.year}-{c.month:02d}"),
        ("patient_name", c.patient_name, c.patient_name),
        ("kvnr", c.kvnr, c.kvnr),
        ("payer_name", c.payer_name, c.payer_name),
        ("pflegegrad", str(c.pflegegrad), c.pflegegrad),
    ):
        cells[key] = printed(text, key)
        truth.put(key, value)

    family = style.hand(INKS["blue"])
    cells["patient_signature"] = signature(
        c.patient_signed,
        "patient_signature",
        rng,
        ink=family.ink,
        name=c.patient_name.split(",")[0],
        font=style.signature_font(),
    )
    sig_date = c.patient_signature_date if c.patient_signed else None
    cells["patient_signature_date"] = family.write(de_date(sig_date) if sig_date else None, None)
    cells["provider_signature"] = signature(
        c.provider_signed,
        "provider_signature",
        rng,
        ink=INKS["black"],
        font=style.signature_font(),
        name="Pflegedienst",
    )
    truth.marks["patient_signature"] = "present" if c.patient_signed else "absent"
    truth.marks["provider_signature"] = "present" if c.provider_signed else "absent"
    truth.fields["doc_type"] = ("visit_log_sgbxi", "present", False)

    margin_mm, label_mm = 8, 47
    day_mm = round((A4_LANDSCAPE[0] - 2 * margin_mm - label_mm) / days, 2)
    context = {
        "c": cells,
        "sections": sections,
        "days": header_days,
        "provider_name": c.provider_name,
        "month_label": f"{GERMAN_MONTHS[c.month - 1]} {c.year}",
        "size_mm": A4_LANDSCAPE,
        "margin_mm": margin_mm,
        "label_mm": label_mm,
        "day_mm": day_mm,
        "table_mm": round(label_mm + days * day_mm, 1),
    }
    return context, truth


# --- Entlassbrief ---------------------------------------------------------------------


def build_hospital_letter(
    c: HospitalLetterContent, style: Style
) -> tuple[dict[str, Any], TruthSpec]:
    rng = style.rng
    truth = TruthSpec()

    def put(path: str, text: str | None, value: Any, min_mm: float = 14) -> Markup:
        truth.put(path, value)
        return printed(text, path, min_mm)

    cells: dict[str, Any] = {
        "hospital_name": put("hospital_name", c.hospital_name, c.hospital_name),
        "hospital_id": put("hospital_id", c.hospital_id, c.hospital_id),
        "patient_name": put("patient_name", c.patient_name, c.patient_name),
        "patient_dob": put("patient_dob", de_date(c.patient_dob), c.patient_dob.isoformat()),
        "kvnr": put("kvnr", c.kvnr, c.kvnr),
        "admission_date": put(
            "admission_date", de_date(c.admitted_at.date()), c.admitted_at.date().isoformat()
        ),
        "admission_time": put(
            "admission_time", c.admitted_at.strftime("%H:%M"), c.admitted_at.strftime("%H:%M")
        ),
        "discharge_date": put(
            "discharge_date", de_date(c.discharged_at.date()), c.discharged_at.date().isoformat()
        ),
        "discharge_time": put(
            "discharge_time",
            c.discharged_at.strftime("%H:%M"),
            c.discharged_at.strftime("%H:%M"),
        ),
    }
    truth.put("discharge_diagnoses", [code for code, _ in c.diagnoses])
    cells["diagnoses"] = Markup("").join(
        Markup('<div class="dx">{}<span class="dxt"> {}</span></div>').format(printed(code), text)
        for code, text in c.diagnoses
    )
    if c.hkp_recommended:
        text = c.hkp_text or "Fortführung der häuslichen Krankenpflege empfohlen."
    else:
        text = "Häusliche Krankenpflege ist nach Entlassung nicht erforderlich."
    cells["hkp_recommended"] = Markup('<span data-field="hkp_recommended">{}</span>').format(text)
    truth.put("hkp_recommended", c.hkp_recommended)
    days = c.hkp_prescription_days
    cells["hkp_days"] = (
        Markup(
            "Im Rahmen des Entlassmanagements wurde häusliche Krankenpflege für {} Tage verordnet."
        ).format(printed(str(days), "hkp_prescription_days"))
        if days
        else ""
    )
    truth.put("hkp_prescription_days", days)
    cells["physician_signature"] = signature(
        c.signed,
        "physician_signature",
        rng,
        ink=INKS["blue"] if rng.random() < 0.7 else INKS["black"],
        name=c.physician.split(",")[0].split()[-1],
        font=style.signature_font(),
    )
    truth.marks["physician_signature"] = "present" if c.signed else "absent"
    truth.fields["doc_type"] = ("hospital_letter", "present", False)

    los = (c.discharged_at.date() - c.admitted_at.date()).days
    context = {
        "c": cells,
        "raw": c,
        "title": "Frau" if c.patient_sex == "f" else "Herr",
        "pronoun": "Ihre Patientin" if c.patient_sex == "f" else "Ihren Patienten",
        "los": los,
        "letter_date": de_date(c.letter_date),
        "size_mm": A4_PORTRAIT,
        "margin_mm": 18,
    }
    return context, truth


# --- Render + ground truth --------------------------------------------------------

BUILDERS: dict[str, Any] = {
    "muster12": build_muster12,
    "visit_log_sgbv": build_visit_log_sgbv,
    "visit_log_sgbxi": build_visit_log_sgbxi,
    "approval_letter": build_approval_letter,
    "hospital_letter": build_hospital_letter,
}
# Form colours per document type: (form_ink, shade).
FORM_COLOURS = {
    "visit_log_sgbv": ("#2b2b2b", "#efefef"),
    "visit_log_sgbxi": ("#1f4e5f", "#e8f0f2"),
    "approval_letter": ("#1d1d1f", "#eef0f3"),
    "hospital_letter": ("#1d1d1f", "#f1f1f1"),
}


def render_document(
    renderer: Renderer,
    doc_type: str,
    content: BaseModel,
    *,
    doc_id: str,
    seed: int,
    split: Literal["dev", "test"] = "dev",
) -> tuple[RenderedPage, TruthSpec, dict[str, Any]]:
    style = default_style(seed, split)
    if doc_type in FORM_COLOURS:
        style.form_ink, style.shade = FORM_COLOURS[doc_type]
    context, truth = BUILDERS[doc_type](content, style)
    # Embed every face of the split: simpler than tracking which ones the dice picked.
    faces = [*load_fonts("print"), *load_fonts("mono"), *style.hands, *style.signatures]
    template = context.get("template", f"{doc_type}.html.j2")
    html = templates.get_template(template).render(
        **context,
        font_css=font_face_css(faces),
        form_ink=style.form_ink,
        shade=style.shade,
        paper=style.paper,
        doc_id=doc_id,
    )
    page = renderer.render(html, context["size_mm"])
    return page, truth, context


def ground_truth(
    page: RenderedPage,
    truth: TruthSpec,
    *,
    doc_id: str,
    doc_type: str,
    variant: Variant,
    seed: int,
    image_name: str,
    patient_id: str | None = None,
    month: str | None = None,
    defects: list[str] | None = None,
) -> GroundTruth:
    fields = {
        path: GTField(
            value=value, status=status, page=0, box=page.fields.get(path), handwritten=hand
        )
        for path, (value, status, hand) in truth.fields.items()
    }
    regions = {}
    for name, state in truth.marks.items():
        box = page.ink.get(name) if state == "present" else None
        box = box or page.regions.get(name)
        if box:
            regions[name] = GTRegion(page=0, box=box, state=state)
        fields[name] = GTField(value=state, status="present", page=0, box=box)
    return GroundTruth(
        doc_id=doc_id,
        doc_type=doc_type,  # type: ignore[arg-type]
        variant=variant,
        seed=seed,
        patient_id=patient_id,
        month=month,
        pages=[GTPage(index=0, image=image_name, width=page.image.width, height=page.image.height)],
        fields=fields,
        regions=regions,
        defects=defects or [],  # type: ignore[arg-type]
    )
