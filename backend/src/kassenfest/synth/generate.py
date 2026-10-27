"""Write a synthetic set to data/synthetic/<set>/ (docs/05 §4.1): `kassenfest synth --set dev`.

    pages/<doc_id>.png|jpg        what you upload; nothing else in the set is for the pipeline
    truth/<doc_id>.json           GroundTruth per document (boxes in the degraded page's pixels)
    cases/<case_id>.json          CaseFile truth per patient-month (rules on truth vs. extraction)
    cases/<case_id>.manifest.json defect labels with documents and affected lines
    master_data.json              what the Pflegedienst knows: staff, patients, doctors, Kassen
    manifest.json                 documents, cases and defect coverage

Document ids are numbered in a seeded shuffle, so neither the id nor the page footer
gives away the patient or the document type.
"""

import datetime as dt
import hashlib
import random
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from kassenfest.config import REPO_ROOT
from kassenfest.schemas.common import DocType
from kassenfest.schemas.domain import Patient, Payer, Physician, Provider
from kassenfest.schemas.ground_truth import DefectId, Variant
from kassenfest.synth import catalog
from kassenfest.synth.degrade import VARIANTS, Degraded, fax
from kassenfest.synth.documents import ground_truth, render_document
from kassenfest.synth.paperwork import DocPlan, documents
from kassenfest.synth.render import RenderedPage, Renderer
from kassenfest.synth.scenarios import (
    RULES,
    TIER_A,
    assign_names,
    build_timeline,
    demo_specs,
    random_specs,
)
from kassenfest.synth.world import (
    MONTH_END,
    MONTH_STR,
    PatientSpec,
    Timeline,
    World,
    build_world,
    case_file,
    visit_order,
)

SetName = Literal["demo", "dev", "test"]
OUT_ROOT = REPO_ROOT / "data" / "synthetic"

# Variant mix per document type; overall close to docs/03 §4.3. bad_photo only for D19.
VARIANT_MIX: dict[str, dict[Variant, float]] = {
    "muster12": {"clean": 0.10, "scan": 0.30, "fax": 0.20, "photo": 0.40},
    "approval_letter": {"clean": 0.35, "scan": 0.25, "fax": 0.25, "photo": 0.15},
    "hospital_letter": {"clean": 0.15, "scan": 0.30, "fax": 0.25, "photo": 0.30},
    "visit_log_sgbv": {"clean": 0.05, "scan": 0.35, "photo": 0.60},
    "visit_log_sgbxi": {"clean": 0.05, "scan": 0.35, "photo": 0.60},
}


@dataclass(frozen=True)
class SetConfig:
    name: SetName
    seed: int
    split: Literal["dev", "test"]  # which handwriting fonts
    patients: int = 0  # 0 = curated demo cast
    quota: int = 0  # each Tier-A defect in at least this many patient-months
    clean: int = 0

    def cast(self) -> list[PatientSpec]:
        if self.name == "demo":
            specs = demo_specs()
        else:
            specs = random_specs(self.seed, self.patients, self.quota, self.clean)
        assign_names(specs, self.seed)
        return specs


SETS: dict[SetName, SetConfig] = {
    "demo": SetConfig("demo", seed=4211, split="dev"),
    "dev": SetConfig("dev", seed=1001, split="dev", patients=19, quota=4, clean=4),
    "test": SetConfig("test", seed=2002, split="test", patients=19, quota=3, clean=3),
}


# --- Manifests ---------------------------------------------------------------------------


class LabelLine(BaseModel):
    """One billed service a defect is about, pointing at its visit-log entry."""

    date: dt.date
    time: str
    code: str
    domain: str
    document_id: str | None
    entry_index: int | None


class DefectEntry(BaseModel):
    id: DefectId
    rules: list[str]
    documents: list[str]
    note: str
    lines: list[LabelLine] = []


class DocEntry(BaseModel):
    doc_id: str
    doc_type: DocType
    variant: Variant
    image: str
    truth: str
    case_id: str
    patient_id: str
    defects: list[DefectId]


class CaseManifest(BaseModel):
    case_id: str
    patient_id: str
    patient_name: str
    month: str
    kind: str
    hero: str | None
    events: list[str]
    defects: list[DefectEntry]
    documents: list[str]
    casefile: str


