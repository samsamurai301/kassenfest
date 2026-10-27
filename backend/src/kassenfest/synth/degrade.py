"""Scan, fax and phone-photo looks (docs/03 §4.3).

Geometry is a single 3x3 matrix per output, so ground-truth boxes move exactly
with the page; everything else (noise, blur, lighting, JPEG) is pixel-only.
"""

import io
import random
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from kassenfest.schemas.common import PixelBox
from kassenfest.schemas.ground_truth import Variant


@dataclass
class Degraded:
    image: Image.Image
    matrix: np.ndarray  # source page pixels -> output pixels
    jpeg_quality: int | None

    def box(self, b: PixelBox) -> PixelBox:
        corners = np.array(
            [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]], dtype=np.float64
        )
        pts = cv2.perspectiveTransform(corners[None], self.matrix)[0]
        w, h = self.image.size
        return (
            float(np.clip(pts[:, 0].min(), 0, w)),
            float(np.clip(pts[:, 1].min(), 0, h)),
            float(np.clip(pts[:, 0].max(), 0, w)),
            float(np.clip(pts[:, 1].max(), 0, h)),
        )


def _jpeg(arr: np.ndarray, quality: int) -> np.ndarray:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=quality)
    return np.array(Image.open(buf).convert("RGB"))


def _noise(arr: np.ndarray, sigma: float, rng: np.random.Generator) -> np.ndarray:
    return np.clip(arr.astype(np.float32) + rng.normal(0, sigma, arr.shape), 0, 255).astype(
        np.uint8
    )


def clean(img: Image.Image, rnd: random.Random) -> Degraded:
    return Degraded(img, np.eye(3), None)


def scan(img: Image.Image, rnd: random.Random) -> Degraded:
    rng = np.random.default_rng(rnd.getrandbits(32))
    arr = np.array(img)
    h, w = arr.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), rnd.uniform(-1.5, 1.5), 1.0)
    m[:, 2] += (rnd.uniform(-12, 12), rnd.uniform(-12, 12))
    arr = cv2.warpAffine(arr, m, (w, h), borderValue=(250, 250, 248))
    arr = (arr.astype(np.float32) * rnd.uniform(0.93, 0.99)).astype(np.uint8)  # paper is not white
    if rnd.random() < 0.5:
        arr = cv2.GaussianBlur(arr, (3, 3), 0.6)
    arr = _noise(arr, rnd.uniform(2.5, 6), rng)
    quality = rnd.randint(70, 88)
    return Degraded(Image.fromarray(_jpeg(arr, quality)), np.vstack([m, [0, 0, 1]]), quality)


