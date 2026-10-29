"""AUD-05: how many subtle defects the auditor agent catches, and what it invents.

The `audit` set (`synth.subtle`) seeds one defect that no rule checks into each of 20
patient-months and leaves 5 clean. Every page is read perfectly (`synth.oracle`), so nothing
the auditor gets wrong is a reading error. Every bill is green on the rules, so the auditor
attacks all of them, the resolver answers each objection, and each objection is scored:

- a catch names the bill's seeded defect: one of the Kasse codes for it, a FACT on one of its
  fields, or words that describe it (how an INFO suspicion says it);
- everything else is unseeded, on a clean bill or beside the seeded defect. Its verdict says
  where it would have gone: upheld onto the board, noted for a human, dismissed.

The word patterns are generous on purpose; `kassenfest eval-auditor` prints every objection
next to its score, to be read by a person.
"""

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import Engine

from kassenfest.agents.auditor import audit_month, clean, due, latest_audits, verdicts
from kassenfest.config import REPO_ROOT, Settings
from kassenfest.db import Document, Extraction, Page, create_db, session_scope
from kassenfest.llm.client import MetaModelClient
from kassenfest.pipeline.month import evaluate_month
from kassenfest.schemas.findings import Objection
from kassenfest.schemas.ground_truth import GroundTruth
from kassenfest.schemas.records import MasterData
from kassenfest.storage import BlobStore
from kassenfest.synth.generate import OUT_ROOT, SetManifest
from kassenfest.synth.oracle import perfect_extraction
from kassenfest.synth.subtle import SUBTLE

OUT_DIR = REPO_ROOT / "var" / "eval" / "audit"


@dataclass(frozen=True)
class Catch:
    codes: frozenset[str]
    fields: str
    """Regex on a FACT's field_path ('' = none counts)."""
    words: str
    """Regex on the statement, German and English."""

    def matches(self, o: Objection) -> bool:
        if o.code in self.codes:
            return True
        if o.code == "FACT" and self.fields and re.search(self.fields, o.field_path or ""):
            return True
        return bool(re.search(self.words, f"{o.statement} {o.statement_en}", re.IGNORECASE))


def _catch(codes: set[str], fields: str, words: str) -> Catch:
    return Catch(frozenset(codes), fields, words)


CATCH: dict[str, Catch] = {
    "S01": _catch(
        {"42004"},
        r"approval_ref",
        r"Genehmigungskennzeichen|approval (number|ref)|Aktenzeichen",
    ),
    "S02": _catch(
        {"41002"},
        r"^kvnr$",
        r"Versicherten-?(nr|nummer)|insurance number|KVNR",
    ),
    "S03": _catch({"41002"}, r"patient_dob", r"Geburtsdatum|date of birth|\bborn\b"),
    "S04": _catch(
        set(),
        r"issue_date|period_from",
        r"rückwirkend|retroactiv|(issued|ausgestellt).{0,40}(after|nach).{0,30}(start|begin|Beginn)"
        r"|before (it was )?issued|vor (der )?Ausstellung",
    ),
    "S05": _catch(
        {"42002"},
        r"measures\[\d+\]",
        r"Präparat|Medikamente? .{0,40}(nicht|ohne|fehl)|drugs?|medicines? .{0,40}(not|without)"
        r"|medications? .{0,40}(not|without|missing)",
    ),
    "S06": _catch(
        set(),
        r"staff_initials",
        r"(cannot|can't|could not) be (attributed|assigned|matched)|not (on|in) the staff"
        r"|unknown|unbekannt|nicht .{0,40}(zugeordnet|zuzuordnen|zuordnen)",
    ),
    "S07": _catch(
        set(),
        r"patient_signature_date",
        r"(signed|unterschrieben|unterzeichnet|signature|Unterschrift).{0,80}"
        r"(before|vor|although|obwohl|after that|danach)",
    ),
    "S08": _catch(
        set(),
        "",
        r"(gleiche|identische|selbe|dieselbe).{0,30}(Uhrzeit|Zeit|Minute)"
        r"|same (time|minute)|identical (times?|minute)|to the minute|every day at",
    ),
    "S09": _catch(
        set(),
        r"entries\[\d+\]\.(start_)?time",
        r"Minuten|minutes? (apart|later|after)|Abstand|kurz (nach|hintereinander)|interval",
    ),
    "S10": _catch(
        set(),
        "",
        r"Handschrift|Schriftbild|Stift|Kugelschreiber|\bpen\b|\bink\b|handwriting"
        r"|one (person|hand)",
    ),
}
assert set(CATCH) == set(SUBTLE)


