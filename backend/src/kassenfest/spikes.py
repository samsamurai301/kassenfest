"""Spikes S1-S4 (docs/05 §5, Wednesday): the numbers behind docs/SPIKES.md.

S1  Muster 12 extraction by variant and reasoning effort
S2  Leistungsnachweis grid: full page vs. row bands
S3  SAM 3.1: concept prompts vs. Muse Spark box -> SAM refine, for signatures and stamps
S4  Muse Spark box accuracy: printed vs. handwritten fields vs. marks
"""

import asyncio
import io
import json
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from PIL import Image
from pydantic import Field

from kassenfest.config import REPO_ROOT, Settings
from kassenfest.eval.scoring import (
    box_hit,
    predicted_boxes,
    score_entries,
    score_fields,
    score_measures,
)
from kassenfest.llm.client import ChatResult, MetaModelClient, ReasoningEffort
from kassenfest.llm.prompts import EXTRACT_SYSTEM, EXTRACT_VERSION, extract_user
from kassenfest.schemas.common import Strict
from kassenfest.schemas.extraction import Muster12, VisitEntry, VisitLogSGBV
from kassenfest.schemas.ground_truth import GroundTruth, GTPage, Variant
from kassenfest.synth import samples
from kassenfest.synth.degrade import VARIANTS, Degraded
from kassenfest.synth.documents import ground_truth, render_document
from kassenfest.synth.render import Renderer
from kassenfest.vision.geometry import iou
from kassenfest.vision.image import PageImage

OUT = REPO_ROOT / "var" / "spikes"


@dataclass
class Sample:
    doc_id: str
    doc_type: str
    variant: Variant
    image: PageImage
    gt: GroundTruth


def _move_truth(gt: GroundTruth, d: Degraded, variant: Variant, image_name: str) -> GroundTruth:
    moved = gt.model_copy(deep=True)
    moved.variant = variant
    moved.pages = [GTPage(index=0, image=image_name, width=d.image.width, height=d.image.height)]
    for f in moved.fields.values():
        if f.box:
            f.box = d.box(f.box)
    for r in moved.regions.values():
        r.box = d.box(r.box)
    return moved


def make_samples(doc_type: str, n: int, variants: list[Variant], seed0: int) -> list[Sample]:
    out_dir = OUT / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = []
    with Renderer() as renderer:
        for i in range(n):
            rnd = random.Random(seed0 + i)
            if doc_type == "muster12":
                content = samples.muster12(rnd, stamp_present=i % 4 != 1, doctor_signed=i % 4 != 2)
            else:
                content = samples.visit_log_sgbv(rnd, patient_signed=i % 2 == 0, missing_initials=3)
            doc_id = f"spike-{doc_type}-{i:02d}"
            page, truth, _ = render_document(
                renderer, doc_type, content, doc_id=doc_id, seed=seed0 + i
            )
            gt = ground_truth(
                page,
                truth,
                doc_id=doc_id,
                doc_type=doc_type,
                variant="clean",
                seed=seed0 + i,
                image_name="",
            )
            for variant in variants:
                d = VARIANTS[variant](page.image, random.Random(seed0 * 31 + i))
                name = f"{doc_id}-{variant}.{'png' if d.jpeg_quality is None else 'jpg'}"
                d.image.save(out_dir / name, quality=d.jpeg_quality or 95)
                moved = _move_truth(gt, d, variant, name)
                (out_dir / f"{doc_id}-{variant}.json").write_text(moved.model_dump_json(indent=1))
                result.append(
                    Sample(doc_id, doc_type, variant, PageImage.from_path(out_dir / name), moved)
                )
    return result


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:5.1f}%" if whole else "   n/a"


async def _extract(
    client: MetaModelClient, s: Sample, schema: Any, effort: ReasoningEffort
) -> ChatResult:
    return await client.chat_json(
        prompt_id=f"extract.{s.doc_type}.{EXTRACT_VERSION}",
        schema=schema,
        system=EXTRACT_SYSTEM,
        user_text=extract_user(s.doc_type),
        images=[s.image],
        reasoning_effort=effort,
    )


# --- S1 + S4 ----------------------------------------------------------------------


