"""HKP rules: one passing and one failing fixture each, plus the docs/02 §8 boundaries."""

from datetime import date as D

import pytest

from kassenfest.rules.engine import pack_for
from kassenfest.rules.reference import load_reference
from kassenfest.rules.tariffs import build_claims
from kassenfest.schemas.domain import Claim
from tests.rules.factories import (
    STRUEMPFE_AN,
    WEGE,
    WUNDE,
    approval,
    approved,
    case,
    daily_visits,
    evaluate,
    hkp_log,
    one,
    prescription,
    result,
    service,
    visit,
    xi_log,
)

PRICE = 790  # 032101 Medikamentengabe, HKP-BY-2026-01 (illustrative)


def test_clean_case_passes_every_hkp_rule():
    assert evaluate(case()) == []


# --- HKP-RX-REQUIRED (D01) ---------------------------------------------------------


def test_rx_required_lines_after_period_end():
    f = one(case(prescriptions=[prescription(period_to=D(2026, 10, 14))]), "HKP-RX-REQUIRED")
    assert f.severity == "block" and f.kasse_codes == ["42002", "42003"]
    assert len(f.claim_line_ids) == 34 and f.amount_at_risk_cents == 34 * PRICE
    assert "endete am 14.10.2026" in f.message_de and "15.10.–31.10.2026" in f.message_de
    assert ("doc-rx1", "period_to") in {(e.document_id, e.field_path) for e in f.evidence}


def test_rx_required_without_any_prescription():
    f = one(case(prescriptions=[]), "HKP-RX-REQUIRED")
    assert len(f.claim_line_ids) == 62 and f.message_en.startswith("No prescription covers 62")


def test_rx_required_service_not_on_the_prescription():
    visits = [*daily_visits(), visit(D(2026, 10, 5), "10:00", WUNDE)]
    f = one(case(visit_logs=[hkp_log(visits)]), "HKP-RX-REQUIRED")
    assert f.claim_line_ids == ["ln-v#62"] and "032150" in f.message_de


def test_rx_required_period_ending_on_the_31st_covers_the_31st():
    assert not evaluate(
        case(prescriptions=[prescription(period_to=D(2026, 10, 31))]), "HKP-RX-REQUIRED"
    )


def test_rx_required_ancillary_travel_rate_needs_only_a_period():
    visits = [*daily_visits(), visit(D(2026, 10, 5), "08:00", WEGE)]
    assert not evaluate(case(visit_logs=[hkp_log(visits)]), "HKP-RX-REQUIRED")


# --- HKP-RX-SIGNED (D09) -----------------------------------------------------------


def test_rx_signed_missing_stamp():
    f = one(case(prescriptions=[prescription(stamp_present=False)]), "HKP-RX-SIGNED")
    assert f.severity == "block" and len(f.claim_line_ids) == 62
    assert "ohne Vertragsarztstempel" in f.message_de
    assert f.evidence[0].field_path == "practice_stamp"


def test_rx_signed_missing_both():
    rx = prescription(stamp_present=False, doctor_signed=False)
    f = one(case(prescriptions=[rx]), "HKP-RX-SIGNED")
    assert "Unterschrift und Vertragsarztstempel" in f.message_de
    assert {"doctor_signature", "practice_stamp"} <= {e.field_path for e in f.evidence}


def test_rx_signed_passes_when_signed_and_stamped():
    assert not evaluate(case(), "HKP-RX-SIGNED")


# --- HKP-ERST-14D (D11) ------------------------------------------------------------


def _erst(days: int):
    rx = prescription(kind="erst", period_from=D(2026, 10, 1), period_to=D(2026, 10, days))
    return case(prescriptions=[rx], visit_logs=[hkp_log(daily_visits()[: days * 2]), xi_log()])


def test_erst_exactly_14_days_passes():
    assert not evaluate(_erst(14), "HKP-ERST-14D")


def test_erst_15_days_warns_about_day_15():
    f = one(_erst(15), "HKP-ERST-14D")
    assert f.severity == "warn"
    assert f.claim_line_ids == ["ln-v#28", "ln-v#29"] and f.amount_at_risk_cents == 2 * PRICE
    assert "15 Tage" in f.message_de and "14.10.2026" in f.message_de


def test_folgeverordnung_is_not_limited_to_14_days():
    assert not evaluate(case(), "HKP-ERST-14D")


# --- HKP-FOLGE-WINDOW (D08) --------------------------------------------------------