# --- the month, read perfectly -----------------------------------------------------------------


def store_set(engine: Engine, blobs: BlobStore, set_dir: Path) -> int:
    """Every document of a synthetic set, as if the pipeline had read it perfectly."""
    manifest = SetManifest.model_validate_json((set_dir / "manifest.json").read_text())
    with session_scope(engine) as s:
        for entry in manifest.documents:
            gt = GroundTruth.model_validate_json((set_dir / entry.truth).read_text())
            s.add(
                Document(
                    id=gt.doc_id,
                    batch_id="bat-eval",
                    filename=Path(entry.image).name,
                    source_sha256=gt.doc_id,
                    source_key=gt.doc_id,
                    doc_type=gt.doc_type,
                    status="done",
                )
            )
            for page in gt.pages:
                image = (set_dir / entry.truth).parent / page.image
                key = blobs.put(image.read_bytes(), image.suffix.lstrip("."))
                s.add(
                    Page(
                        document_id=gt.doc_id,
                        index=page.index,
                        blob_key=key,
                        width=page.width,
                        height=page.height,
                    )
                )
            s.add(
                Extraction(
                    document_id=gt.doc_id,
                    schema_name=gt.doc_type,
                    prompt_id="oracle",
                    reasoning_effort="none",
                    data=perfect_extraction(gt).model_dump(mode="json"),
                    cache_key="-",
                    cost_usd=0,
                    latency_ms=0,
                )
            )
    return len(manifest.documents)


# --- scoring --------------------------------------------------------------------------------


@dataclass
class Scored:
    code: str
    verdict: str
    caught: bool
    statement_en: str
    reason: str


@dataclass
class Bill:
    claim_id: str
    patient_id: str
    defect: str | None
    variants: list[str]
    objections: list[Scored] = field(default_factory=list)
    error: str | None = None

    @property
    def caught(self) -> bool:
        return any(o.caught for o in self.objections)

    @property
    def reached(self) -> bool:
        """A catch the resolver passed on: onto the board or to a human."""
        return any(o.caught and o.verdict in ("upheld", "noted") for o in self.objections)


@dataclass
class Report:
    bills: list[Bill]
    not_green: dict[str, list[str]]
    """Seeded bills the rules flagged: the defect is not subtle there, so not scored."""
    cost_usd: float

    def seeded(self) -> list[Bill]:
        return [b for b in self.bills if b.defect]

    def unseeded(self) -> list[Scored]:
        return [o for b in self.bills for o in b.objections if not o.caught]


def score(month, engine: Engine, manifest: SetManifest) -> list[Bill]:
    audits = latest_audits(engine)
    variants = {d.doc_id: d.variant for d in manifest.documents}
    bills = []
    for case in manifest.cases:
        subtle = [d.id for d in case.defects if d.id in SUBTLE]
        for claim in (c for c in month.claims.values() if c.patient_id == case.patient_id):
            audit = audits.get(claim.id)
            bill = Bill(
                claim_id=claim.id,
                patient_id=case.patient_id,
                defect=subtle[0] if subtle else None,
                variants=[variants[d] for d in case.documents],
                error=audit.error if audit else "not audited",
            )
            catch = CATCH.get(bill.defect or "")
            for round_ in verdicts(audit) if audit else []:
                for v in round_:
                    o = v.objection
                    bill.objections.append(
                        Scored(
                            o.code,
                            v.verdict,
                            bool(catch and catch.matches(o)),
                            o.statement_en,
                            v.reason,
                        )
                    )
            bills.append(bill)
    return bills


