"""Stay, SGB XI, master-data and document rules, with the docs/02 §8 boundaries."""

import dataclasses
from datetime import date as D

import pytest

from kassenfest.rules import evaluate_document
from kassenfest.rules.engine import pack_for
from kassenfest.rules.reference import load_reference
from kassenfest.rules.tariffs import build_claims
from kassenfest.schemas.domain import PflegegradPeriod
from tests.rules.factories import (
    case,
    daily_visits,
    evaluate,
    field,
    hkp_log,
    mark,
    muster12,
    one,
    patient,
    stay,
    ts,
    visit,
    xi_log,
)

LK01 = 3977  # 420 points × €0.0947 (illustrative)
OCT_12 = D(2026, 10, 12)


# --- STAY-HKP / STAY-XI-SACH (D06) -------------------------------------------------


def _brandl(**kw):
    return case(stays=[stay(ts(OCT_12, "10:30"), ts(D(2026, 10, 16), "11:00"), **kw)])


def test_stay_hkp_blocks_visits_while_in_hospital():
    f = one(_brandl(), "STAY-HKP")
    assert f.severity == "block" and f.kasse_codes == ["41003"]
    # Oct 12 18:00, Oct 13–15 (2 a day), Oct 16 08:00 before the 11:00 discharge
    assert f.claim_line_ids == ["ln-v#23", *[f"ln-v#{i}" for i in range(24, 30)], "ln-v#30"]
    assert {"admission_date", "discharge_date"} <= {e.field_path for e in f.evidence}
    assert "Aufnahme 12.10.2026 10:30" in f.message_de


@pytest.mark.parametrize(("hhmm", "billable"), [("07:45", True), ("18:00", False)])
def test_stay_admission_day_compares_timestamps(hhmm, billable):
    c = case(
        visit_logs=[hkp_log([visit(OCT_12, hhmm)])],
        stays=[stay(ts(OCT_12, "10:30"), ts(D(2026, 10, 20), "09:00"))],
    )
    assert (not evaluate(c, "STAY-HKP")) == billable


def test_stay_edge_day_without_time_needs_a_human():
    c = case(visit_logs=[hkp_log([visit(OCT_12, None)])], stays=[stay(ts(OCT_12, "10:30"), None)])
    f = one(c, "STAY-HKP")
    assert f.severity == "warn" and "noch stationär" in f.message_de


def test_stay_admission_day_policy_is_a_pack_parameter():
    c = case(
        visit_logs=[hkp_log([visit(OCT_12, "07:45")])], stays=[stay(ts(OCT_12, "10:30"), None)]
    )
    pack = pack_for(D(2026, 10, 1)).model_copy(deep=True)
    pack.rule("STAY-HKP").params["admission_day_policy"] = "exclude_edge_days"
    assert not evaluate(c, "STAY-HKP")
    assert evaluate(c, "STAY-HKP", pack=pack)


def test_stay_xi_suspends_sachleistung():
    f = one(_brandl(), "STAY-XI-SACH")
    # 09:00 visits: Oct 12 is before admission; Oct 13–16 (16th before the 11:00 discharge)
    assert f.claim_line_ids == ["ln-xi#12", "ln-xi#13", "ln-xi#14", "ln-xi#15"]
    assert f.amount_at_risk_cents == 4 * LK01


def test_short_term_care_suspends_sgbxi_but_is_not_stay_hkp():
    c = _brandl(kind="short_term_care")
    assert evaluate(c, "STAY-XI-SACH") and not evaluate(c, "STAY-HKP")


def test_no_stay_passes():
    assert not evaluate(case(), "STAY-HKP") and not evaluate(case(), "STAY-XI-SACH")


# --- XI-36-BUDGET (D12) ------------------------------------------------------------


def _with_cap(cap_cents: int):
    ref = load_reference()
    amounts = ref.amounts_on(D(2026, 10, 1)).model_copy(
        update={"sachleistung_36_cents": {1: 0, 2: 0, 3: cap_cents, 4: 0, 5: 0}}
    )
    return dataclasses.replace(ref, sgbxi_amounts=[amounts])


def test_budget_exactly_at_the_cap_passes_one_cent_over_warns():
    total = build_claims(case(), load_reference())[1].total_cents
    assert not evaluate(case(), "XI-36-BUDGET", ref=_with_cap(total))
    f = one(case(), "XI-36-BUDGET", ref=_with_cap(total - 1))
    assert f.severity == "warn" and f.amount_at_risk_cents == 1
    assert f.claim_line_ids == ["ln-xi#30"]  # the month's last service


def test_budget_overflow_becomes_eigenanteil():
    c = case(patient=patient(pflegegrad=[PflegegradPeriod(grade=2, valid_from=D(2025, 1, 1))]))
    f = one(c, "XI-36-BUDGET")
    assert f.amount_at_risk_cents == 31 * LK01 - 79600
    assert "Pflegegrad 2 (796,00 €)" in f.message_de and "Eigenanteil" in f.message_de
    assert len(f.claim_line_ids) == 11  # the last 11 visits carry the €436.87