def test_folge_missing_with_care_continuing_blocks_the_gap():
    f = one(case(prescriptions=[prescription(period_to=D(2026, 10, 14))]), "HKP-FOLGE-WINDOW")
    assert f.severity == "block" and f.kasse_codes == ["42003"]
    assert len(f.claim_line_ids) == 34
    # Window = last 3 working days before expiry: Mon 12 – Wed 14 Oct
    assert "zwischen 12.10.2026 und 14.10.2026" in f.message_de


def _with_folge(issued: D):
    first = prescription(period_to=D(2026, 10, 14))
    folge = prescription(
        id="rx2",
        issue_date=issued,
        submitted_to_payer_at=issued,
        period_from=D(2026, 10, 15),
        period_to=D(2026, 12, 31),
    )
    return case(prescriptions=[first, folge])


@pytest.mark.parametrize(
    ("issued", "variant_severity"),
    [
        (D(2026, 10, 9), "info"),  # 4 working days before expiry: too early
        (D(2026, 10, 12), None),  # 3 working days before: in the window
        (D(2026, 10, 14), None),  # on the expiry day: still in the window
        (D(2026, 10, 15), "warn"),  # after expiry: late
    ],
)
def test_folge_window_boundaries(issued, variant_severity):
    found = evaluate(_with_folge(issued), "HKP-FOLGE-WINDOW")
    assert [f.severity for f in found] == ([variant_severity] if variant_severity else [])


def test_folge_late_with_gap_blocks_the_gap_days():
    first = prescription(period_to=D(2026, 10, 14))
    folge = prescription(
        id="rx2",
        issue_date=D(2026, 10, 20),
        submitted_to_payer_at=D(2026, 10, 20),
        period_from=D(2026, 10, 20),
        period_to=D(2026, 12, 31),
    )
    f = one(case(prescriptions=[first, folge]), "HKP-FOLGE-WINDOW")
    assert f.severity == "block" and len(f.claim_line_ids) == 10  # Oct 15–19, 2 a day


def test_folge_due_reminder_when_prescription_ends_soon_after_the_month():
    f = one(case(prescriptions=[prescription(period_to=D(2026, 11, 5))]), "HKP-FOLGE-WINDOW")
    assert f.severity == "info" and f.claim_line_ids == []
    assert "03.11.2026 und 05.11.2026" in f.message_de


def test_folge_no_reminder_for_long_running_prescriptions():
    assert not evaluate(case(), "HKP-FOLGE-WINDOW")


# --- HKP-SUBMIT-4WD (D07) ----------------------------------------------------------


def _dengler(submitted, letter=D(2026, 10, 9), approvals=None):
    rx = prescription(issue_date=D(2026, 10, 1), submitted_to_payer_at=submitted)
    aps = [approval(letter_date=letter)] if approvals is None else approvals
    return case(prescriptions=[rx], approvals=aps)


def test_submit_on_the_4th_working_day_passes():
    assert not evaluate(_dengler(D(2026, 10, 7)), "HKP-SUBMIT-4WD")


def test_submit_late_puts_days_before_approval_at_risk():
    f = one(_dengler(D(2026, 10, 8)), "HKP-SUBMIT-4WD")
    assert f.severity == "warn"
    assert len(f.claim_line_ids) == 16 and f.amount_at_risk_cents == 16 * PRICE  # Oct 1–8
    assert "Frist: 07.10.2026" in f.message_de and "Tag der Deutschen Einheit" in f.message_de
    assert f.evidence[0].field_path == "issue_date" and "2026-10-08" in f.evidence[0].note


def test_submit_late_without_approval_blocks():
    f = one(_dengler(D(2026, 10, 8), approvals=[]), "HKP-SUBMIT-4WD")
    assert f.severity == "block" and len(f.claim_line_ids) == 62


def test_submit_without_proof_is_info():
    f = one(_dengler(None), "HKP-SUBMIT-4WD")
    assert f.severity == "info" and "Faxbericht" in f.message_de


def test_submit_heiligabend_policy_comes_from_the_pack():
    rx = prescription(
        issue_date=D(2026, 12, 23),
        submitted_to_payer_at=D(2026, 12, 31),
        period_from=D(2026, 12, 23),
        period_to=D(2027, 2, 28),
    )
    ap = approval(
        letter_date=D(2027, 1, 5),
        period_from=D(2026, 12, 23),
        period_to=D(2027, 2, 28),
        approved=[approved(valid_from=D(2026, 12, 23), valid_to=D(2027, 2, 28))],
    )
    c = case(
        month="2026-12",
        prescriptions=[rx],
        approvals=[ap],
        visit_logs=[hkp_log(month="2026-12", visits=daily_visits("2026-12"))],
    )
    assert one(c, "HKP-SUBMIT-4WD").message_de.count("30.12.2026") == 1  # deadline Dec 30
    closed = pack_for(D(2026, 12, 1)).model_copy(deep=True)
    closed.calendar.heiligabend = "closed"
    assert not evaluate(c, "HKP-SUBMIT-4WD", pack=closed)  # deadline Dec 31


