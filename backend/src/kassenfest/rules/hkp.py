"""HKP rules (SGB V §37, HKP-Richtlinie, TA HKP), docs/02 §2."""

import datetime as dt
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from kassenfest.rules.engine import Ctx, Hit, Line, doc_evidence, entry_evidence, rule
from kassenfest.rules.reference import HkpPosition
from kassenfest.rules.tariffs import hkp_price
from kassenfest.rules.text import Cents, Loc, fmt
from kassenfest.schemas.common import Frequency
from kassenfest.schemas.domain import Approval, ApprovedService, PrescribedService, Prescription

PER = {
    "day": Loc("täglich", "per day"),
    "week": Loc("wöchentlich", "per week"),
    "month": Loc("monatlich", "per month"),
}


# --- coverage ---------------------------------------------------------------------


def serves(service: PrescribedService, code: str, position: HkpPosition | None) -> bool:
    """A measure names its position, or covers every position of its category."""
    if service.position_no:
        return service.position_no == code
    return position is not None and position.category == service.category


def covers(rx: Prescription, line: Line, position: HkpPosition | None) -> bool:
    """Period covers the day and a measure covers the service (unknown/ancillary: period only)."""
    if not rx.period_from <= line.date <= rx.period_to:
        return False
    if position is None or position.ancillary:
        return True
    return any(serves(s, line.code, position) for s in rx.services)


def covering(ctx: Ctx, line: Line) -> list[Prescription]:
    pos = ctx.position(line.code)
    return [rx for rx in ctx.case.prescriptions if covers(rx, line, pos)]


def categories(ctx: Ctx, rx: Prescription) -> set[str]:
    cats = {s.category for s in rx.services}
    for s in rx.services:
        if s.position_no and (pos := ctx.position(s.position_no)) and pos.category:
            cats.add(pos.category)
    return cats


def in_categories(ctx: Ctx, line: Line, cats: set[str]) -> bool:
    pos = ctx.position(line.code)
    return pos is None or pos.ancillary or pos.category in cats


def submission_deadline(ctx: Ctx, rx: Prescription, params: dict[str, Any]) -> dt.date:
    return ctx.calendar.add_working_days(rx.issue_date, params["working_days_after_issue"])


def timely(ctx: Ctx, rx: Prescription) -> bool:
    """Reached the Kasse in time for provisional cover (HKP-RL §6(5))."""
    params = ctx.pack.rule("HKP-SUBMIT-4WD").params
    sub = rx.submitted_to_payer_at
    return sub is not None and sub <= submission_deadline(ctx, rx, params)


def excess_units(lines: list[Line], freq: Frequency) -> dict[str, int]:
    """Units beyond `freq` per day / ISO week / month; the latest lines are the excess ones."""
    buckets: dict[tuple[int, int], list[Line]] = defaultdict(list)
    for ln in lines:
        d = ln.date
        key = {"day": (d.toordinal(), 0), "week": d.isocalendar()[:2], "month": (d.year, d.month)}
        buckets[key[freq.per]].append(ln)
    out: dict[str, int] = {}
    for group in buckets.values():
        used = 0
        for ln in sorted(group, key=Line.sort_key):
            over = min(ln.line.quantity, max(0, used + ln.line.quantity - freq.count))
            used += ln.line.quantity
            if over:
                out[ln.id] = over
    return out


def freq_text(freq: Frequency) -> Loc:
    per = PER[freq.per]
    return Loc(f"{freq.count}× {per.de}", f"{freq.count}× {per.en}")


def _risk(lines: list[Line], units: dict[str, int]) -> dict[str, int]:
    return {ln.id: units[ln.id] * ln.line.unit_price_cents for ln in lines if ln.id in units}


# --- rules ------------------------------------------------------------------------


