"""Typed facts the rules engine evaluates.

Two producers build these: the synthetic world (the truth) and the pipeline
(what was read from paper). Running the same rules on both is how defect
detection is evaluated. Money is always integer cents.
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from kassenfest.schemas.common import Frequency

Domain = Literal["sgbv", "sgbxi"]


class Staff(BaseModel):
    employee_no: str = Field(description="Beschäftigtennummer (LBNR), 9 digits")
    initials: str = Field(description="Handzeichen, 2-3 letters")
    name: str
    qualification: Literal["pflegefachkraft", "pflegehilfskraft", "auszubildende"]


class Provider(BaseModel):
    name: str
    ik: str
    bundesland: str = "BY"
    municipality: str = Field(description="Drives the holiday calendar, e.g. Mariä Himmelfahrt")
    address: list[str] = Field(default=[], description="Street and town, for letterheads")
    staff: list[Staff] = []
    billing_working_day: int = Field(
        default=5, description="A month's bills go out on this working day of the next month"
    )


class Payer(BaseModel):
    name: str
    ik: str
    kind: Literal["krankenkasse", "pflegekasse"]
    payment_term_days: int = 21
    synthetic: bool = True


class Physician(BaseModel):
    name: str
    lanr: str
    bsnr: str
    address: list[str] = Field(default=[], description="Practice address lines, for letters")


class PflegegradPeriod(BaseModel):
    grade: int = Field(ge=1, le=5)
    valid_from: dt.date


class InsurancePeriod(BaseModel):
    krankenkasse_ik: str
    pflegekasse_ik: str
    valid_from: dt.date
    valid_to: dt.date | None = None


class Patient(BaseModel):
    id: str
    name: str = Field(description="'Nachname, Vorname'")
    dob: dt.date
    kvnr: str
    insurance: list[InsurancePeriod]
    pflegegrad: list[PflegegradPeriod] = []
    deceased_at: dt.datetime | None = None
    copay_exempt: bool = False


class PrescribedService(BaseModel):
    category: str = Field(description="MeasureCategory, e.g. 'medikamentengabe'")
    position_no: str | None = None
    frequency: Frequency | None = None
    details: str | None = None


class Prescription(BaseModel):
    """Verordnung (Muster 12)."""

    id: str
    patient_id: str
    physician_lanr: str
    kind: Literal["erst", "folge"]
    issue_date: dt.date
    period_from: dt.date
    period_to: dt.date
    blank: bool = False
    services: list[PrescribedService]
    icd_codes: list[str] = []
    doctor_signed: bool
    stamp_present: bool
    corrections_present: bool = False
    corrections_initialled: bool = False
    submitted_to_payer_at: dt.date | None = None
    document_id: str | None = None


class ApprovedService(BaseModel):
    position_no: str
    frequency: Frequency | None = None
    valid_from: dt.date
    valid_to: dt.date


class Approval(BaseModel):
    """Genehmigung of the Krankenkasse for a Verordnung."""

    id: str
    patient_id: str
    payer_ik: str
    provider_ik: str
    approval_ref: str
    letter_date: dt.date
    decision: Literal["approved", "partial", "rejected"]
    period_from: dt.date
    period_to: dt.date
    approved: list[ApprovedService]
    prescription_id: str | None = None
    document_id: str | None = None


class Visit(BaseModel):
    """One delivered service on one visit, as billed from the Leistungsnachweis."""

    date: dt.date
    start: dt.time | None = None
    end: dt.time | None = None
    code: str = Field(description="HKP Positionsnummer (SGB V) or LK number (SGB XI)")
    quantity: int = 1
    funding: Literal["hkp", "sachleistung_36", "entlastung_45b"] = "hkp"
    employee_no: str | None = None
    staff_initials: str | None = None
    document_id: str | None = None
    entry_index: int | None = None


class VisitLog(BaseModel):
    """Leistungsnachweis for one patient, payer and month."""

    id: str
    patient_id: str
    payer_ik: str
    month: str = Field(description="YYYY-MM")
    domain: Domain
    visits: list[Visit]
    patient_signed: bool
    missing_signature_reason: Literal[1, 2, 3, 4] | None = None
    provider_signed: bool = True
    document_id: str | None = None


class Stay(BaseModel):
    id: str
    patient_id: str
    kind: Literal["hospital", "rehab", "short_term_care", "hospice", "nursing_home"]
    admitted_at: dt.datetime
    discharged_at: dt.datetime | None = None
    document_id: str | None = None


class ClaimLine(BaseModel):
    id: str
    date: dt.date
    time: dt.time | None = None
    code: str
    quantity: int
    unit_price_cents: int
    funding: Literal["hkp", "sachleistung_36", "entlastung_45b"] = "hkp"
    visit_log_id: str | None = None
    entry_index: int | None = None

    @computed_field
    @property
    def amount_cents(self) -> int:
        return self.unit_price_cents * self.quantity


class Claim(BaseModel):
    id: str
    patient_id: str
    payer_ik: str
    month: str = Field(description="YYYY-MM")
    domain: Domain
    lines: list[ClaimLine]
    tariff_version: str

    @computed_field
    @property
    def total_cents(self) -> int:
        return sum(line.amount_cents for line in self.lines)


class CaseFile(BaseModel):
    """Everything known about one patient for one billing month: the rules engine's input."""

    month: str = Field(description="YYYY-MM")
    provider: Provider
    patient: Patient
    payers: dict[str, Payer] = Field(description="By IK")
    physicians: dict[str, Physician] = Field(default={}, description="By LANR")
    prescriptions: list[Prescription] = []
    approvals: list[Approval] = []
    visit_logs: list[VisitLog] = []
    stays: list[Stay] = []
    prior_claims: list[Claim] = Field(default=[], description="Already sent; for duplicates")
