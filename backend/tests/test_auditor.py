"""The auditor agent and its resolver, on the demo month as a perfect reader would see it.

The resolver needs no model, so every verdict is checked exactly; the agent's rounds run
against a fake model that answers with scripted objections.
"""

import datetime as dt
import typing

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kassenfest.agents import auditor
from kassenfest.agents.auditor import attack, audit_month, dossier, due, upheld_findings
from kassenfest.agents.resolver import CHECKS_FOR, RULES_FOR, resolve, with_reading
from kassenfest.api.app import app
from kassenfest.api.deps import Deps, run_deps
from kassenfest.api.live import build_world
from kassenfest.api.routes import current_world
from kassenfest.llm.client import MetaModelClient
from kassenfest.llm.prompts import as_written
from kassenfest.pipeline.link import value
from kassenfest.pipeline.month import evaluate_month
from kassenfest.rules.engine import pack_for
from kassenfest.rules.reference import load_reference
from kassenfest.schemas.common import Extracted, Mark, Strict
from kassenfest.schemas.findings import KasseCode, Objection
from kassenfest.storage import BlobStore
from tests.conftest import FakeTransport
from tests.test_casefile import DEMO, records, stored_month  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not (DEMO / "manifest.json").exists(), reason="no demo set")
AS_OF = dt.date(2026, 11, 2)


def objection(code: str, **kw) -> Objection:
    values = dict(
        claim_line_ids=[],
        document_id=None,
        page=None,
        field_path=None,
        reads=None,
        statement="Beanstandung.",
        statement_en="Objection.",
    )
    return Objection(code=code, **{**values, **kw})  # type: ignore[arg-type]


@pytest.fixture
def month(stored_month):  # noqa: F811
    return evaluate_month(stored_month, records(), "2026-10")


def bill(month, claim_id: str):
    return dossier(month, month.claims[claim_id], AS_OF).bill


def doc_of(b, doc_type: str):
    return next(d for d in b.documents if d.document.doc_type == doc_type)


# --- vocabulary ---------------------------------------------------------------------


def test_every_kasse_code_has_rules_or_checks_and_matches_the_pack():
    codes = set(typing.get_args(KasseCode))
    assert set(RULES_FOR) == set(CHECKS_FOR) == codes == set(load_reference().kasse_codes)
    assert all(RULES_FOR[c] or CHECKS_FOR[c] for c in codes)
    pack = pack_for(dt.date(2026, 10, 1))
    ids = {r.id for r in pack.rules}
    assert {r for rules in RULES_FOR.values() for r in rules} <= ids
    for spec in pack.rules:  # a rule that emits a code is re-run for that code
        tagged = set(spec.kasse_codes) | {
            c for v in spec.variants.values() for c in v.kasse_codes or []
        }
        for code in tagged:
            assert spec.id in RULES_FOR[code], (spec.id, code)


# --- resolver: Kasse codes -------------------------------------------------------------


def test_a_code_the_rules_confirm_is_upheld(month):
    b = bill(month, "C-p01-2026-10-sgbv")  # Albers: Verordnung ended, visits went on
    hit = next(f for f in b.findings if f.rule_id == "HKP-RX-REQUIRED")
    v = resolve(b, objection("42003", claim_line_ids=hit.claim_line_ids[:1]))
    assert v.verdict == "upheld"
    assert "HKP-RX-REQUIRED: The prescription ended on 14 Oct 2026" in v.reason
    assert v.evidence


def test_a_code_on_a_clean_bill_is_dismissed_with_what_was_checked(month):
    b = bill(month, "C-p05-2026-10-sgbv")  # Eder, clean
    v = resolve(b, objection("42002"))
    assert v.verdict == "dismissed"
    assert v.checked == ["HKP-APPROVAL-EXISTS", "HKP-RX-REQUIRED", "paperwork"]
    assert "found nothing on this bill" in v.reason and "Genehmigung" in v.reason
    assert any(e.field_path == "approval_ref" for e in v.evidence)

    assert "doesn't depend on a Pflegegrad" in resolve(b, objection("43003")).reason
    assert resolve(b, objection("41002")).checked == ["MD-DECEASED", "insurance"]