async def s1_s4(client: MetaModelClient, docs: list[Sample]) -> tuple[dict, dict[str, ChatResult]]:
    report: dict[str, Any] = {}
    medium: dict[str, ChatResult] = {}
    for effort in ("low", "medium"):
        results = await asyncio.gather(*(_extract(client, s, Muster12, effort) for s in docs))
        by: dict[str, list[bool]] = defaultdict(list)
        boxes: dict[str, list[tuple[float, bool]]] = defaultdict(list)
        latency, cost = [], 0.0
        for s, r in zip(docs, results, strict=True):
            if effort == "medium":
                medium[f"{s.doc_id}-{s.variant}"] = r
            latency.append(r.meta.latency_ms)
            cost += r.meta.cost_usd
            for f in score_fields(r.parsed, s.gt):
                kind = "mark" if f.path in s.gt.regions else ("hand" if f.handwritten else "print")
                by[f"{s.variant}/{kind}"].append(f.correct)
                by[f"all/{kind}"].append(f.correct)
                by[f"{s.variant}/all"].append(f.correct)
                if not f.correct:
                    by.setdefault(f"miss:{f.path}", []).append(False)
            for f in score_measures(r.parsed, s.gt):
                by[f"{s.variant}/measures"].append(f.correct)
            if effort == "medium":
                pred = predicted_boxes(r.parsed, s.image.width, s.image.height)
                for path, truth in s.gt.fields.items():
                    if truth.box and path in pred and truth.status == "present":
                        kind = (
                            "mark"
                            if path in s.gt.regions
                            else ("hand" if truth.handwritten else "print")
                        )
                        boxes[kind].append(
                            (iou(pred[path], truth.box), box_hit(pred[path], truth.box))
                        )
        report[effort] = {
            "accuracy": {
                k: round(sum(v) / len(v), 3)
                for k, v in sorted(by.items())
                if not k.startswith("miss:")
            },
            "n": {k: len(v) for k, v in sorted(by.items()) if not k.startswith("miss:")},
            "top_misses": sorted(
                ((k[5:], len(v)) for k, v in by.items() if k.startswith("miss:")),
                key=lambda x: -x[1],
            )[:10],
            "latency_ms_median": statistics.median(latency),
            "cost_usd": round(cost, 4),
        }
        if effort == "medium":
            report["s4_boxes"] = {
                k: {
                    "n": len(v),
                    "iou_median": round(statistics.median(x[0] for x in v), 2),
                    "iou_ge_0.5": round(sum(x[0] >= 0.5 for x in v) / len(v), 2),
                    "centre_hit": round(sum(x[1] for x in v) / len(v), 2),
                }
                for k, v in boxes.items()
            }
    return report, medium


# --- S2 ---------------------------------------------------------------------------


class EntriesBand(Strict):
    entries: list[VisitEntry] = Field(description="Only rows fully visible in the second image")


BANDS = [(0.10, 0.45), (0.40, 0.70), (0.65, 0.95)]
BAND_PROMPT = (
    "Image 1 is the whole Leistungsnachweis, for context (month, service column headers). "
    "Image 2 is a horizontal band cut from the same page. List the entries only for the "
    "rows fully visible in image 2. "
)


async def _bands(client: MetaModelClient, s: Sample) -> tuple[list[VisitEntry], float, int]:
    pil = Image.open(io.BytesIO(s.image.data)).convert("RGB")
    crops = [
        PageImage.from_pil(pil.crop((0, int(a * pil.height), pil.width, int(b * pil.height))))
        for a, b in BANDS
    ]
    results = await asyncio.gather(
        *(
            client.chat_json(
                prompt_id=f"extract.visit_log_band.{EXTRACT_VERSION}",
                schema=EntriesBand,
                system=EXTRACT_SYSTEM,
                user_text=BAND_PROMPT + extract_user("visit_log_sgbv"),
                images=[s.image, crop],
                reasoning_effort="medium",
            )
            for crop in crops
        )
    )
    seen, merged = set(), []
    for r in results:
        for e in r.parsed.entries:
            key = (e.date, e.position_no or e.service, e.start_time)
            if key not in seen:
                seen.add(key)
                merged.append(e)
    return merged, sum(r.meta.cost_usd for r in results), max(r.meta.latency_ms for r in results)