async def run(settings: Settings, set_dir: Path = OUT_ROOT / "audit") -> Report:
    """Read the set perfectly into a fresh database, attack every bill, score the objections."""
    records = MasterData.model_validate_json((set_dir / "master_data.json").read_text())
    manifest = SetManifest.model_validate_json((set_dir / "manifest.json").read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = OUT_DIR / "kassenfest.db"
    db.unlink(missing_ok=True)
    engine, blobs = create_db(db), BlobStore(OUT_DIR / "blobs")
    store_set(engine, blobs, set_dir)

    month = evaluate_month(engine, records, records.month)
    not_green = {
        c.id: sorted(
            {f.rule_id for f in month.findings if f.claim_id == c.id and f.severity != "info"}
        )
        for c in month.claims.values()
        if not clean(month, c)
    }
    dossiers = due(month, engine, settings.as_of())
    summary = await audit_month(
        MetaModelClient(settings), engine, blobs, records, dossiers=dossiers
    )
    bills = [b for b in score(month, engine, manifest) if b.claim_id not in not_green]
    report = Report(bills, not_green, summary.cost_usd)
    (OUT_DIR / "report.json").write_text(json.dumps(asdict(report), indent=1, ensure_ascii=False))
    return report


# --- the report -----------------------------------------------------------------------------


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "0/0"


def markdown(r: Report) -> str:
    seeded = r.seeded()
    controls = [b for b in r.bills if not b.defect]
    unseeded = r.unseeded()
    verdicts = Counter(o.verdict for o in unseeded)
    lines = [
        f"- **Caught** (an objection names the seeded defect): "
        f"{_pct(sum(b.caught for b in seeded), len(seeded))}",
        f"- **Reached a person** (that objection upheld or noted by the resolver): "
        f"{_pct(sum(b.reached for b in seeded), len(seeded))}",
        f"- **Unseeded objections**: {len(unseeded)} on {len(r.bills)} bills "
        f"({sum(len(b.objections) for b in controls)} on the {len(controls)} clean controls): "
        f"{verdicts['upheld']} upheld, {verdicts['noted']} noted, "
        f"{verdicts['dismissed']} dismissed",
        f"- Cost of this run: ${r.cost_usd:.2f}",
        "",
        "| Defect | Bill | Caught by | Verdict | Unseeded beside it |",
        "|---|---|---|---|---|",
    ]
    for b in sorted(seeded, key=lambda b: (b.defect or "", b.claim_id)):
        hits = [o for o in b.objections if o.caught]
        others = [o for o in b.objections if not o.caught]
        lines.append(
            f"| {b.defect} {SUBTLE[b.defect or '']} | {b.claim_id} | "
            f"{', '.join(o.code for o in hits) or '**missed**'} | "
            f"{', '.join(o.verdict for o in hits) or '–'} | "
            f"{', '.join(f'{o.code} {o.verdict}' for o in others) or '–'} |"
        )
    for b in controls:
        lines.append(
            f"| clean | {b.claim_id} | – | – | "
            f"{', '.join(f'{o.code} {o.verdict}' for o in b.objections) or '–'} |"
        )
    if r.not_green:
        lines += ["", "Not scored, the rules flagged them:"]
        lines += [f"- {c}: {', '.join(rules)}" for c, rules in r.not_green.items()]
    return "\n".join(lines)


def details(r: Report) -> str:
    """Every objection with its score, for a person to check the word patterns."""
    out = []
    for b in r.bills:
        out.append(f"\n{b.claim_id} ({b.defect or 'clean'}){f': {b.error}' if b.error else ''}")
        for o in b.objections:
            mark = "CATCH" if o.caught else "     "
            out.append(f"  {mark} {o.code:<5} {o.verdict:<9} {o.statement_en}")
            out.append(f"  {'':<22}{o.reason}")
    return "\n".join(out)
