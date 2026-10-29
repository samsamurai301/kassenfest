"""The auditor agent: Muse Spark plays the Kasse's Prüfer and attacks every clean bill (AUD-01..03).

It sees what a Kasse auditor would: the bill's lines, the provider's records of the patient,
the paperwork as page images and the provider's reading of each field. It may object only
with the Kasse's rejection codes, a FACT about a field on a page, or an INFO suspicion
(docs/02 §9), through structured output: `tool_choice` can't force a tool call. Every
objection goes to the resolver (`agents.resolver`), which needs no model. A second round
shows the auditor the verdicts; it stops early when nothing new comes back.

A bill is audited once per state of what the auditor sees (`Dossier.fingerprint`): a new
upload that changes the bill, the records or the paperwork makes it due again. Upheld
objections become findings, so the bill turns orange for a human to look at.
"""

import asyncio
import datetime as dt
import hashlib
from collections.abc import Collection
from dataclasses import dataclass, field

from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import col, select

from kassenfest.agents.resolver import RESOLVER_VERSION, Bill, resolve
from kassenfest.db import Audit, session_scope
from kassenfest.llm.client import MetaModelClient
from kassenfest.llm.prompts import AUDIT_SYSTEM, AUDIT_VERSION, DOC_NAMES, as_written, audit_user
from kassenfest.pipeline.month import Month, StoredDoc, claim_findings, evaluate_month
from kassenfest.rules.reference import load_reference
from kassenfest.schemas.common import Extracted, Frequency, Mark
from kassenfest.schemas.domain import Claim
from kassenfest.schemas.findings import (
    AuditorOutput,
    Finding,
    Objection,
    ObjectionVerdict,
    claim_status,
)
from kassenfest.schemas.labels import LABELS, ROWS
from kassenfest.schemas.records import MasterData
from kassenfest.storage import BlobStore
from kassenfest.vision.image import PageImage

MAX_ROUNDS = 2
PAPERWORK = {
    "sgbv": ("muster12", "approval_letter", "visit_log_sgbv", "hospital_letter"),
    "sgbxi": ("visit_log_sgbxi", "hospital_letter"),
}
"""What the auditor is shown per kind of bill, in this order."""
DOMAIN = {"sgbv": "häusliche Krankenpflege (SGB V)", "sgbxi": "Pflegesachleistungen (SGB XI)"}
_ROW_META = {"confidence", "page", "box"}


# --- what the auditor sees ------------------------------------------------------------


@dataclass
class Dossier:
    bill: Bill
    text: str
    pages: list[tuple[StoredDoc, int]]
    """The page images, in the order the text numbers them."""
    fingerprint: str
    refs: dict[str, str] = field(default_factory=dict)
    """What the prompt calls lines and documents → their ids: '#3' → line, 'D2' → document.
    Document ids are random per upload; kept out of the prompt, a replay hits the cache."""


def _eur(cents: int) -> str:
    return f"{cents / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _de(day: dt.date | dt.datetime) -> str:
    return day.strftime("%d.%m.%Y")


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Frequency):
        return f"{value.count}x per {value.per}"
    return as_written(value)


def _shown(item: Extracted | Mark) -> str:
    if isinstance(item, Mark):
        return {"present": "ink present", "absent": "blank"}.get(item.state, item.state)
    if item.status == "present":
        return _value(item.value)
    return "blank" if item.status == "empty" else item.status


def _row(item: BaseModel) -> str:
    values = {k: v for k, v in item if k not in _ROW_META and v not in (None, "", [])}
    return ", ".join(f"{k} {_value(v)}" for k, v in values.items())


def fields_read(
    doc: StoredDoc, entries: str = "each line above names its row", indent: str = "  "
) -> list[str]:
    """Every field as the provider read it, one per line; visit-log entries only counted."""
    ext = doc.extraction
    assert ext is not None
    out = []
    for name in type(ext).model_fields:
        item = getattr(ext, name)
        if name == "entries":
            out.append(f"  entries: {len(item)} rows; {entries}")
        elif isinstance(item, list):
            out += [f"  {name}[{i}] ({ROWS[name]} {i + 1}): {_row(r)}" for i, r in enumerate(item)]
        elif isinstance(item, Extracted | Mark):
            out.append(f"  {name} ({LABELS.get(name, name)}): {_shown(item)}")
    return [line.replace("  ", indent, 1) for line in out]