# --- HKP-APPROVAL-EXISTS (D02) -----------------------------------------------------


def test_approval_missing_but_submitted_in_time_is_pending():
    f = one(case(approvals=[]), "HKP-APPROVAL-EXISTS")
    assert f.severity == "warn" and f.kasse_codes == [] and len(f.claim_line_ids) == 62


def test_approval_missing_and_submitted_late_blocks():
    rx = prescription(submitted_to_payer_at=D(2026, 10, 20))
    f = one(case(prescriptions=[rx], approvals=[]), "HKP-APPROVAL-EXISTS")
    assert f.severity == "block" and f.kasse_codes == ["42002", "42003"]


def test_approval_rejected_blocks_with_the_letter_as_evidence():
    f = one(case(approvals=[approval(decision="rejected")]), "HKP-APPROVAL-EXISTS")
    assert f.severity == "block" and f.kasse_codes == ["42002"]
    assert ("doc-ap1", "decision") in {(e.document_id, e.field_path) for e in f.evidence}


def test_approval_without_reference_number():
    f = one(case(approvals=[approval(approval_ref=" ")]), "HKP-APPROVAL-EXISTS")
    assert f.severity == "warn" and f.kasse_codes == ["42004"]


def test_approval_exists_leaves_unprescribed_lines_to_rx_required():
    c = case(
        prescriptions=[prescription(period_to=D(2026, 10, 14))],
        approvals=[approval(period_to=D(2026, 10, 14))],
    )
    assert not evaluate(c, "HKP-APPROVAL-EXISTS")


# --- HKP-APPROVAL-SCOPE (D03) ------------------------------------------------------


def test_scope_partial_approval_blocks_unapproved_position():
    rx = prescription(services=[service(), service("kompression", 1)])
    visits = [*daily_visits(), *daily_visits(times=("08:05",), code=STRUEMPFE_AN)]
    c = case(
        prescriptions=[rx], approvals=[approval(decision="partial")], visit_logs=[hkp_log(visits)]
    )
    f = one(c, "HKP-APPROVAL-SCOPE")
    assert f.severity == "block" and f.kasse_codes == ["43001"]
    assert len(f.claim_line_ids) == 31 and "032130" in f.message_de


def test_scope_frequency_above_approval_blocks_the_excess():
    c = case(approvals=[approval(approved=[approved(count=1)])])
    f = one(c, "HKP-APPROVAL-SCOPE")
    assert len(f.claim_line_ids) == 31 and all(int(i.split("#")[1]) % 2 for i in f.claim_line_ids)
    assert f.amount_at_risk_cents == 31 * PRICE and "1× täglich" in f.message_de


def test_scope_at_the_approved_frequency_passes():
    assert not evaluate(case(), "HKP-APPROVAL-SCOPE")


# --- HKP-FREQ-RX (D10) -------------------------------------------------------------


def test_freq_above_prescription_blocks_the_later_visit_each_day():
    c = case(prescriptions=[prescription(services=[service(count=1)])])
    f = one(c, "HKP-FREQ-RX")
    assert f.severity == "block" and f.kasse_codes == ["43001"]
    assert len(f.claim_line_ids) == 31 and f.amount_at_risk_cents == 31 * PRICE
    assert f.evidence[0].field_path == "measures[0].frequency"


def test_freq_blankoverordnung_is_exempt():
    rx = prescription(blank=True, services=[service(count=1)])
    assert not evaluate(case(prescriptions=[rx]), "HKP-FREQ-RX")


def test_freq_weekly_limit_counts_per_iso_week():
    rx = prescription(services=[service(), service("wundversorgung", 3, "week")])
    wounds = [visit(D(2026, 10, d), "11:00", WUNDE) for d in (5, 6, 7, 8, 12, 14, 16)]
    ap = approval(approved=[approved(), approved(WUNDE, 3, "week")])
    c = case(prescriptions=[rx], approvals=[ap], visit_logs=[hkp_log([*daily_visits(), *wounds])])
    rx_hits = evaluate(c, "HKP-FREQ-RX")
    assert [f.claim_line_ids for f in rx_hits] == [["ln-v#65"]]  # Thu Oct 8, 4th that week
    assert [f.claim_line_ids for f in evaluate(c, "HKP-APPROVAL-SCOPE")] == [["ln-v#65"]]


