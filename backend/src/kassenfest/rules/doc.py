"""Document-quality rules (docs/02 §6).

DOC-READABLE needs per-field status and confidence, which only the extraction
output has (CaseFile holds clean facts), so it runs per extracted document via
`engine.evaluate_document`, not over the CaseFile.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from kassenfest.rules.engine import DocCtx, Hit, document_rule
from kassenfest.schemas.common import Extracted, Mark
from kassenfest.schemas.extraction import Located
from kassenfest.schemas.findings import Evidence

_META = {"confidence", "page", "box"}


@dataclass(frozen=True)
class Reading:
    path: str
    state: str
    confidence: float
    page: int


def readings(obj: Any, path: str = "") -> Iterator[Reading]:
    """Every value the model read, with its status: fields, marks, list rows, Handzeichen."""
    if isinstance(obj, Extracted):
        yield Reading(path, obj.status, obj.confidence, obj.page)
    elif isinstance(obj, Mark):
        yield Reading(
            path, "unreadable" if obj.state == "unclear" else "present", obj.confidence, obj.page
        )
    elif isinstance(obj, BaseModel):
        if isinstance(obj, Located):
            yield Reading(path, "present", obj.confidence, obj.page)
            if getattr(obj, "initials_state", None) == "unclear":
                yield Reading(f"{path}.staff_initials", "unreadable", obj.confidence, obj.page)
        for name in type(obj).model_fields:
            if name not in _META:
                yield from readings(getattr(obj, name), f"{path}.{name}" if path else name)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from readings(item, f"{path}[{i}]")


def matches(path: str, patterns: list[str]) -> bool:
    """'entries[*]' matches 'entries[3]' and 'entries[3].date'."""
    generic = re.sub(r"\[\d+\]", "[*]", path)
    return any(generic == p or generic.startswith((f"{p}.", f"{p}[")) for p in patterns)


@document_rule("DOC-READABLE")
def readable(doc: DocCtx, params: dict[str, Any]) -> Iterator[Hit]:
    patterns = params["billing_fields"].get(doc.doc_type, [])
    low = params["min_confidence"]
    bad = [
        r
        for r in readings(doc.extraction)
        if matches(r.path, patterns)
        and (r.state == "unreadable" or (r.state == "present" and r.confidence < low))
    ]
    if not bad:
        return
    yield Hit(
        key=doc.document_id,
        vars={"fields": [r.path for r in bad], "n_fields": len(bad), "min_confidence": low},
        evidence=[
            Evidence(
                document_id=doc.document_id,
                page=r.page,
                field_path=r.path,
                note=f"{r.state}, confidence {r.confidence:.2f}",
            )
            for r in bad
        ],
    )
