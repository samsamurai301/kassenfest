"""Ground truth the synthetic generator writes next to every document (docs/03 §4.4).

The pipeline never sees it. `fields` uses the same dotted paths as
`schemas.paths.flatten()`, so extraction can be scored field by field.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from kassenfest.schemas.common import DocType, FieldStatus, MarkState, PixelBox

Variant = Literal["clean", "scan", "fax", "photo", "bad_photo", "real_handwriting"]

DefectId = Literal[
    "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10",
    "D11", "D12", "D13", "D14", "D15", "D16", "D17", "D18", "D19", "D20",
    "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10",
]  # fmt: skip
"""Seeded defects, docs/01 §4; S01–S10 are the subtle ones no rule checks (`synth.subtle`)."""


class GTPage(BaseModel):
    index: int
    image: str = Field(description="Path relative to the ground-truth file")
    width: int
    height: int


class GTField(BaseModel):
    value: Any
    status: FieldStatus = "present"
    page: int = 0
    box: PixelBox | None = None
    handwritten: bool = False


class GTRegion(BaseModel):
    """Where a mark (signature, stamp, Handzeichen) is, or should be."""

    page: int = 0
    box: PixelBox
    state: MarkState


class GroundTruth(BaseModel):
    doc_id: str
    doc_type: DocType
    variant: Variant
    seed: int
    patient_id: str | None = None
    month: str | None = Field(default=None, description="YYYY-MM")
    pages: list[GTPage]
    fields: dict[str, GTField]
    regions: dict[str, GTRegion] = Field(
        default={}, description="Keys match Mark field paths, e.g. 'doctor_signature'"
    )
    defects: list[DefectId] = []
    synthetic: Literal[True] = True
