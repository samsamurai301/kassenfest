import random
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kassenfest.synth import samples
from kassenfest.synth.degrade import VARIANTS
from kassenfest.synth.fonts import REQUIRED_GLYPHS, load_fonts, missing_glyphs

chromium_missing = not any(
    Path.home().joinpath("Library/Caches/ms-playwright").glob("chromium-*")
) and not any(Path.home().joinpath(".cache/ms-playwright").glob("chromium-*"))


def test_every_vendored_font_covers_german():
    fonts = load_fonts()
    assert {f.role for f in fonts} >= {"print", "mono", "hand_dev", "hand_test", "signature"}
    for face in fonts:
        assert face.file.exists()
        assert missing_glyphs(face.file) == "", f"{face.family} lacks {REQUIRED_GLYPHS}"


def test_dev_and_test_hands_never_overlap():
    dev = {f.family for f in load_fonts("hand_dev")}
    test = {f.family for f in load_fonts("hand_test")}
    assert dev and test and not dev & test


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_degradation_moves_boxes_with_the_page(variant):
    """Paint a black square, degrade, and check the transformed box still covers the ink."""
    img = Image.new("RGB", (800, 1100), "white")
    arr = np.array(img)
    arr[400:500, 300:420] = 0
    out = VARIANTS[variant](Image.fromarray(arr), random.Random(3))
    x0, y0, x1, y1 = out.box((300, 400, 420, 500))
    dark = np.array(out.image.convert("L")) < 90
    inside = dark[int(y0) : int(y1) + 1, int(x0) : int(x1) + 1].sum()
    # Most of the square's ink stays inside its box (blur and fax noise leak a little).
    assert inside > 0.8 * 100 * 120 * (out.image.width / 800) ** 2 * 0.5
    assert 0 <= x0 < x1 <= out.image.width and 0 <= y0 < y1 <= out.image.height


@pytest.mark.skipif(chromium_missing, reason="run `uv run playwright install chromium`")
def test_render_produces_boxes_for_every_present_field():
    from kassenfest.synth.documents import ground_truth, render_document
    from kassenfest.synth.render import Renderer

    with Renderer() as renderer:
        for doc_type, content in (
            ("muster12", samples.muster12(random.Random(1), stamp_present=False)),
            ("visit_log_sgbv", samples.visit_log_sgbv(random.Random(2), missing_initials=2)),
        ):
            page, truth, _ = render_document(renderer, doc_type, content, doc_id="t", seed=4)
            gt = ground_truth(
                page,
                truth,
                doc_id="t",
                doc_type=doc_type,
                variant="clean",
                seed=4,
                image_name="t.png",
            )
            unboxed = [
                k
                for k, f in gt.fields.items()
                if f.status == "present"
                and f.box is None
                and not k.endswith(
                    ("[#]", "quantity", "doc_type", "corrections_present", "corrections_initialled")
                )
            ]
            assert unboxed == [], (doc_type, unboxed)
            if doc_type == "muster12":
                assert gt.regions["practice_stamp"].state == "absent"
                assert gt.regions["doctor_signature"].state == "present"
            else:
                states = [f.value for k, f in gt.fields.items() if k.endswith("initials_state")]
                assert states.count("absent") == 2
