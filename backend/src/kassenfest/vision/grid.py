"""Rows of a day-per-row form grid (the HKP Leistungsnachweis), found from its ruling lines.

Muse Spark's row boxes drift. On a 31-row grid they are right at the top and a row or
more off by the bottom, and on some photos every row is one off (docs/SPIKES.md,
2026-10-28). The printed ruling lines don't drift. Counting the day rows up from the
table's bottom line puts day d in its band whatever the model's offset. The model's box
still gives the columns, and the pen ink inside the band gives the final box.

Anything that doesn't look like a clean grid returns None, and the model's box stays.
"""

import itertools

import cv2
import numpy as np

from kassenfest.schemas.common import PixelBox

STRIPS = (0.25, 0.5, 0.75)
"""Where across a row box to look for ruling lines; narrow strips tolerate a tilted photo."""
STRIP_PX = 40
REGULAR = (0.75, 1.3)
"""Gaps between day rows stay within this share of the typical row height."""
MAX_SHIFT_ROWS = 3
"""The model may be this many rows off; more, and the grid reading is the suspect."""


def _dark(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(int)
    return ((np.median(gray) - gray) > 50).astype(np.uint8) * 255


def ruling_lines(rgb: np.ndarray, x_centre: float, y0: int, y1: int) -> list[float]:
    """y of each horizontal line crossing narrow vertical strips around `x_centre`."""
    found: list[float] = []
    width = rgb.shape[1]
    x0, x1 = int(max(0, x_centre - STRIP_PX / 2)), int(min(width, x_centre + STRIP_PX / 2))
    strip = _dark(rgb[y0:y1, x0:x1])
    if strip.size == 0:
        return []
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(8, (x1 - x0) * 2 // 3), 1))
    profile = (cv2.morphologyEx(strip, cv2.MORPH_OPEN, kernel) > 0).mean(axis=1)
    run: list[int] = []
    for y in [*np.flatnonzero(profile > 0.5).tolist(), -9]:  # sentinel closes the last run
        if run and y != run[-1] + 1:
            found.append(y0 + sum(run) / len(run))
            run = []
        if y >= 0:
            run.append(y)
    return found


def day_bands(lines: list[float], n_days: int) -> list[tuple[float, float]] | None:
    """(top, bottom) per day: the last n_days bands of the longest regularly spaced run."""
    if len(lines) < n_days + 1:
        return None
    gaps = np.diff(lines)
    pitch = float(np.median(gaps))
    ok = (gaps >= REGULAR[0] * pitch) & (gaps <= REGULAR[1] * pitch)
    best: tuple[int, int] = (0, 0)  # [start, end) over gaps
    start = None
    for i, good in enumerate([*ok.tolist(), False]):
        if good and start is None:
            start = i
        elif not good and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    if best[1] - best[0] < n_days:
        return None
    run = lines[best[0] : best[1] + 1]
    rows = run[-(n_days + 1) :]
    return list(itertools.pairwise(rows))


def _ink_box(rgb: np.ndarray, box: PixelBox) -> PixelBox | None:
    """Tight box around pen ink (or any non-line dark mark) inside `box`."""
    x0, y0, x1, y1 = (round(v) for v in box)
    crop = rgb[y0 + 2 : y1 - 1, x0:x1]  # stay off the band's own ruling lines
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    pen = (hsv[..., 0] >= 95) & (hsv[..., 0] <= 160) & (hsv[..., 1] > 70) & (hsv[..., 2] < 220)
    dark = _dark(crop)
    h, w = dark.shape
    for kernel in ((max(w // 3, 1), 1), (1, max(h * 2 // 3, 1))):  # ruling and cell borders
        dark &= ~cv2.morphologyEx(
            dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, kernel)
        )
    ys, xs = np.nonzero(pen | (dark > 0))
    if len(xs) < 12:
        return None
    pad = 2
    return (
        float(x0 + xs.min() - pad),
        float(y0 + 2 + ys.min() - pad),
        float(x0 + xs.max() + pad),
        float(y0 + 2 + ys.max() + pad),
    )


def snap_rows(
    rgb: np.ndarray, rows: dict[str, tuple[int, PixelBox]], n_days: int
) -> dict[str, PixelBox]:
    """Row path → box on the grid, for rows given as path → (day of month, model box).

    Empty when the grid can't be read or disagrees with the model by more than
    MAX_SHIFT_ROWS: the model's boxes then stay as they are.
    """
    if not rows:
        return {}
    model = list(rows.values())
    pitch = 1.2 * float(np.median([b[3] - b[1] for _, b in model]))
    first, last = min(d for d, _ in model), max(d for d, _ in model)
    margin = MAX_SHIFT_ROWS + 4  # header rows and slack
    y0 = int(max(0, min(b[1] for _, b in model) - (first - 1 + margin) * pitch))
    y1 = int(min(rgb.shape[0], max(b[3] for _, b in model) + (n_days - last + margin) * pitch))
    left, right = min(b[0] for _, b in model), max(b[2] for _, b in model)
    strips = []  # (x, bands): each strip on its own, so a tilted page still lines up
    for f in STRIPS:
        x = left + f * (right - left)
        if (bands := day_bands(ruling_lines(rgb, x, y0, y1), n_days)) is not None:
            strips.append((x, bands))
    if not strips:
        return {}

    def bands_at(box: PixelBox) -> list[tuple[float, float]]:
        centre = (box[0] + box[2]) / 2
        return min(strips, key=lambda s: abs(s[0] - centre))[1]

    shifts = []
    for day, b in model:
        centres = [(top + bottom) / 2 for top, bottom in bands_at(b)]
        nearest = int(np.argmin([abs((b[1] + b[3]) / 2 - c) for c in centres]))
        shifts.append(nearest - (day - 1))
    if abs(float(np.median(shifts))) > MAX_SHIFT_ROWS:
        return {}
    out = {}
    for path, (day, b) in rows.items():
        if not 1 <= day <= n_days:
            continue
        top, bottom = bands_at(b)[day - 1]
        band = (b[0], top, b[2], bottom)
        out[path] = _ink_box(rgb, band) or band
    return out
