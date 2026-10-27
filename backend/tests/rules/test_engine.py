import datetime as dt
from datetime import date as D

import pytest
import yaml

from kassenfest.rules import engine
from kassenfest.rules.engine import CASE_RULES, DOCUMENT_RULES, available_packs, load_pack, pack_for
from kassenfest.rules.text import Cents, DateList, Loc, fmt
from tests.rules.factories import (
    approval,
    approved,
    case,
    daily_visits,
    evaluate,
    hkp_log,
    prescription,
    result,
    xi_log,
)

TIER_A = {
    "HKP-RX-REQUIRED",
    "HKP-RX-SIGNED",
    "HKP-ERST-14D",
    "HKP-FOLGE-WINDOW",
    "HKP-SUBMIT-4WD",
    "HKP-APPROVAL-EXISTS",
    "HKP-APPROVAL-SCOPE",
    "HKP-FREQ-RX",
    "HKP-LN-SIGNATURE",
    "HKP-STAFF-INITIALS",
    "HKP-DUPLICATE",
    "HKP-POSITION-PRICE",
    "STAY-HKP",
    "STAY-XI-SACH",
    "XI-36-BUDGET",
    "XI-LN-SIGNATURE",
    "MD-KVNR-CHECK",
    "MD-DECEASED",
    "DOC-READABLE",
}


def test_pack_2026_01_has_every_tier_a_rule_and_each_is_implemented():
    pack = pack_for(D(2026, 10, 1))
    assert pack.id == "2026-01"
    ids = {r.id for r in pack.rules}
    assert ids == TIER_A
    assert ids == set(CASE_RULES) | set(DOCUMENT_RULES)
    for spec in pack.rules:
        assert spec.sources and spec.message_de and spec.message_en
        assert set(spec.variants) <= {
            "expired",
            "not_prescribed",
            "missing_gap",
            "due",
            "early",
            "late",
            "late_gap",
            "no_approval",
            "no_proof",
            "pending",
            "rejected",
            "no_ref",
            "not_approved",
            "excess",
            "reason",
            "prior",
            "unknown",
            "price",
            "edge_unclear",
            "check_digit",
            "unclear",
        }


def _write_pack(root, pack_id, valid_from, draft=False, max_days=14):
    d = root / pack_id
    d.mkdir()
    manifest = {"id": pack_id, "label": pack_id, "valid_from": valid_from, "draft": draft}
    (d / "pack.yaml").write_text(yaml.safe_dump(manifest))
    rule = {
        "id": "HKP-ERST-14D",
        "version": 1,
        "valid_from": valid_from,
        "domain": "hkp",
        "severity": "warn",
        "params": {"max_days": max_days},
        "sources": ["test"],
        "message_de": "{days}",
        "message_en": "{days}",
    }
    (d / "hkp.yaml").write_text(yaml.safe_dump([rule]))


def test_pack_is_chosen_by_service_date_and_drafts_only_by_id(tmp_path):
    _write_pack(tmp_path, "2025-01", "2025-01-01", max_days=10)
    _write_pack(tmp_path, "2026-01", "2026-01-01")
    _write_pack(tmp_path, "2027-01-draft", "2027-01-01", draft=True, max_days=28)
    available_packs.cache_clear()
    try:
        assert pack_for(D(2025, 6, 1), tmp_path).id == "2025-01"
        assert pack_for(D(2026, 10, 1), tmp_path).id == "2026-01"
        assert pack_for(D(2027, 3, 1), tmp_path).id == "2026-01"  # the draft is not law
        assert pack_for(D(2027, 3, 1), tmp_path, pack_id="2027-01-draft").draft
        with pytest.raises(LookupError):
            pack_for(D(2024, 12, 31), tmp_path)

        # Same Verordnung, different verdict depending on the pack in force.
        rx = prescription(kind="erst", period_from=D(2026, 10, 1), period_to=D(2026, 10, 12))
        c = case(prescriptions=[rx], visit_logs=[])
        old = pack_for(D(2025, 6, 1), tmp_path)
        assert evaluate(c, "HKP-ERST-14D", pack=old)
        assert not evaluate(c, "HKP-ERST-14D", pack=pack_for(D(2026, 10, 1), tmp_path))
    finally:
        available_packs.cache_clear()


def test_load_pack_rejects_duplicate_ids(tmp_path):
    _write_pack(tmp_path, "dup", "2026-01-01")
    (tmp_path / "dup" / "more.yaml").write_text((tmp_path / "dup" / "hkp.yaml").read_text())
    with pytest.raises(ValueError, match="duplicate"):
        load_pack(tmp_path / "dup")


