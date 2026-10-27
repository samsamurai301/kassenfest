"""Rule engine: a registry of pure rule functions plus YAML rule packs chosen by service date.

Rule logic lives in Python (`@rule("HKP-SUBMIT-4WD")`); everything a domain reviewer
might change (severity, day limits, policies, Kasse codes, sources, wording) lives in
`packs/<pack>/*.yaml` (ADR-2). A rule returns `Hit`s; the engine turns them into
`Finding`s with evidence, affected claim lines and the amount at risk (ADR-3).
"""

import calendar as _cal
import datetime as dt
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from kassenfest.rules.calendar import ClosedDayPolicy, WorkingDayCalendar, calendar_for
from kassenfest.rules.reference import HkpPosition, Reference, load_reference
from kassenfest.rules.tariffs import build_claims
from kassenfest.rules.text import Cents, DateList, Lang, render
from kassenfest.schemas.common import DocType, Strict
from kassenfest.schemas.domain import (
    CaseFile,
    Claim,
    ClaimLine,
    Prescription,
    Visit,
    VisitLog,
)
from kassenfest.schemas.findings import (
    ClaimStatus,
    Evidence,
    Finding,
    KasseCode,
    Severity,
    claim_status,
)

PACKS_DIR = Path(__file__).parent / "packs"
SEVERITY_ORDER = {"block": 0, "warn": 1, "info": 2}


# --- rule packs -------------------------------------------------------------------


