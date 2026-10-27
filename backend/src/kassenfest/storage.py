"""Content-addressed blob store on local disk (replaces MinIO for the hackathon, docs/05 §2)."""

import hashlib
import os
import tempfile
from pathlib import Path


class BlobStore:
    """Keys are `<sha256>.<ext>`; writing the same bytes twice is a no-op."""

    def __init__(self, root: Path):
        self.root = root

    def path(self, key: str) -> Path:
        return self.root / key[:2] / key

    def put(self, data: bytes, ext: str) -> str:
        key = f"{hashlib.sha256(data).hexdigest()}.{ext.lstrip('.').lower()}"
        path = self.path(key)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        return key

    def get(self, key: str) -> bytes:
        return self.path(key).read_bytes()
