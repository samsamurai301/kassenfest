"""Runs uploaded files through ingest -> classify -> extract -> validate -> localize.

Linking to patients and evaluating rules plug in after this once the synth world
and rules engine land (docs/05 §5, Fri/Sat). Every step emits an Event, which the
CLI prints and the API will stream over SSE.
"""

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine

from kassenfest.db import Batch, Document, Extraction, Localization, Page, session_scope
from kassenfest.llm.client import MetaModelClient, ReasoningEffort
from kassenfest.llm.prompts import (
    CLASSIFY_SYSTEM,
    CLASSIFY_VERSION,
    EXTRACT_SYSTEM,
    EXTRACT_VERSION,
    extract_user,
)
from kassenfest.pipeline.localize import localize_marks
from kassenfest.pipeline.pages import to_pages
from kassenfest.pipeline.validate import validate
from kassenfest.schemas.extraction import EXTRACTION_SCHEMAS, Classification
from kassenfest.storage import BlobStore
from kassenfest.vision.image import PageImage

# Spike S1/S2: Muster 12 is as accurate at `low`; visit grids get `medium` until tested lower.
EFFORT: dict[str, ReasoningEffort] = {
    "muster12": "low",
    "approval_letter": "low",
    "hospital_letter": "low",
    "visit_log_sgbv": "medium",
    "visit_log_sgbxi": "medium",
}
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


@dataclass
class Event:
    document_id: str
    step: str  # stored | classified | extracted | localized | done | error
    detail: str = ""


class Pipeline:
    def __init__(
        self,
        client: MetaModelClient,
        engine: Engine,
        blobs: BlobStore,
        on_event: Callable[[Event], None] | None = None,
    ):
        self.client, self.engine, self.blobs = client, engine, blobs
        self.on_event = on_event or (lambda _: None)

    async def ingest(self, files: list[tuple[str, bytes]], label: str | None = None) -> str:
        """Store every file and its pages, then process all documents concurrently."""
        with session_scope(self.engine) as s:
            batch = Batch(label=label)
            s.add(batch)
        jobs = []
        for filename, data in files:
            pages = await asyncio.to_thread(to_pages, data, filename)
            ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
            with session_scope(self.engine) as s:
                doc = Document(
                    batch_id=batch.id,
                    filename=filename,
                    source_sha256=hashlib.sha256(data).hexdigest(),
                    source_key=self.blobs.put(data, ext),
                )
                s.add(doc)
                for i, page in enumerate(pages):
                    key = self.blobs.put(page.data, _EXT.get(page.mime, "png"))
                    s.add(
                        Page(
                            document_id=doc.id,
                            index=i,
                            blob_key=key,
                            width=page.width,
                            height=page.height,
                        )
                    )
            self.on_event(Event(doc.id, "stored", f"{filename}: {len(pages)} page(s)"))
            jobs.append(self.process(doc.id, pages))
        await asyncio.gather(*jobs)
        return batch.id

    async def process(self, doc_id: str, pages: list[PageImage]) -> None:
        try:
            self._set(doc_id, status="processing")
            cls = await self.client.chat_json(
                prompt_id=f"classify.{CLASSIFY_VERSION}",
                schema=Classification,
                system=CLASSIFY_SYSTEM,
                user_text=f"Classify these {len(pages)} page image(s), in order.",
                images=pages,
                reasoning_effort="low",
            )
            first = cls.parsed.pages[0] if cls.parsed.pages else None
            doc_type = first.doc_type if first else "other"
            self._set(
                doc_id,
                doc_type=doc_type,
                classification_confidence=first.confidence if first else None,
                synthetic_watermark=cls.parsed.synthetic_watermark,
            )
            self.on_event(Event(doc_id, "classified", doc_type))
            if doc_type not in EXTRACTION_SCHEMAS:
                self._set(doc_id, status="done")
                self.on_event(Event(doc_id, "done", "not a billing document"))
                return

            effort = EFFORT[doc_type]
            result = await self.client.chat_json(
                prompt_id=f"extract.{doc_type}.{EXTRACT_VERSION}",
                schema=EXTRACTION_SCHEMAS[doc_type],
                system=EXTRACT_SYSTEM,
                user_text=extract_user(doc_type),
                images=pages,
                reasoning_effort=effort,
            )
            doc = result.parsed
            issues = validate(doc)
            if len({p.doc_type for p in cls.parsed.pages}) > 1:
                issues.append("pages classified as different document types; check the scan")
            self.on_event(Event(doc_id, "extracted", f"{len(issues)} issue(s)"))

            located, mark_issues = await localize_marks(self.client, pages, doc)
            issues += mark_issues
            with session_scope(self.engine) as s:
                s.add(
                    Extraction(
                        document_id=doc_id,
                        schema_name=type(doc).__name__,
                        prompt_id=f"extract.{doc_type}.{EXTRACT_VERSION}",
                        reasoning_effort=effort,
                        data=doc.model_dump(mode="json"),
                        issues=issues,
                        cache_key=result.meta.key,
                        cost_usd=result.meta.cost_usd,
                        latency_ms=result.meta.latency_ms,
                    )
                )
                for loc in located:
                    s.add(
                        Localization(
                            document_id=doc_id,
                            page=loc.page,
                            field_path=loc.field_path,
                            source=loc.source,
                            box=list(loc.box),
                            confidence=loc.confidence,
                            ink_ratio=loc.ink_ratio,
                        )
                    )
            self.on_event(
                Event(doc_id, "localized", ", ".join(f"{x.field_path}:{x.source}" for x in located))
            )
            self._set(doc_id, status="done")
            self.on_event(Event(doc_id, "done"))
        except Exception as exc:  # one bad page must not stop the batch
            self._set(doc_id, status="error", error=f"{type(exc).__name__}: {exc}")
            self.on_event(Event(doc_id, "error", str(exc)))

    def _set(self, doc_id: str, **values: object) -> None:
        with session_scope(self.engine) as s:
            doc = s.get(Document, doc_id)
            assert doc is not None
            for key, value in values.items():
                setattr(doc, key, value)
            s.add(doc)
