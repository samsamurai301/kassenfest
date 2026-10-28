"""The screens' World from the pipeline: stored documents → evaluated month.

Rebuilt whenever the database changes (a document finished or was re-processed), else
served from memory. Same `World` as the fixtures, so the routes don't care which.
"""

import datetime as dt
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, func
from sqlmodel import select

from kassenfest.api.fixtures import World
from kassenfest.api.models import DocumentField, DocumentInfo, PageInfo
from kassenfest.config import Settings
from kassenfest.db import Document, Extraction, create_db, session_scope
from kassenfest.pipeline.link import value
from kassenfest.pipeline.month import Month, StoredDoc, evaluate_month
from kassenfest.rules.calendar import calendar_for
from kassenfest.rules.reference import load_reference
from kassenfest.rules.tariffs import claim_id
from kassenfest.schemas.common import Extracted, Mark
from kassenfest.schemas.extraction import (
    ApprovedItem,
    CareEntry,
    Located,
    PrescribedMeasure,
    RejectedItem,
    VisitEntry,
)
from kassenfest.schemas.findings import Finding
from kassenfest.schemas.records import MasterData
from kassenfest.storage import BlobStore

TARIFF_NOTE = (
    "Prices come from data/reference: illustrative demo values, not a real §132a or §89 contract."
)

LABELS = {
    "payer_name": "Krankenkasse bzw. Kostenträger",
    "payer_ik": "Kostenträgerkennung",
    "patient_name": "Name, Vorname des Versicherten",
    "patient_dob": "geb. am",
    "kvnr": "Versicherten-Nr.",
    "bsnr": "Betriebsstätten-Nr.",
    "lanr": "Arzt-Nr.",
    "issue_date": "Datum",
    "icd_codes": "Diagnose(n) (ICD-10)",
    "prescription_kind": "Erst-/Folgeverordnung",
    "accident": "Unfall, Unfallfolgen",
    "blank_prescription": "Blankoverordnung",
    "period_from": "vom",
    "period_to": "bis",
    "further_notes": "Weitere Hinweise",
    "doctor_signature": "Unterschrift des Arztes",
    "practice_stamp": "Vertragsarztstempel",
    "corrections_initialled": "Korrektur abgezeichnet",
    "letter_date": "Datum des Schreibens",
    "approval_ref": "Genehmigungskennzeichen",
    "provider_name": "Pflegedienst",
    "provider_ik": "IK Pflegedienst",
    "prescription_issue_date": "Verordnung vom",
    "decision": "Entscheidung",
    "month": "Monat",
    "responsible_nurse": "Verantwortliche Pflegefachkraft",
    "patient_signature": "Unterschrift Versicherte/r",
    "patient_signature_date": "Datum der Unterschrift",
    "missing_signature_reason": "Kennzeichen fehlende Unterschrift",
    "provider_signature": "Unterschrift / Stempel Pflegedienst",
    "pflegegrad": "Pflegegrad",
    "hospital_name": "Krankenhaus",
    "hospital_id": "Standortkennzeichen",
    "admission_date": "Aufnahme",
    "admission_time": "Aufnahme, Uhrzeit",
    "discharge_date": "Entlassung",
    "discharge_time": "Entlassung, Uhrzeit",
    "discharge_diagnoses": "Entlassdiagnosen",
    "hkp_recommended": "Häusliche Krankenpflege empfohlen",
    "hkp_prescription_days": "HKP-Tage verordnet",
    "physician_signature": "Unterschrift Arzt",
}
ROWS = {
    "measures": "Maßnahme",
    "approved_items": "Genehmigt",
    "rejected_items": "Abgelehnt",
    "entries": "Zeile",
}
_MARK_STATUS = {"present": "present", "absent": "empty", "unclear": "unreadable"}


def _de(iso: str | None) -> str:
    return dt.date.fromisoformat(iso).strftime("%d.%m.") if iso else "?"


def _row(item: Located) -> str:
    """One list row as a short line for the field list."""
    match item:
        case VisitEntry():
            parts = [_de(item.date), item.start_time, item.position_no, item.staff_initials]
        case CareEntry():
            parts = [_de(item.date), item.time, item.lk_code, item.staff_initials]
        case PrescribedMeasure():
            freq = item.frequency
            parts = [item.category, freq and f"{freq.count}×/{freq.per}", item.details]
        case ApprovedItem():
            parts = [item.position_no, item.description, f"bis {_de(item.valid_to)}"]
        case RejectedItem():
            parts = [item.description, item.reason]
        case _:
            parts = []
    return " · ".join(str(p) for p in parts if p)


