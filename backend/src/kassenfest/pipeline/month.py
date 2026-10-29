"""A billing month from what the pipeline stored: link, build case files, run the rules.

Nothing here calls a model, so the month is recomputed in well under a second whenever
a rule, the records or the case builder change. Evidence from the rules names a field;
this is where it gets the pixel box the viewer draws: the tightened box stored for the
field (`pipeline.evidence`), else the model's box for the field or for its row.
"""

import datetime as dt
import re
from dataclasses import dataclass, field

from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import col, select

from kassenfest.db import Document, Extraction, Localization, Page, session_scope
from kassenfest.pipeline.casefile import SourceDoc, build_cases
from kassenfest.pipeline.link import Link, link
from kassenfest.pipeline.validate import validate
from kassenfest.rules.engine import EngineResult, evaluate_document, run
from kassenfest.rules.reference import load_reference
from kassenfest.rules.tariffs import claim_id
from kassenfest.schemas.common import Extracted, Mark, PixelBox
from kassenfest.schemas.domain import CaseFile, Claim
from kassenfest.schemas.extraction import EXTRACTION_SCHEMAS, Located
from kassenfest.schemas.findings import Evidence, Finding
from kassenfest.schemas.records import MasterData
from kassenfest.vision.geometry import from_norm1000


@dataclass
class StoredDoc:
    document: Document
    pages: list[Page]
    extraction: BaseModel | None
    issues: list[str]
    boxes: dict[str, tuple[int, PixelBox]] = field(default_factory=dict)
    """field path → (page, pixel box)."""
    sources: dict[str, str] = field(default_factory=dict)
    """field path → where its stored box came from (`Localization.source`)."""
    ink: dict[str, float] = field(default_factory=dict)
    """field path → dark-pixel share inside its stored box, where measured."""
    link: Link | None = None

    @property
    def patient_id(self) -> str | None:
        return self.link.patient_id if self.link else None


@dataclass
class Month:
    month: str
    records: MasterData
    docs: dict[str, StoredDoc]
    cases: dict[str, CaseFile]
    results: dict[str, EngineResult]
    findings: list[Finding]
    """Case and document findings, evidence boxed, each on the claim it concerns."""

    @property
    def claims(self) -> dict[str, Claim]:
        return {c.id: c for r in self.results.values() for c in r.claims}


SEVERITY_RANK = {"block": 0, "warn": 1, "info": 2}


def claim_findings(claim: Claim, findings: list[Finding]) -> list[Finding]:
    """The claim's own findings, and claim-less ones that hit any of its lines; worst first."""
    lines = {line.id for line in claim.lines}
    found = [
        f
        for f in findings
        if f.claim_id == claim.id or (f.claim_id is None and lines & set(f.claim_line_ids))
    ]
    return sorted(found, key=lambda f: (SEVERITY_RANK[f.severity], -f.amount_at_risk_cents))


def field_boxes(doc: BaseModel, pages: list[Page]) -> dict[str, tuple[int, PixelBox]]:
    """Every box the model gave: fields, marks and list rows, in page pixels."""
    out: dict[str, tuple[int, PixelBox]] = {}

    def put(path: str, page: int, box) -> None:
        if box is None or not pages:
            return
        p = pages[min(page, len(pages) - 1)]
        corners = (box.x_min, box.y_min, box.x_max, box.y_max)
        out[path] = (page, from_norm1000(corners, p.width, p.height))

    def walk(obj: object, path: str) -> None:
        if isinstance(obj, Extracted | Mark | Located):
            put(path, obj.page, obj.box)
        if isinstance(obj, BaseModel) and not isinstance(obj, Extracted | Mark):
            for name in type(obj).model_fields:
                walk(getattr(obj, name), f"{path}.{name}" if path else name)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{path}[{i}]")
            rows = [out[f"{path}[{i}]"] for i in range(len(obj)) if f"{path}[{i}]" in out]
            if rows:  # the list as a whole: all its rows on the first page they're on
                page = rows[0][0]
                x0, y0, x1, y1 = zip(*(b for p, b in rows if p == page), strict=True)
                out[path] = (page, (min(x0), min(y0), max(x1), max(y1)))

    walk(doc, "")
    return out