def _records(bill: Bill) -> list[str]:
    case, patient = bill.case, bill.case.patient
    out = [f"Patient: {patient.name}, born {_de(patient.dob)}, Versicherten-Nr. {patient.kvnr}."]
    for p in patient.insurance:
        kasse = case.payers.get(p.krankenkasse_ik)
        until = f" to {_de(p.valid_to)}" if p.valid_to else ""
        out.append(
            f"Insured with {kasse.name if kasse else '?'} (Krankenkasse IK {p.krankenkasse_ik}, "
            f"Pflegekasse IK {p.pflegekasse_ik}) from {_de(p.valid_from)}{until}."
        )
    out += [f"Pflegegrad {g.grade} from {_de(g.valid_from)}." for g in patient.pflegegrad]
    if patient.deceased_at:
        out.append(f"Died {patient.deceased_at:%d.%m.%Y %H:%M}.")
    staff = "; ".join(f"{s.initials} = {s.name}, {s.qualification}" for s in case.provider.staff)
    out.append(f"Staff (Handzeichen): {staff}.")
    return out


FUNDING = {
    "hkp": "",
    "sachleistung_36": " | §36 Sachleistung",
    "entlastung_45b": " | §45b Entlastung",
}


def _lines(bill: Bill, labels: dict[str, str]) -> list[str]:
    funded = " | funded as" if bill.claim.domain == "sgbxi" else ""
    out = [f"Lines (id | date | time | position | service | amount{funded} | Handzeichen | row):"]
    for ln in bill.claim.lines:
        visit = bill.visit(ln)
        hz = (visit.staff_initials if visit else None) or "none"
        time = ln.time.strftime("%H:%M") if ln.time else "-"
        qty = f" x{ln.quantity}" if ln.quantity > 1 else ""
        out.append(
            f"#{ln.id.rsplit('#', 1)[1]} | {ln.date:%a %d.%m.%Y} | {time} | {ln.code} | "
            f"{labels.get(ln.code, '?')}{qty} | {_eur(ln.amount_cents)}{FUNDING[ln.funding]} | "
            f"{hz} | entries[{ln.entry_index}]"
        )
    return out


def dossier(month: Month, claim: Claim, as_of: dt.date) -> Dossier:
    ref = load_reference()
    order = PAPERWORK[claim.domain]
    docs = sorted(
        (
            d
            for d in month.docs.values()
            if d.patient_id == claim.patient_id
            and d.extraction is not None
            and d.document.doc_type in order
        ),
        key=lambda d: (order.index(d.document.doc_type or ""), d.document.created_at),
    )
    bill = Bill(month, claim, docs, as_of, ref)
    payer = bill.case.payers.get(claim.payer_ik)
    provider = bill.case.provider
    labels = {c: p.label_de for c, p in ref.hkp_positions.items()} | {
        c: lk.label_de for c, lk in ref.leistungskomplexe.items()
    }
    text = [
        f"Bill {claim.id}: {DOMAIN[claim.domain]}, {claim.month}, {len(claim.lines)} lines, "
        f"total {_eur(claim.total_cents)}.",
        f"Payer: {payer.name if payer else '?'} (IK {claim.payer_ik}). "
        f"Provider: {provider.name} (IK {provider.ik}).",
        "",
        "The provider's records:",
        *_records(bill),
        "",
        *_lines(bill, labels),
        "",
        "Paperwork, as page images in this order, with what the provider read on each:",
    ]
    pages: list[tuple[StoredDoc, int]] = []
    refs = {f"#{ln.id.rsplit('#', 1)[1]}": ln.id for ln in claim.lines}
    for k, d in enumerate(docs, 1):
        first = len(pages) + 1
        pages += [(d, p.index) for p in d.pages]
        shown = f"image {first}" if len(d.pages) == 1 else f"images {first}-{len(pages)}"
        text.append(f"Document D{k}, {shown}: {DOC_NAMES[d.document.doc_type or '']}.")
        text += fields_read(d)
        refs[f"D{k}"] = d.document.id
    notes = [f for f in bill.findings if f.severity == "info"]
    text += ["", "The provider's rule check found nothing to object to."]
    text += [f"Note from the rule check: {f.message_en}" for f in notes]
    body = "\n".join(text)
    keys = [d.pages[i].blob_key for d, i in pages]
    ids = [d.document.id for d in docs]  # a new upload of the same pages is due again
    seen = [AUDIT_VERSION, RESOLVER_VERSION, _system(), body, *keys, *ids]
    digest = hashlib.sha256("\n".join(seen).encode())
    return Dossier(bill, body, pages, digest.hexdigest(), refs)


