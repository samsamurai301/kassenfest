"""Record/replay cache for model calls.

The key hashes the normalized request: inline images are replaced by the sha256
of their bytes, so the same prompt on the same page always hits the same entry,
and cache files stay small enough to commit for the demo set.
"""

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_DATA_URL_MARKER = ";base64,"


class CacheMiss(RuntimeError):
    """Raised in replay mode when a request has no recorded response."""


def normalize_request(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: normalize_request(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [normalize_request(v) for v in value]
    if isinstance(value, str) and value.startswith("data:") and _DATA_URL_MARKER in value:
        payload = value.split(_DATA_URL_MARKER, 1)[1]
        return "sha256:" + hashlib.sha256(base64.b64decode(payload)).hexdigest()
    return value


def cache_key(request: dict[str, Any]) -> str:
    canonical = json.dumps(
        normalize_request(request), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class CacheEntry:
    key: str
    model: str
    prompt_id: str
    request: dict[str, Any]
    response: dict[str, Any]
    cost_usd: float
    latency_ms: int
    created_at: str


class ResponseCache:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> CacheEntry | None:
        path = self._path(key)
        if not path.exists():
            return None
        return CacheEntry(**json.loads(path.read_text(encoding="utf-8")))

    def put(self, entry: CacheEntry) -> None:
        path = self._path(entry.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash mid-write never leaves a truncated entry.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(entry), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