@pytest.mark.parametrize(
    ("policy", "cap"),
    [
        ("max_in_month", 149700),
        ("start_of_month", 79600),
        ("prorate", (14 * 79600 + 17 * 149700) // 31),
    ],
)
def test_budget_pflegegrad_change_on_the_15th(policy, cap):
    grades = [
        PflegegradPeriod(grade=2, valid_from=D(2025, 1, 1)),
        PflegegradPeriod(grade=3, valid_from=D(2026, 10, 15)),
    ]
    c = case(patient=patient(pflegegrad=grades))
    pack = pack_for(D(2026, 10, 1)).model_copy(deep=True)
    pack.rule("XI-36-BUDGET").params["pflegegrad_change_policy"] = policy
    found = evaluate(c, "XI-36-BUDGET", pack=pack)
    over = max(0, 31 * LK01 - cap)
    assert sum(f.amount_at_risk_cents for f in found) == over
    if found:
        assert "Pflegegrad 2→3" in found[0].message_de


def test_budget_ignores_entlastungsbetrag_lines():
    extra = [visit(D(2026, 10, d), "15:00", "LK10", funding="entlastung_45b") for d in range(1, 29)]
    xi = xi_log(
        visits=[*daily_visits(times=("09:00",), code="LK01", funding="sachleistung_36"), *extra]
    )
    assert not evaluate(case(visit_logs=[hkp_log(), xi]), "XI-36-BUDGET")


# --- XI-LN-SIGNATURE (D04) ---------------------------------------------------------


def test_xi_signature_missing_warns():
    f = one(case(visit_logs=[hkp_log(), xi_log(patient_signed=False)]), "XI-LN-SIGNATURE")
    assert f.severity == "warn" and len(f.claim_line_ids) == 31
    assert f.evidence[0].document_id == "doc-ln-xi"


def test_xi_signature_present_passes():
    assert not evaluate(case(), "XI-LN-SIGNATURE")


# --- MD-KVNR-CHECK (D16) -----------------------------------------------------------


def test_kvnr_wrong_check_digit_blocks_every_claim():
    found = evaluate(case(patient=patient(kvnr="A123456781")), "MD-KVNR-CHECK")
    assert [f.claim_id for f in found] == ["C-ln-v", "C-ln-xi"]
    assert all(f.severity == "block" and "Prüfziffer" in f.message_de for f in found)
    assert ("doc-rx1", "kvnr") in {(e.document_id, e.field_path) for e in found[0].evidence}


def test_kvnr_bad_format():
    f = evaluate(case(patient=patient(kvnr="12345")), "MD-KVNR-CHECK")[0]
    assert "Format" in f.message_de


def test_kvnr_valid_passes():
    assert not evaluate(case(), "MD-KVNR-CHECK")


# --- MD-DECEASED (D15) -------------------------------------------------------------


def test_deceased_blocks_services_after_death():
    found = evaluate(case(patient=patient(deceased_at=ts(D(2026, 10, 20), "14:00"))), "MD-DECEASED")
    by_claim = {f.claim_id: f for f in found}
    assert len(by_claim["C-ln-v"].claim_line_ids) == 1 + 22  # Oct 20 18:00, Oct 21–31
    assert len(by_claim["C-ln-xi"].claim_line_ids) == 11  # 09:00 on the 20th is before death
    assert "Kennzeichen 1" in by_claim["C-ln-v"].message_de


@pytest.mark.parametrize(("hhmm", "flagged"), [("16:00", True), ("10:00", False)])
def test_deceased_same_day_compares_times(hhmm, flagged):
    c = case(
        patient=patient(deceased_at=ts(D(2026, 10, 20), "14:00")),
        visit_logs=[hkp_log([visit(D(2026, 10, 20), hhmm)])],
    )
    assert bool(evaluate(c, "MD-DECEASED")) == flagged


def test_deceased_same_day_without_time_warns():
    c = case(
        patient=patient(deceased_at=ts(D(2026, 10, 20), "14:00")),
        visit_logs=[hkp_log([visit(D(2026, 10, 20), None)])],
    )
    assert one(c, "MD-DECEASED").severity == "warn"


def test_alive_passes():
    assert not evaluate(case(), "MD-DECEASED")


# --- DOC-READABLE (D19) ------------------------------------------------------------


def test_readable_document_passes():
    assert evaluate_document(muster12(), document_id="doc-rx1", on=D(2026, 10, 1)) == []


def test_unreadable_and_low_confidence_billing_fields_warn():
    doc = muster12(
        kvnr=field(None, "unreadable", 0.3),
        period_to=field("2026-12-31", confidence=0.4),
        practice_stamp=mark("unclear", 0.5),
        further_notes=field("schwer lesbar", confidence=0.2),  # not billing-relevant
    )
    (f,) = evaluate_document(doc, document_id="doc-rx1", on=D(2026, 10, 1), patient_id="p01")
    assert f.rule_id == "DOC-READABLE" and f.severity == "warn"
    assert [e.field_path for e in f.evidence] == ["kvnr", "period_to", "practice_stamp"]
    assert all(e.document_id == "doc-rx1" for e in f.evidence)
    assert "0,7" in f.message_de and f.claim_line_ids == []


def test_readable_flags_low_confidence_rows_by_wildcard():
    measures = [{**muster12().measures[0].model_dump(), "confidence": 0.5}]
    (f,) = evaluate_document(muster12(measures=measures), document_id="d", on=D(2026, 10, 1))
    assert [e.field_path for e in f.evidence] == ["measures[0]"]


def test_empty_field_is_not_unreadable():
    doc = muster12(lanr=field(None, "empty", 0.9))
    assert evaluate_document(doc, document_id="d", on=D(2026, 10, 1)) == []
