"""The inbox: upload a batch of paperwork and watch the pipeline read it (docs/01 ING-01).

POST /api/batches stores the files and answers at once. The batch is then read in the
background (`Pipeline`) and its evidence boxes tightened (`tighten_evidence`). Every
step is an event, kept for the life of the process and streamed over SSE, so a page
opened or reloaded mid-run first replays what it missed. When a batch is done the board
shows it: the screens' World is rebuilt whenever the database changes (`api.live`).
"""

import asyncio
import io
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine, func
from sqlmodel import col, select

from kassenfest.api.live import db_engine
from kassenfest.api.models import (
    BatchDetail,
    BatchEvent,
    BatchList,
    BatchPhase,
    BatchSummary,
    InboxDocument,
    PipelineStep,
)
from kassenfest.config import get_settings
from kassenfest.db import Batch, Document, Extraction, Page, session_scope
from kassenfest.ingest import SUFFIXES
from kassenfest.llm.client import MetaModelClient
from kassenfest.pipeline.evidence import tighten_evidence
from kassenfest.pipeline.runner import Event, Pipeline
from kassenfest.schemas.records import MasterData
from kassenfest.storage import BlobStore
from kassenfest.vision.image import PageImage

router = APIRouter(prefix="/api")

MAX_UNZIPPED = 500 * 1024 * 1024
KEEPALIVE_S = 15.0
RECENT_BATCHES = 10


@dataclass
class Deps:
    """What reading a batch needs: a dependency, so tests can swap in a fake model."""

    client: MetaModelClient
    engine: Engine
    blobs: BlobStore
    records: MasterData | None


@lru_cache(maxsize=1)
def _client() -> MetaModelClient:
    return MetaModelClient(get_settings())  # one client: one concurrency limit for all runs


@lru_cache(maxsize=2)
def _records(path: Path, mtime_ns: int) -> MasterData:
    return MasterData.model_validate_json(path.read_text())


def run_deps() -> Deps:
    settings = get_settings()
    path = settings.records_path
    records = _records(path, path.stat().st_mtime_ns) if path.exists() else None
    return Deps(_client(), db_engine(settings.db_path), BlobStore(settings.blob_dir), records)


RunDeps = Annotated[Deps, Depends(run_deps)]


# --- Batches being read --------------------------------------------------------------


@dataclass
class Run:
    phase: BatchPhase = "reading"
    events: list[BatchEvent] = field(default_factory=list)
    steps: dict[str, tuple[PipelineStep, str]] = field(default_factory=dict)
    """document → its last step and what it found."""
    listeners: set[asyncio.Queue[BatchEvent]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None


class Inbox:
    """Batches read by this process: phase, each document's last step, every event."""

    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}

    async def start(self, deps: Deps, files: list[tuple[str, bytes]], label: str | None) -> str:
        """Store the files, then read them in the background; returns the batch id."""
        pipeline = Pipeline(deps.client, deps.engine, deps.blobs, records=deps.records)
        batch_id = pipeline.new_batch(label)
        run = self.runs[batch_id] = Run()
        pipeline.on_event = lambda e: self._document(batch_id, deps, e)
        stored = await pipeline.store(batch_id, files)
        run.task = asyncio.create_task(self._read(batch_id, deps, pipeline, stored))
        return batch_id

    async def _read(
        self,
        batch_id: str,
        deps: Deps,
        pipeline: Pipeline,
        stored: list[tuple[str, list[PageImage]]],
    ) -> None:
        try:
            await pipeline.process_all(stored)  # a failing document is marked, not raised
            self._phase(batch_id, "evidence", "Tightening the evidence boxes")
            ids = {doc_id for doc_id, _ in stored}
            done = await tighten_evidence(deps.client, deps.engine, deps.blobs, only=ids)
        except Exception as exc:  # what was read stays read; the batch must still end
            self._phase(batch_id, "done", f"Stopped early: {type(exc).__name__}: {exc}")
        else:
            fields = done.fields + done.found
            self._phase(batch_id, "done", f"{done.rows} visit rows and {fields} fields boxed")

    def _emit(self, batch_id: str, run: Run, **values: object) -> None:
        event = BatchEvent(seq=len(run.events) + 1, batch_id=batch_id, phase=run.phase, **values)
        run.events.append(event)
        for queue in run.listeners:
            queue.put_nowait(event)

    def _document(self, batch_id: str, deps: Deps, e: Event) -> None:
        run = self.runs[batch_id]
        run.steps[e.document_id] = (e.step, e.detail)  # type: ignore[assignment]
        (doc,) = rows(deps, run, document_id=e.document_id)
        self._emit(batch_id, run, kind="document", document=doc, detail=e.detail)

    def _phase(self, batch_id: str, phase: BatchPhase, detail: str) -> None:
        run = self.runs[batch_id]
        run.phase = phase
        self._emit(batch_id, run, kind="phase", detail=detail)

    async def follow(self, batch_id: str) -> AsyncIterator[BatchEvent | None]:
        """Every event of a batch read by this process, past ones first, until it is done;
        None every KEEPALIVE_S seconds without news. Nothing for any other batch."""
        run = self.runs.get(batch_id)
        if run is None:
            return
        queue: asyncio.Queue[BatchEvent] = asyncio.Queue()
        past, finished = list(run.events), run.phase == "done"
        run.listeners.add(queue)  # no await since copying `past`: nothing falls in between
        try:
            for event in past:
                yield event
            while not finished:
                try:
                    event = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
                except TimeoutError:
                    yield None
                    continue
                yield event
                finished = event.kind == "phase" and event.phase == "done"
        finally:
            run.listeners.discard(queue)


