"""How well the evidence boxes the viewer draws match the ground truth: `kassenfest eval-boxes`.

Two measures, because fields and visit-log rows fail differently:
- fields: IoU of the served box with the truth's ink box, next to the model's own box.
- rows: does the served row box contain the entry's own ink (time and Handzeichen)?
  IoU misleads here: a box over the right cells scores low against tight ink boxes,
  while a box one row off can still overlap.
"""

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine

from kassenfest.pipeline.month import field_boxes, load_docs
from kassenfest.schemas.common import PixelBox
from kassenfest.schemas.extraction import VisitLogSGBV
from kassenfest.schemas.ground_truth import GroundTruth
from kassenfest.vision.geometry import iou


@dataclass
class BoxScores:
    model: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    served: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    rows: dict[str, list[bool]] = field(default_factory=lambda: defaultdict(list))
    """variant → per field IoU (model's box, served box) / per row: on the right entry."""


ENTRY_KEY = ("date", "position_no", "start_time")
INK_CELLS = ("start_time", "staff_initials")


def _contains(box: PixelBox, inner: tuple[float, ...]) -> bool:
    x, y = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def score(engine: Engine, truth_dir: Path) -> BoxScores:
    scores = BoxScores()
    for doc in load_docs(engine):
        truth_file = truth_dir / f"{Path(doc.document.filename).stem}.json"
        if doc.extraction is None or not truth_file.exists():
            continue
        gt = GroundTruth.model_validate_json(truth_file.read_text())
        model = field_boxes(doc.extraction, doc.pages)
        for path, f in gt.fields.items():
            if f.box and f.status == "present" and "[" not in path and path in model:
                scores.model[gt.variant].append(iou(f.box, model[path][1]))
                scores.served[gt.variant].append(iou(f.box, doc.boxes[path][1]))
        if isinstance(doc.extraction, VisitLogSGBV):
            ink: dict[tuple, list] = {}
            for i in range(gt.fields["entries[#]"].value):
                cell = {n: gt.fields.get(f"entries[{i}].{n}") for n in ENTRY_KEY + INK_CELLS}
                key = tuple(cell[n].value if cell[n] else None for n in ENTRY_KEY)
                ink[key] = [cell[n].box for n in INK_CELLS if cell[n] and cell[n].box]
            for i, e in enumerate(doc.extraction.entries):
                boxes = ink.get((e.date, e.position_no, e.start_time))
                if boxes and (path := f"entries[{i}]") in doc.boxes:
                    served = doc.boxes[path][1]
                    scores.rows[gt.variant].append(all(_contains(served, b) for b in boxes))
    return scores


def report(scores: BoxScores) -> str:
    def line(values: list[float]) -> str:
        share = sum(v >= 0.3 for v in values) / len(values)
        return f"median IoU {statistics.median(values):.2f}, {share:.0%} >= 0.3"

    variants = sorted(scores.served)
    out = ["fields: model's box -> served box"]
    for name in [*variants, "all"]:
        keys = variants if name == "all" else [name]
        model = [x for k in keys for x in scores.model[k]]
        served = [x for k in keys for x in scores.served[k]]
        out.append(f"  {name:9} n={len(served):4}  {line(model)}  ->  {line(served)}")
    out.append("visit-log rows on the right entry")
    for name in [*sorted(scores.rows), "all"]:
        hits = [
            x for k in (sorted(scores.rows) if name == "all" else [name]) for x in scores.rows[k]
        ]
        if hits:
            out.append(f"  {name:9} {sum(hits)}/{len(hits)} = {sum(hits) / len(hits):.0%}")
    return "\n".join(out)