class SetManifest(BaseModel):
    set: SetName
    seed: int
    handwriting: str
    month: str
    synthetic: Literal[True] = True
    documents: list[DocEntry]
    cases: list[CaseManifest]
    coverage: dict[str, int]  # patient-months per defect
    coverage_docs: dict[str, int]  # documents per defect
    variants: dict[str, int]


class MasterData(BaseModel):
    """The Pflegedienst's own records (KVNRs as typed into its software)."""

    synthetic: Literal[True] = True
    month: str
    provider: Provider
    patients: list[Patient]
    physicians: list[Physician]
    payers: list[Payer]
    hospital: dict[str, str]


# --- Planning (no rendering) -----------------------------------------------------------------


@dataclass
class PlannedDoc:
    plan: DocPlan
    case_id: str
    patient_id: str
    variant: Variant
    seed: int
    defects: list[DefectId]
    doc_id: str = ""


@dataclass
class Case:
    case_id: str
    timeline: Timeline
    docs: list[PlannedDoc] = field(default_factory=list)


@dataclass
class SetPlan:
    config: SetConfig
    world: World
    cases: list[Case]

    @property
    def docs(self) -> list[PlannedDoc]:
        return sorted((d for c in self.cases for d in c.docs), key=lambda d: d.doc_id)


def _seed(*parts: object) -> int:
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def plan_set(name: SetName) -> SetPlan:
    """World, timelines with defects and the document pile, with ids and variants."""
    config = SETS[name]
    world = build_world(config.seed)
    cases = []
    for spec in config.cast():
        tl = build_timeline(world, spec)
        case = Case(f"{spec.key}-{MONTH_STR}", tl)
        for plan in documents(world, tl):
            seed = _seed(config.seed, spec.key, plan.key)
            mix = VARIANT_MIX[plan.doc_type]
            variant = (
                spec.variants.get(plan.key)
                or random.Random(seed).choices(list(mix), weights=list(mix.values()))[0]
            )
            defects = sorted({lab.defect for lab in tl.labels if plan.key in lab.docs})
            case.docs.append(PlannedDoc(plan, case.case_id, spec.key, variant, seed, defects))  # type: ignore[arg-type]
        cases.append(case)
    pile = [d for c in cases for d in c.docs]
    random.Random(f"{config.seed}:ids").shuffle(pile)
    for i, doc in enumerate(pile, 1):
        doc.doc_id = f"syn-{name}-{i:03d}"
    return SetPlan(config, world, cases)


def _lines(case: Case, ids: dict[str, str]) -> dict[int, LabelLine]:
    """LabelLine for every October service, keyed by id(rec)."""
    out = {}
    for domain in case.timeline.domains:
        for i, r in enumerate(visit_order(case.timeline, domain)):
            out[id(r)] = LabelLine(
                date=r.date,
                time=r.when.strftime("%H:%M"),
                code=r.code,
                domain=domain,
                document_id=ids.get(f"visit_log_{domain}"),
                entry_index=i,
            )
    return out


def case_manifest(case: Case) -> CaseManifest:
    tl = case.timeline
    ids = {d.plan.key: d.doc_id for d in case.docs}
    lines = _lines(case, ids)
    return CaseManifest(
        case_id=case.case_id,
        patient_id=tl.record.id,
        patient_name=tl.record.name,
        month=MONTH_STR,
        kind=tl.spec.kind,
        hero=tl.spec.hero,
        events=list(tl.spec.events),
        defects=[
            DefectEntry(
                id=lab.defect,
                rules=RULES[lab.defect],
                documents=[ids[k] for k in lab.docs if k in ids],
                note=lab.note,
                lines=[lines[id(r)] for r in lab.lines if id(r) in lines],
            )
            for lab in tl.labels
        ],
        documents=sorted(ids.values()),
        casefile=f"{case.case_id}.json",
    )


def coverage(plan: SetPlan) -> tuple[dict[str, int], dict[str, int]]:
    by_case = {d: 0 for d in TIER_A}
    by_doc = {d: 0 for d in TIER_A}
    for case in plan.cases:
        for d in {lab.defect for lab in case.timeline.labels}:
            by_case[d] += 1
        for doc in case.docs:
            for d in doc.defects:
                by_doc[d] += 1
    return by_case, by_doc