def fax(img: Image.Image, rnd: random.Random) -> Degraded:
    rng = np.random.default_rng(rnd.getrandbits(32))
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), rnd.uniform(-0.8, 0.8), 1.0)
    gray = cv2.warpAffine(gray, m, (w, h), borderValue=255)
    # Fine-mode fax: half the vertical resolution, then stretched back.
    gray = cv2.resize(
        cv2.resize(gray, (w, h // 2), interpolation=cv2.INTER_AREA),
        (w, h),
        interpolation=cv2.INTER_NEAREST,
    )
    binary = np.where(gray < rnd.randint(150, 185), 0, 255).astype(np.uint8)
    speckle = rng.random(binary.shape) < 0.0015
    binary[speckle] = 0
    for _ in range(rnd.randint(0, 3)):
        y = rnd.randint(0, h - 2)
        binary[y : y + 1, :] = np.minimum(
            binary[y : y + 1, :], np.where(rng.random(w) < 0.5, 0, 255)
        )
    header = f"FAX  27.10.2026 08:{rnd.randint(10, 59)}  +49 991 {rnd.randint(1000, 9999)}  S. 01"
    cv2.putText(binary, header, (20, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, 0, 1, cv2.LINE_AA)
    rgb = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)
    return Degraded(Image.fromarray(rgb), np.vstack([m, [0, 0, 1]]), None)


def _table(h: int, w: int, rnd: random.Random, rng: np.random.Generator) -> np.ndarray:
    """Desk surface: a base colour with low-frequency blotches and fine grain."""
    base = np.array(
        rnd.choice([(150, 112, 78), (182, 160, 130), (95, 92, 88), (205, 200, 190), (120, 84, 60)]),
        np.float32,
    )
    low = cv2.resize(
        rng.normal(0, 1, (8, 8)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC
    )
    grain = cv2.GaussianBlur(
        rng.normal(0, 1, (h, w)).astype(np.float32), (0, 0), sigmaX=6, sigmaY=0.8
    )
    shade = 1 + 0.08 * low[..., None] + 0.05 * grain[..., None]
    return np.clip(base * shade, 0, 255).astype(np.uint8)


def photo(img: Image.Image, rnd: random.Random, *, severity: float = 1.0) -> Degraded:
    rng = np.random.default_rng(rnd.getrandbits(32))
    page = np.array(img)
    h, w = page.shape[:2]
    pad_x, pad_y = int(w * 0.09), int(h * 0.09)
    cw, ch = w + 2 * pad_x, h + 2 * pad_y
    jitter = 0.045 * severity
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32(
        [
            [pad_x + rnd.uniform(-1, 1) * jitter * w, pad_y + rnd.uniform(-1, 1) * jitter * h],
            [pad_x + w + rnd.uniform(-1, 1) * jitter * w, pad_y + rnd.uniform(-1, 1) * jitter * h],
            [
                pad_x + w + rnd.uniform(-1, 1) * jitter * w,
                pad_y + h + rnd.uniform(-1, 1) * jitter * h,
            ],
            [pad_x + rnd.uniform(-1, 1) * jitter * w, pad_y + h + rnd.uniform(-1, 1) * jitter * h],
        ]
    )
    homography = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(page, homography, (cw, ch))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), homography, (cw, ch))
    out = np.where(mask[..., None] > 0, warped, _table(ch, cw, rnd, rng)).astype(np.float32)

    # Lighting: a directional gradient plus a soft shadow (hand or phone).
    yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float32)
    angle = rnd.uniform(0, 2 * np.pi)
    ramp = (np.cos(angle) * xx / cw + np.sin(angle) * yy / ch + 1) / 2
    light = rnd.uniform(0.72, 0.9) + rnd.uniform(0.12, 0.25) * ramp
    if rnd.random() < 0.6:
        cx, cy = rnd.uniform(0, cw), rnd.uniform(0, ch)
        r = rnd.uniform(0.25, 0.5) * max(cw, ch)
        light *= 1 - rnd.uniform(0.12, 0.3) * severity * np.exp(
            -(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r**2))
        )
    tint = np.array([rnd.uniform(0.97, 1.03), 1.0, rnd.uniform(0.92, 1.0)], np.float32)
    out = np.clip(out * light[..., None] * tint, 0, 255).astype(np.uint8)
    out = cv2.GaussianBlur(out, (0, 0), rnd.uniform(0.5, 1.2) * severity)
    out = _noise(out, rnd.uniform(2, 5) * severity, rng)

    scale = min(1.0, 2000 / max(cw, ch))
    if scale < 1:
        out = cv2.resize(out, (round(cw * scale), round(ch * scale)), interpolation=cv2.INTER_AREA)
    matrix = np.diag([scale, scale, 1.0]) @ homography
    quality = rnd.randint(72, 90)
    return Degraded(Image.fromarray(_jpeg(out, quality)), matrix, quality)


def bad_photo(img: Image.Image, rnd: random.Random) -> Degraded:
    return photo(img, rnd, severity=2.6)


VARIANTS: dict[Variant, Callable[[Image.Image, random.Random], Degraded]] = {
    "clean": clean,
    "scan": scan,
    "fax": fax,
    "photo": photo,
    "bad_photo": bad_photo,
}