def test_rules_outside_their_validity_are_skipped():
    pack = pack_for(D(2026, 10, 1))
    late = pack.model_copy(deep=True)
    late.rule("HKP-RX-REQUIRED").valid_from = D(2026, 11, 1)
    c = case(prescriptions=[])
    assert evaluate(c, "HKP-RX-REQUIRED")
    assert not evaluate(c, "HKP-RX-REQUIRED", pack=late)


def test_clean_case_has_no_findings_and_is_green():
    r = result(case())
    assert r.findings == []
    assert r.status() == "green" and r.at_risk_cents() == 0
    assert [c.total_cents for c in r.claims] == [62 * 790, 31 * 3977]


def test_every_finding_has_evidence_ids_and_money():
    # Albers: Verordnung ended Oct 14, care continued → two rules hit the same 34 lines.
    rx = prescription(period_to=D(2026, 10, 14))
    r = result(case(prescriptions=[rx]))
    assert {f.rule_id for f in r.findings} == {"HKP-RX-REQUIRED", "HKP-FOLGE-WINDOW"}
    for f in r.findings:
        assert f.evidence and all(e.document_id for e in f.evidence)
        assert f.claim_id == "C-ln-v" and len(f.claim_line_ids) == 34
        assert f.amount_at_risk_cents == 34 * 790
        assert f.patient_id == "p01" and f.rule_version == 1
    # €-at-risk counts each line once even though two rules hit it.
    assert r.at_risk_cents() == 34 * 790
    assert r.status("C-ln-v") == "red" and r.status("C-ln-xi") == "green"


def test_finding_ids_are_stable_across_runs():
    c = case(prescriptions=[prescription(period_to=D(2026, 10, 14))])
    assert [f.id for f in evaluate(c)] == [f.id for f in evaluate(c)]


def test_only_the_billing_month_is_billed():
    september = hkp_log(id="ln-sep", month="2026-09", visits=daily_visits("2026-09"))
    r = result(case(visit_logs=[hkp_log(), xi_log(), september]))
    assert [c.id for c in r.claims] == ["C-ln-v", "C-ln-xi"]


def test_leap_year_february_2028_uses_the_pack_in_force():
    rx = prescription(
        issue_date=D(2028, 1, 26),
        submitted_to_payer_at=D(2028, 1, 27),
        period_from=D(2028, 2, 1),
        period_to=D(2028, 3, 31),
    )
    ap = approval(
        letter_date=D(2028, 2, 2),
        period_from=D(2028, 2, 1),
        period_to=D(2028, 3, 31),
        approved=[approved(valid_from=D(2028, 2, 1), valid_to=D(2028, 3, 31))],
    )
    c = case(
        month="2028-02",
        prescriptions=[rx],
        approvals=[ap],
        visit_logs=[
            hkp_log(month="2028-02", visits=daily_visits("2028-02")),
            xi_log(month="2028-02"),
        ],
    )
    r = result(c)
    assert r.pack_id == "2026-01" and r.findings == []
    assert len(r.claims[0].lines) == 58 and r.claims[0].lines[-1].date == D(2028, 2, 29)


def test_message_values_render_per_language():
    assert fmt(Cents(123456), "de") == "1.234,56 €" and fmt(Cents(-5), "en") == "-€0.05"
    days = DateList([D(2026, 10, d) for d in (15, 16, 17, 20)] + [D(2026, 11, 2)])
    assert fmt(days, "de") == "15.10.–17.10.2026, 20.10.2026, 02.11.2026"
    assert fmt(days, "en") == "15–17 Oct 2026, 20 Oct 2026, 2 Nov 2026"
    assert fmt(DateList([D(2026, 9, 30), D(2026, 10, 1)]), "en") == "30 Sep – 1 Oct 2026"
    assert fmt(dt.datetime(2026, 10, 12, 10, 30), "de") == "12.10.2026 10:30"
    assert fmt(Loc("täglich", "per day"), "en") == "per day"
    assert fmt(0.7, "de") == "0,7" and fmt(None, "en") == "–"


def test_rule_registry_rejects_duplicates():
    with pytest.raises(ValueError):
        engine.rule("HKP-RX-REQUIRED")(lambda ctx, params: [])


def test_readme_lists_every_rule_in_the_pack():
    readme = (engine.Path(engine.__file__).parent / "README.md").read_text(encoding="utf-8")
    missing = [r.id for r in pack_for(D(2026, 10, 1)).rules if f"| `{r.id}` |" not in readme]
    assert missing == []