def _text(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return "ja" if raw else "nein"
    if isinstance(raw, list):
        return ", ".join(map(str, raw))
    return str(raw)


def document_fields(doc: StoredDoc) -> list[DocumentField]:
    """What the viewer lists: every field, mark and row the model placed on the page."""
    ext = doc.extraction
    if ext is None:
        return []
    out = []
    for name in type(ext).model_fields:
        item = getattr(ext, name)
        if isinstance(item, Extracted | Mark) and name in doc.boxes:
            page, box = doc.boxes[name]
            status = item.status if isinstance(item, Extracted) else _MARK_STATUS[item.state]
            shown = _text(item.value) if isinstance(item, Extracted) else None
            label = LABELS.get(name, name)
            out.append(
                DocumentField(
                    path=name, label=label, value=shown, status=status, page=page, box=box
                )
            )
        elif isinstance(item, list) and name in ROWS:
            for i, row in enumerate(item):
                if (path := f"{name}[{i}]") in doc.boxes:
                    page, box = doc.boxes[path]
                    label = f"{ROWS[name]} {i + 1}"
                    out.append(
                        DocumentField(
                            path=path,
                            label=label,
                            value=_row(row),
                            status="present",
                            page=page,
                            box=box,
                        )
                    )
    return out


def title(doc: StoredDoc) -> str:
    ext = doc.extraction
    if ext is None:
        return doc.document.filename

    def get(name: str):
        return value(ext, name)

    match doc.document.doc_type:
        case "muster12":
            which = {"erst": "Erstverordnung", "folge": "Folgeverordnung"}.get(
                get("prescription_kind"), "Verordnung"
            )
            return f"Muster 12, {which} of {_long(get('issue_date'))}"
        case "approval_letter":
            return f"Genehmigung {get('approval_ref') or ''}, {_long(get('letter_date'))}".strip()
        case "visit_log_sgbv":
            return f"Leistungsnachweis, {_month(get('month'))}"
        case "visit_log_sgbxi":
            return f"Leistungsnachweis Pflege, {_month(get('month'))}"
        case "hospital_letter":
            return f"Entlassbrief, {get('hospital_name') or 'Krankenhaus'}"
    return doc.document.filename


def _long(iso: str | None) -> str:
    return dt.date.fromisoformat(iso).strftime("%-d %b") if iso else "unknown date"


def _month(ym: str | None) -> str:
    return dt.date.fromisoformat(f"{ym}-01").strftime("%B") if ym else "unknown month"


def _assign_claims(month: Month, findings: list[Finding]) -> list[Finding]:
    """Document findings (no lines) go on the claim their document feeds: a visit log on its
    own claim, a Verordnung or Genehmigung on the patient's HKP claim."""
    by_log = {
        log.document_id: claim_id(log) for case in month.cases.values() for log in case.visit_logs
    }
    hkp = {pid: c.id for pid, r in month.results.items() for c in r.claims if c.domain == "sgbv"}
    out = []
    for f in findings:
        if f.claim_id is None and not f.claim_line_ids and f.evidence:
            doc = month.docs.get(f.evidence[0].document_id)
            target = by_log.get(f.evidence[0].document_id)
            if target is None and doc and doc.document.doc_type in ("muster12", "approval_letter"):
                target = hkp.get(f.patient_id)
            f = f.model_copy(update={"claim_id": target})
        out.append(f)
    return out


def _holidays(records: MasterData) -> dict[dt.date, str]:
    cal = calendar_for(records.provider.bundesland, records.provider.municipality)
    first = dt.date.fromisoformat(f"{records.month}-01")
    days = (first + dt.timedelta(days=i) for i in range(31))
    return {
        d: name
        for d in days
        if d.month == first.month and (name := cal.holiday_name(d)) is not None
    }


def build_world(engine: Engine, records: MasterData, blob_dir: Path) -> World:
    month = evaluate_month(engine, records, records.month)
    blobs = BlobStore(blob_dir)
    ref = load_reference()
    w = World(
        source="pipeline",
        month=records.month,
        as_of=dt.date.today(),
        provider=records.provider,
        payers={p.ik: p for p in records.payers},
        physicians={p.lanr: p for p in records.physicians},
        code_labels={code: p.label_de for code, p in ref.hkp_positions.items()}
        | {lk: info.label_de for lk, info in ref.leistungskomplexe.items()},
        holidays=_holidays(records),
        tariff_note=TARIFF_NOTE,
    )
    linked = {d.patient_id for d in month.docs.values() if d.patient_id}
    w.patients = {p.id: p for p in records.patients if p.id in linked}
    for case in month.cases.values():
        w.prescriptions += case.prescriptions
        w.approvals += case.approvals
        w.stays += case.stays
        w.visit_logs += case.visit_logs
    w.claims = {c.id: c for r in month.results.values() for c in r.claims}
    w.findings = _assign_claims(month, month.findings)
    for doc in month.docs.values():
        d = doc.document
        w.documents[d.id] = DocumentInfo(
            id=d.id,
            doc_type=d.doc_type or "other",  # type: ignore[arg-type]
            title=title(doc),
            patient_id=doc.patient_id,
            received_on=d.created_at.date(),
            pages=[PageInfo(index=p.index, width=p.width, height=p.height) for p in doc.pages],
        )
        w.document_fields[d.id] = document_fields(doc)
        w.page_files[d.id] = [blobs.path(p.blob_key) for p in doc.pages]
    return w


@lru_cache(maxsize=4)
def _engine(db_path: Path) -> Engine:
    return create_db(db_path)


@lru_cache(maxsize=2)
def _cached(db_path: Path, records_path: Path, blob_dir: Path, stamp: tuple) -> World:
    records = MasterData.model_validate_json(records_path.read_text())
    return build_world(_engine(db_path), records, blob_dir)


def pipeline_world(settings: Settings) -> World | None:
    """The pipeline's month, or None before it has processed anything."""
    if not settings.db_path.exists():
        return None
    engine = _engine(settings.db_path)
    with session_scope(engine) as s:
        done = s.exec(select(func.count()).where(Document.status == "done")).one()
        latest = s.exec(select(func.max(Extraction.created_at))).one()
    if not done:
        return None
    return _cached(settings.db_path, settings.records_path, settings.blob_dir, (done, latest))
