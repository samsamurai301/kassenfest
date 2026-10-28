"""`kassenfest ingest`: run files through the pipeline from the command line."""

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
