"""Uploaded file -> upright page images the Model API accepts (ING-02).

HEIC is not accepted by the API, PDFs are rendered at the synth resolution, EXIF
rotation from phones is applied, and very large photos are scaled down: beyond
~2200 px the model gains nothing and pays in tokens and latency.
"""

import io

import pypdfium2 as pdfium
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from kassenfest.vision.image import PageImage

register_heif_opener()

MAX_SIDE = 2200
PDF_DPI = 150


_EXIF_ORIENTATION = 0x0112


def _fit(img: Image.Image) -> PageImage:
    img = ImageOps.exif_transpose(img).convert("RGB")
    scale = MAX_SIDE / max(img.size)
    if scale < 1:
        size = (round(img.width * scale), round(img.height * scale))
        img = img.resize(size, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return PageImage.from_bytes(buf.getvalue())


def to_pages(data: bytes, filename: str = "") -> list[PageImage]:
    if data[:5] == b"%PDF-" or filename.lower().endswith(".pdf"):
        pdf = pdfium.PdfDocument(data)
        try:
            return [_fit(pdf[i].render(scale=PDF_DPI / 72).to_pil()) for i in range(len(pdf))]
        finally:
            pdf.close()
    with Image.open(io.BytesIO(data)) as img:
        unchanged = (
            img.format in ("JPEG", "PNG", "WEBP")
            and max(img.size) <= MAX_SIDE
            and img.getexif().get(_EXIF_ORIENTATION, 1) == 1
        )
        if unchanged:  # keep the original bytes: no re-encoding loss, stable cache keys
            return [PageImage.from_bytes(data)]
        return [_fit(img)]
