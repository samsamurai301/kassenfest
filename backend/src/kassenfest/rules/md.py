"""Master-data and eligibility rules (docs/02 §5)."""

import re
from collections.abc import Iterator
from typing import Any

from kassenfest.rules.checkdigits import is_valid_kvnr
from kassenfest.rules.engine import Ctx, Hit, Line, doc_evidence, rule


@rule("MD-KVNR-CHECK")
def kvnr_check(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    kvnr = ctx.case.patient.kvnr
    if is_valid_kvnr(kvnr):
        return
    variant = "check_digit" if re.fullmatch(r"[A-Z]\d{9}", kvnr) else None
    docs = [*ctx.case.prescriptions, *ctx.case.approvals, *ctx.case.stays]
    evidence = [e for obj in docs for e in doc_evidence(obj, "kvnr")]
    claims = list(ctx.by_claim(ctx.lines))
    if not claims:
        yield Hit(key="case", variant=variant, vars={"kvnr": kvnr}, evidence=evidence)
    for claim, lines in claims:
        yield Hit(
            key=claim.id,
            variant=variant,
            lines=lines,
            line_field=None,
            vars={"kvnr": kvnr},
            evidence=doc_evidence(ctx.log_of(claim), "kvnr") + evidence,
        )


@rule("MD-DECEASED")
def deceased(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    died = ctx.case.patient.deceased_at
    if died is None:
        return

    def state(ln: Line) -> str | None:
        if ln.date > died.date():
            return "after"
        if ln.date == died.date():
            if ln.at is None:
                return "unclear"
            return "after" if ln.at > died else None
        return None

    for claim, lines in ctx.by_claim(ctx.lines):
        for kind, variant in (("after", None), ("unclear", "unclear")):
            hit_lines = [ln for ln in lines if state(ln) == kind]
            if hit_lines:
                yield Hit(
                    key=f"{claim.id}:{kind}",
                    variant=variant,
                    lines=hit_lines,
                    line_field="time",
                    vars={"deceased_at": died},
                )
