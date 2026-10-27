import datetime as dt
import itertools
import random
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

from kassenfest.rules import run
from kassenfest.rules.engine import pack_for
from kassenfest.schemas.paths import flatten
from kassenfest.synth import catalog, identifiers
from kassenfest.synth.generate import OUT_ROOT, SETS, case_manifest, coverage, plan_set
from kassenfest.synth.render import templates
from kassenfest.synth.scenarios import TIER_A
from kassenfest.synth.world import MONTH_END, MONTH_START, case_file

chromium_missing = not any(
    Path.home().joinpath("Library/Caches/ms-playwright").glob("chromium-*")
) and not any(Path.home().joinpath(".cache/ms-playwright").glob("chromium-*"))


@cache
def planned(name: str):
    plan = plan_set(name)  # type: ignore[arg-type]
    cases = [(c, case_file(plan.world, c.timeline)) for c in plan.cases]
    return plan, cases


# --- Identifiers -----------------------------------------------------------------------------


def test_check_digits_match_the_documented_examples():
    from kassenfest.rules.checkdigits import (
        ik_check_digit,
        kvnr_check_digit,
        lanr_check_digit,
    )

    assert ik_check_digit("26032682") == 2
    assert kvnr_check_digit("A12345678") == 0
    assert lanr_check_digit("123456") == 6


def test_generated_identifiers_are_valid_and_corruption_is_not():
    rng = random.Random(7)
    for _ in range(200):
        kvnr = identifiers.generate_kvnr(rng)
        assert identifiers.is_valid_kvnr(kvnr)
        assert not identifiers.is_valid_kvnr(identifiers.corrupt_kvnr(kvnr, rng))
        assert identifiers.is_valid_ik(identifiers.generate_ik(rng))
        assert identifiers.is_valid_lanr(identifiers.generate_lanr(rng))
        assert identifiers.generate_bsnr(rng).startswith("71")
        assert identifiers.generate_location_code(rng).startswith("77")
    for kasse in catalog.KASSEN:
        assert identifiers.is_valid_ik(kasse.krankenkasse_ik)
        assert identifiers.is_valid_ik(kasse.pflegekasse_ik)


def test_samples_use_valid_identifiers_and_reference_positions():
    from kassenfest.synth import samples

    for seed in range(30):
        rng = random.Random(seed)
        m12, log, letter = (
            samples.muster12(rng),
            samples.visit_log_sgbv(rng),
            samples.approval_letter(rng),
        )
        assert identifiers.is_valid_kvnr(m12.kvnr) and identifiers.is_valid_lanr(m12.lanr)
        assert identifiers.is_valid_ik(m12.payer_ik) and identifiers.is_valid_ik(letter.payer_ik)
        assert identifiers.is_valid_ik(log.provider_ik)
        assert {s.position_no for s in log.services} <= set(catalog.HKP_SERVICES)


# --- The rules engine on the truth finds exactly the injected defects ---------------------------


@pytest.mark.parametrize("name", ["demo", "dev", "test"])
def test_rules_engine_on_truth_fires_exactly_the_injected_defects(name):
    """Per patient-month: block/warn findings map to the labelled defects, and each
    line-level defect affects the same billed lines (date, time, position) as labelled.
    D19 needs extraction confidences, which the truth doesn't have."""
    plan, _ = planned(name)
    defects_of = {spec.id: set(spec.defects) for spec in pack_for(MONTH_START).rules}
    for case in plan.cases:
        ids = {d.plan.key: d.doc_id for d in case.docs}
        result = run(case_file(plan.world, case.timeline, ids))
        line = {ln.id: (ln.date, ln.time, ln.code) for c in result.claims for ln in c.lines}
        fired: dict[str, Counter] = {}
        for f in result.findings:
            if f.severity in ("block", "warn"):
                for d in defects_of[f.rule_id]:
                    fired.setdefault(d, Counter()).update(line[i] for i in f.claim_line_ids)
        labels = {lab.defect: lab for lab in case.timeline.labels}
        assert set(fired) == set(labels) - {"D19", "D20"}, case.case_id
        for d, lab in labels.items():
            if lab.lines:
                mine = Counter((r.date, r.when.time(), r.code) for r in lab.lines)
                assert fired[d] == mine, (case.case_id, d)


