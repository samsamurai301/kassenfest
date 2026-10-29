"""Actions: what somebody at the Pflegedienst has to do before a bill can go out.

The fixer agent (`agents.fixer`) files them from the findings; the fixtures hand-write them.
Every one carries a drafted letter or note: Kassenfest never sends anything itself.
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

ActionKind = Literal[
    "folgeverordnung_request",
    "stamp_request",
    "prescription_change",
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
    run_id: str | None = Field(None, description="The fixer agent's run that filed it, if any")
