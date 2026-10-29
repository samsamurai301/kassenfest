"""Link, case builder and month evaluation, checked against the committed demo set.

A perfect reader (synth.oracle) must give exactly the findings the rules give on the
truth: then every difference on live data is a reading error, not a building error.
"""

import datetime as dt
from collections import Counter
from functools import cache

import pytest
from fastapi.testclient import TestClient

from kassenfest.api.app import app
from kassenfest.api.live import build_world
from kassenfest.api.routes import current_world
from kassenfest.db import Document, Extraction, Page, create_db, session_scope
from kassenfest.pipeline.casefile import SourceDoc, build_cases
from kassenfest.pipeline.link import link, name_key
from kassenfest.pipeline.month import boxed, evaluate_month
from kassenfest.rules.engine import EngineResult, run
from kassenfest.schemas.domain import CaseFile
from kassenfest.schemas.findings import Evidence
from kassenfest.schemas.ground_truth import GroundTruth
from kassenfest.schemas.records import MasterData
from kassenfest.synth.generate import OUT_ROOT
from kassenfest.synth.oracle import perfect_extraction

DEMO = OUT_ROOT / "demo"
AS_OF = dt.date(2026, 11, 2)
pytestmark = pytest.mark.skipif(not (DEMO / "manifest.json").exists(), reason="no demo set")


@cache
def records() -> MasterData:
    return MasterData.model_validate_json((DEMO / "master_data.json").read_text())


@cache
def truths() -> tuple[GroundTruth, ...]:
    files = sorted((DEMO / "truth").glob("*.json"))
    return tuple(GroundTruth.model_validate_json(f.read_text()) for f in files)


def truth_cases() -> list[CaseFile]:
    files = sorted((DEMO / "cases").glob("p??-*.json"))
    return [CaseFile.model_validate_json(f.read_text()) for f in files if "manifest" not in f.name]


def flagged(result: EngineResult) -> dict[str, Counter]:
    """rule → the billed lines it puts at risk, by (date, time, code)."""
    line = {ln.id: (ln.date, ln.time, ln.code) for c in result.claims for ln in c.lines}
    out: dict[str, Counter] = {}
    for f in result.findings:
        out.setdefault(f"{f.rule_id}/{f.severity}", Counter()).update(
            line[i] for i in f.claim_line_ids
        )
    return out


# --- link -----------------------------------------------------------------------------


def test_names_match_in_either_order_and_with_umlauts_folded():
    assert name_key("Albers, Erika") == name_key("Frau Erika Albers") == ("albers", "erika")
    assert name_key("Jäger, Renate") == name_key("JAEGER, Renate")


def test_every_demo_document_links_to_its_patient():
    for gt in truths():
        assert link(perfect_extraction(gt), records()).patient_id == gt.patient_id, gt.doc_id


def test_a_card_kvnr_unlike_the_records_links_by_name_and_says_so():
    gt = next(g for g in truths() if g.doc_type == "muster12")
    doc = perfect_extraction(gt)
    doc.kvnr.value = "Z999999999"
    found = link(doc, records())
    assert (found.patient_id, found.method) == (gt.patient_id, "name_dob")
    assert found.issues and "Z999999999" in found.issues[0]
    doc.patient_name.value = "Niemand, Nobody"
    assert link(doc, records()).patient_id is None


# --- case builder ---------------------------------------------------------------------


def test_perfect_readings_give_exactly_the_findings_of_the_truth():
    docs = [SourceDoc(gt.doc_id, perfect_extraction(gt), gt.patient_id or "") for gt in truths()]
    built = build_cases("2026-10", records(), docs)
    assert not built.issues
    for truth in truth_cases():
        mine, want = run(built.cases[truth.patient.id]), run(truth)
        assert flagged(mine) == flagged(want), truth.patient.id
        assert {c.id: c.total_cents for c in mine.claims} == {
            c.id: c.total_cents for c in want.claims
        }


def test_unreadable_key_dates_are_noted_not_guessed():
    gt = next(g for g in truths() if g.doc_type == "muster12")
    doc = perfect_extraction(gt)
    doc.period_to.value, doc.period_to.status = None, "unreadable"
    for m in doc.measures:
        m.duration_to = None
    built = build_cases("2026-10", records(), [SourceDoc("d1", doc, gt.patient_id or "")])
    assert built.cases[gt.patient_id or ""].prescriptions == []
    assert built.issues == {"d1": ["Verordnungszeitraum unreadable: not used as a Verordnung"]}


# --- month from the database, and the screens on top of it ----------------------------


@pytest.fixture
def stored_month(tmp_path):
    """The demo month as if the pipeline had read every page perfectly."""
    engine = create_db(tmp_path / "k.db")
    with session_scope(engine) as s:
        for gt in truths():
            doc = Document(
                id=gt.doc_id,
                batch_id="bat-test",
                filename=f"{gt.doc_id}.png",
                source_sha256=gt.doc_id,
                source_key=f"{gt.doc_id}.png",
                doc_type=gt.doc_type,
                status="done",
            )
            s.add(doc)
            page = gt.pages[0]
            s.add(
                Page(
                    document_id=doc.id, index=0, blob_key="x", width=page.width, height=page.height
                )
            )
            s.add(
                Extraction(
                    document_id=doc.id,
                    schema_name=gt.doc_type,
                    prompt_id="oracle",
                    reasoning_effort="none",
                    data=perfect_extraction(gt).model_dump(mode="json"),
                    cache_key="-",
                    cost_usd=0,
                    latency_ms=0,
                )
            )
    return engine


def test_month_from_the_database_matches_the_truth(stored_month):
    month = evaluate_month(stored_month, records(), "2026-10")
    for truth in truth_cases():
        assert flagged(month.results[truth.patient.id]) == flagged(run(truth)), truth.patient.id
    assert all(d.patient_id for d in month.docs.values())


def test_evidence_gets_its_rows_box_when_the_cell_has_none(stored_month):
    month = evaluate_month(stored_month, records(), "2026-10")
    doc = next(iter(month.docs.values()))
    doc.boxes = {"entries[3]": (0, (1.0, 2.0, 3.0, 4.0))}
    ev = Evidence(document_id=doc.document.id, field_path="entries[3].start_time")
    assert boxed(ev, month.docs).box == (1.0, 2.0, 3.0, 4.0)
    assert boxed(ev.model_copy(update={"field_path": "kvnr"}), month.docs).box is None


def test_the_board_tells_the_demo_story_from_the_pipeline(stored_month, tmp_path):
    world = build_world(stored_month, records(), tmp_path / "blobs", AS_OF)
    before = dict(app.dependency_overrides)
    app.dependency_overrides[current_world] = lambda: world
    try:
        board = TestClient(app).get("/api/months/2026-10/board").json()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(before)
    status = {(c["patient_name"].split(",")[0], c["domain"]): c["status"] for c in board["cards"]}
    assert status[("Albers", "sgbv")] == "red"  # D01 + D08
    assert status[("Brandl", "sgbv")] == "red"  # D06 hospital stay
    assert status[("Christl", "sgbv")] == "orange"  # D04 signature, fixable
    assert status[("Dengler", "sgbv")] == "red"  # D07 + D09
    assert status[("Eder", "sgbv")] == status[("Eder", "sgbxi")] == "green"
    assert board["at_risk_cents"] == sum(c["at_risk_cents"] for c in board["cards"]) > 0