async def s2(client: MetaModelClient, docs: list[Sample]) -> dict:
    full = await asyncio.gather(*(_extract(client, s, VisitLogSGBV, "medium") for s in docs))
    banded = await asyncio.gather(*(_bands(client, s) for s in docs))
    rows = []
    for s, f, (entries, b_cost, b_latency) in zip(docs, full, banded, strict=True):
        sf, sb = score_entries(f.parsed.entries, s.gt), score_entries(entries, s.gt)
        header = score_fields(f.parsed, s.gt)
        rows.append(
            {
                "doc": f"{s.doc_id}-{s.variant}",
                "truth_entries": sf.truth_entries,
                "full": {
                    "recall": round(sf.recall, 3),
                    "precision": round(sf.precision, 3),
                    "time_ok": round(sf.time_correct / max(sf.matched, 1), 3),
                    "initials_state_ok": round(sf.initials_state_correct / max(sf.matched, 1), 3),
                    "latency_ms": f.meta.latency_ms,
                    "cost_usd": round(f.meta.cost_usd, 4),
                },
                "bands": {
                    "recall": round(sb.recall, 3),
                    "precision": round(sb.precision, 3),
                    "time_ok": round(sb.time_correct / max(sb.matched, 1), 3),
                    "initials_state_ok": round(sb.initials_state_correct / max(sb.matched, 1), 3),
                    "latency_ms": b_latency,
                    "cost_usd": round(b_cost, 4),
                },
                "header_fields_ok": round(sum(h.correct for h in header) / len(header), 3),
                "patient_signature": [h.correct for h in header if h.path == "patient_signature"],
            }
        )
    return {"docs": rows}


# --- S3 ---------------------------------------------------------------------------

CONCEPTS = {"signature": ["signature", "handwritten signature"], "stamp": ["stamp", "rubber stamp"]}


async def s3(client: MetaModelClient, docs: list[Sample], muse: dict[str, ChatResult]) -> dict:
    tally: dict[str, list[float]] = defaultdict(list)
    false_pos: dict[str, list[bool]] = defaultdict(list)

    async def concept_run(s: Sample, region: str, concept: str) -> None:
        truth = s.gt.regions[region]
        seg = await client.segment(s.image, concept=concept, prompt_id=f"spike.sam.{concept}")
        best = max((iou(x.box, truth.box) for x in seg.segments), default=0.0)
        if truth.state == "present":
            tally[f"concept:{concept}/{s.variant}"].append(best)
        else:
            false_pos[f"concept:{concept}"].append(best >= 0.3)

    async def refine_run(s: Sample, region: str) -> None:
        truth = s.gt.regions[region]
        r = muse.get(f"{s.doc_id}-{s.variant}")
        if r is None or truth.state != "present":
            return
        box = predicted_boxes(r.parsed, s.image.width, s.image.height).get(region)
        if box is None:
            tally[f"refine/{s.variant}"].append(0.0)
            return
        tally[f"muse_box/{s.variant}"].append(iou(box, truth.box))
        seg = await client.segment(s.image, boxes=[box], prompt_id="spike.sam.refine")
        tally[f"refine/{s.variant}"].append(
            max((iou(x.box, truth.box) for x in seg.segments), default=0.0)
        )

    jobs = []
    for s in docs:
        for region in s.gt.regions:
            kind = "stamp" if "stamp" in region else "signature"
            jobs += [concept_run(s, region, c) for c in CONCEPTS[kind]]
            if s.doc_type == "muster12":
                jobs.append(refine_run(s, region))
    await asyncio.gather(*jobs)
    return {
        "present_iou": {
            k: {
                "n": len(v),
                "median": round(statistics.median(v), 2),
                "hit_ge_0.5": round(sum(x >= 0.5 for x in v) / len(v), 2),
            }
            for k, v in sorted(tally.items())
        },
        "absent_false_positive": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(false_pos.items())},
    }


async def run(settings: Settings, which: str, n_m12: int, n_vl: int) -> int:
    client = MetaModelClient(settings)
    report: dict[str, Any] = {}
    # Playwright sync API must not run inside the event loop.
    m12 = await asyncio.to_thread(make_samples, "muster12", n_m12, ["clean", "scan", "photo"], 100)
    medium: dict[str, ChatResult] = {}
    if which in ("s1", "s3", "all"):
        report["s1"], medium = await s1_s4(client, m12)
    if which in ("s2", "all"):
        vl = await asyncio.to_thread(make_samples, "visit_log_sgbv", n_vl, ["clean", "photo"], 500)
        report["s2"] = await s2(client, vl)
    if which in ("s3", "all"):
        report["s3"] = await s3(client, m12, medium)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"results-{which}.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str))
    print(f"\nimages + truth: {OUT / 'docs'}  ·  results: {OUT / f'results-{which}.json'}")
    return 0