def load_docs(engine: Engine) -> list[StoredDoc]:
    """Every processed document with its latest extraction; SAM boxes win over the model's."""
    with session_scope(engine) as s:
        docs = s.exec(select(Document).where(Document.status == "done")).all()
        out = []
        for doc in docs:
            pages = list(
                s.exec(select(Page).where(Page.document_id == doc.id).order_by(col(Page.index)))
            )
            ext = s.exec(
                select(Extraction)
                .where(Extraction.document_id == doc.id)
                .order_by(col(Extraction.created_at).desc())
            ).first()
            stored = StoredDoc(doc, pages, None, [])
            if ext is not None and doc.doc_type in EXTRACTION_SCHEMAS:
                model = EXTRACTION_SCHEMAS[doc.doc_type].model_validate(ext.data)  # type: ignore[index]
                # Normalizers may have changed since this was stored; they're idempotent.
                stored.extraction = model
                stored.issues = list(dict.fromkeys([*ext.issues, *validate(model)]))
                stored.boxes = field_boxes(stored.extraction, pages)
                for loc in s.exec(select(Localization).where(Localization.document_id == doc.id)):
                    stored.boxes[loc.field_path] = (loc.page, tuple(loc.box))  # type: ignore[arg-type]
                    stored.sources[loc.field_path] = loc.source
                    if loc.ink_ratio is not None:
                        stored.ink[loc.field_path] = loc.ink_ratio
            s.expunge_all()
            out.append(stored)
    return out


_LAST_STEP = re.compile(r"(^|\.)[^.\[]+$|\[\d+\]$")


def box_key(doc: StoredDoc, path: str | None) -> str | None:
    """The path whose box stands for `path`: its own, else its row's ('entries[3].start_time')."""
    while path:
        if path in doc.boxes:
            return path
        path = _LAST_STEP.sub("", path)
    return None


def boxed(evidence: Evidence, docs: dict[str, StoredDoc]) -> Evidence:
    """Fill in the pixel box, if the evidence has none yet."""
    doc = docs.get(evidence.document_id)
    if evidence.box is not None or doc is None:
        return evidence
    key = box_key(doc, evidence.field_path)
    if key is None:
        return evidence
    page, box = doc.boxes[key]
    return evidence.model_copy(update={"page": page, "box": box})


def assign_claims(
    cases: dict[str, CaseFile],
    results: dict[str, EngineResult],
    docs: dict[str, StoredDoc],
    findings: list[Finding],
) -> list[Finding]:
    """Document findings (no lines) go on the claim their document feeds: a visit log on its
    own claim, a Verordnung or Genehmigung on the patient's HKP claim."""
    by_log = {log.document_id: claim_id(log) for case in cases.values() for log in case.visit_logs}
    hkp = {pid: c.id for pid, r in results.items() for c in r.claims if c.domain == "sgbv"}
    out = []
    for f in findings:
        if f.claim_id is None and not f.claim_line_ids and f.evidence:
            doc = docs.get(f.evidence[0].document_id)
            target = by_log.get(f.evidence[0].document_id)
            if target is None and doc and doc.document.doc_type in ("muster12", "approval_letter"):
                target = hkp.get(f.patient_id)
            f = f.model_copy(update={"claim_id": target})
        out.append(f)
    return out


def evaluate_month(engine: Engine, records: MasterData, month: str) -> Month:
    docs = {d.document.id: d for d in load_docs(engine)}
    for d in docs.values():
        if d.extraction is not None:
            d.link = link(d.extraction, records)
            d.issues += d.link.issues
    sources = [
        SourceDoc(d.document.id, d.extraction, d.patient_id)
        for d in docs.values()
        if d.extraction is not None and d.patient_id
    ]
    ref = load_reference()
    built = build_cases(month, records, sources, ref)
    for doc_id, issues in built.issues.items():
        docs[doc_id].issues += issues
    results = {pid: run(case, ref=ref) for pid, case in built.cases.items()}

    first_day = dt.date.fromisoformat(f"{month}-01")
    findings = [f for r in results.values() for f in r.findings]
    for d in docs.values():
        if d.extraction is not None:
            findings += evaluate_document(
                d.extraction,
                document_id=d.document.id,
                on=first_day,
                patient_id=d.patient_id or "unlinked",
            )
    findings = [
        f.model_copy(update={"evidence": [boxed(e, docs) for e in f.evidence]}) for f in findings
    ]
    findings = assign_claims(built.cases, results, docs, findings)
    return Month(month, records, docs, built.cases, results, findings)
