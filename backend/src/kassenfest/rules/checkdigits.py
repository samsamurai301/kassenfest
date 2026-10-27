"""Check digits for IK, KVNR and LANR (docs/03 §3.1), plus generators for synthetic numbers.

Synthetic numbers with valid check digits can collide with real ones: every
document that carries them must also carry the synthetic watermark.
"""

import random
import re
import string

_IK = re.compile(r"\d{9}")
_KVNR = re.compile(r"[A-Z]\d{9}")
_LANR = re.compile(r"\d{9}")
_BSNR = re.compile(r"\d{9}")


def _digit_sum(n: int) -> int:
    return n // 10 + n % 10


def ik_check_digit(first8: str) -> int:
    """Digits 3–8 weighted 2,1,2,1,2,1, products reduced to their digit sum, sum mod 10."""
    if not re.fullmatch(r"\d{8}", first8):
        raise ValueError(f"IK needs 8 digits before the check digit: {first8!r}")
    weights = (2, 1, 2, 1, 2, 1)
    return sum(_digit_sum(int(d) * w) for d, w in zip(first8[2:], weights, strict=True)) % 10


def is_valid_ik(ik: str) -> bool:
    return bool(_IK.fullmatch(ik)) and ik_check_digit(ik[:8]) == int(ik[8])


def kvnr_check_digit(first9: str) -> int:
    """Letter → 01–26, then 10 digits weighted 1,2,1,2,…, digit-sum products, sum mod 10."""
    if not re.fullmatch(r"[A-Z]\d{8}", first9):
        raise ValueError(f"KVNR needs a letter and 8 digits before the check digit: {first9!r}")
    digits = f"{ord(first9[0]) - ord('A') + 1:02d}{first9[1:]}"
    return sum(_digit_sum(int(d) * (1 + i % 2)) for i, d in enumerate(digits)) % 10


def is_valid_kvnr(kvnr: str) -> bool:
    return bool(_KVNR.fullmatch(kvnr)) and kvnr_check_digit(kvnr[:9]) == int(kvnr[9])


def lanr_check_digit(first6: str) -> int:
    """Digits 1–6 weighted 4,9,4,9,4,9 (plain products), (10 − sum mod 10) mod 10."""
    if not re.fullmatch(r"\d{6}", first6):
        raise ValueError(f"LANR needs 6 digits before the check digit: {first6!r}")
    total = sum(int(d) * w for d, w in zip(first6, (4, 9, 4, 9, 4, 9), strict=True))
    return (10 - total % 10) % 10


def is_valid_lanr(lanr: str) -> bool:
    """9 digits: 6-digit serial, check digit, 2-digit Fachgruppe."""
    return bool(_LANR.fullmatch(lanr)) and lanr_check_digit(lanr[:6]) == int(lanr[6])


def is_valid_bsnr(bsnr: str, kv_region: str | None = None) -> bool:
    """Format only: 9 digits, the first two the KV region (Bayern 71). No check digit."""
    return bool(_BSNR.fullmatch(bsnr)) and (kv_region is None or bsnr.startswith(kv_region))


# --- generators for synthetic data -------------------------------------------------


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


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
