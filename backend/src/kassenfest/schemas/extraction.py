"""What Muse Spark returns per document type (docs/03 §4.2).

These describe the paper, not the truth: dates stay ISO strings as written, every
field says whether it was read, blank or illegible, and where on the page it is.
`kassenfest.pipeline` validates and converts them into `schemas.domain` facts.
"""

from typing import Literal

from pydantic import Field

from kassenfest.schemas.common import (
    Box1000,
    DocType,
    Extracted,
    Frequency,
    Mark,
    Strict,
)

ISO_DATE = "ISO date YYYY-MM-DD (convert from DD.MM.YYYY)"
ISO_MONTH = "Billing month as YYYY-MM"

MeasureCategory = Literal[
    "medikamentengabe",
    "injektion",
    "blutzucker",
    "kompression",
    "wundversorgung",
    "positionswechsel",
    "anleitung",
    "grundpflege",
    "hauswirtschaft",
    "unterstuetzungspflege",
    "krankenhausvermeidungspflege",
    "sonstige",
]


class Located(Strict):
    """Mixin fields for list items: one confidence and box for the whole row."""

    confidence: float = Field(description="0-1 for the row as a whole")
    page: int = Field(description="0-based page index")
    box: Box1000 | None = Field(description="Region of the row or cell")


# --- Classification -----------------------------------------------------------


class PageClass(Strict):
    page: int = Field(description="0-based page index")
    doc_type: DocType
    confidence: float = Field(description="0-1")
    starts_new_document: bool = Field(
        description="True if this page begins a document, False if it continues the previous page"
    )


class Classification(Strict):
    pages: list[PageClass]
    synthetic_watermark: bool = Field(
        description="True if the 'MUSTER – SYNTHETISCH – KEIN ECHTES DOKUMENT' mark is visible"
    )


# --- Muster 12: Verordnung häuslicher Krankenpflege -----------------------------


class PrescribedMeasure(Located):
    category: MeasureCategory
    details: str | None = Field(
        description="Präparat, Wundart/Lokalisation/Größe/Grad, Seite etc. as written"
    )
    frequency: Frequency | None
    duration_from: str | None = Field(description=ISO_DATE)
    duration_to: str | None = Field(description=ISO_DATE)


class Muster12(Strict):
    doc_type: Literal["muster12"]
    payer_name: Extracted[str] = Field(description="Krankenkasse bzw. Kostenträger")
    payer_ik: Extracted[str] = Field(description="Kostenträgerkennung, 9 digits")
    patient_name: Extracted[str] = Field(description="'Nachname, Vorname' as written")
    patient_dob: Extracted[str] = Field(description=ISO_DATE)
    kvnr: Extracted[str] = Field(description="Versicherten-Nr.: 1 letter + 9 digits")
    bsnr: Extracted[str] = Field(description="Betriebsstätten-Nr., 9 digits")
    lanr: Extracted[str] = Field(description="Arzt-Nr. (LANR), 9 digits")
    issue_date: Extracted[str] = Field(description=f"Ausstellungsdatum, {ISO_DATE}")
    icd_codes: Extracted[list[str]] = Field(description="ICD-10 codes, e.g. ['E11.9']")
    prescription_kind: Extracted[Literal["erst", "folge"]] = Field(
        description="Erstverordnung or Folgeverordnung tick box"
    )
    accident: Extracted[bool] = Field(description="Unfall / Unfallfolgen tick box")
    blank_prescription: Extracted[bool] = Field(
        description="Blankoverordnung: nurse decides frequency and duration"
    )
    period_from: Extracted[str] = Field(description=f"Verordnungszeitraum vom, {ISO_DATE}")
    period_to: Extracted[str] = Field(description=f"Verordnungszeitraum bis, {ISO_DATE}")
    measures: list[PrescribedMeasure]
    further_notes: Extracted[str] = Field(description="Weitere Hinweise, free text")
    doctor_signature: Mark = Field(description="Unterschrift des Arztes")
    practice_stamp: Mark = Field(description="Vertragsarztstempel")
    corrections_present: bool = Field(description="Any crossed-out or overwritten entry")
    corrections_initialled: Mark = Field(
        description="Doctor's initials/stamp next to corrections; absent if none"
    )


# --- Genehmigung (approval letter from the Kasse) --------------------------------


class ApprovedItem(Located):
    position_no: str | None = Field(description="6-digit HKP Positionsnummer if printed")
    description: str
    frequency: Frequency | None
    valid_from: str | None = Field(description=ISO_DATE)
    valid_to: str | None = Field(description=ISO_DATE)


class RejectedItem(Located):
    description: str
    reason: str | None