@pytest.mark.parametrize("name", ["demo", "dev", "test"])
def test_world_invariants(name):
    plan, cases = planned(name)
    for case, cf in cases:
        labels = {lab.defect for lab in case.timeline.labels}
        stays = sorted(cf.stays, key=lambda s: s.admitted_at)
        for a, b in itertools.pairwise(stays):
            assert a.discharged_at and a.discharged_at < b.admitted_at, case.case_id
        for s in stays:
            assert s.discharged_at and s.admitted_at < s.discharged_at
            if cf.patient.deceased_at:
                assert s.discharged_at < cf.patient.deceased_at
        # Labelled lines are real billed visits of this month.
        for lab in case.timeline.labels:
            for r in lab.lines:
                assert MONTH_START <= r.date <= MONTH_END
                assert r in case.timeline.recs
        assert ("D20" in labels) == (labels == {"D20"})
        # Every visit has an entry index matching its position on the sheet.
        for log in cf.visit_logs:
            assert [v.entry_index for v in log.visits] == list(range(len(log.visits)))
    names = [c.timeline.record.last_name for c in plan.cases]
    assert len(names) == len(set(names)), "surnames repeat within a world"


def test_defect_coverage_meets_the_quotas():
    for name, quota in (("dev", 4), ("test", 3), ("demo", 1)):
        plan, _ = planned(name)
        by_case, by_doc = coverage(plan)
        for d in TIER_A:
            assert by_case[d] >= quota, (name, d, by_case[d])
            if d not in ("D20",):
                assert by_doc[d] >= quota, (name, d)
    plan, _ = planned("demo")
    heroes = {c.timeline.spec.hero: {lab.defect for lab in c.timeline.labels} for c in plan.cases}
    assert heroes["Frau Albers"] == {"D01", "D08"}
    assert heroes["Herr Brandl"] == {"D06"}
    assert heroes["Frau Christl"] == {"D04"}
    assert heroes["Herr Dengler"] == {"D07", "D09"}
    assert heroes["Frau Eder"] == {"D20"}


def test_set_sizes():
    sizes = {name: len(planned(name)[0].docs) for name in ("demo", "dev", "test")}
    assert 35 <= sizes["demo"] <= 45
    assert 55 <= sizes["dev"] <= 70
    assert 55 <= sizes["test"] <= 70


def test_demo_story_dates():
    _, cases = planned("demo")
    by_hero = {c.timeline.spec.hero: cf for c, cf in cases}
    albers = by_hero["Frau Albers"]
    assert [rx.period_to for rx in albers.prescriptions] == [dt.date(2026, 10, 14)]
    assert max(v.date for v in albers.visit_logs[0].visits) == dt.date(2026, 10, 31)
    brandl = by_hero["Herr Brandl"].stays[0]
    assert brandl.admitted_at == dt.datetime(2026, 10, 12, 10, 30)
    assert brandl.discharged_at == dt.datetime(2026, 10, 16, 11, 15)
    erst = by_hero["Herr Dengler"].prescriptions[0]
    assert erst.issue_date == dt.date(2026, 10, 1)
    assert erst.submitted_to_payer_at == dt.date(2026, 10, 8)
    assert catalog.add_working_days(erst.issue_date, 4) == dt.date(2026, 10, 7)
    assert not erst.stamp_present and erst.doctor_signed


def test_plans_are_deterministic_and_seeds_differ():
    a, b = plan_set("dev"), plan_set("dev")
    for ca, cb in zip(a.cases, b.cases, strict=True):
        assert case_file(a.world, ca.timeline) == case_file(b.world, cb.timeline)
        assert case_manifest(ca) == case_manifest(cb)
    assert [d.doc_id for d in a.docs] == [d.doc_id for d in b.docs]
    test = plan_set("test")
    assert {c.timeline.record.card_kvnr for c in a.cases}.isdisjoint(
        c.timeline.record.card_kvnr for c in test.cases
    )
    assert SETS["test"].split == "test" and SETS["dev"].split == "dev"


