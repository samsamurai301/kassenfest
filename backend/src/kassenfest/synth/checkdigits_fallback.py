"""Local stand-in for `kassenfest.rules.checkdigits` until the rules-engine branch is on main.

Same function names and signatures, same rules (docs/03 §3.1). Delete this file once
`synth/identifiers.py` imports from `kassenfest.rules.checkdigits` instead.
"""

import random
import string


def _digit_sum(n: int) -> int:
    return n // 10 + n % 10


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def ik_check_digit(first8: str) -> int:
    """Digits 3–8 weighted 2,1,2,1,2,1, products reduced to their digit sum, sum mod 10."""
    weights = (2, 1, 2, 1, 2, 1)
    return sum(_digit_sum(int(d) * w) for d, w in zip(first8[2:], weights, strict=True)) % 10


def is_valid_ik(ik: str) -> bool:
    return len(ik) == 9 and ik.isdigit() and ik_check_digit(ik[:8]) == int(ik[8])


def kvnr_check_digit(first9: str) -> int:
    """Letter → 01–26, then 10 digits weighted 1,2,1,2,…, digit-sum products, sum mod 10."""
    digits = f"{ord(first9[0]) - ord('A') + 1:02d}{first9[1:]}"
    return sum(_digit_sum(int(d) * (1 + i % 2)) for i, d in enumerate(digits)) % 10


def is_valid_kvnr(kvnr: str) -> bool:
    return (
        len(kvnr) == 10
        and kvnr[0] in string.ascii_uppercase
        and kvnr[1:].isdigit()
        and kvnr_check_digit(kvnr[:9]) == int(kvnr[9])
    )


def lanr_check_digit(first6: str) -> int:
    """Digits 1–6 weighted 4,9,4,9,4,9 (plain products), (10 − sum mod 10) mod 10."""
    total = sum(int(d) * w for d, w in zip(first6, (4, 9, 4, 9, 4, 9), strict=True))
    return (10 - total % 10) % 10


def is_valid_lanr(lanr: str) -> bool:
    return len(lanr) == 9 and lanr.isdigit() and lanr_check_digit(lanr[:6]) == int(lanr[6])


def generate_ik(rng: random.Random, klass: str = "46", region: str = "99") -> str:
    """IK class: 10 Krankenkasse, 18 Pflegekasse, 46 Pflegedienst, 50 Sozialstation."""
    first8 = f"{klass}{region}{_digits(rng, 4)}"
    return f"{first8}{ik_check_digit(first8)}"


def generate_kvnr(rng: random.Random) -> str:
    first9 = f"{rng.choice(string.ascii_uppercase)}{rng.choice('123456789')}{_digits(rng, 7)}"
    return f"{first9}{kvnr_check_digit(first9)}"


def generate_lanr(rng: random.Random, fachgruppe: str = "01") -> str:
    first6 = f"{rng.choice('123456789')}{_digits(rng, 5)}"
    return f"{first6}{lanr_check_digit(first6)}{fachgruppe}"


def generate_bsnr(rng: random.Random, kv_region: str = "71") -> str:
    return f"{kv_region}{_digits(rng, 7)}"
