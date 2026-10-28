"""The Pflegedienst's own records: what it knows without reading any paper.

Its billing software holds staff, patients (KVNRs as typed in), doctors and Kassen,
the claims already sent, and the fax server's send reports. The pipeline links
documents to patients with these and fills the facts a page cannot show: when a
Verordnung reached the Kasse, and what was billed before.
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from kassenfest.schemas.domain import Claim, Patient, Payer, Physician, Provider


class FaxReport(BaseModel):
    """Sendebericht: the fax server's proof that a Verordnung went to the Kasse."""

    patient_id: str
    issue_date: dt.date = Field(description="Ausstellungsdatum of the Verordnung sent")
    physician_lanr: str
    sent_on: dt.date


class MasterData(BaseModel):
    """master_data.json of a synthetic set; a real install reads its billing software."""

    synthetic: Literal[True] = True
    month: str
    provider: Provider
    patients: list[Patient]
    physicians: list[Physician]
    payers: list[Payer]
    hospital: dict[str, str]
    fax_reports: list[FaxReport] = []
    billed: list[Claim] = Field(default=[], description="Claims already sent, earlier months")
