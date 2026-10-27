import pytest

from kassenfest.vision.geometry import from_norm1000, iou


def test_norm1000_scales_to_pixels_and_clamps_overshoot():
    assert from_norm1000((0, 500, 1001, 1000), width=2000, height=800) == (0, 400, 2000, 800)


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(50 / 150)