inbox = Inbox()


# --- What the screens get --------------------------------------------------------------

_STEP_OF_STATUS: dict[str, PipelineStep] = {
    "queued": "stored",
    "processing": "stored",
    "done": "done",
    "superseded": "done",
    "error": "error",
}


def rows(
    deps: Deps, run: Run | None, *, batch_id: str | None = None, document_id: str | None = None
) -> list[InboxDocument]:
    """The batch's documents (or one document) as the inbox lists them, in upload order."""
    with session_scope(deps.engine) as s:
        query = select(Document).order_by(col(Document.created_at))
        if batch_id is not None:
            query = query.where(Document.batch_id == batch_id)
        if document_id is not None:
            query = query.where(Document.id == document_id)
        docs = s.exec(query).all()
        ids = [d.id for d in docs]
        pages = dict(
            s.exec(
                select(Page.document_id, func.count())
                .where(col(Page.document_id).in_(ids))
                .group_by(col(Page.document_id))
            ).all()
        )
        issues: dict[str, list[str]] = {}
        latest_first = select(Extraction).order_by(col(Extraction.created_at))
        for ext in s.exec(latest_first.where(col(Extraction.document_id).in_(ids))):
            issues[ext.document_id] = ext.issues  # the latest extraction wins
    names = {p.id: p.name for p in deps.records.patients} if deps.records else {}
    out = []
    for d in docs:
        step, detail = (run.steps if run else {}).get(d.id, (_STEP_OF_STATUS[d.status], ""))
        out.append(
            InboxDocument(
                id=d.id,
                filename=d.filename,
                status=d.status,  # type: ignore[arg-type]
                step=step,
                detail=detail,
                doc_type=d.doc_type,  # type: ignore[arg-type]
                patient_id=d.patient_id,
                patient_name=names.get(d.patient_id or ""),
                pages=pages.get(d.id, 0),
                issues=issues.get(d.id, []),
                error=d.error,
            )
        )
    return out


def _summary(batch: Batch, docs: list[InboxDocument]) -> BatchSummary:
    run = inbox.runs.get(batch.id)
    unfinished = any(d.status in ("queued", "processing") for d in docs)
    return BatchSummary(
        id=batch.id,
        label=batch.label,
        created_at=batch.created_at.replace(tzinfo=UTC),  # SQLite drops the zone
        phase=run.phase if run else "interrupted" if unfinished else "done",
        files=len(docs),
        done=sum(d.status in ("done", "superseded") for d in docs),
        failed=sum(d.status == "error" for d in docs),
    )


def _detail(deps: Deps, batch_id: str) -> BatchDetail:
    with session_scope(deps.engine) as s:
        batch = s.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(404, f"No batch {batch_id}")
    docs = rows(deps, inbox.runs.get(batch_id), batch_id=batch_id)
    return BatchDetail(**_summary(batch, docs).model_dump(), documents=docs)


def unpack(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Images and PDFs, also from inside ZIPs; anything else (.DS_Store, ._ files) is skipped."""
    out, unzipped = [], 0
    for name, data in files:
        base = Path(name).name
        if base.lower().endswith(".zip"):
            try:
                archive = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile as exc:
                raise HTTPException(422, f"{base} is not a readable ZIP") from exc
            with archive:
                for info in sorted(archive.infolist(), key=lambda i: i.filename):
                    inner = Path(info.filename).name
                    if info.is_dir() or inner.startswith(".") or not _readable(inner):
                        continue
                    unzipped += info.file_size
                    if unzipped > MAX_UNZIPPED:
                        raise HTTPException(413, f"{base} unpacks to more than 500 MB")
                    out.append((inner, archive.read(info)))
        elif not base.startswith(".") and _readable(base):
            out.append((base, data))
    return out


def _readable(name: str) -> bool:
    return Path(name).suffix.lower() in SUFFIXES


# --- Endpoints ---------------------------------------------------------------------------


@router.post("/batches", status_code=202)
async def upload_batch(
    files: list[UploadFile], deps: RunDeps, label: Annotated[str | None, Form()] = None
) -> BatchDetail:
    """Store the files and start reading them; follow along on /batches/{id}/events."""
    contents = unpack([(f.filename or "upload", await f.read()) for f in files])
    if not contents:
        raise HTTPException(422, "No images or PDFs in the upload (PNG, JPG, HEIC, PDF or a ZIP)")
    batch_id = await inbox.start(deps, contents, label)
    return _detail(deps, batch_id)


@router.get("/batches")
def list_batches(deps: RunDeps) -> BatchList:
    with session_scope(deps.engine) as s:
        batches = s.exec(
            select(Batch).order_by(col(Batch.created_at).desc()).limit(RECENT_BATCHES)
        ).all()
    return BatchList(
        batches=[_summary(b, rows(deps, inbox.runs.get(b.id), batch_id=b.id)) for b in batches]
    )


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: str, deps: RunDeps) -> BatchDetail:
    return _detail(deps, batch_id)


@router.get(
    "/batches/{batch_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {"model": BatchEvent, "description": "text/event-stream, one BatchEvent per event"}
    },
)
async def batch_events(batch_id: str, deps: RunDeps) -> StreamingResponse:
    """Server-sent events while this process reads the batch: past ones first, then live.
    Ends after the 'done' phase, or at once for a batch that isn't being read."""
    _detail(deps, batch_id)  # 404 for an unknown batch

    async def stream() -> AsyncIterator[str]:
        async for event in inbox.follow(batch_id):
            if event is None:
                yield ": still reading\n\n"
            else:
                yield f"id: {event.seq}\ndata: {event.model_dump_json()}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