def _system() -> str:
    codes = load_reference().kasse_codes
    return AUDIT_SYSTEM.format(
        codes="\n".join(f"  {c}: {i.label_de} ({i.label_en})" for c, i in codes.items())
    )


# --- the attack -------------------------------------------------------------------------


@dataclass
class Attack:
    rounds: list[list[ObjectionVerdict]]
    repeats: int
    cost_usd: float


def _ours(o: Objection, refs: dict[str, str]) -> Objection:
    """The objection with real line and document ids; unknown refs stay as given."""
    ids = [refs.get(i.strip(), refs.get(f"#{i.strip()}", i)) for i in o.claim_line_ids]
    doc = refs.get((o.document_id or "").strip(), o.document_id)
    return o.model_copy(update={"claim_line_ids": list(dict.fromkeys(ids)), "document_id": doc})


def _key(o: Objection) -> tuple:
    return (o.code, tuple(sorted(o.claim_line_ids)), o.document_id, o.field_path, o.reads)


def _answered(o: Objection, v: ObjectionVerdict) -> tuple[str, str, str]:
    """How the auditor's own objection (its refs, not ids) was answered."""
    where = f" on {o.document_id} {o.field_path} reads '{o.reads}'" if o.code == "FACT" else ""
    lines = f" (lines {', '.join(o.claim_line_ids)})" if o.claim_line_ids else ""
    return f"{o.code}{lines}{where}: {o.statement_en}", v.verdict, v.reason


async def attack(client: MetaModelClient, blobs: BlobStore, d: Dossier) -> Attack:
    images = [PageImage.from_path(blobs.path(doc.pages[i].blob_key)) for doc, i in d.pages]
    rounds: list[list[ObjectionVerdict]] = []
    answered: list[tuple[str, str, str]] = []
    seen: set[tuple] = set()
    repeats, cost = 0, 0.0
    for n in range(1, MAX_ROUNDS + 1):
        result = await client.chat_json(
            prompt_id=f"audit.round{n}.{AUDIT_VERSION}",
            schema=AuditorOutput,
            system=_system(),
            user_text=audit_user(d.text, answered),
            images=images,
            reasoning_effort="high",
        )
        cost += result.meta.cost_usd
        verdicts = []
        for raw in result.parsed.objections:
            o = _ours(raw, d.refs)
            if _key(o) in seen:
                repeats += 1
                continue
            seen.add(_key(o))
            verdicts.append(v := resolve(d.bill, o))
            answered.append(_answered(raw, v))
        if not verdicts:
            break
        rounds.append(verdicts)
    return Attack(rounds, repeats, cost)


# --- which bills, and what came of it ------------------------------------------------------


def latest_audits(engine: Engine) -> dict[str, Audit]:
    """The newest audit of every claim."""
    with session_scope(engine) as s:
        rows = s.exec(select(Audit).order_by(col(Audit.created_at))).all()
    return {a.claim_id: a for a in rows}


def current_audits(month: Month, engine: Engine, as_of: dt.date) -> dict[str, Audit]:
    """Each clean bill's newest audit, where it is of the bill as it is now."""
    latest = latest_audits(engine)
    out = {}
    for claim in month.claims.values():
        audit = latest.get(claim.id)
        if audit is None or not clean(month, claim):
            continue
        if audit.fingerprint == dossier(month, claim, as_of).fingerprint:
            out[claim.id] = audit
    return out


