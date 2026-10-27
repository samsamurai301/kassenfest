"""Ground truth -> the extraction a perfect reader would return.

`perfect_extraction(gt)` fills the document's extraction schema from its ground truth
(confidence 1, no boxes). Flattening it gives back exactly the ground-truth keys, which
is what the tests check; the pipeline can feed it to its CaseFile builder to separate
reading errors from building errors.
"""

import types
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

from kassenfest.schemas.common import Extracted, Mark, Strict
from kassenfest.schemas.extraction import EXTRACTION_SCHEMAS
from kassenfest.schemas.ground_truth import GroundTruth

_ROW_META = {"confidence": 1.0, "page": 0, "box": None}


def perfect_extraction(gt: GroundTruth) -> Strict:
    model = EXTRACTION_SCHEMAS[gt.doc_type]
    return model.model_validate(_fill(model, "", gt))


def _fill(model: type[BaseModel], prefix: str, gt: GroundTruth) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        if prefix and name in _ROW_META:  # per-row bookkeeping of list items
            out[name] = _ROW_META[name]
            continue
        out[name] = _value(info.annotation, f"{prefix}.{name}" if prefix else name, gt)
    return out


def _value(annotation: Any, path: str, gt: GroundTruth) -> Any:
    field = gt.fields.get(path)
    if isinstance(annotation, type) and issubclass(annotation, Extracted):
        status = field.status if field else "empty"
        value = field.value if field and status == "present" else None
        return {"value": value, "status": status, **_ROW_META}
    if isinstance(annotation, type) and issubclass(annotation, Mark):
        return {"state": field.value if field else "absent", **_ROW_META}
    if get_origin(annotation) is list:
        (item,) = get_args(annotation)
        count = gt.fields[f"{path}[#]"].value
        return [_fill(item, f"{path}[{i}]", gt) for i in range(count)]
    if get_origin(annotation) in (Union, types.UnionType):
        inner = [a for a in get_args(annotation) if a is not type(None)]
        if field is not None and field.value is None:
            return None
        if len(inner) == 1 and isinstance(inner[0], type) and issubclass(inner[0], BaseModel):
            return _fill(inner[0], path, gt)
        return field.value if field else None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _fill(annotation, path, gt)
    if field is None:
        raise KeyError(f"{gt.doc_id}: no ground truth for required field {path!r}")
    return field.value