def test_lines_that_are_not_on_the_bill_are_dismissed(month):
    v = resolve(bill(month, "C-p05-2026-10-sgbv"), objection("42002", claim_line_ids=["#999"]))
    assert (v.verdict, v.reason) == ("dismissed", "Lines #999 aren't on this bill.")


def test_info_is_noted_never_upheld(month):
    v = resolve(bill(month, "C-p05-2026-10-sgbxi"), objection("INFO"))
    assert v.verdict == "noted"


def test_a_mismatched_approval_number_is_upheld(month):
    b = bill(month, "C-p05-2026-10-sgbv")
    assert resolve(b, objection("42004")).verdict == "dismissed"
    doc_of(b, "visit_log_sgbv").extraction.approval_ref.value = "DAK-000000001"
    v = resolve(b, objection("42004"))
    assert v.verdict == "upheld"
    assert "DAK-000000001" in v.reason and "a human should check both pages" in v.reason
    assert len(v.evidence) == 2


# --- resolver: FACT ---------------------------------------------------------------------


def test_with_reading_normalizes_like_the_reader():
    class Doc(Strict):
        when: Extracted[str]
        codes: Extracted[list[str]]
        tick: Extracted[bool]
        signed: Mark

    when = Extracted[str](value="2026-10-31", status="present", confidence=1, page=0, box=None)
    doc = Doc(
        when=when,
        codes=Extracted[list[str]](value=None, status="empty", confidence=1, page=0, box=None),
        tick=Extracted[bool](value=False, status="present", confidence=1, page=0, box=None),
        signed=Mark(state="present", confidence=1, page=0, box=None),
    )
    assert with_reading(doc, "codes", "E11.9, I10").codes.value == ["E11.9", "I10"]
    assert with_reading(doc, "tick", "x").tick.value is True
    assert with_reading(doc, "signed", "").signed.state == "absent"
    assert with_reading(doc, "when", "").when.status == "empty"
    assert with_reading(doc, "nope", "1") is None


def test_a_fact_with_our_own_reading_is_dismissed(month):
    b = bill(month, "C-p05-2026-10-sgbv")
    rx = doc_of(b, "muster12")
    ours = as_written(value(rx.extraction, "period_to"))
    v = resolve(
        b, objection("FACT", document_id=rx.document.id, field_path="period_to", reads=ours)
    )
    assert v.verdict == "dismissed" and v.reason.startswith("We read the same in bis")


def test_a_reading_that_would_change_the_outcome_is_upheld(month):
    b = bill(month, "C-p05-2026-10-sgbv")
    rx = doc_of(b, "muster12")
    v = resolve(
        b, objection("FACT", document_id=rx.document.id, field_path="period_to", reads="10.10.2026")
    )
    assert v.verdict == "upheld"
    assert "auditor reads 10.10.2026" in v.reason and "HKP-RX-REQUIRED" in v.reason
    assert "every rule with the auditor's reading" in v.checked


def test_a_reading_that_changes_nothing_is_dismissed(month):
    b = bill(month, "C-p05-2026-10-sgbv")
    rx = doc_of(b, "muster12")
    v = resolve(
        b,
        objection("FACT", document_id=rx.document.id, field_path="further_notes", reads="Bitte"),
    )
    assert v.verdict == "dismissed" and v.reason.endswith("nothing on this bill changes.")


def test_a_misread_insurance_number_is_answered_by_the_other_documents(month):
    b = bill(month, "C-p05-2026-10-sgbv")
    rx = doc_of(b, "muster12")
    rx.extraction.kvnr.value = "M108879567"  # one letter misread, as on the live run
    v = resolve(b, objection("41002", document_id=rx.document.id, field_path="kvnr"))
    assert v.verdict == "dismissed"
    assert "approves this Verordnung" in v.reason and "most likely misread" in v.reason

    for d in b.documents:  # nothing else ties it to her: a human looks
        if d is not rx and d.extraction and hasattr(d.extraction, "kvnr"):
            d.extraction.kvnr.value = "X000000000"
    b.case.approvals.clear()
    assert (
        resolve(b, objection("41002", document_id=rx.document.id, field_path="kvnr")).verdict
        == "upheld"
    )


# --- the agent ------------------------------------------------------------------------------


def scripted(rounds: list[list[dict]]):
    """A fake model answering round n with rounds[n-1]."""

    def answer(kwargs):
        text = kwargs["messages"][1]["content"][0]["text"]
        n = 2 if "Your objections so far" in text else 1
        return {"objections": rounds[n - 1] if n <= len(rounds) else []}

    return answer