class ApprovalLetter(Strict):
    doc_type: Literal["approval_letter"]
    payer_name: Extracted[str]
    payer_ik: Extracted[str] = Field(description="9 digits")
    letter_date: Extracted[str] = Field(description=ISO_DATE)
    approval_ref: Extracted[str] = Field(description="Genehmigungskennzeichen / Aktenzeichen")
    patient_name: Extracted[str]
    kvnr: Extracted[str]
    provider_name: Extracted[str] = Field(description="Pflegedienst addressed")
    provider_ik: Extracted[str] = Field(description="IK of the Pflegedienst, 9 digits")
    prescription_issue_date: Extracted[str] = Field(
        description=f"Date of the Verordnung this decides on, {ISO_DATE}"
    )
    decision: Extracted[Literal["approved", "partial", "rejected"]]
    period_from: Extracted[str] = Field(description=ISO_DATE)
    period_to: Extracted[str] = Field(description=ISO_DATE)
    approved_items: list[ApprovedItem]
    rejected_items: list[RejectedItem]


# --- Leistungsnachweis SGB V (HKP visit log) ------------------------------------


class VisitEntry(Located):
    date: str = Field(description=ISO_DATE)
    start_time: str | None = Field(description="HH:MM")
    end_time: str | None = Field(description="HH:MM")
    position_no: str | None = Field(description="6-digit HKP Positionsnummer if printed")
    service: str | None = Field(description="Service label as printed in the row/column")
    quantity: int
    staff_initials: str | None = Field(description="Handzeichen as written; null if none")
    employee_no: str | None = Field(description="Beschäftigtennummer if written")
    initials_state: Literal["present", "absent", "unclear"] = Field(
        description="Is there a Handzeichen in the cell?"
    )


class VisitLogSGBV(Strict):
    doc_type: Literal["visit_log_sgbv"]
    provider_ik: Extracted[str]
    patient_name: Extracted[str]
    kvnr: Extracted[str]
    payer_name: Extracted[str]
    month: Extracted[str] = Field(description=ISO_MONTH)
    approval_ref: Extracted[str] = Field(description="Genehmigungskennzeichen if printed")
    responsible_nurse: Extracted[str] = Field(description="Verantwortliche Pflegefachkraft")
    entries: list[VisitEntry] = Field(description="One entry per delivered service per visit")
    patient_signature: Mark = Field(description="Unterschrift Versicherte/r or Angehörige/r")
    patient_signature_date: Extracted[str] = Field(description=ISO_DATE)
    missing_signature_reason: Extracted[Literal["1", "2", "3", "4"]] = Field(
        description="Kennzeichen if no signature: 1 verstorben, 2 stationär, "
        "3 körperlich/geistig nicht möglich, 4 sonstiges"
    )
    provider_signature: Mark = Field(description="Unterschrift/Stempel des Pflegedienstes")


# --- Leistungsnachweis SGB XI ---------------------------------------------------


class CareEntry(Located):
    date: str = Field(description=ISO_DATE)
    time: str | None = Field(description="HH:MM")
    lk_code: str | None = Field(description="Leistungskomplex number, e.g. '2' or 'LK 2'")
    lk_label: str | None
    count: int
    funding: Literal["sachleistung_36", "entlastung_45b"] = Field(
        description="§36 Pflegesachleistung or §45b Entlastungsbetrag column/section"
    )
    staff_initials: str | None
    initials_state: Literal["present", "absent", "unclear"]


class VisitLogSGBXI(Strict):
    doc_type: Literal["visit_log_sgbxi"]
    provider_ik: Extracted[str]
    patient_name: Extracted[str]
    kvnr: Extracted[str]
    payer_name: Extracted[str] = Field(description="Pflegekasse")
    pflegegrad: Extracted[int] = Field(description="1-5")
    month: Extracted[str] = Field(description=ISO_MONTH)
    entries: list[CareEntry]
    patient_signature: Mark
    provider_signature: Mark


# --- Entlassbrief / Aufnahmeanzeige ---------------------------------------------


class HospitalLetter(Strict):
    doc_type: Literal["hospital_letter"]
    hospital_name: Extracted[str]
    hospital_id: Extracted[str] = Field(description="IK or Standortkennzeichen (77…)")
    patient_name: Extracted[str]
    patient_dob: Extracted[str] = Field(description=ISO_DATE)
    kvnr: Extracted[str]
    admission_date: Extracted[str] = Field(description=f"Aufnahme, {ISO_DATE}")
    admission_time: Extracted[str] = Field(description="HH:MM if stated")
    discharge_date: Extracted[str] = Field(description=f"Entlassung, {ISO_DATE}")
    discharge_time: Extracted[str] = Field(description="HH:MM if stated")
    discharge_diagnoses: Extracted[list[str]] = Field(description="ICD-10 codes")
    hkp_recommended: Extracted[bool] = Field(description="Häusliche Krankenpflege empfohlen")
    hkp_prescription_days: Extracted[int] = Field(
        description="Days of HKP prescribed by the hospital (max 7)"
    )
    physician_signature: Mark


EXTRACTION_SCHEMAS: dict[DocType, type[Strict]] = {
    "muster12": Muster12,
    "approval_letter": ApprovalLetter,
    "visit_log_sgbv": VisitLogSGBV,
    "visit_log_sgbxi": VisitLogSGBXI,
    "hospital_letter": HospitalLetter,
}