@pytest.mark.skipif(not (OUT_ROOT / "demo" / "manifest.json").exists(), reason="no demo set")
def test_committed_demo_set_is_current():
    """Regenerate with `kassenfest synth --set demo` after changing the generator."""
    plan, _ = planned("demo")
    root = OUT_ROOT / "demo"
    for case in plan.cases:
        ids = {d.plan.key: d.doc_id for d in case.docs}
        expected = case_file(plan.world, case.timeline, ids).model_dump_json(indent=1) + "\n"
        assert (root / "cases" / f"{case.case_id}.json").read_text() == expected, case.case_id
        manifest = case_manifest(case).model_dump_json(indent=1) + "\n"
        assert (root / "cases" / f"{case.case_id}.manifest.json").read_text() == manifest


# --- Documents ----------------------------------------------------------------------------


def test_every_document_template_carries_the_watermark():
    names = [n for n in templates.list_templates() if not n.startswith("_")]
    assert len(names) == 6
    for name in names:
        html = templates.loader.get_source(templates, name)[0]
        parent = html.split('{% extends "', 1)[1].split('"', 1)[0]
        while parent != "_page.html.j2":
            html = templates.loader.get_source(templates, parent)[0]
            parent = html.split('{% extends "', 1)[1].split('"', 1)[0]
    page = templates.loader.get_source(templates, "_page.html.j2")[0]
    assert "MUSTER – SYNTHETISCH – KEIN ECHTES DOKUMENT" in page


@pytest.mark.skipif(chromium_missing, reason="run `uv run playwright install chromium`")
def test_ground_truth_keys_are_flatten_paths_for_every_doc_type(tmp_path):
    from kassenfest.schemas.ground_truth import GroundTruth
    from kassenfest.synth.generate import render_doc
    from kassenfest.synth.oracle import perfect_extraction
    from kassenfest.synth.render import Renderer

    plan, _ = planned("demo")
    (tmp_path / "pages").mkdir()
    (tmp_path / "truth").mkdir()
    picked = {}
    for case in plan.cases:
        for doc in case.docs:
            kind = doc.plan.doc_type
            if kind == "approval_letter":
                kind += "_" + doc.plan.content.style  # type: ignore[attr-defined]
            picked.setdefault(kind, (doc, case.timeline))
    assert set(picked) == {
        "muster12", "approval_letter_a", "approval_letter_b",
        "visit_log_sgbv", "visit_log_sgbxi", "hospital_letter",
    }  # fmt: skip
    with Renderer() as renderer:
        for doc, tl in picked.values():
            render_doc(renderer, doc, tl, "dev", tmp_path)
            gt = GroundTruth.model_validate_json(
                (tmp_path / "truth" / f"{doc.doc_id}.json").read_text()
            )
            flat = flatten(perfect_extraction(gt))
            assert set(gt.fields) == set(flat), doc.plan.doc_type
            for key, f in gt.fields.items():
                if f.status == "present":
                    assert flat[key].value == f.value, (doc.plan.doc_type, key)
                    # Everything on the page has a box, except counts and bookkeeping.
                    bookkeeping = ("[#]", "quantity", "doc_type", "corrections_present")
                    if not key.endswith((*bookkeeping, "corrections_initialled")):
                        assert f.box is not None, (doc.plan.doc_type, key)
            assert (tmp_path / gt.pages[0].image.removeprefix("../")).exists()
            assert gt.defects == doc.defects


