import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kassenfest.api.app import app
from kassenfest.api.fixtures import MONTH, ik, kvnr, world

client = TestClient(app)


def get(path: str) -> dict:
    res = client.get(path)
    assert res.status_code == 200, res.text
    return res.json()


def test_check_digits_match_the_worked_examples():
    # docs/03 §3.1
    assert ik("26032682") == "260326822"
    assert kvnr("A", "12345678") == "A123456780"


def test_board_tells_the_demo_story():
    board = get(f"/api/months/{MONTH}/board")
    status = {(c["patient_id"], c["domain"]): c["status"] for c in board["cards"]}
    assert status[("p-albers", "sgbv")] == "red"
    assert status[("p-brandl", "sgbv")] == "red"
    assert status[("p-christl", "sgbv")] == "orange"
    assert status[("p-dengler", "sgbv")] == "red"
    assert status[("p-eder", "sgbv")] == status[("p-eder", "sgbxi")] == "green"
    assert board["at_risk_cents"] == sum(c["at_risk_cents"] for c in board["cards"])
    assert [s["status"] for s in board["by_status"]] == ["red", "orange", "green"]
    # Red first, so the board opens on what needs attention.
    assert board["cards"][0]["status"] == "red"


def test_unknown_month_is_404():
    assert client.get("/api/months/2026-09/board").status_code == 404


@pytest.mark.parametrize("claim_id", sorted(world().claims))
def test_claim_detail(claim_id):
    detail = get(f"/api/claims/{claim_id}")
    claim = detail["claim"]
    assert 0 <= detail["at_risk_cents"] <= claim["total_cents"]
    line_ids = {line["id"] for line in claim["lines"]}
    for finding in detail["findings"]:
        assert set(finding["claim_line_ids"]) <= line_ids
        assert finding["message_de"] and finding["message_en"] and finding["sources"]
    assert set(detail["code_labels"]) == {line["code"] for line in claim["lines"]}


def test_lines_flagged_by_two_rules_count_once():
    detail = get(f"/api/claims/c-albers-sgbv-{MONTH}")
    assert len(detail["findings"]) == 2
    assert detail["at_risk_cents"] == detail["findings"][0]["amount_at_risk_cents"]


def test_hospital_stay_keeps_visits_outside_the_stay():
    detail = get(f"/api/claims/c-brandl-sgbv-{MONTH}")
    (finding,) = detail["findings"]
    lines = {line["id"]: line for line in detail["claim"]["lines"]}
    flagged = {(lines[i]["date"], lines[i]["time"]) for i in finding["claim_line_ids"]}
    assert ("2026-10-12", "07:30:00") not in flagged
    assert ("2026-10-12", "18:00:00") in flagged
    assert ("2026-10-16", "07:30:00") in flagged
    assert ("2026-10-16", "18:00:00") not in flagged


def test_every_evidence_box_is_on_its_page():
    for finding in world().findings:
        for ev in finding.evidence:
            doc = get(f"/api/documents/{ev.document_id}")["document"]
            page = doc["pages"][ev.page]
            assert ev.box is not None
            x0, y0, x1, y1 = ev.box
            assert 0 <= x0 < x1 <= page["width"] and 0 <= y0 < y1 <= page["height"]


def test_document_page_is_a_png_of_the_advertised_size():
    doc = get("/api/documents/doc-christl-ln")
    assert any(f["rule_id"] == "HKP-LN-SIGNATURE" for f in doc["findings"])
    res = client.get("/api/documents/doc-christl-ln/pages/0")
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(res.content))
    page = doc["document"]["pages"][0]
    assert image.size == (page["width"], page["height"])
    assert client.get("/api/documents/doc-christl-ln/pages/1").status_code == 404


def test_timeline_shows_the_hospital_stay():
    timeline = get("/api/patients/p-brandl/timeline")
    assert timeline["first_day"] == "2026-10-01" and timeline["last_day"] == "2026-10-31"
    (stay,) = timeline["stays"]
    assert stay["admitted_at"].startswith("2026-10-12")
    assert timeline["visit_logs"] and timeline["claims"]


def test_actions_are_sorted_by_due_date():
    actions = get(f"/api/months/{MONTH}/actions")
    due = [a["due_date"] for a in actions["actions"]]
    assert due == sorted(due)
    finding_ids = {f.id for f in world().findings}
    for action in actions["actions"]:
        assert set(action["finding_ids"]) <= finding_ids
        assert action["letter"]["body"]
