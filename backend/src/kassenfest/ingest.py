"""`kassenfest ingest`, `evidence` and `audit`: the pipeline from the command line."""

from datetime import date
from pathlib import Path

from sqlmodel import select

from kassenfest.config import Settings
from kassenfest.db import Document, Extraction, Localization, create_db, session_scope
from kassenfest.llm.client import MetaModelClient
from kassenfest.pipeline.evidence import tighten_evidence
from kassenfest.pipeline.runner import Event, Pipeline
from kassenfest.schemas.records import MasterData
from kassenfest.storage import BlobStore

SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".pdf"}


def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in SUFFIXES)
        elif p.suffix.lower() in SUFFIXES:
            files.append(p)
    return files


async def evidence(settings: Settings) -> int:
    """Tighten the evidence boxes of every stored document (also run after every ingest)."""
    engine = create_db(settings.db_path)
    client, blobs = MetaModelClient(settings), BlobStore(settings.blob_dir)
    done = await tighten_evidence(client, engine, blobs)
    print(
        f"evidence: {done.rows} visit-log rows on the form grid, "
        f"{done.fields}/{done.candidates} fields tightened by SAM, "
        f"{done.found}/{done.asked} more found on a crop"
    )
    return 0


async def audit(settings: Settings, claim_ids: list[str]) -> int:
    """Let the auditor agent attack the clean bills that are due (also run after every upload)."""
    from kassenfest.agents.auditor import audit_month, due, latest_audits, verdicts
    from kassenfest.pipeline.month import evaluate_month

    if not settings.records_path.exists():
        print(f"no records at {settings.records_path}: no bills to audit")
        return 1
    records = MasterData.model_validate_json(settings.records_path.read_text())
    engine = create_db(settings.db_path)
    client, blobs = MetaModelClient(settings), BlobStore(settings.blob_dir)
    month = evaluate_month(engine, records, records.month)
    dossiers = due(month, engine, date.today(), claim_ids or None)
    print(f"audit: {len(dossiers)} clean bills due")
    done = await audit_month(client, engine, blobs, records, dossiers=dossiers)
    latest = latest_audits(engine)
    for d in dossiers:
        a = latest[d.bill.claim.id]
        print(
            f"\n{d.bill.claim.id} ({d.bill.case.patient.name})"
            + (f": {a.error}" if a.error else "")
        )
        for n, round_ in enumerate(verdicts(a), 1):
            for v in round_:
                o = v.objection
                print(f"  round {n} {o.code:<5} {v.verdict:<9} {o.statement_en}")
                print(f"  {'':<22}{v.reason}")
    print(
        f"\naudit: {done.audited} bills attacked, {done.objections} objections, "
        f"{done.upheld} upheld, {done.failed} failed, ${done.cost_usd:.3f}"
    )
    return 1 if done.failed else 0


async def run(settings: Settings, paths: list[str], label: str | None) -> int:
    files = collect(paths)
    if not files:
        print("no images or PDFs found")
        return 1
    engine = create_db(settings.db_path)
    names: dict[str, str] = {}

    def show(e: Event) -> None:
        if e.step == "stored":
            names[e.document_id] = e.detail.split(":")[0]
        print(f"  {names.get(e.document_id, e.document_id):<36} {e.step:<10} {e.detail}")

    records = None
    if settings.records_path.exists():
        records = MasterData.model_validate_json(settings.records_path.read_text())
    else:
        print(f"no records at {settings.records_path}: documents stay unlinked")
    pipeline = Pipeline(
        MetaModelClient(settings), engine, BlobStore(settings.blob_dir), show, records
    )
    batch_id = await pipeline.ingest([(f.name, f.read_bytes()) for f in files], label=label)
    await evidence(settings)

    with session_scope(engine) as s:
        docs = s.exec(select(Document).where(Document.batch_id == batch_id)).all()
        print(f"\nbatch {batch_id}: {len(docs)} document(s) in {settings.db_path}")
        for d in docs:
            ext = s.exec(select(Extraction).where(Extraction.document_id == d.id)).first()
            locs = s.exec(select(Localization).where(Localization.document_id == d.id)).all()
            issues = ext.issues if ext else []
            print(
                f"  {d.filename:<36} {d.status:<6} {d.doc_type or '-':<16} "
                f"{d.patient_id or 'unlinked':<9} "
                f"issues {len(issues)}  boxes {len(locs)}"
                + (f"  error: {d.error}" if d.error else "")
            )
            for issue in issues:
                print(f"      · {issue}")
    return 0