def raw(code: str, **kw) -> dict:
    return objection(code, **kw).model_dump()


@pytest.fixture
def blobs(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    store.path("x").parent.mkdir(parents=True)
    Image.new("RGB", (100, 140), "white").save(store.path("x"), format="PNG")  # stored_month's key
    return store


async def test_two_rounds_repeats_dropped_lines_mapped(month, blobs, make_settings):
    d = dossier(month, month.claims["C-p05-2026-10-sgbv"], AS_OF)
    transport = FakeTransport(
        chat_content=scripted(
            [
                [raw("42002", claim_line_ids=["#0"]), raw("INFO")],
                [raw("42002", claim_line_ids=["#0"])],
            ]
        )
    )
    result = await attack(MetaModelClient(make_settings(), transport=transport), blobs, d)

    assert [[v.verdict for v in r] for r in result.rounds] == [["dismissed", "noted"]]
    assert result.repeats == 1
    assert result.rounds[0][0].objection.claim_line_ids == ["p05-2026-10-sgbv#0"]
    calls = [kw for kind, kw in transport.calls if kind == "chat"]
    assert len(calls) == 2 and calls[0]["reasoning_effort"] == "high"
    assert "dismissed: HKP-APPROVAL-EXISTS" in calls[1]["messages"][1]["content"][0]["text"]
    assert len(calls[0]["messages"][1]["content"]) == 1 + len(d.pages)  # text + page images
    prompt = calls[0]["messages"][1]["content"][0]["text"]
    assert "Document D1" in prompt and not any(p.document.id in prompt for p, _ in d.pages)


async def test_audits_are_stored_once_per_state_and_upheld_ones_become_findings(
    stored_month,  # noqa: F811
    blobs,
    make_settings,
    tmp_path,
):
    m = evaluate_month(stored_month, records(), "2026-10")
    eder = m.claims["C-p05-2026-10-sgbv"]
    rx = next(
        d for d in m.docs.values() if d.patient_id == "p05" and d.document.doc_type == "muster12"
    )
    period = raw("FACT", document_id="D1", field_path="period_to", reads="10.10.2026")  # D1: rx
    client = MetaModelClient(
        make_settings(), transport=FakeTransport(chat_content=scripted([[period]]))
    )

    clean = {d.bill.claim.id for d in due(m, stored_month, AS_OF)}
    assert eder.id in clean and "C-p01-2026-10-sgbv" not in clean
    done = await audit_month(
        client, stored_month, blobs, records(), claim_ids=[eder.id], as_of=AS_OF
    )

    assert (done.audited, done.objections, done.upheld) == (1, 1, 1)
    assert eder.id not in {d.bill.claim.id for d in due(m, stored_month, AS_OF)}
    (finding,) = upheld_findings(eder, auditor.latest_audits(stored_month)[eder.id])
    assert finding.evidence[0].document_id == rx.document.id
    assert (finding.rule_id, finding.severity, finding.claim_id) == ("AUDITOR", "warn", eder.id)

    world = build_world(stored_month, records(), tmp_path / "blobs")
    assert world.audits[eder.id].state == "done" and world.audits[eder.id].upheld == 1
    assert world.audits["C-p01-2026-10-sgbv"].state == "not_needed"
    assert world.audits["C-p05-2026-10-sgbxi"].state == "pending"
    deps = Deps(client, stored_month, blobs, records())
    app.dependency_overrides[current_world] = lambda: world
    app.dependency_overrides[run_deps] = lambda: deps
    try:
        api = TestClient(app)
        card = next(
            c
            for c in api.get("/api/months/2026-10/board").json()["cards"]
            if c["claim_id"] == eder.id
        )
        assert (card["status"], card["audit"]["upheld"]) == ("orange", 1)
        detail = api.get(f"/api/claims/{eder.id}").json()
        assert detail["audit"]["rounds"][0]["verdicts"][0]["verdict"] == "upheld"
        assert api.post("/api/claims/C-p01-2026-10-sgbv/audit").status_code == 409
        assert api.post(f"/api/claims/{eder.id}/audit").json()["state"] == "done"
    finally:
        app.dependency_overrides.clear()
