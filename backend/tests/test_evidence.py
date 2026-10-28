"""Evidence boxes: visit-log rows on the printed grid, fields refined by SAM in batches,
and what SAM can't tighten asked again on a crop."""

import base64
import io

import numpy as np
from meta_sam_parser._mask_codec import _encode_raster
from PIL import Image, ImageDraw

from kassenfest.config import REPO_ROOT
from kassenfest.db import Document, Page
from kassenfest.llm.client import MetaModelClient
from kassenfest.pipeline.evidence import to_find
from kassenfest.pipeline.localize import crop_region, find_on_crops, refine_boxes
from kassenfest.pipeline.month import StoredDoc
from kassenfest.schemas.common import Box1000
from kassenfest.schemas.ground_truth import GroundTruth
from kassenfest.synth.oracle import perfect_extraction
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


def _norm(box: tuple[float, ...], region: tuple[int, int, int, int]) -> dict[str, int]:
    """A page box on the 0-1000 grid of a crop, as Muse Spark answers."""
    w, h = region[2] - region[0], region[3] - region[1]
    x0, y0, x1, y1 = box
    return {
        "x_min": round((x0 - region[0]) * 1000 / w),
        "y_min": round((y0 - region[1]) * 1000 / h),
        "x_max": round((x1 - region[0]) * 1000 / w),
        "y_max": round((y1 - region[1]) * 1000 / h),
    }


async def test_a_value_found_on_a_crop_maps_back_to_the_page_and_sam_tightens_it(make_settings):
    img = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(img)
    draw.line([(300, 200), (380, 215)], fill=PEN, width=3)  # the date
    draw.line([(60, 60), (160, 75)], fill=PEN, width=3)  # the KVNR
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page = PageImage.from_bytes(buf.getvalue())
    # The model's boxes sit a line below the ink, as on the photos.
    rough = {
        "period_to": (290.0, 222.0, 390.0, 242.0),
        "kvnr": (50.0, 80.0, 170.0, 95.0),
        "lanr": (400.0, 300.0, 500.0, 320.0),
    }
    ink = {"period_to": (298.0, 198.0, 382.0, 217.0), "kvnr": (58.0, 58.0, 162.0, 77.0)}
    sizes = []

    def muse(request):
        content = request["messages"][1]["content"]
        crop = Image.open(
            io.BytesIO(base64.b64decode(content[1]["image_url"]["url"].split(",")[1]))
        )
        sizes.append(crop.size)
        path = next(p for p in rough if f"({p})" in content[0]["text"])
        if path not in ink:
            return {"found": False, "text": None, "box": None}
        region = crop_region(rough[path], 600, 400)
        return {"found": True, "text": "x", "box": _norm(ink[path], region)}

    # SAM tightens the date (object "1") and returns nothing for the KVNR.
    transport = FakeTransport(
        chat_content=muse, sam_text=lambda _: _sam_objects({1: (296, 196, 383, 218)}, (600, 400))
    )
    client = MetaModelClient(make_settings(), transport=transport)
    asks = {p: (box, f"Find the field ({p}).") for p, box in rough.items()}

    found = {x.field_path: x for x in await find_on_crops(client, page, 0, asks)}

    assert all(800 <= max(size) <= 1300 for size in sizes)  # upscaled to about 1000 px
    assert found["period_to"].source == "crop_sam"
    assert found["period_to"].box == (296, 196, 384, 219)
    assert found["kvnr"].source == "crop"
    assert np.allclose(found["kvnr"].box, ink["kvnr"], atol=1)
    assert "lanr" not in found  # not in the crop: the model's box stays


def test_crop_questions_go_to_values_read_but_not_tightened():
    gt = GroundTruth.model_validate_json(
        (REPO_ROOT / "data/synthetic/demo/truth/syn-demo-004.json").read_text()
    )
    rx = perfect_extraction(gt)
    box = Box1000(x_min=100, y_min=100, x_max=200, y_max=150)

    def put(name: str, **update) -> None:
        setattr(rx, name, getattr(rx, name).model_copy(update={"box": box, **update}))

    put("kvnr", status="present", value="A123456780")  # SAM tightened it in this run
    put("period_to", status="present", value="2026-10-14")
    put("lanr", status="unreadable", value=None)
    put("further_notes", status="empty", value=None)
    put("doctor_signature", state="present")  # SAM missed it at ingest
    put("practice_stamp", state="present")  # SAM's stamp detector found it
    doc = StoredDoc(
        Document(
            id="d",
            batch_id="b",
            filename="f.png",
            source_sha256="s",
            source_key="k",
            doc_type="muster12",
            status="done",
        ),
        [Page(document_id="d", index=0, blob_key="x", width=1000, height=1000)],
        rx,
        [],
        sources={"doctor_signature": "muse", "practice_stamp": "sam_concept"},
    )

    asks = to_find(doc, tightened={"kvnr"})[0]

    assert set(asks) == {"period_to", "lanr", "doctor_signature"}
    assert asks["period_to"][0] == (100.0, 100.0, 200.0, 150.0)
    assert asks["period_to"][1].endswith("Find the bis (period_to), which reads: 14.10.2026.")
    assert "hard to read" in asks["lanr"][1]
    assert asks["doctor_signature"][1].endswith("the ink in that field.")
