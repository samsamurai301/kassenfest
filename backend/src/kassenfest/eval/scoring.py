"""Score an extraction against ground truth, field by field.

Values are normalized before comparing (case, spacing, date and time formats), so
a field is wrong only when the meaning is wrong. List items are matched by content
(measures by category, visit entries by date + service + time), not by index.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from kassenfest.schemas.common import Box1000, Extracted, Mark, PixelBox
from kassenfest.schemas.ground_truth import GroundTruth
from kassenfest.schemas.paths import flatten
from kassenfest.vision.geometry import from_norm1000

_LIST_ITEM = re.compile(r"^(\w+)\[(\d+)\]\.(.+)$")
_SKIP = ("[#]", "doc_type", "corrections_present", "corrections_initialled")


def norm(value: Any) -> Any:
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, list):
        return sorted(str(norm(v)) for v in value)
    text = re.sub(r"\s+", " ", str(value)).strip().casefold()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", text):  # billing month as printed: 10/2026
        return f"{m[2]}-{int(m[1]):02d}"
    if m := re.fullmatch(r"(\d{1,2})[:.](\d{2})", text):
        return f"{int(m[1]):02d}:{m[2]}"
    if re.fullmatch(r"[a-z]?[\d ]{6,}", text):  # identifiers: drop spaces
        return text.replace(" ", "")
    return text


def same(a: Any, b: Any) -> bool:
    na, nb = norm(a), norm(b)
    # An unticked box and a blank field mean the same thing.
    if (na is None or na is False) and (nb is None or nb is False):
        return True
    return na == nb


@dataclass
class FieldScore:
    path: str
    handwritten: bool
    truth: Any
    predicted: Any
    truth_status: str
    predicted_status: str | None
    correct: bool


def score_fields(pred: BaseModel, gt: GroundTruth) -> list[FieldScore]:
    """Scalar fields and marks; list items are scored by score_measures / score_entries."""
    flat = flatten(pred)
    out = []
    for path, truth in gt.fields.items():
        if path.endswith(_SKIP) or _LIST_ITEM.match(path):
            continue
        got = flat.get(path)
        out.append(
            FieldScore(
                path=path,
                handwritten=truth.handwritten,
                truth=truth.value,
                predicted=got.value if got else None,
                truth_status=truth.status,
                predicted_status=got.status if got else None,
                correct=same(truth.value, got.value if got else None),
            )
        )
    return out


def _gt_items(gt: GroundTruth, name: str) -> list[dict[str, Any]]:
    items: dict[int, dict[str, Any]] = {}
    for path, f in gt.fields.items():
        if (m := _LIST_ITEM.match(path)) and m[1] == name:
            items.setdefault(int(m[2]), {})[m[3]] = f.value
    return [items[i] for i in sorted(items)]


def score_measures(pred: BaseModel, gt: GroundTruth) -> list[FieldScore]:
    truth = {m["category"]: m for m in _gt_items(gt, "measures")}
    got = {m.category: m for m in getattr(pred, "measures", [])}
    out = []
    for category in truth.keys() | got.keys():
        t, p = truth.get(category, {}), got.get(category)
        flat_p = {k: v.value for k, v in flatten(p).items()} if p else {}
        for key in (
            "category",
            "details",
            "frequency.count",
            "frequency.per",
            "duration_from",
            "duration_to",
        ):
            out.append(
                FieldScore(
                    path=f"measures[{category}].{key}",
                    handwritten=False,
                    truth=t.get(key),
                    predicted=flat_p.get(key),
                    truth_status="present" if t else "absent",
                    predicted_status="present" if p else None,
                    correct=bool(t) and bool(p) and same(t.get(key), flat_p.get(key)),
                )
            )
    return out


@dataclass
class EntryScore:
    truth_entries: int
    predicted_entries: int
    matched: int
    time_correct: int
    initials_state_correct: int
    initials_correct: int

    @property
    def recall(self) -> float:
        return self.matched / self.truth_entries if self.truth_entries else 1.0

    @property
    def precision(self) -> float:
        return self.matched / self.predicted_entries if self.predicted_entries else 1.0


def _service_key(position_no: Any, service: Any) -> str:
    pos = norm(position_no)
    return str(pos) if pos else str(norm(service))[:6]


def score_entries(pred_entries: Iterable[BaseModel], gt: GroundTruth) -> EntryScore:
    """Greedy match on (date, service column), then the closest time."""
    truth = _gt_items(gt, "entries")
    pool: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in truth:
        pool.setdefault((e["date"], _service_key(e["position_no"], e["service"])), []).append(e)
    preds = list(pred_entries)
    matched = time_ok = state_ok = initials_ok = 0
    for p in preds:
        key = (norm(p.date), _service_key(p.position_no, p.service))  # type: ignore[attr-defined]
        candidates = pool.get(key) or []
        if not candidates:
            continue
        p_time = norm(p.start_time)  # type: ignore[attr-defined]
        best = min(candidates, key=lambda e: 0 if norm(e["start_time"]) == p_time else 1)
        candidates.remove(best)
        matched += 1
        time_ok += norm(best["start_time"]) == p_time
        state_ok += best["initials_state"] == p.initials_state  # type: ignore[attr-defined]
        initials_ok += same(best["staff_initials"], p.staff_initials)  # type: ignore[attr-defined]
    return EntryScore(len(truth), len(preds), matched, time_ok, state_ok, initials_ok)


def predicted_boxes(pred: BaseModel, width: int, height: int) -> dict[str, PixelBox]:
    """Pixel boxes for every Extracted / Mark field, keyed like flatten()."""
    out: dict[str, PixelBox] = {}

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, Extracted | Mark):
            if isinstance(obj.box, Box1000):
                b = obj.box
                out[path] = from_norm1000((b.x_min, b.y_min, b.x_max, b.y_max), width, height)
        elif isinstance(obj, BaseModel):
            for name in type(obj).model_fields:
                walk(getattr(obj, name), f"{path}.{name}" if path else name)

    walk(pred, "")
    return out


def box_hit(pred: PixelBox, truth: PixelBox) -> bool:
    """DocILE-style hit: the predicted box contains the truth box's centre."""
    cx, cy = (truth[0] + truth[2]) / 2, (truth[1] + truth[3]) / 2
    return pred[0] <= cx <= pred[2] and pred[1] <= cy <= pred[3]