def master_data(plan: SetPlan) -> MasterData:
    kassen = [Payer(name=k.name, ik=k.krankenkasse_ik, kind="krankenkasse") for k in catalog.KASSEN]
    kassen += [
        Payer(name=k.pflegekasse_name, ik=k.pflegekasse_ik, kind="pflegekasse")
        for k in catalog.KASSEN
    ]
    return MasterData(
        month=MONTH_STR,
        provider=plan.world.provider,
        patients=[c.timeline.record.domain() for c in plan.cases],
        physicians=[d.domain() for d in plan.world.doctors],
        payers=kassen,
        hospital={"name": catalog.HOSPITAL_NAME, "location_code": plan.world.hospital_id},
    )


# --- Rendering and writing ----------------------------------------------------------------------


def _fax_sent(doc: PlannedDoc, tl: Timeline) -> dt.datetime:
    """When the fax header says it was sent: the Muster 12 to the Kasse on submission."""
    kind, _, ref = doc.plan.key.partition(":")
    day = MONTH_END + dt.timedelta(days=2)
    if kind == "muster12":
        rx = next(p for p in tl.prescriptions if p.id == ref)
        day = rx.submitted_to_payer_at or rx.issue_date
    elif kind in ("approval_letter", "hospital_letter"):
        day = doc.plan.content.letter_date  # type: ignore[attr-defined]
    rnd = random.Random(doc.seed)
    return dt.datetime.combine(day, dt.time(rnd.randint(8, 16), rnd.randint(0, 59)))


def _degrade(page: RenderedPage, doc: PlannedDoc, tl: Timeline) -> Degraded:
    rnd = random.Random(doc.seed)
    if doc.variant == "fax":
        return fax(page.image, rnd, sent=_fax_sent(doc, tl))
    return VARIANTS[doc.variant](page.image, rnd)


def _round(box: tuple[float, ...]) -> tuple[float, float, float, float]:
    return tuple(round(v, 1) for v in box)  # type: ignore[return-value]


def render_doc(renderer: Renderer, doc: PlannedDoc, tl: Timeline, split: str, out: Path) -> str:
    """Render, degrade, write the page image and its ground truth. Returns the image name."""
    page, truth, _ = render_document(
        renderer,
        doc.plan.doc_type,
        doc.plan.content,
        doc_id=doc.doc_id,
        seed=doc.seed,
        split=split,  # type: ignore[arg-type]
    )
    deg = _degrade(page, doc, tl)
    moved = RenderedPage(
        image=deg.image,
        fields={k: _round(deg.box(b)) for k, b in page.fields.items()},
        regions={k: _round(deg.box(b)) for k, b in page.regions.items()},
        ink={k: _round(deg.box(b)) for k, b in page.ink.items()},
    )
    lossy = doc.variant in ("scan", "photo", "bad_photo")
    image = f"{doc.doc_id}.{'jpg' if lossy else 'png'}"
    if lossy:
        deg.image.save(out / "pages" / image, quality=deg.jpeg_quality or 85)
    else:
        deg.image.save(out / "pages" / image, optimize=True)
    gt = ground_truth(
        moved,
        truth,
        doc_id=doc.doc_id,
        doc_type=doc.plan.doc_type,
        variant=doc.variant,
        seed=doc.seed,
        image_name=f"../pages/{image}",
        patient_id=doc.patient_id,
        month=MONTH_STR,
        defects=list(doc.defects),
    )
    (out / "truth" / f"{doc.doc_id}.json").write_text(gt.model_dump_json(indent=1) + "\n")
    return image


def _dump(path: Path, model: BaseModel) -> None:
    path.write_text(model.model_dump_json(indent=1) + "\n")


