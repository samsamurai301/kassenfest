"""Hospital / rehab / care-home stays vs. visits at home (docs/02 §3)."""

from collections.abc import Iterator
from typing import Any, Literal

from kassenfest.rules.engine import Ctx, Hit, Line, doc_evidence, rule
from kassenfest.rules.text import Loc
from kassenfest.schemas.domain import Stay

KIND = {
    "hospital": Loc("Krankenhaus", "hospital"),
    "rehab": Loc("Reha", "rehab"),
    "short_term_care": Loc("Kurzzeitpflege", "short-term care"),
    "hospice": Loc("Hospiz", "hospice"),
    "nursing_home": Loc("Pflegeheim", "nursing home"),
}
STILL_ADMITTED = Loc("noch stationär", "still admitted")


def during(stay: Stay, line: Line, policy: str) -> Literal["yes", "no", "unclear"]:
    """Was the patient away on this visit? Edge days follow `admission_day_policy`.

    timestamp: compare the visit time with admission/discharge time (unknown time → unclear)
    exclude_edge_days: admission and discharge days are never billable
    include_edge_days: admission and discharge days are always billable
    """
    admitted, discharged = stay.admitted_at, stay.discharged_at
    if line.date < admitted.date() or (discharged and line.date > discharged.date()):
        return "no"
    edge = line.date == admitted.date() or (
        discharged is not None and line.date == discharged.date()
    )
    if not edge:
        return "yes"
    if policy == "exclude_edge_days":
        return "yes"
    if policy == "include_edge_days":
        return "no"
    if line.at is None:
        return "unclear"
    return "yes" if admitted <= line.at and (discharged is None or line.at < discharged) else "no"


def stay_hits(ctx: Ctx, params: dict[str, Any], lines: list[Line]) -> Iterator[Hit]:
    for stay in ctx.case.stays:
        if stay.kind not in params["stay_kinds"]:
            continue
        result = {ln.id: during(stay, ln, params["admission_day_policy"]) for ln in lines}
        vars = {
            "kind": KIND[stay.kind],
            "admitted": stay.admitted_at,
            "discharged": stay.discharged_at or STILL_ADMITTED,
        }
        evidence = doc_evidence(stay, "admission_date", "discharge_date")
        for claim, group in ctx.by_claim(lines):
            for state, variant in (("yes", None), ("unclear", "edge_unclear")):
                hit_lines = [ln for ln in group if result[ln.id] == state]
                if hit_lines:
                    yield Hit(
                        key=f"{stay.id}:{claim.id}:{state}",
                        variant=variant,
                        lines=hit_lines,
                        line_field="time" if variant else "date",
                        vars=vars,
                        evidence=evidence,
                    )


@rule("STAY-HKP")
def stay_hkp(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    yield from stay_hits(ctx, params, [ln for ln in ctx.hkp_lines if ln.line.funding == "hkp"])


@rule("STAY-XI-SACH")
def stay_xi_sach(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    lines = [ln for ln in ctx.xi_lines if ln.line.funding == "sachleistung_36"]
    yield from stay_hits(ctx, params, lines)
