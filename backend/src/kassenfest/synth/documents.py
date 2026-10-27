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

from markupsafe import Markup
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
    count: int
    per: Literal["day", "week", "month"]
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


def build_muster12(c: Muster12Content, style: Style) -> tuple[dict[str, Any], TruthSpec]:
    rng = style.rng
    mode = rng.choices(["printed", "mixed", "handwritten"], weights=[0.35, 0.4, 0.25])[0]
    doctor = style.hand(INKS["blue"] if rng.random() < 0.7 else INKS["black"])
    truth = TruthSpec()

    def put(path: str, text: str | None, value: Any, by_hand: bool, min_mm: float = 18) -> Markup:
        truth.put(path, value, hand=by_hand and text is not None)
        return doctor.write(text, path, min_mm) if by_hand else printed(text, path, min_mm)

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
        "limitations": doctor.write(c.limitations) if header_by_hand else printed(c.limitations),
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
        freq_text = f"{m.count}x {PER_LABEL[m.per]}"
        truth.put(f"{p}.frequency.count", m.count, hand=loose_by_hand)
        truth.put(f"{p}.frequency.per", m.per, hand=loose_by_hand)
        freq_field = f"{p}.frequency.count {p}.frequency.per"
        rows.append(
            {
                "tick": tick(True, f"{p}.category"),
                "label": label,
                "details": put(f"{p}.details", m.details, m.details, header_by_hand, 40),
                "frequency": doctor.write(freq_text, freq_field)
                if loose_by_hand
                else printed(freq_text, freq_field),
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
        "cell_pt": 9.5 if slots > 4 else 10.5,
        "day_mm": day_mm,
        "time_mm": round(time_mm, 1),
        "hz_mm": round(hz_mm, 1),
        "table_mm": round(day_mm + slots * (time_mm + hz_mm), 1),
    }
    return context, truth


# --- Render + ground truth --------------------------------------------------------

BUILDERS = {"muster12": build_muster12, "visit_log_sgbv": build_visit_log_sgbv}


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
    if doc_type == "visit_log_sgbv":
        style.form_ink, style.shade = "#2b2b2b", "#efefef"
    context, truth = BUILDERS[doc_type](content, style)
    # Embed every face of the split: simpler than tracking which ones the dice picked.
    faces = [*load_fonts("print"), *load_fonts("mono"), *style.hands, *style.signatures]
    html = templates.get_template(f"{doc_type}.html.j2").render(
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