def write_set(name: SetName, out: Path | None = None, *, log=print) -> SetManifest:
    started = time.monotonic()
    plan = plan_set(name)
    out = out or OUT_ROOT / name
    for sub in ("pages", "truth", "cases"):
        shutil.rmtree(out / sub, ignore_errors=True)
        (out / sub).mkdir(parents=True)

    images: dict[str, str] = {}
    with Renderer() as renderer:
        for case in plan.cases:
            for doc in case.docs:
                images[doc.doc_id] = render_doc(
                    renderer, doc, case.timeline, plan.config.split, out
                )
        log(f"rendered {len(images)} documents in {time.monotonic() - started:.0f}s")

    cases = []
    for case in plan.cases:
        ids = {d.plan.key: d.doc_id for d in case.docs}
        _dump(out / "cases" / f"{case.case_id}.json", case_file(plan.world, case.timeline, ids))
        manifest = case_manifest(case)
        _dump(out / "cases" / f"{case.case_id}.manifest.json", manifest)
        cases.append(manifest)
    _dump(out / "master_data.json", master_data(plan))

    by_case, by_doc = coverage(plan)
    variants: dict[str, int] = {}
    for doc in plan.docs:
        variants[doc.variant] = variants.get(doc.variant, 0) + 1
    manifest = SetManifest(
        set=name,
        seed=plan.config.seed,
        handwriting=f"hand_{plan.config.split}",
        month=MONTH_STR,
        documents=[
            DocEntry(
                doc_id=d.doc_id,
                doc_type=d.plan.doc_type,
                variant=d.variant,
                image=f"pages/{images[d.doc_id]}",
                truth=f"truth/{d.doc_id}.json",
                case_id=d.case_id,
                patient_id=d.patient_id,
                defects=d.defects,
            )
            for d in plan.docs
        ],
        cases=cases,
        coverage=by_case,
        coverage_docs=by_doc,
        variants=dict(sorted(variants.items())),
    )
    _dump(out / "manifest.json", manifest)
    (out / "README.md").write_text(readme(manifest))
    return manifest


def readme(manifest: SetManifest) -> str:
    docs = {d.doc_id: d for d in manifest.documents}
    heroes = ["| Patient | Case | Defects | Documents |", "|---|---|---|---|"]
    for c in manifest.cases:
        if c.hero:
            defects = ", ".join(sorted({d.id for d in c.defects}))
            pile = ", ".join(f"`{i}` {docs[i].doc_type} ({docs[i].variant})" for i in c.documents)
            heroes.append(f"| {c.hero} | `{c.case_id}` | {defects} | {pile} |")
    hero_table = "\n".join(heroes) if len(heroes) > 2 else "_No hero patients in this set._"
    return f"""# Synthetic set `{manifest.set}` — generated, do not edit

Regenerate with `make synth SET={manifest.set}`
(seed {manifest.seed}, {manifest.handwriting} fonts).
Everything here is synthetic: Pflegedienst Sonnenschein GmbH, its patients, doctors and
the hospital are invented; Kassen names are real, their IKs are not. Every page carries
the watermark "MUSTER – SYNTHETISCH – KEIN ECHTES DOKUMENT".

{len(manifest.documents)} documents, {len(manifest.cases)} patient-months ({manifest.month}).
Variants: {", ".join(f"{k} {v}" for k, v in manifest.variants.items())}.

| Path | What |
|---|---|
| `pages/` | page images, the only input for the pipeline |
| `truth/<doc_id>.json` | `GroundTruth`: field values, pixel boxes, mark regions, defect labels |
| `cases/<case_id>.json` | `CaseFile` truth for one patient-month |
| `cases/<case_id>.manifest.json` | defects with rules, documents and affected visit-log lines |
| `master_data.json` | the Pflegedienst's own records (staff, patients, doctors, Kassen) |
| `manifest.json` | all of the above in one index, plus coverage |

## Hero patients

{hero_table}

## Defect coverage

{coverage_table(manifest)}
"""


def coverage_table(manifest: SetManifest) -> str:
    rows = ["| Defect | Rules | Patient-months | Documents |", "|---|---|---|---|"]
    for d in TIER_A:
        rules = ", ".join(f"`{r}`" for r in RULES[d]) or "— (clean)"
        rows.append(f"| {d} | {rules} | {manifest.coverage[d]} | {manifest.coverage_docs[d]} |")
    return "\n".join(rows)


def main(name: SetName, out: str | None = None) -> None:
    manifest = write_set(name, Path(out) if out else None)
    print(f"{name}: {len(manifest.documents)} documents, {len(manifest.cases)} patient-months")
    print("variants:", ", ".join(f"{k} {v}" for k, v in manifest.variants.items()))
    print(coverage_table(manifest))
