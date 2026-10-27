"""SGB XI rules (ambulant Pflegesachleistung), docs/02 §4."""

import datetime as dt
from collections.abc import Iterator
from typing import Any

from kassenfest.rules.engine import Ctx, Hit, Line, doc_evidence, rule
from kassenfest.rules.hkp import signature_hits
from kassenfest.rules.reference import SgbxiAmounts
from kassenfest.rules.text import Cents
from kassenfest.schemas.domain import Patient


def grade_on(patient: Patient, day: dt.date) -> int | None:
    periods = [p for p in patient.pflegegrad if p.valid_from <= day]
    return max(periods, key=lambda p: p.valid_from).grade if periods else None


def sachleistung_cap(
    patient: Patient, start: dt.date, end: dt.date, amounts: SgbxiAmounts, policy: str
) -> tuple[int, list[int]]:
    """§36 cap for the month and the grades seen in it.

    Pflegegrad changes mid-month are a policy question [L]/[N] (docs/02 §11.3):
    max_in_month (higher grade for the whole month), start_of_month, or prorate
    (daily share of each grade's cap, rounded down).
    """
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    grades = [grade_on(patient, d) or 0 for d in days]

    def cap(grade: int) -> int:
        return amounts.sachleistung_36_cents.get(grade, 0)

    seen = list(dict.fromkeys(grades))
    if policy == "start_of_month":
        return cap(grades[0]), seen
    if policy == "prorate":
        return sum(cap(g) for g in grades) // len(days), seen
    if policy == "max_in_month":
        return cap(max(grades)), seen
    raise ValueError(f"unknown pflegegrad_change_policy {policy!r}")


def entlastung_carryover_valid(earned_year: int, used_on: dt.date, amounts: SgbxiAmounts) -> bool:
    """§45b: unused Entlastungsbetrag can be used until 30 June of the next year."""
    if amounts.entlastung_carryover_until is None:
        return used_on.year == earned_year
    month, day = map(int, amounts.entlastung_carryover_until.split("-"))
    return used_on <= dt.date(earned_year + 1, month, day)


@rule("XI-36-BUDGET")
def budget_36(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    amounts = ctx.ref.amounts_on(ctx.month_start)
    cap, grades = sachleistung_cap(
        ctx.case.patient,
        ctx.month_start,
        ctx.month_end,
        amounts,
        params["pflegegrad_change_policy"],
    )
    for claim, lines in ctx.by_claim(ctx.xi_lines):
        lines = [ln for ln in lines if ln.line.funding == "sachleistung_36"]
        total = sum(ln.amount for ln in lines)
        if total <= cap:
            continue
        # The month's last services are the ones that no longer fit the budget.
        risk: dict[str, int] = {}
        left = total - cap
        for ln in sorted(lines, key=Line.sort_key, reverse=True):
            risk[ln.id] = min(ln.amount, left)
            left -= risk[ln.id]
            if not left:
                break
        yield Hit(
            key=claim.id,
            lines=[ln for ln in lines if ln.id in risk],
            line_risk_cents=risk,
            line_field=None,
            vars={
                "total": Cents(total),
                "cap": Cents(cap),
                "excess": Cents(total - cap),
                "pflegegrad": "→".join(str(g) for g in grades),
                "amounts_version": amounts.version,
            },
            evidence=doc_evidence(ctx.log_of(claim), "pflegegrad"),
        )


@rule("XI-LN-SIGNATURE")
def ln_signature(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    yield from signature_hits(ctx, "sgbxi")
