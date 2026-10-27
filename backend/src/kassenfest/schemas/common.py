"""Building blocks shared by extraction, ground truth, domain and findings."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocType = Literal[
    "muster12",
    "approval_letter",
    "visit_log_sgbv",
    "visit_log_sgbxi",
    "hospital_letter",
    "other",
]

FieldStatus = Literal["present", "empty", "unreadable"]
"""present: read · empty: field blank on the form · unreadable: ink there, not legible."""

MarkState = Literal["present", "absent", "unclear"]
"""Signatures, stamps, Handzeichen, ticks: is there ink where it belongs?"""

PixelBox = tuple[float, float, float, float]
"""left, top, right, bottom in page pixels (right/bottom exclusive)."""


class Strict(BaseModel):
    """Base for schemas the model fills: every key required, no extra keys.

    Fields carry no defaults and no numeric constraints on purpose: constrained
    decoding then emits every key, and out-of-range values are clamped in our
    code instead of failing validation.
    """

    model_config = ConfigDict(extra="forbid")


class Box1000(Strict):
    """Box on Muse Spark's 0–1000 page grid, origin top-left, x right, y down."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int


class Frequency(Strict):
    count: int = Field(description="How many times per period, e.g. 3 for '3x tgl.'")
    per: Literal["day", "week", "month"]


class Extracted[T](Strict):
    """One field as read from the page, with how sure we are and where it is."""

    value: T | None = Field(
        description="The value exactly as meant on the form; null unless present"
    )
    status: FieldStatus = Field(
        description="present = read; empty = field blank on the form; "
        "unreadable = something is written but not legible (never guess)"
    )
    confidence: float = Field(description="0-1: certainty that value is exactly what is written")
    page: int = Field(description="0-based page index")
    box: Box1000 | None = Field(description="Where the value is written; null if not located")


class Mark(Strict):
    """A signature, stamp, Handzeichen or tick: presence matters more than content."""

    state: MarkState = Field(description="present = ink in the field; absent = field is empty")
    confidence: float = Field(description="0-1")
    page: int = Field(description="0-based page index")
    box: Box1000 | None = Field(
        description="Region of the mark, or of the empty field where it belongs"
    )