@rule("HKP-RX-REQUIRED")
def rx_required(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    for claim, lines in ctx.by_claim(ctx.hkp_lines):
        groups: dict[str, list[Line]] = defaultdict(list)
        for ln in lines:
            if covering(ctx, ln):
                continue
            in_period = any(
                rx.period_from <= ln.date <= rx.period_to for rx in ctx.case.prescriptions
            )
            ended = any(rx.period_to < ln.date for rx in ctx.case.prescriptions)
            groups["not_prescribed" if in_period else "expired" if ended else "none"].append(ln)
        for variant, group in groups.items():
            first = min(ln.date for ln in group)
            last_rx = max(
                (rx for rx in ctx.case.prescriptions if rx.period_to < first),
                key=lambda rx: rx.period_to,
                default=None,
            )
            evidence = doc_evidence(last_rx, "period_to") if variant == "expired" else []
            yield Hit(
                key=f"{claim.id}:{variant}",
                lines=group,
                variant=None if variant == "none" else variant,
                vars={
                    "period_to": last_rx.period_to if last_rx else None,
                    "codes": sorted({ln.code for ln in group}),
                },
                evidence=evidence,
            )


@rule("HKP-RX-SIGNED")
def rx_signed(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    def complete(rx: Prescription) -> bool:
        return rx.doctor_signed and rx.stamp_present

    for rx in ctx.month_prescriptions:
        missing = [
            (path, label)
            for ok, path, label in (
                (rx.doctor_signed, "doctor_signature", Loc("Unterschrift", "signature")),
                (rx.stamp_present, "practice_stamp", Loc("Vertragsarztstempel", "practice stamp")),
            )
            if not ok
        ]
        if not missing:
            continue
        lines = [
            ln
            for ln in ctx.hkp_lines
            if rx in (cov := covering(ctx, ln)) and not any(complete(o) for o in cov)
        ]
        labels = [label for _, label in missing]
        yield Hit(
            key=rx.id,
            lines=lines,
            vars={
                "issue_date": rx.issue_date,
                "missing": Loc(
                    " und ".join(x.de for x in labels), " and ".join(x.en for x in labels)
                ),
            },
            evidence=doc_evidence(rx, *(path for path, _ in missing)),
        )


@rule("HKP-ERST-14D")
def erst_14d(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    max_days = params["max_days"]
    for rx in ctx.month_prescriptions:
        days = (rx.period_to - rx.period_from).days + 1
        if rx.kind != "erst" or days <= max_days:
            continue
        limit_end = rx.period_from + dt.timedelta(days=max_days - 1)
        lines = [
            ln
            for ln in ctx.hkp_lines
            if ln.date > limit_end and rx in (cov := covering(ctx, ln)) and len(cov) == 1
        ]
        yield Hit(
            key=rx.id,
            lines=lines,
            vars={
                "period_from": rx.period_from,
                "period_to": rx.period_to,
                "days": days,
                "max_days": max_days,
                "limit_end": limit_end,
            },
            evidence=doc_evidence(rx, "period_from", "period_to"),
        )


def _successor(ctx: Ctx, rx: Prescription) -> Prescription | None:
    cats = categories(ctx, rx)
    later = [
        p
        for p in ctx.case.prescriptions
        if p.id != rx.id and p.period_from > rx.period_from and categories(ctx, p) & cats
    ]
    return min(later, key=lambda p: p.period_from, default=None)


@rule("HKP-FOLGE-WINDOW")
def folge_window(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    lookahead = dt.timedelta(days=params["proactive_lookahead_days"])
    for rx in ctx.case.prescriptions:
        if not ctx.month_start - dt.timedelta(days=1) <= rx.period_to <= ctx.month_end + lookahead:
            continue
        window = ctx.calendar.last_working_days(rx.period_to, params["window_working_days"])
        cats = categories(ctx, rx)
        succ = _successor(ctx, rx)
        until = succ.period_from if succ else ctx.month_end + dt.timedelta(days=1)
        gap = [
            ln
            for ln in ctx.hkp_lines
            if rx.period_to < ln.date < until
            and in_categories(ctx, ln, cats)
            and not covering(ctx, ln)
        ]
        vars = {"period_to": rx.period_to, "window_start": window[0], "window_end": rx.period_to}
        evidence = doc_evidence(rx, "period_to")

        if succ is None:
            if gap:
                yield Hit(key=rx.id, variant="missing_gap", lines=gap, vars=vars, evidence=evidence)
            elif rx.period_to >= ctx.month_end:
                yield Hit(key=rx.id, variant="due", vars=vars, evidence=evidence)
            continue
        if succ.kind != "folge":
            continue
        vars["issue_date"] = succ.issue_date
        evidence += doc_evidence(succ, "issue_date")
        if succ.issue_date < window[0]:
            yield Hit(key=rx.id, variant="early", vars=vars, evidence=evidence)
        elif succ.issue_date > rx.period_to:
            if gap:
                yield Hit(key=rx.id, variant="late_gap", lines=gap, vars=vars, evidence=evidence)
            else:
                before = [
                    ln
                    for ln in ctx.hkp_lines
                    if rx.period_to < ln.date < succ.issue_date and succ in covering(ctx, ln)
                ]
                yield Hit(key=rx.id, variant="late", lines=before, vars=vars, evidence=evidence)


def _approval_for(ctx: Ctx, rx: Prescription) -> Approval | None:
    linked = [a for a in ctx.case.approvals if a.prescription_id == rx.id]
    overlapping = [
        a
        for a in ctx.case.approvals
        if a.period_from <= rx.period_to and a.period_to >= rx.period_from
    ]
    return min(linked or overlapping, key=lambda a: a.letter_date, default=None)


@rule("HKP-SUBMIT-4WD")
def submit_4wd(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    for rx in ctx.month_prescriptions:
        deadline = submission_deadline(ctx, rx, params)
        issued_now = ctx.month_start <= rx.issue_date <= ctx.month_end
        skipped = [
            f"{d:%d.%m.} {name}"
            for i in range(1, (deadline - rx.issue_date).days + 1)
            if (name := ctx.calendar.holiday_name(d := rx.issue_date + dt.timedelta(days=i)))
        ]
        vars = {
            "issue_date": rx.issue_date,
            "deadline": deadline,
            "n": params["working_days_after_issue"],
            "submitted": rx.submitted_to_payer_at,
            "holidays": skipped or "–",
        }
        sub = rx.submitted_to_payer_at
        if sub is None:
            if issued_now:
                yield Hit(
                    key=rx.id,
                    variant="no_proof",
                    vars=vars,
                    evidence=doc_evidence(rx, "issue_date"),
                )
            continue
        if sub <= deadline:
            continue
        covered = [ln for ln in ctx.hkp_lines if rx in covering(ctx, ln)]
        approval = _approval_for(ctx, rx)
        if approval is not None and approval.decision != "rejected":
            lines = [ln for ln in covered if ln.date < approval.letter_date]
            vars["approval_date"] = approval.letter_date
            variant = None
        else:
            lines, variant = covered, "no_approval"
        if not lines and not issued_now:
            continue
        note = f"submitted {sub.isoformat()}, deadline {deadline.isoformat()}"
        yield Hit(
            key=rx.id,
            variant=variant,
            lines=lines,
            vars=vars,
            evidence=doc_evidence(rx, "issue_date", note=note)
            + doc_evidence(approval, "letter_date"),
        )


def _approvals_on(ctx: Ctx, day: dt.date) -> list[Approval]:
    return [a for a in ctx.case.approvals if a.period_from <= day <= a.period_to]


@rule("HKP-APPROVAL-EXISTS")
def approval_exists(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    for claim, lines in ctx.by_claim(ctx.hkp_lines):
        groups: dict[str, list[Line]] = defaultdict(list)
        cited: dict[str, list[Approval]] = defaultdict(list)
        for ln in lines:
            rxs = covering(ctx, ln)
            if not rxs:
                continue  # HKP-RX-REQUIRED owns lines without a Verordnung
            approvals = _approvals_on(ctx, ln.date)
            valid = [a for a in approvals if a.decision != "rejected"]
            if valid:
                if not any(a.approval_ref.strip() for a in valid):
                    groups["no_ref"].append(ln)
                    cited["no_ref"] += valid
            elif approvals:
                groups["rejected"].append(ln)
                cited["rejected"] += approvals
            else:
                groups["pending" if any(timely(ctx, rx) for rx in rxs) else "missing"].append(ln)
        for kind, group in groups.items():
            approvals = list({a.id: a for a in cited[kind]}.values())
            field = "approval_ref" if kind == "no_ref" else "decision"
            yield Hit(
                key=f"{claim.id}:{kind}",
                variant=None if kind == "missing" else kind,
                lines=group,
                evidence=[e for a in approvals for e in doc_evidence(a, field)],
            )


def _approved_item(ctx: Ctx, line: Line) -> ApprovedService | None:
    for a in _approvals_on(ctx, line.date):
        if a.decision == "rejected":
            continue
        for item in a.approved:
            if item.position_no == line.code and item.valid_from <= line.date <= item.valid_to:
                return item
    return None


@rule("HKP-APPROVAL-SCOPE")
def approval_scope(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    for claim, lines in ctx.by_claim(ctx.hkp_lines):
        not_approved: list[Line] = []
        by_item: dict[int, tuple[ApprovedService, list[Line]]] = {}
        for ln in lines:
            pos = ctx.position(ln.code)
            if (pos and pos.ancillary) or not any(
                a.decision != "rejected" for a in _approvals_on(ctx, ln.date)
            ):
                continue
            item = _approved_item(ctx, ln)
            if item is None:
                not_approved.append(ln)
            elif item.frequency:
                by_item.setdefault(id(item), (item, []))[1].append(ln)
        approvals = {a.id: a for ln in lines for a in _approvals_on(ctx, ln.date)}.values()
        evidence = [e for a in approvals for e in doc_evidence(a, "approved_items")]
        if not_approved:
            yield Hit(
                key=f"{claim.id}:not_approved",
                variant="not_approved",
                lines=not_approved,
                vars={"codes": sorted({ln.code for ln in not_approved})},
                evidence=evidence,
            )
        for item, group in by_item.values():
            assert item.frequency is not None
            units = excess_units(group, item.frequency)
            if not units:
                continue
            over = [ln for ln in group if ln.id in units]
            yield Hit(
                key=f"{claim.id}:{item.position_no}:{item.valid_from}",
                variant="excess",
                lines=over,
                line_risk_cents=_risk(over, units),
                vars={
                    "code": item.position_no,
                    "approved": freq_text(item.frequency),
                    "excess_units": sum(units.values()),
                },
                evidence=evidence,
            )


@rule("HKP-FREQ-RX")
def freq_rx(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    for rx in ctx.month_prescriptions:
        if rx.blank:
            continue  # Blankoverordnung: the nurse sets the frequency (HKP-RL §5a)
        for i, service in enumerate(rx.services):
            if service.frequency is None:
                continue
            matched = []
            for ln in ctx.hkp_lines:
                pos = ctx.position(ln.code)
                if (
                    rx.period_from <= ln.date <= rx.period_to
                    and pos is not None
                    and not pos.ancillary
                    and serves(service, ln.code, pos)
                ):
                    matched.append(ln)
            units = excess_units(matched, service.frequency)
            if not units:
                continue
            over = [ln for ln in matched if ln.id in units]
            yield Hit(
                key=f"{rx.id}:{i}",
                lines=over,
                line_risk_cents=_risk(over, units),
                vars={
                    "service": service.position_no or service.category,
                    "prescribed": freq_text(service.frequency),
                    "excess_units": sum(units.values()),
                    "issue_date": rx.issue_date,
                },
                evidence=doc_evidence(rx, f"measures[{i}].frequency"),
            )


REASONS = {
    1: Loc("verstorben", "deceased"),
    2: Loc("stationär", "inpatient"),
    3: Loc("körperlich/geistig nicht möglich", "physically or mentally unable"),
    4: Loc("sonstiges", "other"),
}


def signature_hits(ctx: Ctx, domain: str) -> Iterator[Hit]:
    """Patient signature on the Leistungsnachweis, once per month (shared with XI)."""
    for claim in ctx.claims:
        log = ctx.log_of(claim)
        if claim.domain != domain or log is None or log.patient_signed:
            continue
        reason = log.missing_signature_reason
        fields = ["patient_signature", *(["missing_signature_reason"] if reason else [])]
        yield Hit(
            key=claim.id,
            variant="reason" if reason else None,
            lines=ctx.lines_of(claim),
            line_field=None,
            vars={"month": log.month, "reason": REASONS[reason] if reason else None},
            evidence=doc_evidence(log, *fields),
        )


@rule("HKP-LN-SIGNATURE")
def ln_signature(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    yield from signature_hits(ctx, "sgbv")


@rule("HKP-STAFF-INITIALS")
def staff_initials(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    for claim, lines in ctx.by_claim(ctx.hkp_lines):
        missing = [
            ln
            for ln in lines
            if ln.visit is not None and not (ln.visit.staff_initials or ln.visit.employee_no)
        ]
        if missing:
            yield Hit(key=claim.id, lines=missing, line_field="initials")


@rule("HKP-DUPLICATE")
def duplicate(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    prior_lines = [
        (pc, pl) for pc in ctx.case.prior_claims if pc.domain == "sgbv" for pl in pc.lines
    ]
    for claim, lines in ctx.by_claim(ctx.hkp_lines):
        seen: dict[tuple, Line] = {}
        within: list[Line] = []
        evidence = []
        for ln in sorted(lines, key=Line.sort_key):
            if ln.time is None:
                continue  # no time → can't tell two visits from one duplicate (HKP-302-FIELDS)
            key = (ln.date, ln.time, ln.code)
            if key in seen:
                within.append(ln)
                evidence.append(entry_evidence(seen[key], "time"))
            else:
                seen[key] = ln
        if within:
            yield Hit(
                key=f"{claim.id}:within",
                lines=within,
                line_field="time",
                evidence=[e for e in evidence if e],
            )

        sent: list[Line] = []
        prior_ids: set[str] = set()
        for ln in lines:
            if ln in within:
                continue
            for pc, pl in prior_lines:
                same_day = (pl.date, pl.code) == (ln.date, ln.code)
                if same_day and (ln.time is None or pl.time is None or pl.time == ln.time):
                    sent.append(ln)
                    prior_ids.add(pc.id)
                    break
        if sent:
            yield Hit(
                key=f"{claim.id}:prior",
                variant="prior",
                lines=sent,
                line_field="time",
                vars={"prior_claims": sorted(prior_ids)},
            )


@rule("HKP-POSITION-PRICE")
def position_price(ctx: Ctx, params: dict[str, Any]) -> Iterator[Hit]:
    for claim, lines in ctx.by_claim(ctx.hkp_lines):
        unknown: list[Line] = []
        wrong: dict[str, int] = {}
        details: list[Loc] = []
        for ln in lines:
            price = hkp_price(ctx.ref, ln.code, ln.date)
            if price is None:
                unknown.append(ln)
            elif price.unit_cents != ln.line.unit_price_cents:
                wrong[ln.id] = abs(ln.line.unit_price_cents - price.unit_cents) * ln.line.quantity
                billed, tariff = Cents(ln.line.unit_price_cents), Cents(price.unit_cents)
                de = f"{fmt(billed, 'de')} statt {fmt(tariff, 'de')}"
                en = f"{fmt(billed, 'en')} instead of {fmt(tariff, 'en')}"
                details.append(
                    Loc(
                        f"{ln.code} am {ln.date:%d.%m.}: {de}",
                        f"{ln.code} on {ln.date:%d %b}: {en}",
                    )
                )
        if unknown:
            yield Hit(
                key=f"{claim.id}:unknown",
                variant="unknown",
                lines=unknown,
                line_field="code",
                vars={"codes": sorted({ln.code for ln in unknown})},
            )
        if wrong:
            yield Hit(
                key=f"{claim.id}:price",
                variant="price",
                lines=[ln for ln in lines if ln.id in wrong],
                line_field="code",
                line_risk_cents=wrong,
                vars={"details": details, "tariff": claim.tariff_version},
            )
