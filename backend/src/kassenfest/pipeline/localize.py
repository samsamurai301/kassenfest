"""Pixel boxes for evidence, following the spike decisions (docs/SPIKES.md, 2026-10-27).

- stamps: SAM concept "stamp" (18/18 hits), matched to the model's box
- signatures and text fields: Muse Spark box -> SAM box refine (+0.15-0.20 IoU)
- empty marks: the model's box of the empty field, plus an ink-ratio second opinion
"""

import asyncio
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from kassenfest.llm.client import MetaModelClient
from kassenfest.schemas.common import Box1000, Mark, PixelBox
from kassenfest.vision.geometry import from_norm1000, iou
from kassenfest.vision.image import PageImage
from kassenfest.vision.ink import PRESENT_BUT_BLANK, disagrees, ink_ratio


@dataclass
class Located:
    field_path: str
    page: int
    box: PixelBox
    source: Literal["muse", "sam_refine", "sam_concept"]
    confidence: float | None = None
    ink_ratio: float | None = None


def _px(box: Box1000, page: PageImage) -> PixelBox:
    return from_norm1000((box.x_min, box.y_min, box.x_max, box.y_max), page.width, page.height)


MAX_GROWTH = 1.4
"""A refinement that grows past this share of the model's box means the model pointed at the
wrong place and SAM segmented whatever was there (spike pages: every such case had IoU <= 0.3)."""


def _area(b: PixelBox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


async def refine(
    client: MetaModelClient, pages: list[PageImage], path: str, page_index: int, box: Box1000
) -> Located:
    """Tighten a model box with SAM; keep the model box when SAM finds nothing,
    grows the box, or lands on blank paper."""
    page = pages[min(page_index, len(pages) - 1)]
    rough = _px(box, page)
    result = await client.segment(page, boxes=[rough], prompt_id="localize.refine")
    if result.segments:
        seg = result.segments[0]
        plausible = _area(seg.box) <= MAX_GROWTH * _area(rough)
        if plausible and ink_ratio(page, seg.box) >= PRESENT_BUT_BLANK:
            return Located(path, page_index, seg.box, "sam_refine", seg.confidence)
    return Located(path, page_index, rough, "muse")


async def _stamp(
    client: MetaModelClient, pages: list[PageImage], path: str, mark: Mark, rough: PixelBox
) -> Located:
    page = pages[min(mark.page, len(pages) - 1)]
    result = await client.segment(page, concept="stamp", prompt_id="localize.stamp")
    best = max(result.segments, key=lambda s: iou(s.box, rough), default=None)
    if best is not None and iou(best.box, rough) > 0.1:
        return Located(path, mark.page, best.box, "sam_concept", best.confidence)
    assert mark.box is not None
    return await refine(client, pages, path, mark.page, mark.box)


async def _one(
    client: MetaModelClient, pages: list[PageImage], path: str, mark: Mark
) -> tuple[Located, str | None]:
    assert mark.box is not None
    page = pages[min(mark.page, len(pages) - 1)]
    rough = _px(mark.box, page)
    if mark.state == "present" and "stamp" in path:
        located = await _stamp(client, pages, path, mark, rough)
    elif mark.state == "present":
        located = await refine(client, pages, path, mark.page, mark.box)
    else:
        located = Located(path, mark.page, rough, "muse", mark.confidence)
    located.ink_ratio = round(ink_ratio(page, located.box), 4)
    issue = None
    # SAM's "stamp" detector is itself the evidence of ink (18/18, no false positives);
    # the pixel check is weak on pale, speckled stamp ink in photos.
    if located.source != "sam_concept" and disagrees(mark.state, located.ink_ratio):
        issue = f"{path}: model says {mark.state} but ink ratio is {located.ink_ratio:.3f}"
    return located, issue


async def localize_marks(
    client: MetaModelClient, pages: list[PageImage], doc: BaseModel
) -> tuple[list[Located], list[str]]:
    marks = [
        (name, value)
        for name in type(doc).model_fields
        if isinstance(value := getattr(doc, name), Mark) and value.box is not None
    ]
    results = await asyncio.gather(*(_one(client, pages, name, mark) for name, mark in marks))
    return [r[0] for r in results], [r[1] for r in results if r[1]]
