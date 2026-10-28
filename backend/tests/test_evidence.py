"""Evidence boxes: visit-log rows on the printed grid, fields refined by SAM in batches."""

import io

import numpy as np
from meta_sam_parser._mask_codec import _encode_raster
from PIL import Image, ImageDraw

from kassenfest.llm.client import MetaModelClient
from kassenfest.pipeline.localize import refine_boxes
from kassenfest.vision.grid import snap_rows
from kassenfest.vision.image import PageImage
from tests.conftest import FakeTransport

HEADER, DAYS, TOP, PITCH = 2, 30, 100, 24
PEN = (31, 58, 147)


def grid_page(ink_days: tuple[int, ...]) -> tuple[np.ndarray, list[int]]:
    """A day-per-row grid like the HKP Leistungsnachweis, with pen strokes in some rows."""
    lines = [TOP + i * PITCH for i in range(HEADER + DAYS + 1)]
    img = Image.new("RGB", (620, lines[-1] + 120), (250, 249, 245))
    draw = ImageDraw.Draw(img)
    for y in lines:
        draw.line([(60, y), (560, y)], fill=(40, 40, 40), width=2)
    for x in (60, 160, 360, 560):
        draw.line([(x, TOP), (x, lines[-1])], fill=(40, 40, 40), width=2)
    draw.rectangle([60, lines[-1] + 12, 560, lines[-1] + 90], outline=(40, 40, 40), width=2)
    for day in ink_days:
        y = lines[HEADER + day - 1]
        draw.line([(200, y + 7), (240, y + 16)], fill=PEN, width=3)
    return np.array(img), lines


def test_rows_snap_to_their_day_even_when_the_model_is_a_row_off():
    days = (1, 5, 29)
    rgb, lines = grid_page(days)

    def band_below(day: int) -> tuple[float, float, float, float]:
        return (165.0, lines[HEADER + day] + 3.0, 355.0, lines[HEADER + day + 1] - 3.0)

    one_low = {f"entries[{i}]": (day, band_below(day)) for i, day in enumerate(days)}
    snapped = snap_rows(rgb, one_low, n_days=DAYS)
    for i, day in enumerate(days):
        x0, y0, x1, y1 = snapped[f"entries[{i}]"]
        assert lines[HEADER + day - 1] - 2 <= y0 and y1 <= lines[HEADER + day] + 2, day
        assert x0 >= 195 and x1 <= 245  # tightened to the pen stroke


def test_an_empty_cell_keeps_its_band_and_no_grid_means_no_snap():
    rgb, lines = grid_page(ink_days=())
    row = {"entries[0]": (3, (165.0, lines[HEADER + 2] + 3.0, 355.0, lines[HEADER + 3] - 3.0))}
    box = snap_rows(rgb, row, n_days=DAYS)["entries[0]"]
    expected = (165.0, lines[HEADER + 2], 355.0, lines[HEADER + 3])  # the whole band
    assert np.allclose(box, expected, atol=1)
    blank = np.full_like(rgb, 250)
    assert snap_rows(blank, row, n_days=DAYS) == {}


def _sam_objects(boxes: dict[int, tuple[int, int, int, int]], size: tuple[int, int]) -> str:
    parts = []
    for object_id, (x1, y1, x2, y2) in boxes.items():
        mw, mh = x2 - x1 + 1, y2 - y1 + 1
        mask = _encode_raster([1] * (mw * mh), mw, mh)
        parts.append(
            f"{object_id}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={size[0]};h={size[1]};c=0.8|>"
            f"<|mask;x=0;y=0;c=0.8;data={mh},{mw},{mask}|>"
        )
    return "<0f>" + ",".join(parts)


async def test_refine_boxes_matches_sam_objects_to_boxes_by_id(make_settings):
    img = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(img).line([(210, 110), (260, 125)], fill=PEN, width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page = PageImage.from_bytes(buf.getvalue())
    # SAM tightens only the second box (object "2"); the first comes back empty.
    transport = FakeTransport(
        sam_text=lambda _: _sam_objects({2: (205, 105, 265, 130)}, (400, 300))
    )
    client = MetaModelClient(make_settings(), transport=transport)

    found = await refine_boxes(
        client, page, 0, {"kvnr": (20, 20, 120, 60), "period_to": (190, 95, 280, 140)}
    )

    assert [(x.field_path, x.source, x.box) for x in found] == [
        ("period_to", "sam_refine", (205, 105, 266, 131))
    ]
