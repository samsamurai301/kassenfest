"""HTML/CSS form templates -> page images, with pixel boxes for every tagged element.

Templates tag elements with `data-field` (extraction paths, space-separated if one
element carries several), `data-region` (where a mark belongs) and `data-ink` (the
mark itself). Field and region boxes are unions over the element and its descendants,
so per-glyph transforms on handwriting are included. Ink boxes are tight to the painted
pixels: the mark is rendered alone and measured, since an SVG frame or a script font's
line box is much larger than the ink (SAM is scored against these).
"""

import base64
import io
from dataclasses import dataclass, field
from types import TracebackType

import numpy as np
from jinja2 import Environment, PackageLoader, select_autoescape
from PIL import Image
from playwright.sync_api import Browser, Playwright, sync_playwright

from kassenfest.schemas.common import PixelBox
from kassenfest.synth.fonts import FontFace

DPI = 150
SCALE = DPI / 96  # CSS px are 1/96 inch
MM_TO_CSS = 96 / 25.4
A4_PORTRAIT = (210.0, 297.0)
A4_LANDSCAPE = (297.0, 210.0)

_BOXES_JS = """
() => {
  const union = (el) => {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of [el, ...el.querySelectorAll('*')]) {
      const r = n.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top);
      x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom);
    }
    return x0 === Infinity ? null : [x0, y0, x1, y1];
  };
  const collect = (attr) => {
    const out = {};
    for (const el of document.querySelectorAll(`[${attr}]`)) {
      const box = union(el);
      if (!box) continue;
      for (const name of el.getAttribute(attr).split(' ')) if (name) out[name] = box;
    }
    return out;
  };
  // The table cell or block each field sits in, to check nothing spills over.
  const cells = {};
  for (const el of document.querySelectorAll('[data-field]')) {
    const cell = el.parentElement.closest('td, th, .cell, li, p, div');
    if (!cell) continue;
    const r = cell.getBoundingClientRect();
    for (const name of el.getAttribute('data-field').split(' '))
      if (name) cells[name] = [r.left, r.top, r.right, r.bottom];
  }
  return {
    fields: collect('data-field'), regions: collect('data-region'), ink: collect('data-ink'), cells,
  };
}
"""

# Show only one mark: everything else invisible, the page background stays.
_ISOLATE_JS = """
async (name) => {
  const style = document.createElement('style');
  style.id = '__isolate';
  style.textContent = `body * { visibility: hidden !important; }
    [data-ink="${name}"], [data-ink="${name}"] * { visibility: visible !important; }`;
  document.head.appendChild(style);
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
}
"""
_RESTORE_JS = "() => document.getElementById('__isolate').remove()"
INK_THRESHOLD = 215  # a pixel is ink if any channel is darker than this on white paper

# Fonts loaded, then two frames, so the screenshot never catches a half-rastered page.
_SETTLE_JS = """
async () => {
  await document.fonts.ready;
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  return true;
}
"""

templates = Environment(
    loader=PackageLoader("kassenfest.synth", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass
class RenderedPage:
    image: Image.Image
    fields: dict[str, PixelBox]
    regions: dict[str, PixelBox]
    ink: dict[str, PixelBox]
    cells: dict[str, PixelBox] = field(default_factory=dict)  # field -> its cell or block


def font_face_css(faces: list[FontFace]) -> str:
    """Embed fonts as data URIs so rendering never depends on system fonts."""
    rules = []
    for face in faces:
        data = base64.b64encode(face.file.read_bytes()).decode("ascii")
        rules.append(
            f"@font-face {{ font-family: '{face.family}'; "
            f"src: url(data:font/ttf;base64,{data}) format('truetype'); }}"
        )
    return "\n".join(rules)


class Renderer:
    """One Chromium for many pages: `with Renderer() as r: r.render(html, A4_PORTRAIT)`."""

    _pw: Playwright
    _browser: Browser

    def __enter__(self) -> "Renderer":
        self._pw = sync_playwright().start()
        # One raster thread: threaded tiles make SVG filters (stamp ink) differ run to run.
        self._browser = self._pw.chromium.launch(args=["--num-raster-threads=1"])
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._browser.close()
        self._pw.stop()

    def render(self, html: str, size_mm: tuple[float, float]) -> RenderedPage:
        width, height = (round(v * MM_TO_CSS) for v in size_mm)
        page = self._browser.new_page(
            viewport={"width": width, "height": height}, device_scale_factor=SCALE
        )
        try:
            page.set_content(html, wait_until="load")
            page.evaluate(_SETTLE_JS)
            png = page.screenshot(full_page=False)
            boxes = page.evaluate(_BOXES_JS)
            ink = {
                name: _tight_ink(page, name, box, (width, height))
                for name, box in boxes["ink"].items()
            }
        finally:
            page.close()

        def scale(group: dict[str, list[float]]) -> dict[str, PixelBox]:
            return {
                k: (v[0] * SCALE, v[1] * SCALE, v[2] * SCALE, v[3] * SCALE)
                for k, v in group.items()
            }

        return RenderedPage(
            image=Image.open(io.BytesIO(png)).convert("RGB"),
            fields=scale(boxes["fields"]),
            regions=scale(boxes["regions"]),
            ink=ink,
            cells=scale(boxes["cells"]),
        )


def _tight_ink(page, name: str, css_box: list[float], viewport: tuple[int, int]) -> PixelBox:
    """Page-pixel box of the pixels the mark paints, from a screenshot of it alone."""
    # Clip origin on a multiple of 16 CSS px = 25 device px, so pixels map back exactly.
    pad = 4
    x0, y0 = (max(0.0, (v - pad) // 16 * 16) for v in css_box[:2])
    x1, y1 = min(viewport[0], css_box[2] + pad), min(viewport[1], css_box[3] + pad)
    loose = (css_box[0] * SCALE, css_box[1] * SCALE, css_box[2] * SCALE, css_box[3] * SCALE)
    page.evaluate(_ISOLATE_JS, name)
    try:
        png = page.screenshot(clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})
    finally:
        page.evaluate(_RESTORE_JS)
    dark = np.array(Image.open(io.BytesIO(png)).convert("RGB")).min(axis=2) < INK_THRESHOLD
    ys, xs = np.nonzero(dark)
    if not len(xs):
        return loose
    ox, oy = x0 * SCALE, y0 * SCALE
    return (ox + xs.min(), oy + ys.min(), ox + xs.max() + 1.0, oy + ys.max() + 1.0)
