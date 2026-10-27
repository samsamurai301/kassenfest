"""Flatten an extraction into dotted paths, the shared key space of extraction and truth."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from kassenfest.schemas.common import Extracted, FieldStatus, Mark

# Per-row bookkeeping, not facts about the document.
_META_FIELDS = {"confidence", "page", "box"}


@dataclass(frozen=True)
class FlatField:
    value: Any
    status: FieldStatus


def flatten(doc: BaseModel) -> dict[str, FlatField]:
    """Paths look like 'kvnr', 'measures[0].frequency.count', 'entries[#]' (list length)."""
    out: dict[str, FlatField] = {}
    _walk(doc, "", out)
    return out


def _walk(obj: Any, path: str, out: dict[str, FlatField]) -> None:
    if isinstance(obj, Extracted):
        out[path] = FlatField(obj.value, obj.status)
    elif isinstance(obj, Mark):
        out[path] = FlatField(obj.state, "present")
    elif isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            if name not in _META_FIELDS:
                _walk(getattr(obj, name), f"{path}.{name}" if path else name, out)
    elif isinstance(obj, list):
        out[f"{path}[#]"] = FlatField(len(obj), "present")
        for i, item in enumerate(obj):
            _walk(item, f"{path}[{i}]", out)
    else:
        out[path] = FlatField(obj, "empty" if obj is None else "present")