def test_freq_quantity_counts_units():
    visits = [visit(D(2026, 10, 1), "08:00", quantity=3)]
    f = one(case(visit_logs=[hkp_log(visits)]), "HKP-FREQ-RX")
    assert f.amount_at_risk_cents == PRICE  # 3 units against 2 a day


# --- HKP-LN-SIGNATURE (D04) --------------------------------------------------------


def test_ln_signature_missing_is_orange_and_points_at_the_box():
    r = result(case(visit_logs=[hkp_log(patient_signed=False), xi_log()]))
    (f,) = [f for f in r.findings if f.rule_id == "HKP-LN-SIGNATURE"]
    assert f.severity == "warn" and len(f.claim_line_ids) == 62
    assert [e.field_path for e in f.evidence] == ["patient_signature"]
    assert r.status("C-ln-v") == "orange"


def test_ln_signature_missing_with_reason_is_info():
    log = hkp_log(patient_signed=False, missing_signature_reason=2)
    f = one(case(visit_logs=[log]), "HKP-LN-SIGNATURE")
    assert f.severity == "info" and "stationär" in f.message_de


def test_ln_signature_present_passes():
    assert not evaluate(case(), "HKP-LN-SIGNATURE")


# --- HKP-STAFF-INITIALS (D05) ------------------------------------------------------


def test_staff_initials_missing_on_two_entries():
    visits = daily_visits()
    visits[4] = visits[4].model_copy(update={"staff_initials": None, "employee_no": None})
    visits[9] = visits[9].model_copy(update={"staff_initials": None, "employee_no": None})
    f = one(case(visit_logs=[hkp_log(visits)]), "HKP-STAFF-INITIALS")
    assert f.severity == "warn" and f.claim_line_ids == ["ln-v#4", "ln-v#9"]
    assert [e.field_path for e in f.evidence] == [
        "entries[4].staff_initials",
        "entries[9].staff_initials",
    ]


def test_staff_employee_number_alone_is_enough():
    visits = [v.model_copy(update={"staff_initials": None}) for v in daily_visits()]
    assert not evaluate(case(visit_logs=[hkp_log(visits)]), "HKP-STAFF-INITIALS")


# --- HKP-DUPLICATE (D18) -----------------------------------------------------------


def test_duplicate_row_within_the_month():
    visits = [*daily_visits(), visit(D(2026, 10, 3), "08:00")]
    f = one(case(visit_logs=[hkp_log(visits)]), "HKP-DUPLICATE")
    assert f.severity == "block" and f.kasse_codes == ["42007"]
    assert f.claim_line_ids == ["ln-v#62"] and f.amount_at_risk_cents == PRICE
    assert "entries[4].start_time" in {e.field_path for e in f.evidence}  # the original row


def test_duplicate_against_an_already_sent_bill():
    sent = build_claims(case(), load_reference())[0].model_copy(update={"id": "C-sent-1"})
    sent = sent.model_copy(update={"lines": sent.lines[:4]})
    f = one(case(prior_claims=[sent]), "HKP-DUPLICATE")
    assert len(f.claim_line_ids) == 4 and "C-sent-1" in f.message_de


def test_duplicate_needs_a_time_to_tell_visits_apart():
    visits = [visit(D(2026, 10, 1), None), visit(D(2026, 10, 1), None)]
    assert not evaluate(case(visit_logs=[hkp_log(visits)]), "HKP-DUPLICATE")


# --- HKP-POSITION-PRICE ------------------------------------------------------------


def test_position_unknown_in_tariff():
    visits = [*daily_visits(), visit(D(2026, 10, 2), "09:00", "039999")]
    found = evaluate(case(visit_logs=[hkp_log(visits)]), "HKP-POSITION-PRICE")
    assert [(f.kasse_codes, f.claim_line_ids) for f in found] == [(["44001"], ["ln-v#62"])]


def test_price_differs_from_contract_tariff():
    c = case()
    claims = build_claims(c, load_reference())
    lines = list(claims[0].lines)
    lines[0] = lines[0].model_copy(update={"unit_price_cents": 850})
    claims[0] = Claim.model_validate({**claims[0].model_dump(), "lines": lines})
    f = one(c, "HKP-POSITION-PRICE", claims=claims)
    assert f.kasse_codes == ["44003"] and f.amount_at_risk_cents == 60
    assert "8,50 € statt 7,90 €" in f.message_de


def test_engine_built_prices_always_match():
    assert not evaluate(case(), "HKP-POSITION-PRICE")


def test_position_price_ignores_sgbxi_lines():
    xi = xi_log(visits=[visit(D(2026, 10, 1), "09:00", "LK99", funding="sachleistung_36")])
    assert not evaluate(case(visit_logs=[hkp_log(), xi]), "HKP-POSITION-PRICE")