class Variant(BaseModel):
    """A named situation within one rule, with its own severity, codes or wording."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity | None = None
    kasse_codes: list[KasseCode] | None = None
    message_de: str | None = None
    message_en: str | None = None


class RuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    valid_from: dt.date
    valid_to: dt.date | None = None
    domain: Literal["hkp", "stay", "sgbxi", "md", "doc"]
    severity: Severity
    kasse_codes: list[KasseCode] = []
    defects: list[str] = []
    params: dict[str, Any] = {}
    sources: list[str]
    evidence_required: list[str] = []
    message_de: str
    message_en: str
    variants: dict[str, Variant] = {}

    def active(self, start: dt.date, end: dt.date) -> bool:
        return self.valid_from <= end and (self.valid_to is None or start <= self.valid_to)


class CalendarPolicy(BaseModel):
    heiligabend: ClosedDayPolicy = "working_day"
    silvester: ClosedDayPolicy = "working_day"


class RulePack(BaseModel):
    id: str
    label: str
    valid_from: dt.date
    valid_to: dt.date | None = None
    draft: bool = False
    calendar: CalendarPolicy = CalendarPolicy()
    rules: list[RuleSpec]

    def rule(self, rule_id: str) -> RuleSpec:
        for r in self.rules:
            if r.id == rule_id:
                return r
        raise KeyError(f"rule {rule_id} is not in pack {self.id}")


def load_pack(directory: Path) -> RulePack:
    """pack.yaml holds the manifest; every other *.yaml file is a list of rules."""
    manifest = yaml.safe_load((directory / "pack.yaml").read_text(encoding="utf-8"))
    rules = [
        RuleSpec.model_validate(r)
        for path in sorted(directory.glob("*.yaml"))
        if path.name != "pack.yaml"
        for r in yaml.safe_load(path.read_text(encoding="utf-8"))
    ]
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate rule ids in pack {directory.name}")
    return RulePack.model_validate({**manifest, "rules": rules})


@lru_cache
def available_packs(packs_dir: Path = PACKS_DIR) -> tuple[RulePack, ...]:
    return tuple(load_pack(p) for p in sorted(packs_dir.iterdir()) if (p / "pack.yaml").exists())


def pack_for(day: dt.date, packs_dir: Path = PACKS_DIR, pack_id: str | None = None) -> RulePack:
    """The pack in force on the service date (never today's date); drafts only by id."""
    packs = available_packs(packs_dir)
    if pack_id is not None:
        return next(p for p in packs if p.id == pack_id)
    live = [
        p
        for p in packs
        if not p.draft and p.valid_from <= day and (p.valid_to is None or day <= p.valid_to)
    ]
    if not live:
        raise LookupError(f"no rule pack in force on {day}")
    return max(live, key=lambda p: p.valid_from)


# --- what rules see ---------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    """A claim line together with the visit entry and Leistungsnachweis it came from."""

    claim: Claim
    line: ClaimLine
    log: VisitLog | None
    visit: Visit | None

    @property
    def id(self) -> str:
        return self.line.id

    @property
    def date(self) -> dt.date:
        return self.line.date

    @property
    def time(self) -> dt.time | None:
        return self.line.time

    @property
    def code(self) -> str:
        return self.line.code

    @property
    def amount(self) -> int:
        return self.line.amount_cents

    @property
    def at(self) -> dt.datetime | None:
        return dt.datetime.combine(self.date, self.time) if self.time else None

    def sort_key(self) -> tuple[dt.date, dt.time, str]:
        return (self.date, self.time or dt.time.max, self.id)


# Entry field names differ between the SGB V and SGB XI Leistungsnachweis extraction.
_ENTRY_FIELDS = {
    "sgbv": {
        "date": "date",
        "time": "start_time",
        "code": "position_no",
        "initials": "staff_initials",
    },
    "sgbxi": {"date": "date", "time": "time", "code": "lk_code", "initials": "staff_initials"},
}


def entry_evidence(line: Line, field: str | None = "date") -> Evidence | None:
    """Points at the Leistungsnachweis row (and cell) a claim line came from."""
    doc = (line.visit.document_id if line.visit else None) or (line.log and line.log.document_id)
    if not doc:
        return None
    path = f"entries[{line.line.entry_index}]"
    if field:
        path += f".{_ENTRY_FIELDS[line.claim.domain][field]}"
    return Evidence(document_id=doc, field_path=path)


def doc_evidence(obj: Any, *field_paths: str, note: str | None = None) -> list[Evidence]:
    """Evidence on a domain object's source document; empty if it has none."""
    doc = getattr(obj, "document_id", None) if obj is not None else None
    if not doc:
        return []
    return [Evidence(document_id=doc, field_path=p, note=note) for p in field_paths or (None,)]


@dataclass
class Ctx:
    case: CaseFile
    ref: Reference
    pack: RulePack
    calendar: WorkingDayCalendar
    claims: list[Claim]
    lines: list[Line]

    @cached_property
    def month_start(self) -> dt.date:
        year, month = map(int, self.case.month.split("-"))
        return dt.date(year, month, 1)

    @cached_property
    def month_end(self) -> dt.date:
        start = self.month_start
        return start.replace(day=_cal.monthrange(start.year, start.month)[1])

    @cached_property
    def hkp_lines(self) -> list[Line]:
        return [ln for ln in self.lines if ln.claim.domain == "sgbv"]

    @cached_property
    def xi_lines(self) -> list[Line]:
        return [ln for ln in self.lines if ln.claim.domain == "sgbxi"]

    @cached_property
    def month_prescriptions(self) -> list[Prescription]:
        """Verordnungen whose period overlaps the billing month."""
        return [
            rx
            for rx in self.case.prescriptions
            if rx.period_from <= self.month_end and rx.period_to >= self.month_start
        ]

    def position(self, code: str) -> HkpPosition | None:
        return self.ref.hkp_positions.get(code)

    def log_of(self, claim: Claim) -> VisitLog | None:
        log_ids = {ln.line.visit_log_id for ln in self.lines if ln.claim.id == claim.id}
        return next((v for v in self.case.visit_logs if v.id in log_ids), None)

    def lines_of(self, claim: Claim) -> list[Line]:
        return [ln for ln in self.lines if ln.claim.id == claim.id]

    @staticmethod
    def by_claim(lines: Iterable[Line]) -> Iterator[tuple[Claim, list[Line]]]:
        groups: dict[str, list[Line]] = {}
        for ln in lines:
            groups.setdefault(ln.claim.id, []).append(ln)
        for group in groups.values():
            yield group[0].claim, group


@dataclass
class Hit:
    """One finding as a rule sees it; the engine adds wording, ids and money."""

    key: str
    vars: dict[str, Any] = field(default_factory=dict)
    lines: list[Line] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    variant: str | None = None
    line_field: str | None = "date"
    line_risk_cents: dict[str, int] | None = None
    amount_at_risk_cents: int = 0


@dataclass(frozen=True)
class DocCtx:
    """One extracted document, for rules that need confidences (CaseFile has none)."""

    document_id: str
    doc_type: DocType
    extraction: Strict
    patient_id: str
    on: dt.date


CaseRule = Callable[[Ctx, dict[str, Any]], Iterable[Hit]]
DocumentRule = Callable[[DocCtx, dict[str, Any]], Iterable[Hit]]

CASE_RULES: dict[str, CaseRule] = {}
DOCUMENT_RULES: dict[str, DocumentRule] = {}


def rule(rule_id: str) -> Callable[[CaseRule], CaseRule]:
    def register(fn: CaseRule) -> CaseRule:
        if rule_id in CASE_RULES or rule_id in DOCUMENT_RULES:
            raise ValueError(f"rule {rule_id} registered twice")
        CASE_RULES[rule_id] = fn
        return fn

    return register


def document_rule(rule_id: str) -> Callable[[DocumentRule], DocumentRule]:
    def register(fn: DocumentRule) -> DocumentRule:
        if rule_id in CASE_RULES or rule_id in DOCUMENT_RULES:
            raise ValueError(f"rule {rule_id} registered twice")
        DOCUMENT_RULES[rule_id] = fn
        return fn

    return register


# --- running ----------------------------------------------------------------------


@dataclass
class EngineResult:
    pack_id: str
    claims: list[Claim]
    findings: list[Finding]
    line_risk: dict[str, dict[str, int]] = field(default_factory=dict)
    """finding id → claim line id → cents at risk on that line."""

    def _for_claim(self, claim_id: str | None) -> list[Finding]:
        if claim_id is None:
            return self.findings
        return [f for f in self.findings if f.claim_id in (claim_id, None)]

    def status(self, claim_id: str | None = None) -> ClaimStatus:
        return claim_status(self._for_claim(claim_id))

    def at_risk_cents(
        self, claim_id: str | None = None, severities: Iterable[Severity] = ("block",)
    ) -> int:
        """Money at risk, each line counted once (several rules often hit the same line)."""
        wanted = set(severities)
        per_line: dict[str, int] = {}
        loose = 0
        for f in self._for_claim(claim_id):
            if f.severity not in wanted:
                continue
            risk = self.line_risk.get(f.id, {})
            if not risk:
                loose += f.amount_at_risk_cents
            for line_id, cents in risk.items():
                per_line[line_id] = max(per_line.get(line_id, 0), cents)
        return sum(per_line.values()) + loose


def _lines(case: CaseFile, claims: list[Claim]) -> list[Line]:
    logs = {log.id: log for log in case.visit_logs}
    out: list[Line] = []
    for claim in claims:
        for cl in claim.lines:
            log = logs.get(cl.visit_log_id or "")
            visit = None
            if log is not None:
                visit = next(
                    (
                        v
                        for i, v in enumerate(log.visits)
                        if (v.entry_index if v.entry_index is not None else i) == cl.entry_index
                    ),
                    None,
                )
            out.append(Line(claim, cl, log, visit))
    return out


def _messages(spec: RuleSpec, variant: Variant | None, values: dict[str, Any]) -> dict[Lang, str]:
    de = (variant and variant.message_de) or spec.message_de
    en = (variant and variant.message_en) or spec.message_en
    return {"de": render(de, values, "de"), "en": render(en, values, "en")}


def _finding(spec: RuleSpec, hit: Hit, patient_id: str) -> tuple[Finding, dict[str, int]]:
    variant = spec.variants[hit.variant] if hit.variant else None
    lines = list({ln.id: ln for ln in sorted(hit.lines, key=Line.sort_key)}.values())
    risk = hit.line_risk_cents or {ln.id: ln.amount for ln in lines}
    risk = {ln.id: risk[ln.id] for ln in lines if ln.id in risk}
    amount = sum(risk.values()) if lines else hit.amount_at_risk_cents

    evidence = list(hit.evidence)
    if hit.line_field is not None or not evidence:
        evidence += [e for ln in lines if (e := entry_evidence(ln, hit.line_field))]
    unique = list({(e.document_id, e.page, e.field_path): e for e in evidence}.values())

    claims = {ln.claim.id for ln in lines}
    values = {
        "n_lines": len(lines),
        "dates": DateList(ln.date for ln in lines),
        "amount": Cents(amount),
        **hit.vars,
    }
    text = _messages(spec, variant, values)
    finding = Finding(
        id=f"{spec.id}:{hit.key}",
        rule_id=spec.id,
        rule_version=spec.version,
        severity=(variant and variant.severity) or spec.severity,
        patient_id=patient_id,
        claim_id=claims.pop() if len(claims) == 1 else None,
        claim_line_ids=[ln.id for ln in lines],
        message_de=text["de"],
        message_en=text["en"],
        sources=spec.sources,
        evidence=unique,
        kasse_codes=(
            variant.kasse_codes if variant and variant.kasse_codes is not None else spec.kasse_codes
        ),
        amount_at_risk_cents=amount,
    )
    return finding, risk


def _sorted(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id, f.id))


