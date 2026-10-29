"""The screens' World from the pipeline: stored documents → evaluated month.

Rebuilt whenever the database changes (a document finished or was re-processed), else
served from memory. Same `World` as the fixtures, so the routes don't care which.
"""

import datetime as dt
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, func
from sqlmodel import select

from kassenfest.agents.auditor import checked_findings, clean, current_audits, verdicts
from kassenfest.agents.fixer import actions, briefs, latest_fixes
from kassenfest.api.fixtures import World
from kassenfest.api.models import (
    AuditRound,
    ClaimAudit,
    DocumentField,
    DocumentInfo,
    FixerStatus,
    FixRun,
    FixStep,
    PageInfo,
)
from kassenfest.config import Settings
from kassenfest.db import Document, create_db, session_scope
from kassenfest.pipeline.link import value
from kassenfest.pipeline.month import Month, StoredDoc, evaluate_month
from kassenfest.rules.calendar import calendar_for
from kassenfest.rules.reference import Reference, load_reference
from kassenfest.schemas.common import Extracted, Mark
from kassenfest.schemas.extraction import (
    ApprovedItem,
    CareEntry,
    Located,
    PrescribedMeasure,
    RejectedItem,
    VisitEntry,
)
from kassenfest.schemas.labels import LABELS, ROWS
from kassenfest.schemas.records import MasterData
from kassenfest.storage import BlobStore

TARIFF_NOTE = (
    "Prices come from data/reference: illustrative demo values, not a real §132a or §89 contract."
)

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


def _holidays(records: MasterData) -> dict[dt.date, str]:
    cal = calendar_for(records.provider.bundesland, records.provider.municipality)
    first = dt.date.fromisoformat(f"{records.month}-01")
    days = (first + dt.timedelta(days=i) for i in range(31))
    return {
        d: name
        for d in days
        if d.month == first.month and (name := cal.holiday_name(d)) is not None
    }


def build_world(engine: Engine, records: MasterData, blob_dir: Path, as_of: dt.date) -> World:
    month = evaluate_month(engine, records, records.month)
    blobs = BlobStore(blob_dir)
    ref = load_reference()
    w = World(
        source="pipeline",
        month=records.month,
        as_of=as_of,
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
    w.claims = month.claims
    w.findings = month.findings
    _audits(w, engine, month, ref)
    _fixes(w, engine, month)
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


def _audits(w: World, engine: Engine, month: Month, ref: Reference) -> None:
    """Each clean bill's audit, if it is of the bill as it is now; upheld objections become
    findings, so the board shows them."""
    current = current_audits(month, engine, w.as_of)
    labels = {code: info.label_en for code, info in ref.kasse_codes.items()}
    for claim in w.claims.values():
        if not clean(month, claim):
            w.audits[claim.id] = ClaimAudit(state="not_needed")
            continue
        audit = current.get(claim.id)
        if audit is None:
            w.audits[claim.id] = ClaimAudit(state="pending", code_labels=labels)
            continue
        rounds = verdicts(audit)
        flat = [v.verdict for r in rounds for v in r]
        w.audits[claim.id] = ClaimAudit(
            state="error" if audit.error else "done",
            upheld=flat.count("upheld"),
            dismissed=flat.count("dismissed"),
            noted=flat.count("noted"),
            created_at=audit.created_at.replace(tzinfo=dt.UTC),  # SQLite drops the zone
            model=audit.model,
            rounds=[AuditRound(round=i, verdicts=r) for i, r in enumerate(rounds, 1)],
            repeats=audit.repeats,
            error=audit.error,
            code_labels=labels,
        )
    w.findings = checked_findings(month, current)


def _fixes(w: World, engine: Engine, month: Month) -> None:
    """Each patient's actions, if the fixer drafted them for the findings as they are now
    (upheld audit objections included, so this runs after `_audits`)."""
    latest = latest_fixes(engine)
    due = []
    for pid, b in briefs(month, w.findings, w.as_of).items():
        fix = latest.get(pid)
        if fix is None or fix.fingerprint != b.fingerprint or fix.error:
            due.append(b.case.patient.name)
            continue
        filed = actions(fix)
        w.actions += filed
        w.fix_runs[fix.id] = FixRun(
            id=fix.id,
            patient_id=pid,
            patient_name=b.case.patient.name,
            created_at=fix.created_at.replace(tzinfo=dt.UTC),  # SQLite drops the zone
            as_of=fix.as_of,
            model=fix.model,
            steps=[FixStep.model_validate(s) for s in fix.steps],
            note=fix.note,
            error=fix.error,
            refs=fix.refs,
            actions=[a.id for a in filed],
        )
    models = {r.model for r in w.fix_runs.values()}
    w.fixer = FixerStatus(
        state="pending" if due else "done",
        due=due,
        drafted=len(w.fix_runs),
        model=models.pop() if len(models) == 1 else None,
    )


@lru_cache(maxsize=4)
def db_engine(db_path: Path) -> Engine:
    return create_db(db_path)


@lru_cache(maxsize=2)
def _cached(
    db_path: Path, records_path: Path, blob_dir: Path, as_of: dt.date, stamp: tuple
) -> World:
    records = MasterData.model_validate_json(records_path.read_text())
    return build_world(db_engine(db_path), records, blob_dir, as_of)


def pipeline_world(settings: Settings) -> World | None:
    """The pipeline's month, or None before it has processed anything."""
    if not settings.db_path.exists():
        return None
    with session_scope(db_engine(settings.db_path)) as s:
        done = s.exec(select(func.count()).where(Document.status == "done")).one()
    if not done:
        return None
    # Every commit touches the SQLite file (no WAL), so its mtime covers new documents,
    # extractions and boxes alike; the records' mtime covers edits to the records.
    stamp = (settings.db_path.stat().st_mtime_ns, settings.records_path.stat().st_mtime_ns)
    as_of = settings.as_of()
    return _cached(settings.db_path, settings.records_path, settings.blob_dir, as_of, stamp)
