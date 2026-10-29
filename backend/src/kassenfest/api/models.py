"""API-only response models: thin wrappers around the shared schemas for the web screens.

Everything with domain meaning (Claim, Finding, Patient, …) is the shared model itself;
these only bundle it per screen and add what the UI needs to draw it.
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from kassenfest.schemas.common import DocType, FieldStatus, PixelBox
from kassenfest.schemas.domain import (
    Approval,
    Claim,
    Domain,
    Patient,
    Payer,
    Physician,
    Prescription,
    Provider,
    Stay,
    VisitLog,
)
from kassenfest.schemas.findings import ClaimStatus, Finding, ObjectionVerdict

# --- Auditor --------------------------------------------------------------------

AuditState = Literal["not_needed", "pending", "running", "done", "error", "unavailable"]
"""not_needed: the rules already object · pending: clean, not audited in its current state ·
unavailable: fixture data, nothing to audit."""


class AuditStatus(BaseModel):
    state: AuditState
    upheld: int = 0
    dismissed: int = 0
    noted: int = 0


class AuditRound(BaseModel):
    round: int
    verdicts: list[ObjectionVerdict]


class ClaimAudit(AuditStatus):
    """The Kasse auditor agent's attack on a clean bill and the resolver's verdicts."""

    created_at: dt.datetime | None = None
    model: str | None = None
    rounds: list[AuditRound] = []
    repeats: int = Field(0, description="Objections dropped because they were raised before")
    error: str | None = None
    code_labels: dict[str, str] = Field({}, description="Kasse rejection code -> English label")


# --- Documents -------------------------------------------------------------------


class PageInfo(BaseModel):
    index: int
    width: int
    height: int


class DocumentInfo(BaseModel):
    id: str
    doc_type: DocType
    title: str = Field(description="Short English title, e.g. 'Muster 12, issued 1 Oct'")
    patient_id: str | None
    received_on: dt.date | None = None
    pages: list[PageInfo]


class DocumentField(BaseModel):
    """A field as read from the page, with where it is: drives the viewer's field list."""

    path: str = Field(description="flatten() path, e.g. 'period_to'")
    label: str = Field(description="Label as printed on the form (German)")
    value: str | None
    status: FieldStatus
    page: int = 0
    box: PixelBox


class DocumentDetail(BaseModel):
    document: DocumentInfo
    fields: list[DocumentField]
    findings: list[Finding] = Field(description="Findings with evidence on this document")
    claim_ids: list[str]


# --- Actions ---------------------------------------------------------------------

ActionKind = Literal[
    "folgeverordnung_request",
    "stamp_request",
    "signature_request",
    "kasse_letter",
    "eigenanteil_notice",
    "claim_correction",
    "staff_followup",
]


class Letter(BaseModel):
    """A drafted letter or note (German); never sent by Kassenfest itself."""

    channel: Literal["fax", "post", "handover", "internal"]
    recipient: list[str] = Field(description="Address block, one line per item")
    subject: str
    body: str


class Action(BaseModel):
    id: str
    kind: ActionKind
    title: str
    why: str = Field(description="One English sentence: what goes wrong if nobody acts")
    patient_id: str
    patient_name: str
    claim_id: str | None
    finding_ids: list[str]
    due_date: dt.date
    amount_cents: int = Field(description="Money on the linked findings")
    status: Literal["draft", "open"]
    letter: Letter


class ActionList(BaseModel):
    month: str
    as_of: dt.date = Field(description="'Today' in the demo world; countdowns count from here")
    actions: list[Action]


# --- Board and claim ------------------------------------------------------------


class BoardCard(BaseModel):
    claim_id: str
    patient_id: str
    patient_name: str
    payer: Payer
    domain: Domain
    status: ClaimStatus
    total_cents: int
    at_risk_cents: int
    line_count: int
    finding_count: int
    top_finding: Finding | None
    audit: AuditStatus


class StatusTotal(BaseModel):
    status: ClaimStatus
    count: int
    total_cents: int
    at_risk_cents: int


class MonthBoard(BaseModel):
    month: str
    as_of: dt.date
    provider: Provider
    total_cents: int
    at_risk_cents: int
    by_status: list[StatusTotal]
    cards: list[BoardCard]


class ClaimDetail(BaseModel):
    claim: Claim
    as_of: dt.date
    status: ClaimStatus
    at_risk_cents: int
    patient: Patient
    payer: Payer
    findings: list[Finding]
    documents: list[DocumentInfo]
    actions: list[Action]
    code_labels: dict[str, str] = Field(description="Positionsnummer / LK -> German label")
    tariff_note: str
    audit: ClaimAudit


# --- Timeline --------------------------------------------------------------------


class Holiday(BaseModel):
    date: dt.date
    name: str


class PatientTimeline(BaseModel):
    patient: Patient
    month: str
    first_day: dt.date
    last_day: dt.date
    holidays: list[Holiday]
    physicians: list[Physician]
    payers: list[Payer]
    prescriptions: list[Prescription]
    approvals: list[Approval]
    stays: list[Stay]
    visit_logs: list[VisitLog]
    claims: list[Claim]
    findings: list[Finding]
    documents: list[DocumentInfo]
    code_labels: dict[str, str]


# --- Inbox -----------------------------------------------------------------------

PipelineStep = Literal["stored", "classified", "extracted", "linked", "localized", "done", "error"]
DocumentStatus = Literal["queued", "processing", "done", "error", "superseded"]
BatchPhase = Literal["reading", "evidence", "audit", "done", "interrupted"]
"""reading documents → tightening evidence boxes → the auditor attacks the clean bills → done;
interrupted: the server stopped."""


class InboxDocument(BaseModel):
    """One uploaded file and how far the pipeline has got with it."""

    id: str
    filename: str
    status: DocumentStatus
    step: PipelineStep = Field(description="The last step reached")
    detail: str = Field("", description="What that step found, e.g. 'muster12'")
    doc_type: DocType | None
    patient_id: str | None
    patient_name: str | None
    pages: int
    issues: list[str] = Field(description="What the reader flagged for a human to check")
    error: str | None


class BatchSummary(BaseModel):
    id: str
    label: str | None
    created_at: dt.datetime
    phase: BatchPhase
    files: int
    done: int = Field(description="Documents read (including ones a later upload replaced)")
    failed: int


class BatchDetail(BatchSummary):
    documents: list[InboxDocument]


class BatchList(BaseModel):
    batches: list[BatchSummary] = Field(description="Newest first")


class BatchEvent(BaseModel):
    """One server-sent event on /api/batches/{id}/events (the JSON in its data line)."""

    seq: int
    batch_id: str
    kind: Literal["document", "phase"]
    phase: BatchPhase
    document: InboxDocument | None = Field(None, description="The document after this step")
    detail: str = ""
