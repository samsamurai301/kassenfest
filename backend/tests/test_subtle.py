"""The auditor eval's seeded set: subtle defects no rule checks, and how catches are scored."""

import datetime as dt
from collections import Counter

import pytest

from kassenfest.db import create_db
from kassenfest.eval.auditor import CATCH, score, store_set
from kassenfest.pipeline.month import evaluate_month
from kassenfest.rules import run
from kassenfest.schemas.findings import Objection
from kassenfest.storage import BlobStore
from kassenfest.synth import identifiers
from kassenfest.synth.generate import SetManifest
from kassenfest.synth.subtle import HKP_ONLY, SUBTLE
from kassenfest.synth.world import MONTH_START, case_file
from tests.test_casefile import DEMO, records
from tests.test_synth_world import planned


def contents(case) -> dict:
    return {d.plan.key: d.plan.content for d in case.docs}


def test_every_subtle_defect_is_seeded_twice_and_leaves_the_bill_green():
    plan, _ = planned("audit")
    seeded = Counter(d for c in plan.cases for d in c.timeline.spec.defects)
    assert seeded == Counter({d: 2 for d in SUBTLE})
    assert sum(not c.timeline.spec.defects for c in plan.cases) == 5
    for case in plan.cases:
        spec = case.timeline.spec
        assert not (set(spec.defects) & HKP_ONLY) or spec.kind == "hkp", case.case_id
        ids = {d.plan.key: d.doc_id for d in case.docs}
        result = run(case_file(plan.world, case.timeline, ids))
        flagged = [f.rule_id for f in result.findings if f.severity != "info"]
        assert flagged == [], (case.case_id, spec.defects, flagged)
    assert all(not c.timeline.spec.key.startswith("s") for c in plan.cases)  # ids say nothing


def test_each_defect_shows_where_its_label_says():
    plan, _ = planned("audit")
    for case in plan.cases:
        tl, docs = case.timeline, contents(case)
        for label in tl.labels:
            first = docs.get(label.docs[0])
            match label.defect:
                case "S01":
                    genehmigung = docs[label.docs[1]].approval_ref
                    differ = [a != b for a, b in zip(first.approval_ref, genehmigung, strict=True)]
                    assert sum(differ) == 1, (first.approval_ref, genehmigung)
                case "S02":
                    assert first.kvnr != tl.record.card_kvnr
                    assert identifiers.is_valid_kvnr(first.kvnr)
                case "S03":
                    assert first.patient_dob != tl.record.dob
                case "S04":
                    erst = tl.prescriptions[0]
                    assert erst.period_from < erst.issue_date == first.issue_date
                    assert label.lines and all(r.date < erst.issue_date for r in label.lines)
                case "S05":
                    meds = [m for m in first.measures if m.category == "medikamentengabe"]
                    assert meds and all(m.details is None for m in meds)
                case "S06":
                    stranger = len(first.staff) - 1
                    assert first.staff[stranger].initials not in {
                        s.initials for s in plan.world.staff
                    }
                    assert sum(v.staff == stranger for v in first.visits) >= 3
                case "S07":
                    assert first.patient_signature_date < dt.date(2026, 10, 20)
                case "S08":  # one time per column (SGB V) or Einsatz (SGB XI), all month

                    def column(v):
                        return (v.service, v.slot) if hasattr(v, "service") else (v.einsatz,)

                    times = {(column(v), v.time) for v in first.visits}
                    assert len(times) == len({column(v) for v in first.visits})
                case "S09":
                    for r in label.lines:
                        morning = next(
                            m for m in tl.october_of("sgbv")
                            if m.date == r.date and m.code == r.code and m is not r
                        )  # fmt: skip
                        assert (
                            dt.timedelta(minutes=3)
                            < r.when - morning.when
                            < dt.timedelta(minutes=15)
                        )
                case "S10":
                    assert first.one_hand
    assert MONTH_START.month == 10


def objection(code: str, *, field: str | None = None, en: str = "Something else.") -> Objection:
    return Objection(
        code=code,  # type: ignore[arg-type]
        claim_line_ids=[],
        document_id="D1" if field else None,
        page=0 if field else None,
        field_path=field,
        reads="x" if field else None,
        statement="Etwas anderes.",
        statement_en=en,
    )


def test_a_catch_names_the_seeded_defect_by_code_field_or_words():
    assert CATCH["S01"].matches(objection("42004"))
    assert CATCH["S01"].matches(objection("FACT", field="approval_ref"))
    assert not CATCH["S01"].matches(objection("43005"))
    assert CATCH["S02"].matches(objection("FACT", field="kvnr"))
    assert not CATCH["S02"].matches(objection("FACT", field="payer_ik"))
    assert CATCH["S08"].matches(objection("INFO", en="Every visit is logged at the same time."))
    assert CATCH["S10"].matches(objection("INFO", en="All entries are in the same handwriting."))
    assert not CATCH["S10"].matches(objection("INFO", en="The signature is dated 30 Oct."))
    assert CATCH["S07"].matches(
        objection("INFO", en="The patient signed on 15 Oct, before the later visits.")
    )


@pytest.mark.skipif(not (DEMO / "manifest.json").exists(), reason="no demo set")
def test_a_set_is_read_perfectly_and_every_bill_scored(tmp_path):
    engine = create_db(tmp_path / "k.db")
    assert store_set(engine, BlobStore(tmp_path / "blobs"), DEMO) == 42
    month = evaluate_month(engine, records(), "2026-10")
    assert all(d.patient_id for d in month.docs.values())
    assert all((tmp_path / "blobs").rglob("*.*"))
    manifest = SetManifest.model_validate_json((DEMO / "manifest.json").read_text())
    bills = score(month, engine, manifest)
    assert len(bills) == len(month.claims)
    assert all(b.defect is None and b.error == "not audited" for b in bills)  # no S defects here
