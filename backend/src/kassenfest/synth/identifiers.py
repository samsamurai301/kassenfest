"""Every IK, KVNR, LANR and BSNR in the synthetic world comes from here.

Check digits follow docs/03 §3.1 and come from `kassenfest.rules.checkdigits`, the same
module the rules engine validates with. This module adds the synth-only numbers.

Synthetic numbers with valid check digits can collide with real ones: every page that
carries them also carries the synthetic watermark.
"""

import random
import string

from kassenfest.rules.checkdigits import (
    generate_bsnr,
    generate_ik,
    generate_kvnr,
    generate_lanr,
    is_valid_ik,
    is_valid_kvnr,
    is_valid_lanr,
)

__all__ = [
    "corrupt_kvnr",
    "generate_bsnr",
    "generate_employee_no",
    "generate_ik",
    "generate_kvnr",
    "generate_lanr",
    "generate_location_code",
    "is_valid_ik",
    "is_valid_kvnr",
    "is_valid_lanr",
]


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def generate_location_code(rng: random.Random) -> str:
    """Krankenhaus-Standortkennzeichen: 77 + 7 digits, used instead of a BSNR."""
    return f"77{_digits(rng, 7)}"


def generate_employee_no(rng: random.Random) -> str:
    """Beschäftigtennummer (LBNR): 9 digits, never the TA HKP placeholders 99999999x."""
    return f"{rng.choice('12345678')}{_digits(rng, 8)}"


def corrupt_kvnr(kvnr: str, rng: random.Random) -> str:
    """The same KVNR with a wrong check digit, as if one digit was mistyped (defect D16)."""
    wrong = (int(kvnr[9]) + rng.randint(1, 9)) % 10
    return f"{kvnr[:9]}{wrong}"
