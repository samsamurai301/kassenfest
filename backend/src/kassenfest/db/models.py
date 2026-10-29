"""SQLite tables for what the pipeline produces (docs/01 §2.2, trimmed to Tier A).

Extractions are stored as the model returned them (JSON); typed facts are rebuilt
from them, so changing a normalizer never needs a migration.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlmodel import JSON, Column, Field, SQLModel


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(UTC)


class Batch(SQLModel, table=True):
    """One upload: a month of paperwork dropped in at once."""

    id: str = Field(default_factory=lambda: _id("bat"), primary_key=True)
    label: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Document(SQLModel, table=True):
    id: str = Field(default_factory=lambda: _id("doc"), primary_key=True)
    batch_id: str = Field(foreign_key="batch.id", index=True)
    filename: str
    source_sha256: str = Field(index=True)
    source_key: str = Field(description="Blob key of the uploaded file as received")
    doc_type: str | None = None
    classification_confidence: float | None = None
    synthetic_watermark: bool | None = None
    patient_id: str | None = Field(default=None, index=True)
    status: str = "queued"  # queued | processing | done | error | superseded
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Page(SQLModel, table=True):
    id: str = Field(default_factory=lambda: _id("pag"), primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    index: int
    blob_key: str
    width: int
    height: int


class Extraction(SQLModel, table=True):
    id: str = Field(default_factory=lambda: _id("ext"), primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    schema_name: str
    prompt_id: str
    reasoning_effort: str
    data: dict[str, Any] = Field(sa_column=Column(JSON))
    issues: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    cache_key: str
    cost_usd: float
    latency_ms: int
    created_at: datetime = Field(default_factory=_now)


class Localization(SQLModel, table=True):
    """A pixel box for one field or mark: what the evidence viewer draws."""

    id: str = Field(default_factory=lambda: _id("loc"), primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    page: int = 0
    field_path: str
    source: str  # muse | sam_refine | sam_concept | grid | crop | crop_sam
    box: list[float] = Field(sa_column=Column(JSON))
    confidence: float | None = None
    ink_ratio: float | None = Field(default=None, description="Dark-pixel share inside the box")


class Audit(SQLModel, table=True):
    """The Kasse auditor agent's attack on one clean bill, and the resolver's verdicts."""

    id: str = Field(default_factory=lambda: _id("aud"), primary_key=True)
    claim_id: str = Field(index=True)
    fingerprint: str = Field(index=True, description="sha256 of everything the auditor saw")
    model: str
    rounds: list[Any] = Field(
        default_factory=list, sa_column=Column(JSON), description="Per round: verdicts"
    )
    repeats: int = Field(default=0, description="Objections dropped as repeats")
    error: str | None = None
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=_now)
