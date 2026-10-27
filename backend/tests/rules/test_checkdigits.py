"""Check-digit test vectors from docs/03 §3.1."""

import random

import pytest

from kassenfest.rules.checkdigits import (
    generate_bsnr,
    generate_ik,
    generate_kvnr,
    generate_lanr,
    ik_check_digit,
    is_valid_bsnr,
    is_valid_ik,
    is_valid_kvnr,
    is_valid_lanr,
    kvnr_check_digit,
    lanr_check_digit,
)


def test_worked_examples():
    assert ik_check_digit("26032682") == 2
    assert kvnr_check_digit("A12345678") == 0
    assert lanr_check_digit("123456") == 6


@pytest.mark.parametrize(
    ("check", "valid", "invalid"),
    [
        (is_valid_ik, ["260326822", "108310400"], ["260326823", "26032682", "2603268a2"]),
        (is_valid_kvnr, ["A123456780"], ["A123456781", "a123456780", "A12345678", "1123456780"]),
        (is_valid_lanr, ["123456601", "123456699"], ["123457601", "12345660", "1234566010"]),
    ],
)
def test_validation(check, valid, invalid):
    assert all(check(v) for v in valid)
    assert not any(check(v) for v in invalid)


def test_bsnr_is_format_only():
    assert is_valid_bsnr("711234500", kv_region="71")
    assert not is_valid_bsnr("721234500", kv_region="71")
    assert not is_valid_bsnr("71123450")


def test_check_digit_rejects_bad_input():
    with pytest.raises(ValueError):
        ik_check_digit("1234567")
    with pytest.raises(ValueError):
        kvnr_check_digit("123456789")


def test_generators_make_valid_numbers():
    rng = random.Random(42)
    for _ in range(200):
        assert is_valid_ik(generate_ik(rng, klass="46"))
        assert is_valid_kvnr(generate_kvnr(rng))
        lanr = generate_lanr(rng, fachgruppe="01")
        assert is_valid_lanr(lanr) and lanr.endswith("01")
        assert is_valid_bsnr(generate_bsnr(rng), kv_region="71")


def test_generators_are_deterministic_per_seed():
    assert generate_kvnr(random.Random(7)) == generate_kvnr(random.Random(7))
    assert generate_ik(random.Random(7), klass="10").startswith("1099")