def checked_findings(month: Month, audits: dict[str, Audit]) -> list[Finding]:
    """The rules' findings and the objections the resolver upheld on these audits."""
    upheld = [f for cid, a in audits.items() for f in upheld_findings(month.claims[cid], a)]
    return month.findings + upheld


def clean(month: Month, claim: Claim) -> bool:
    """Green on the rules: the bills the auditor attacks."""
    return claim_status(claim_findings(claim, month.findings)) == "green"


@dataclass
class AuditSummary:
    audited: int = 0
    objections: int = 0
    upheld: int = 0
    failed: int = 0
    cost_usd: float = 0.0


def due(
    month: Month, engine: Engine, as_of: dt.date, claim_ids: Collection[str] | None = None
) -> list[Dossier]:
    """Clean bills with no audit of what the auditor would see now (or only a failed one)."""
    latest = latest_audits(engine)
    out = []
    for claim in month.claims.values():
        if (claim_ids is not None and claim.id not in claim_ids) or not clean(month, claim):
            continue
        d = dossier(month, claim, as_of)
        done = latest.get(claim.id)
        if done is None or done.fingerprint != d.fingerprint or done.error is not None:
            out.append(d)
    return out


async def audit_month(
    client: MetaModelClient,
    engine: Engine,
    blobs: BlobStore,
    records: MasterData,
    *,
    claim_ids: Collection[str] | None = None,
    as_of: dt.date | None = None,
    dossiers: list[Dossier] | None = None,
) -> AuditSummary:
    """Attack every clean bill that is due (or the given dossiers) and store the verdicts."""
    if dossiers is None:
        month = evaluate_month(engine, records, records.month)
        dossiers = due(month, engine, as_of or dt.date.today(), claim_ids)
    results = await asyncio.gather(
        *(attack(client, blobs, d) for d in dossiers), return_exceptions=True
    )
    summary = AuditSummary()
    with session_scope(engine) as s:
        for d, result in zip(dossiers, results, strict=True):
            audit = Audit(
                claim_id=d.bill.claim.id,
                fingerprint=d.fingerprint,
                model=client.settings.muse_model,
            )
            if isinstance(result, BaseException):
                audit.error = f"{type(result).__name__}: {result}"
                summary.failed += 1
            else:
                audit.rounds = [[v.model_dump(mode="json") for v in r] for r in result.rounds]
                audit.repeats, audit.cost_usd = result.repeats, result.cost_usd
                verdicts = [v for r in result.rounds for v in r]
                summary.audited += 1
                summary.objections += len(verdicts)
                summary.upheld += sum(v.verdict == "upheld" for v in verdicts)
                summary.cost_usd += result.cost_usd
            s.add(audit)
    return summary


def verdicts(audit: Audit) -> list[list[ObjectionVerdict]]:
    return [[ObjectionVerdict.model_validate(v) for v in r] for r in audit.rounds]


AUDITOR_SOURCE = "Kasse auditor agent; confirmed by the resolver's rule and record checks"


def upheld_findings(claim: Claim, audit: Audit) -> list[Finding]:
    """Objections the resolver upheld, as findings on the claim: never green, never red
    (a human decides; ADR-3). In German the Kasse's words, in English what the check found."""
    out = []
    amounts = {ln.id: ln.amount_cents for ln in claim.lines}
    for r, round_ in enumerate(verdicts(audit), 1):
        for i, v in enumerate(round_, 1):
            if v.verdict != "upheld":
                continue
            o = v.objection
            lines = [line_id for line_id in o.claim_line_ids if line_id in amounts]
            out.append(
                Finding(
                    id=f"AUDITOR:{claim.id}:{r}.{i}",
                    rule_id="AUDITOR",
                    rule_version=1,
                    severity="warn",
                    patient_id=claim.patient_id,
                    claim_id=claim.id,
                    claim_line_ids=lines,
                    message_de=o.statement,
                    message_en=v.reason,
                    sources=[AUDITOR_SOURCE],
                    evidence=v.evidence,
                    kasse_codes=[o.code] if o.code not in ("FACT", "INFO") else [],  # type: ignore[list-item]
                    amount_at_risk_cents=sum(amounts[x] for x in lines)
                    if lines
                    else claim.total_cents,
                )
            )
    return out
