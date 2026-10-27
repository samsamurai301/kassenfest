"""Tariff lookup and the claim builder: visit log × tariff valid on the service date → claim.

Pure functions over integer cents. The LLM never produces an amount (ADR-1).
"""

import datetime as dt
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from kassenfest.rules.reference import Reference, valid_on
from kassenfest.schemas.domain import CaseFile, Claim, ClaimLine, Domain, VisitLog


@dataclass(frozen=True)
class Price:
    unit_cents: int
    version: str


def normalize_lk(code: str) -> str:
    """'2', 'LK 2', 'lk02' → 'LK02'; anything else is returned stripped."""
    m = re.fullmatch(r"(?:LK)?\s*0*(\d{1,3})", code.strip(), flags=re.IGNORECASE)
    return f"LK{int(m.group(1)):02d}" if m else code.strip()


def normalize_code(domain: Domain, code: str) -> str:
    return normalize_lk(code) if domain == "sgbxi" else re.sub(r"\s", "", code)


def points_to_cents(points: int, punktwert_eur: Decimal) -> int:
    return int((points * punktwert_eur * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def hkp_price(ref: Reference, code: str, day: dt.date) -> Price | None:
    tariff = valid_on(ref.hkp_tariffs, day)
    if tariff is None or code not in tariff.prices_cents:
        return None
    return Price(tariff.prices_cents[code], tariff.version)


def lk_price(ref: Reference, code: str, day: dt.date) -> Price | None:
    lk = ref.leistungskomplexe.get(normalize_lk(code))
    pw = valid_on(ref.punktwerte, day)
    if lk is None or pw is None:
        return None
    return Price(points_to_cents(lk.points, pw.punktwert_eur), pw.version)


def price(ref: Reference, domain: Domain, code: str, day: dt.date) -> Price | None:
    """Unit price on `day`, or None if the code isn't in the tariff valid that day."""
    return lk_price(ref, code, day) if domain == "sgbxi" else hkp_price(ref, code, day)


def claim_id(log: VisitLog) -> str:
    return f"C-{log.id}"


def line_id(log: VisitLog, index: int) -> str:
    return f"{log.id}#{index}"


def build_claim(log: VisitLog, ref: Reference) -> Claim:
    """One line per visit entry; codes missing from the tariff get price 0 (HKP-POSITION-PRICE)."""
    lines: list[ClaimLine] = []
    versions: list[str] = []
    for i, visit in enumerate(log.visits):
        code = normalize_code(log.domain, visit.code)
        found = price(ref, log.domain, code, visit.date)
        if found and found.version not in versions:
            versions.append(found.version)
        lines.append(
            ClaimLine(
                id=line_id(log, i),
                date=visit.date,
                time=visit.start,
                code=code,
                quantity=visit.quantity,
                unit_price_cents=found.unit_cents if found else 0,
                funding=visit.funding,
                visit_log_id=log.id,
                entry_index=visit.entry_index if visit.entry_index is not None else i,
            )
        )
    return Claim(
        id=claim_id(log),
        patient_id=log.patient_id,
        payer_ik=log.payer_ik,
        month=log.month,
        domain=log.domain,
        lines=lines,
        tariff_version="+".join(versions) or "none",
    )


def build_claims(case: CaseFile, ref: Reference) -> list[Claim]:
    """Claims for the case's billing month; logs for other months are history, not billed here."""
    return [build_claim(log, ref) for log in case.visit_logs if log.month == case.month]
