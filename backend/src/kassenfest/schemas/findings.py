"""Rule findings, evidence and the auditor's objections (docs/02 §0, §9)."""

from typing import Literal

from pydantic import BaseModel, Field

from kassenfest.schemas.common import PixelBox, Strict

Severity = Literal["block", "warn", "info"]
ClaimStatus = Literal["green", "orange", "red"]
"""green: ready · orange: fixable or needs a human look · red: will be rejected as is."""

KasseCode = Literal[
    "41002",
    "41003",
    "42002",
    "42003",
    "42004",
    "42005",
    "42006",
    "42007",
    "42008",
    "42009",
    "43001",
    "43002",
    "43003",
    "43004",
    "43005",
    "44001",
    "44003",
    "44004",
]
"""Official TA HKP 10.1 / TA5 rejection codes: the auditor's only blocking vocabulary."""


class Evidence(BaseModel):
    document_id: str
    page: int = 0
    field_path: str | None = Field(default=None, description="flatten() path, e.g. 'period_to'")
    box: PixelBox | None = None
    mask_ref: str | None = Field(default=None, description="Blob key of a SAM mask, if any")
    note: str | None = None


class Finding(BaseModel):
    id: str
    rule_id: str
    rule_version: int
    severity: Severity
    patient_id: str
    claim_id: str | None = None
    claim_line_ids: list[str] = []
    message_de: str
    message_en: str
    sources: list[str] = Field(description="Legal sources, e.g. 'HKP-RL §6(5)'")
    evidence: list[Evidence] = []
    kasse_codes: list[KasseCode] = []
    amount_at_risk_cents: int = 0


def claim_status(findings: list[Finding]) -> ClaimStatus:
    """No evidence-backed block → never red (ADR-3)."""
    if any(f.severity == "block" and f.evidence for f in findings):
        return "red"
    if any(f.severity in ("block", "warn") for f in findings):
        return "orange"
    return "green"


# --- Auditor (LLM-facing) --------------------------------------------------------


class Objection(Strict):
    code: KasseCode | Literal["FACT", "INFO"] = Field(
        description="A Kasse rejection code; FACT for a concrete document fact; "
        "INFO for a soft suspicion that may never block"
    )
    claim_line_ids: list[str] = Field(description="Affected claim lines; empty = whole claim")
    document_id: str | None = Field(description="Required for FACT")
    page: int | None
    field_path: str | None = Field(description="Required for FACT, e.g. 'period_to'")
    statement: str = Field(description="One sentence, as the Kasse would write it")


class AuditorOutput(Strict):
    objections: list[Objection]


class ObjectionVerdict(BaseModel):
    objection: Objection
    verdict: Literal["upheld", "dismissed"]
    reason: str
    rule_ids_checked: list[str] = []
