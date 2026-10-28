"""Pixel boxes for evidence, following the spike decisions (docs/SPIKES.md, 2026-10-27).

- stamps: SAM concept "stamp" (18/18 hits), matched to the model's box
- signatures and text fields: Muse Spark box -> SAM box refine (+0.15-0.20 IoU)
- empty marks: the model's box of the empty field, plus an ink-ratio second opinion

After each batch every field that was read is refined the same way (`pipeline.evidence`),
16 boxes per SAM call. What SAM can't tighten is asked again on a crop (docs/SPIKES.md,
2026-10-28): Muse Spark on an upscaled crop around its first box, then SAM on that.
"""

import asyncio
import io
from dataclasses import dataclass, replace
from typing import Literal

from PIL import Image
from pydantic import BaseModel

from kassenfest.llm.client import MetaModelClient
from kassenfest.llm.prompts import FIND_SYSTEM, FIND_VERSION
from kassenfest.schemas.common import Box1000, Mark, PixelBox, Strict
from kassenfest.vision.geometry import from_norm1000, iou
from kassenfest.vision.image import PageImage
from kassenfest.vision.ink import PRESENT_BUT_BLANK, disagrees, ink_ratio


@dataclass
class Located:
    field_path: str
    page: int
    box: PixelBox
    source: Literal["muse", "sam_refine", "sam_concept", "grid", "crop", "crop_sam"]
    confidence: float | None = None
    ink_ratio: float | None = None


def _px(box: Box1000, page: PageImage) -> PixelBox:
    return from_norm1000((box.x_min, box.y_min, box.x_max, box.y_max), page.width, page.height)


MAX_GROWTH = 1.4
"""A refinement that grows past this share of the model's box means the model pointed at the
wrong place and SAM segmented whatever was there (spike pages: every such case had IoU <= 0.3)."""


def _area(b: PixelBox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _plausible(
    page: PageImage,
    refined: PixelBox,
    rough: PixelBox,
    max_growth: float = MAX_GROWTH,
    need_ink: bool = True,
) -> bool:
    return _area(refined) <= max_growth * _area(rough) and (
        not need_ink or ink_ratio(page, refined) >= PRESENT_BUT_BLANK
    )


async def refine(
    client: MetaModelClient, pages: list[PageImage], path: str, page_index: int, box: Box1000
) -> Located:
    """Tighten a model box with SAM; keep the model box when SAM finds nothing,
    grows the box, or lands on blank paper."""
    page = pages[min(page_index, len(pages) - 1)]
    rough = _px(box, page)
    result = await client.segment(page, boxes=[rough], prompt_id="localize.refine")
    if result.segments and _plausible(page, result.segments[0].box, rough):
        seg = result.segments[0]
        return Located(path, page_index, seg.box, "sam_refine", seg.confidence)
    return Located(path, page_index, rough, "muse")


async def refine_boxes(
    client: MetaModelClient,
    page: PageImage,
    page_index: int,
    rough: dict[str, PixelBox],
    *,
    max_growth: float = MAX_GROWTH,
    need_ink: bool = True,
) -> list[Located]:
    """SAM refine for many boxes on one page, 16 per call; only the boxes SAM tightened."""
    items = list(rough.items())
    out = []
    for start in range(0, len(items), 16):
        chunk = items[start : start + 16]
        result = await client.segment(
            page, boxes=[box for _, box in chunk], prompt_id="evidence.refine"
        )
        by_id = {str(seg.object_id): seg for seg in result.segments}
        for i, (path, box) in enumerate(chunk, start=1):
            seg = by_id.get(str(i))
            if seg is not None and _plausible(page, seg.box, box, max_growth, need_ink):
                out.append(Located(path, page_index, seg.box, "sam_refine", seg.confidence))
    return out


class CropBox(Strict):  # no docstring: it would become part of the JSON schema in the request
    found: bool
    text: str | None
    box: Box1000 | None


CROP_PX = 1000
"""Crops are upscaled to about this long side. At their natural few hundred pixels, Muse
Spark's box missed the value by a text line about a quarter of the time."""
CROP_GROWTH = 2.0
"""SAM may grow a box found on a crop this much: those boxes sit tight on the ink."""


def crop_region(box: PixelBox, width: int, height: int) -> tuple[int, int, int, int]:
    """The model's box plus room for its usual miss: a line or two up or down, a bit sideways."""
    x0, y0, x1, y1 = box
    mx, my = max(0.5 * (x1 - x0), 0.04 * width), max(1.5 * (y1 - y0), 0.06 * height)
    return (
        int(max(0, x0 - mx)),
        int(max(0, y0 - my)),
        int(min(width, x1 + mx)),
        int(min(height, y1 + my)),
    )


def _crop(page: PageImage, region: tuple[int, int, int, int]) -> PageImage:
    with Image.open(io.BytesIO(page.data)) as img:
        crop = img.convert("RGB").crop(region)
    k = min(4, max(1, round(CROP_PX / max(crop.size))))
    return PageImage.from_pil(
        crop.resize((crop.width * k, crop.height * k), Image.Resampling.LANCZOS)
    )


async def find_on_crop(
    client: MetaModelClient, page: PageImage, page_index: int, path: str, rough: PixelBox, ask: str
) -> Located | None:
    """Muse Spark's box for one value, asked again on an upscaled crop around its first box."""
    region = crop_region(rough, page.width, page.height)
    result = await client.chat_json(
        prompt_id=f"evidence.crop.{FIND_VERSION}",
        schema=CropBox,
        system=FIND_SYSTEM,
        user_text=ask,
        images=[_crop(page, region)],
        reasoning_effort="low",
    )
    answer = result.parsed
    if not answer.found or answer.box is None:
        return None
    b = answer.box
    x0, y0, x1, y1 = from_norm1000(
        (b.x_min, b.y_min, b.x_max, b.y_max), region[2] - region[0], region[3] - region[1]
    )
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    left, top = region[0], region[1]
    return Located(path, page_index, (x0 + left, y0 + top, x1 + left, y1 + top), "crop")


async def find_on_crops(
    client: MetaModelClient,
    page: PageImage,
    page_index: int,
    asks: dict[str, tuple[PixelBox, str]],
) -> list[Located]:
    """For values SAM couldn't tighten (path → model box, question): Muse Spark on a crop,
    then SAM on the box it found.

    SAM's box stands unless it grows past CROP_GROWTH. No ink check: the ink ratio reads
    zero inside tight text boxes on photos, and Muse has just pointed at the ink.
    """
    found = await asyncio.gather(
        *(find_on_crop(client, page, page_index, p, box, ask) for p, (box, ask) in asks.items())
    )
    crops = {x.field_path: x for x in found if x is not None}
    tight = await refine_boxes(
        client,
        page,
        page_index,
        {p: x.box for p, x in crops.items()},
        max_growth=CROP_GROWTH,
        need_ink=False,
    )
    for x in tight:
        crops[x.field_path] = replace(x, source="crop_sam")
    return list(crops.values())


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
