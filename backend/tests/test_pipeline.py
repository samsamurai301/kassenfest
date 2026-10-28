import datetime as dt
import io

import numpy as np
import pytest
from meta_sam_parser._mask_codec import _encode_raster
from PIL import Image, ImageDraw
from sqlmodel import select

from kassenfest.db import Document, Extraction, Localization, create_db, session_scope
from kassenfest.llm.client import MetaModelClient
from kassenfest.pipeline.pages import MAX_SIDE, to_pages
from kassenfest.pipeline.runner import Pipeline
from kassenfest.pipeline.validate import validate
from kassenfest.schemas.domain import Patient, Provider
from kassenfest.schemas.extraction import Muster12, VisitLogSGBV
from kassenfest.schemas.records import MasterData
from kassenfest.storage import BlobStore
from kassenfest.vision.image import PageImage
from kassenfest.vision.ink import disagrees, ink_ratio
from tests.conftest import FakeTransport
from tests.test_schemas import _field, _mark, _muster12


def _png(img: Image.Image, fmt: str = "PNG", **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


# --- pages ------------------------------------------------------------------------


def test_small_png_passes_through_unchanged():
    data = _png(Image.new("RGB", (400, 300), "white"))
    (page,) = to_pages(data, "a.png")
    assert page.data == data and (page.width, page.height) == (400, 300)


def test_exif_rotation_is_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to display
    data = _png(Image.new("RGB", (400, 300), "white"), "JPEG", exif=exif)
    (page,) = to_pages(data, "phone.jpg")
    assert (page.width, page.height) == (300, 400)


def test_large_photos_are_scaled_down_and_pdfs_split():
    (page,) = to_pages(_png(Image.new("RGB", (4000, 3000), "white"), "JPEG"), "big.jpg")
    assert max(page.width, page.height) == MAX_SIDE
    pdf = _png(
        Image.new("RGB", (595, 842), "white"),
        "PDF",
        save_all=True,
        append_images=[Image.new("RGB", (595, 842))],
    )
    assert len(to_pages(pdf, "scan.pdf")) == 2


# --- validate ---------------------------------------------------------------------


def test_validate_normalizes_dates_and_flags_garbage():
    doc = _muster12(
        issue_date=_field("01.10.2026"),
        period_to=_field("32.10.2026"),
        kvnr=_field("a 123456780"),
    )
    issues = validate(doc)
    assert doc.issue_date.value == "2026-10-01"
    assert doc.period_to.value is None and doc.period_to.status == "unreadable"
    assert doc.kvnr.value == "A123456780"
    assert issues == ["period_to: unparseable date '32.10.2026'"]
    assert doc.measures[0].duration_from == "2026-10-01"


EMPTY_LOG_FIELDS = (
    "provider_ik",
    "patient_name",
    "kvnr",
    "payer_name",
    "approval_ref",
    "responsible_nurse",
    "patient_signature_date",
    "missing_signature_reason",
)


def test_validate_checks_period_order_and_billing_month():
    assert validate(_muster12(period_to=_field("2026-09-30"))) == [
        "period_to 2026-09-30 is before period_from 2026-10-01"
    ]
    log = VisitLogSGBV.model_validate(
        {
            "doc_type": "visit_log_sgbv",
            **{k: _field(None, "empty") for k in EMPTY_LOG_FIELDS},
            "month": _field("10/2026"),
            "entries": [
                {
                    **dict.fromkeys(("end_time", "position_no", "employee_no", "box")),
                    "date": "01.10.2026",
                    "start_time": "7.05",
                    "service": "Medikamentengabe",
                    "quantity": 1,
                    "staff_initials": "MK",
                    "initials_state": "present",
                    "confidence": 0.9,
                    "page": 0,
                }
            ],
            "patient_signature": _mark("present"),
            "provider_signature": _mark("present"),
        }
    )
    assert validate(log) == []
    assert log.month.value == "2026-10"
    assert (log.entries[0].date, log.entries[0].start_time) == ("2026-10-01", "07:05")


# --- ink --------------------------------------------------------------------------


def _field_image(signed: bool) -> tuple[PageImage, tuple[float, float, float, float]]:
    img = Image.new("RGB", (600, 300), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((50, 50, 550, 250), outline=(162, 58, 74), width=3)  # red drop-out form border
    d.text((60, 225), "Unterschrift des Arztes", fill=(162, 58, 74))
    if signed:
        d.line(
            [(120, 160), (200, 100), (260, 180), (330, 110), (420, 170)],
            fill=(31, 58, 147),
            width=4,
        )
    return PageImage.from_pil(img), (50, 50, 550, 250)


def test_ink_ratio_separates_empty_from_signed_fields():
    empty, box = _field_image(signed=False)
    signed, _ = _field_image(signed=True)
    assert ink_ratio(empty, box) < 0.001
    assert ink_ratio(signed, box) > 0.01
    assert not disagrees("absent", ink_ratio(empty, box))
    assert disagrees("absent", 0.2) and disagrees("present", 0.0)


# --- pipeline end to end (fake API) -----------------------------------------------


def _sam_record(box: tuple[int, int, int, int], size: tuple[int, int]) -> str:
    x1, y1, x2, y2 = box
    mw, mh = x2 - x1 + 1, y2 - y1 + 1
    payload = _encode_raster([1] * (mw * mh), mw, mh)
    return (
        f"<0f>0<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={size[0]};h={size[1]};c=0.8|>"
        f"<|mask;x=0;y=0;c=0.8;data={mh},{mw},{payload}|>"
    )


@pytest.fixture
def pipeline_env(make_settings, tmp_path):
    def chat(kwargs):
        name = kwargs["response_format"]["json_schema"]["name"]
        if name == "Classification":
            return {
                "pages": [
                    {
                        "page": 0,
                        "doc_type": "muster12",
                        "confidence": 0.97,
                        "starts_new_document": True,
                    }
                ],
                "synthetic_watermark": True,
            }
        doc = _muster12(
            issue_date=_field("01.10.2026"),
            doctor_signature={
                "state": "present",
                "confidence": 0.9,
                "page": 0,
                "box": {"x_min": 600, "y_min": 700, "x_max": 900, "y_max": 800},
            },
            practice_stamp={
                "state": "present",
                "confidence": 0.9,
                "page": 0,
                "box": {"x_min": 100, "y_min": 700, "x_max": 450, "y_max": 820},
            },
        )
        return doc.model_dump(mode="json")

    def sam(kwargs):
        text = kwargs["input"][0]["content"][0]["text"]
        return (
            _sam_record((60, 350, 170, 400), (200, 500))
            if text == "stamp"
            else _sam_record((125, 360, 175, 390), (200, 500))
        )

    transport = FakeTransport(chat_content=chat, sam_text=sam)  # fmt: skip
    settings = make_settings()
    engine = create_db(tmp_path / "k.db")
    return transport, settings, engine, BlobStore(tmp_path / "blobs")


async def test_pipeline_stores_document_extraction_and_evidence_boxes(pipeline_env):
    transport, settings, engine, blobs = pipeline_env
    events = []
    pipeline = Pipeline(
        MetaModelClient(settings, transport=transport), engine, blobs, events.append
    )
    page = Image.fromarray(np.full((500, 200, 3), 255, np.uint8))
    ImageDraw.Draw(page).line([(130, 380), (150, 365), (170, 385)], fill=(31, 58, 147), width=3)
    image = _png(page)  # a blue pen stroke where the fake SAM finds the signature

    batch_id = await pipeline.ingest([("m12.png", image)], label="test")

    with session_scope(engine) as s:
        (doc,) = s.exec(select(Document).where(Document.batch_id == batch_id)).all()
        assert (doc.status, doc.doc_type, doc.synthetic_watermark) == ("done", "muster12", True)
        ext = s.exec(select(Extraction).where(Extraction.document_id == doc.id)).one()
        assert ext.data["issue_date"]["value"] == "2026-10-01"  # validated before storing
        assert ext.reasoning_effort == "low"
        locs = {
            x.field_path: x
            for x in s.exec(select(Localization).where(Localization.document_id == doc.id))
        }
    assert locs["practice_stamp"].source == "sam_concept"
    assert locs["doctor_signature"].source == "sam_refine"
    assert locs["doctor_signature"].box == [125, 360, 176, 391]
    assert "corrections_initialled" not in locs  # no box from the model: nothing to draw
    assert [e.step for e in events] == ["stored", "classified", "extracted", "localized", "done"]
    assert Muster12.model_validate(ext.data).kvnr.value == "A123456780"


async def test_reprocessing_a_file_supersedes_the_earlier_run_and_links_it(pipeline_env):
    transport, settings, engine, blobs = pipeline_env
    records = MasterData(
        month="2026-10",
        provider=Provider(name="Pflegedienst", ik="469960557", municipality="Deggendorf"),
        patients=[
            Patient(
                id="p1",
                name="Muster, Erika",
                dob=dt.date(1940, 1, 1),
                kvnr="A123456780",
                insurance=[],
            )
        ],
        physicians=[],
        payers=[],
        hospital={},
    )
    events = []
    client = MetaModelClient(settings, transport=transport)
    pipeline = Pipeline(client, engine, blobs, events.append, records)
    image = _png(Image.new("RGB", (200, 500), "white"))

    await pipeline.ingest([("m12.png", image)])
    await pipeline.ingest([("m12 again.png", image)])

    with session_scope(engine) as s:
        docs = s.exec(select(Document)).all()
        assert sorted(d.status for d in docs) == ["done", "superseded"]
        assert {d.patient_id for d in docs} == {"p1"}
    assert ("linked", "p1 by kvnr") in [(e.step, e.detail) for e in events]


async def test_pipeline_marks_a_failed_document_and_keeps_going(pipeline_env):
    transport, settings, engine, blobs = pipeline_env
    transport.chat_content = lambda kwargs: {"not": "valid"}
    pipeline = Pipeline(MetaModelClient(settings, transport=transport), engine, blobs)
    batch_id = await pipeline.ingest([("bad.png", _png(Image.new("RGB", (100, 100), "white")))])
    with session_scope(engine) as s:
        (doc,) = s.exec(select(Document).where(Document.batch_id == batch_id)).all()
    assert doc.status == "error" and "ValidationError" in (doc.error or "")


async def test_refine_keeps_model_box_when_sam_grows_it(make_settings):
    from kassenfest.pipeline.localize import refine
    from kassenfest.schemas.common import Box1000

    img = Image.new("RGB", (200, 500), "white")
    ImageDraw.Draw(img).rectangle((0, 0, 199, 499), outline=(31, 58, 147), width=6)
    page = PageImage.from_pil(img)
    transport = FakeTransport(sam_text=_sam_record((0, 0, 199, 499), (200, 500)))  # whole page
    client = MetaModelClient(make_settings(), transport=transport)
    rough = Box1000(x_min=600, y_min=700, x_max=900, y_max=800)
    located = await refine(client, [page], "doctor_signature", 0, rough)
    assert located.source == "muse"
    assert located.box == (120.0, 350.0, 180.0, 400.0)


def test_validate_makes_malformed_identifiers_unreadable():
    doc = _muster12(payer_ik=_field("10990018"), kvnr=_field("A 123456780"))
    assert validate(doc) == ["payer_ik: unexpected format '10990018'"]
    assert doc.payer_ik.value is None and doc.payer_ik.status == "unreadable"
    assert doc.kvnr.value == "A123456780"
    assert validate(doc) == []  # idempotent: safe to re-run on stored extractions
