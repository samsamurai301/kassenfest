"""SAM 3.1 prompt building and output parsing, on top of meta_sam_parser."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from meta_sam_parser import (
    CompletedOutcome,
    FramePrompt,
    PromptBox,
    PromptObject,
    SegmentationBoxRecord,
    SegmentationMask,
    SegmentationMaskRecord,
    build_object_prompt,
    decode_mask_to_raster,
    image_segmentation_format,
)

from kassenfest.vision.geometry import Box

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Segment:
    object_id: str
    box: Box
    confidence: float | None
    mask: SegmentationMask | None

    def mask_array(self) -> np.ndarray | None:
        """Box-local boolean raster, shape (mask.height, mask.width)."""
        if self.mask is None:
            return None
        raw = decode_mask_to_raster(self.mask)
        return np.frombuffer(raw, dtype=np.uint8).reshape(self.mask.height, self.mask.width) > 0


def parse_sam_output(text: str) -> list[Segment]:
    """Parse a complete image response. Empty text means no match, not an error."""
    parser = image_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    for diag in result.diagnostics:
        log.warning("SAM output %s: %s (%r)", diag.code, diag.message, diag.raw[:120])

    boxes: dict[str, SegmentationBoxRecord] = {}
    masks: dict[str, SegmentationMaskRecord] = {}
    for record in result.records:
        if isinstance(record, SegmentationBoxRecord):
            boxes[record.object_id] = record
        elif isinstance(record, SegmentationMaskRecord):
            masks[record.object_id] = record  # later revisions win

    segments = []
    for object_id, b in boxes.items():
        m = masks.get(object_id)
        confidence = b.confidence if b.confidence is not None else (m and m.confidence)
        segments.append(
            Segment(
                object_id=object_id,
                box=(b.left, b.top, b.right, b.bottom),
                confidence=confidence,
                mask=m.mask if m else None,
            )
        )
    return segments


def box_prompt(width: int, height: int, boxes: Sequence[Box]) -> str:
    """Prompt text asking SAM to refine each pixel box into a mask (max 16 objects)."""
    if not 1 <= len(boxes) <= 16:
        raise ValueError("SAM accepts 1–16 prompted objects")
    objects = [
        PromptObject(
            id=i + 1,
            prompts=[FramePrompt(frame=0, box=PromptBox(*(round(v) for v in box)))],
        )
        for i, box in enumerate(boxes)
    ]
    return build_object_prompt(size=(width, height), objects=objects)
