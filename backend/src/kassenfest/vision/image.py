import base64
import hashlib
import io
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from PIL import Image

# MIME types the Meta Model API accepts inline; anything else is re-encoded as PNG.
_API_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}


@dataclass(frozen=True)
class PageImage:
    """One page as the models see it: encoded bytes plus pixel size."""

    data: bytes
    mime: str
    width: int
    height: int

    @classmethod
    def from_bytes(cls, data: bytes) -> "PageImage":
        with Image.open(io.BytesIO(data)) as img:
            mime = _API_MIME.get(img.format or "")
            if mime is None:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                data, mime = buf.getvalue(), "image/png"
            return cls(data=data, mime=mime, width=img.width, height=img.height)

    @classmethod
    def from_path(cls, path: str | Path) -> "PageImage":
        return cls.from_bytes(Path(path).read_bytes())

    @classmethod
    def from_pil(cls, img: Image.Image, fmt: str = "PNG") -> "PageImage":
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return cls.from_bytes(buf.getvalue())

    @cached_property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def data_url(self) -> str:
        return f"data:{self.mime};base64,{base64.b64encode(self.data).decode('ascii')}"