def run(
    case: CaseFile,
    *,
    ref: Reference | None = None,
    pack: RulePack | None = None,
    claims: list[Claim] | None = None,
) -> EngineResult:
    """Build the month's claims (unless given) and evaluate every active case rule."""
    ref = ref or load_reference()
    year, month = map(int, case.month.split("-"))
    pack = pack or pack_for(dt.date(year, month, 1))
    calendar = calendar_for(
        case.provider.bundesland,
        case.provider.municipality,
        pack.calendar.heiligabend,
        pack.calendar.silvester,
    )
    claims = build_claims(case, ref) if claims is None else claims
    ctx = Ctx(case, ref, pack, calendar, claims, _lines(case, claims))

    findings: list[Finding] = []
    line_risk: dict[str, dict[str, int]] = {}
    for spec in pack.rules:
        fn = CASE_RULES.get(spec.id)
        if fn is None or not spec.active(ctx.month_start, ctx.month_end):
            continue
        for hit in fn(ctx, spec.params):
            finding, risk = _finding(spec, hit, case.patient.id)
            findings.append(finding)
            line_risk[finding.id] = risk
    return EngineResult(pack.id, claims, _sorted(findings), line_risk)


def evaluate(case: CaseFile, **kwargs: Any) -> list[Finding]:
    return run(case, **kwargs).findings


def evaluate_document(
    extraction: Strict,
    *,
    document_id: str,
    on: dt.date,
    patient_id: str = "unlinked",
    pack: RulePack | None = None,
) -> list[Finding]:
    """Rules over one extracted document (e.g. DOC-READABLE needs confidences)."""
    pack = pack or pack_for(on)
    doc_type = getattr(extraction, "doc_type", "other")
    doc = DocCtx(document_id, doc_type, extraction, patient_id, on)
    findings = [
        _finding(spec, hit, patient_id)[0]
        for spec in pack.rules
        if (fn := DOCUMENT_RULES.get(spec.id)) and spec.active(on, on)
        for hit in fn(doc, spec.params)
    ]
    return _sorted(findings)
