"""Tight evidence boxes for stored documents, run after every batch (docs/SPIKES.md, 2026-10-28).

- SGB V visit-log rows: the day's band between the form's ruling lines, tightened to the
  pen ink (`vision.grid`). The model's own row boxes drift by a row or more down the page.
- every field that was read: Muse Spark's box refined by SAM 3.1, 16 boxes per call, so
  about one call per page, with the guards used for marks (`pipeline.localize`).
  Spike decision 4 said "every field a finding cites"; batching makes all of them cheap,
  and the document viewer lists them all.
- what SAM couldn't tighten (mostly on photos and faxes, where the model's box misses the
  ink), unreadable fields, and inked marks SAM missed at ingest: Muse Spark again, on an
  upscaled crop around its box, then SAM on the box it found. One call per field.

Results are stored as Localization rows, which `pipeline.month` prefers over the model's
boxes. Running it again replaces them (from the cache: the requests don't change).
"""

import asyncio
import calendar
import io
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass

import numpy as np
from PIL import Image
from sqlalchemy import Engine
from sqlmodel import col, delete

from kassenfest.db import Localization, session_scope
from kassenfest.llm.client import MetaModelClient
from kassenfest.llm.prompts import as_written, find_user
from kassenfest.pipeline.localize import Located, find_on_crops, refine_boxes
from kassenfest.pipeline.month import StoredDoc, field_boxes, load_docs
from kassenfest.schemas.common import Extracted, Mark, PixelBox
from kassenfest.schemas.extraction import VisitLogSGBV
from kassenfest.storage import BlobStore
from kassenfest.vision.grid import snap_rows
from kassenfest.vision.image import PageImage


@dataclass
class Tightened:
    rows: int = 0
    """Visit-log rows placed on the form's grid."""
    fields: int = 0
    """Fields tightened by SAM."""
    candidates: int = 0
    """Fields sent to SAM."""
    found: int = 0
    """Fields found again on a crop."""
    asked: int = 0
    """Fields asked again on a crop."""


def _page(blobs: BlobStore, doc: StoredDoc, index: int) -> PageImage:
    return PageImage.from_path(blobs.path(doc.pages[index].blob_key))


def grid_rows(doc: StoredDoc, page: PageImage) -> list[Located]:
    """Every row of a one-page SGB V Leistungsnachweis, snapped to the printed grid."""
    log = doc.extraction
    if not isinstance(log, VisitLogSGBV) or len(doc.pages) != 1:
        return []
    model = field_boxes(log, doc.pages)  # the model's own boxes, not an earlier snap
    rows = {}
    for i, entry in enumerate(log.entries):
        path = f"entries[{i}]"
        if path in model and entry.date and len(entry.date) == 10 and entry.date[8:].isdigit():
            rows[path] = (int(entry.date[8:]), model[path][1])
    month = log.month.value or (log.entries[0].date[:7] if log.entries else None)
    if not rows or not month:
        return []
    year, mon = map(int, month.split("-"))
    rgb = np.array(Image.open(io.BytesIO(page.data)).convert("RGB"))
    snapped = snap_rows(rgb, rows, calendar.monthrange(year, mon)[1])
    return [Located(path, 0, box, "grid") for path, box in snapped.items()]


def to_refine(doc: StoredDoc) -> dict[int, dict[str, PixelBox]]:
    """page → path → model box for every top-level field that was read.

    Decided by the extraction alone, never by earlier runs, so the same document always
    sends the same SAM requests and a replay finds them in the cache. Marks are refined
    at ingest (`localize_marks`).
    """
    out: dict[int, dict[str, PixelBox]] = defaultdict(dict)
    for key, (page, box) in field_boxes(doc.extraction, doc.pages).items():
        item = getattr(doc.extraction, key, None)
        if isinstance(item, Extracted) and item.status == "present":
            out[page][key] = box
    return out


SAM_AT_INGEST = ("sam_refine", "sam_concept")


def to_find(doc: StoredDoc, tightened: set[str]) -> dict[int, dict[str, tuple[PixelBox, str]]]:
    """page → path → (model box, question) for every value that was read but has no tight
    box: fields SAM left alone in this run (`tightened` are the ones it did), unreadable
    fields, and inked marks that SAM missed at ingest.

    Like `to_refine`, decided by the extraction and SAM's answers, which come from the
    cache on a replay. A mark found on a crop before is asked again, from the cache.
    """
    out: dict[int, dict[str, tuple[PixelBox, str]]] = defaultdict(dict)
    doc_type = doc.document.doc_type or ""
    for key, (page, box) in field_boxes(doc.extraction, doc.pages).items():
        item = getattr(doc.extraction, key, None)
        if isinstance(item, Extracted) and item.status != "empty" and key not in tightened:
            reads = as_written(item.value) if item.status == "present" else None
            out[page][key] = (box, find_user(doc_type, key, reads))
        elif (
            isinstance(item, Mark)
            and item.state != "absent"
            and doc.sources.get(key) not in SAM_AT_INGEST
        ):
            out[page][key] = (box, find_user(doc_type, key, None, mark=True))
    return out


def _tightened(found: list[Located]) -> set[str]:
    return {x.field_path for x in found if x.source == "sam_refine"}


def _store(engine: Engine, located: dict[str, list[Located]]) -> None:
    with session_scope(engine) as s:
        for doc_id, items in located.items():
            paths = [x.field_path for x in items]
            s.exec(
                delete(Localization).where(
                    col(Localization.document_id) == doc_id,
                    col(Localization.field_path).in_(paths),
                )
            )
            for x in items:
                s.add(
                    Localization(
                        document_id=doc_id,
                        page=x.page,
                        field_path=x.field_path,
                        source=x.source,
                        box=list(x.box),
                        confidence=x.confidence,
                    )
                )


async def _one(client: MetaModelClient, blobs: BlobStore, doc: StoredDoc) -> list[Located]:
    found = []
    if doc.document.doc_type == "visit_log_sgbv":
        found += grid_rows(doc, _page(blobs, doc, 0))
    for index, boxes in to_refine(doc).items():
        found += await refine_boxes(client, _page(blobs, doc, index), index, boxes)
    for index, asks in to_find(doc, _tightened(found)).items():
        found += await find_on_crops(client, _page(blobs, doc, index), index, asks)
    return found


async def tighten_evidence(
    client: MetaModelClient, engine: Engine, blobs: BlobStore, only: Collection[str] | None = None
) -> Tightened:
    """Tight boxes for every stored document, or only for the documents in `only`."""
    docs = [
        d
        for d in load_docs(engine)
        if d.extraction is not None and (only is None or d.document.id in only)
    ]
    results = await asyncio.gather(*(_one(client, blobs, d) for d in docs))
    report = Tightened(candidates=sum(len(b) for d in docs for b in to_refine(d).values()))
    for d, found in zip(docs, results, strict=True):
        report.rows += sum(x.source == "grid" for x in found)
        report.fields += sum(x.source == "sam_refine" for x in found)
        report.found += sum(x.source in ("crop", "crop_sam") for x in found)
        report.asked += sum(len(a) for a in to_find(d, _tightened(found)).values())
    _store(engine, {d.document.id: found for d, found in zip(docs, results, strict=True)})
    return report
