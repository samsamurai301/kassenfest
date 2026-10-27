import re
from datetime import date as D
from decimal import Decimal

from kassenfest.rules.checkdigits import is_valid_ik
from kassenfest.rules.reference import load_reference
from kassenfest.rules.sgbxi import entlastung_carryover_valid
from kassenfest.rules.tariffs import (
    build_claim,
    hkp_price,
    lk_price,
    normalize_lk,
    points_to_cents,
)
from tests.rules.factories import hkp_log, visit, xi_log

REF = load_reference()


def test_payers_are_synthetic_with_valid_iks():
    assert len(REF.kassen) == 10
    payers = REF.payers()
    assert len(payers) == 20 and all(p.synthetic for p in payers.values())
    assert all(is_valid_ik(ik) for ik in payers)
    assert {p.kind for p in payers.values()} == {"krankenkasse", "pflegekasse"}


def test_hkp_positions_follow_the_six_digit_pattern():
    # digits 1–2 legal basis (01, 03, 10), digit 3 care type (1, 2, 3)
    assert all(re.fullmatch(r"(01|03|10)[123]\d{3}", code) for code in REF.hkp_positions)
    for tariff in REF.hkp_tariffs:
        assert set(tariff.prices_cents) == set(REF.hkp_positions)
        assert all(isinstance(c, int) and c > 0 for c in tariff.prices_cents.values())


def test_hkp_price_uses_the_tariff_valid_on_the_service_date():
    assert hkp_price(REF, "032101", D(2025, 12, 31)).version == "HKP-BY-2025-01"
    assert hkp_price(REF, "032101", D(2026, 1, 1)).version == "HKP-BY-2026-01"
    assert hkp_price(REF, "032101", D(2024, 6, 1)) is None
    assert hkp_price(REF, "039999", D(2026, 10, 1)) is None


def test_lk_price_is_points_times_punktwert_rounded_half_up():
    assert points_to_cents(250, Decimal("0.0909")) == 2273  # 22.725 → 22.73, not banker's 22.72
    assert lk_price(REF, "LK01", D(2026, 10, 1)).unit_cents == points_to_cents(
        420, Decimal("0.0947")
    )
    assert lk_price(REF, "LK99", D(2026, 10, 1)) is None


def test_normalize_lk():
    assert normalize_lk("2") == normalize_lk("LK 2") == normalize_lk("lk02") == "LK02"
    assert normalize_lk(" Sonder ") == "Sonder"


def test_claim_builder_prices_each_line_in_cents():
    log = hkp_log(
        visits=[
            visit(D(2026, 10, 1)),
            visit(D(2026, 10, 1), "18:00", quantity=2),
            visit(D(2026, 10, 2), code="039999"),
        ]
    )
    claim = build_claim(log, REF)
    assert [ln.unit_price_cents for ln in claim.lines] == [790, 790, 0]
    assert [ln.amount_cents for ln in claim.lines] == [790, 1580, 0]
    assert claim.total_cents == 2370
    assert claim.tariff_version == "HKP-BY-2026-01"
    assert claim.lines[1].id == "ln-v#1" and claim.lines[1].time.hour == 18
    assert claim.lines[0].visit_log_id == "ln-v"


def test_claim_builder_spanning_tariff_versions_and_sgbxi_codes():
    log = hkp_log(visits=[visit(D(2025, 12, 31)), visit(D(2026, 1, 2))], month="2025-12")
    assert build_claim(log, REF).tariff_version == "HKP-BY-2025-01+HKP-BY-2026-01"
    xi = build_claim(xi_log(visits=[visit(D(2026, 10, 1), code="lk 1")]), REF)
    assert xi.lines[0].code == "LK01" and xi.lines[0].unit_price_cents == 3977


def test_sgbxi_amounts_by_date_and_drafts_only_by_name():
    assert REF.amounts_on(D(2026, 10, 1)).sachleistung_36_cents[3] == 149700
    assert REF.amounts_on(D(2025, 3, 1)).gemeinsamer_jahresbetrag_cents is None
    assert REF.amounts_on(D(2025, 7, 1)).gemeinsamer_jahresbetrag_cents == 353900
    assert REF.amounts_on(D(2027, 6, 1)).version == "SGBXI-2026-01"
    assert REF.amounts_on(D(2027, 6, 1), version="PNOG-2027-01-DRAFT").draft


def test_entlastung_carryover_expires_end_of_june():
    amounts = REF.amounts_on(D(2026, 6, 30))
    assert entlastung_carryover_valid(2025, D(2026, 6, 30), amounts)
    assert not entlastung_carryover_valid(2025, D(2026, 7, 1), amounts)