@pytest.mark.skipif(chromium_missing, reason="run `uv run playwright install chromium`")
def test_new_templates_render_marks_and_states():
    from kassenfest.synth import samples
    from kassenfest.synth.documents import ground_truth, render_document
    from kassenfest.synth.render import Renderer

    with Renderer() as renderer:
        for doc_type, content, marks in (
            ("approval_letter",
             samples.approval_letter(random.Random(1), style="a", partial=True), {}),
            ("approval_letter", samples.approval_letter(random.Random(2), style="b"), {}),
            ("visit_log_sgbxi", samples.visit_log_sgbxi(random.Random(3), patient_signed=False),
             {"patient_signature": "absent", "provider_signature": "present"}),
            ("hospital_letter", samples.hospital_letter(random.Random(4), signed=False),
             {"physician_signature": "absent"}),
        ):  # fmt: skip
            page, truth, _ = render_document(renderer, doc_type, content, doc_id="t", seed=4)
            gt = ground_truth(
                page, truth, doc_id="t", doc_type=doc_type, variant="clean", seed=4, image_name="t"
            )
            assert {k: r.state for k, r in gt.regions.items()} == marks
            assert page.image.size in ((1241, 1755), (1755, 1241))
            if doc_type == "approval_letter" and content.rejected:  # type: ignore[attr-defined]
                assert gt.fields["decision"].value == "partial"
                assert gt.fields["rejected_items[#]"].value == 1


def _demo_doc_per_type():
    plan, _ = planned("demo")
    picked = {}
    for case in plan.cases:
        for doc in case.docs:
            kind = doc.plan.doc_type
            if kind == "approval_letter":
                kind += "_" + doc.plan.content.style  # type: ignore[attr-defined]
            picked.setdefault(kind, doc)
    return list(picked.values())


@pytest.mark.skipif(chromium_missing, reason="run `uv run playwright install chromium`")
@pytest.mark.parametrize("split", ["dev", "test"])
def test_fields_stay_inside_their_cells(split):
    """Handwriting never runs into the next cell or over another field (0.5 mm slack for
    glyph jitter). Muster 12 seeds 101, 119 and 125 used to overflow the date columns."""
    from kassenfest.synth import samples
    from kassenfest.synth.documents import render_document
    from kassenfest.synth.render import Renderer

    slack = 3.0  # page pixels at 150 dpi
    docs = [(d.plan.doc_type, d.plan.content, d.seed) for d in _demo_doc_per_type()]
    docs += [("muster12", samples.muster12(random.Random(s)), s) for s in (101, 119, 125, 7)]
    with Renderer() as renderer:
        for doc_type, content, seed in docs:
            page, _, _ = render_document(
                renderer, doc_type, content, doc_id="t", seed=seed, split=split
            )
            for key, box in page.fields.items():
                cell = page.cells.get(key)
                if cell:
                    inside = (
                        box[0] >= cell[0] - slack
                        and box[1] >= cell[1] - slack
                        and box[2] <= cell[2] + slack
                        and box[3] <= cell[3] + slack
                    )
                    assert inside, (doc_type, seed, key, box, cell)
            elements = {}  # one box per element; an element may carry several keys
            for key, box in page.fields.items():
                elements.setdefault(box, key)
            boxes = list(elements.items())
            for i, (a, ka) in enumerate(boxes):
                for b, kb in boxes[i + 1 :]:
                    w = min(a[2], b[2]) - max(a[0], b[0])
                    h = min(a[3], b[3]) - max(a[1], b[1])
                    assert w <= slack or h <= slack, (doc_type, seed, ka, kb)


@pytest.mark.skipif(chromium_missing, reason="run `uv run playwright install chromium`")
def test_ink_boxes_are_tight_to_the_ink():
    """Every edge of a signature or stamp box touches ink, so SAM is scored against the
    mark itself, not its SVG frame or a script font's line box."""
    import numpy as np

    from kassenfest.synth.documents import render_document
    from kassenfest.synth.render import INK_THRESHOLD, Renderer

    checked = 0
    with Renderer() as renderer:
        for doc in _demo_doc_per_type():
            page, _, _ = render_document(
                renderer, doc.plan.doc_type, doc.plan.content, doc_id="t", seed=doc.seed
            )
            dark = np.array(page.image).min(axis=2) < INK_THRESHOLD
            for name, (x0, y0, x1, y1) in page.ink.items():
                x0, y0, x1, y1 = int(x0), int(y0), int(x1) - 1, int(y1) - 1
                rows, cols = slice(y0, y1 + 1), slice(x0, x1 + 1)
                edges = (dark[rows, x0], dark[rows, x1], dark[y0, cols], dark[y1, cols])
                assert all(e.any() for e in edges), (doc.plan.doc_type, name)
                checked += 1
    assert checked >= 6
