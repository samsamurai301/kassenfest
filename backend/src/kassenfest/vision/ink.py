"""Is there ink in a field? A deterministic second opinion on the model's mark state (SAM-04).

Printed ruling lines and box borders are removed first (long thin horizontal or
vertical runs), and the red drop-out colour of Muster forms is ignored.

Calibration on the spike pages (docs/SPIKES.md, 2026-10-27): with Muse Spark's
field boxes, empty fields scored up to 0.048 (printed labels inside the cell,
scan noise) and signed fields as low as 0.0 (box missed the ink), while the
model's own present/absent call was right 64/64. So the model decides; this
only flags strong disagreement for human review.
"""

import io

import cv2
import numpy as np
from PIL import Image

from kassenfest.schemas.common import PixelBox
from kassenfest.vision.image import PageImage

ABSENT_BUT_INKED = 0.08
"""Model says empty, yet more ink than any truly empty field in calibration (max 0.048)."""
PRESENT_BUT_BLANK = 0.0005
"""Model says signed, yet the box is practically blank: wrong box or a very faint mark."""


def ink_ratio(page: PageImage, box: PixelBox, inset: float = 0.06) -> float:
    img = np.array(Image.open(io.BytesIO(page.data)).convert("RGB"))
    x0, y0, x1, y1 = box
    dx, dy = (x1 - x0) * inset, (y1 - y0) * inset  # stay off the field's own border
    crop = img[int(y0 + dy) : int(y1 - dy), int(x0 + dx) : int(x1 - dx)]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    paper = cv2.medianBlur(gray, 31) if min(gray.shape) > 31 else np.full_like(gray, 255)
    # Muster forms print in a red drop-out colour so scanners can ignore it; so do we.
    form_red = ((hue < 12) | (hue > 165)) & (sat > 60)
    pen = (hue >= 95) & (hue <= 160) & (sat > 70) & (val < 220)  # blue / violet ink and stamps
    dark = (paper.astype(int) - gray.astype(int)) > 60
    ink = (dark & ~form_red) | pen
    ink = ink.astype(np.uint8) * 255
    h, w = ink.shape
    lines = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 3, 1), 1))
    )
    lines |= cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 3, 1)))
    )
    ink &= ~lines
    return float((ink > 0).mean())


def disagrees(state: str, ratio: float) -> bool:
    """True when the pixels clearly contradict the model's mark state."""
    if state == "absent":
        return ratio > ABSENT_BUT_INKED
    if state == "present":
        return ratio < PRESENT_BUT_BLANK
    return False
