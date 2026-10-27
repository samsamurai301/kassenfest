# Rules engine

Deterministic checks of one patient-month (`schemas.domain.CaseFile`) before the bill goes
to the Kasse. The LLM reads documents; this package decides and computes every amount
(ADR-1). Rule logic is Python; everything a domain reviewer may change (severity, day
limits, policies, Kasse codes, sources, wording) is YAML (ADR-2).

> **Not legal advice.** Sources are cited per rule so a domain reviewer can check them.
> All prices are **illustrative**; all payer IKs are **fake** (`synthetic: true`).

## Use

```python
from kassenfest.rules import evaluate, evaluate_document, run

findings = evaluate(case)  # list[Finding], block → warn → info
result = run(case)  # EngineResult: claims, findings, pack_id
result.status("C-ln-v")  # green | orange | red for one claim
result.at_risk_cents()  # € at risk over block findings, each line counted once

# DOC-READABLE needs field confidences, which CaseFile doesn't carry:
evaluate_document(muster12_extraction, document_id="doc-7", on=date(2026, 10, 1), patient_id="p01")
```

`run(case, ref=..., pack=..., claims=...)` takes a different reference set, rule pack or
pre-built claims (e.g. from billing software) for tests and "what if" runs.

## Layout

| File | What |
|---|---|
| `engine.py` | `@rule` registry, pack loader, `run` / `evaluate` / `evaluate_document`, `Hit` → `Finding` |
| `hkp.py`, `stay.py`, `sgbxi.py`, `md.py`, `doc.py` | rule functions (pure: `(ctx, params) → Hit*`) |
| `packs/<id>/pack.yaml` + `*.yaml` | rule pack: manifest + rule specs |
| `calendar.py` | Bavarian working days (`is_working_day`, `add_working_days`), municipality + Heiligabend/Silvester policy |
| `checkdigits.py` | IK, KVNR, LANR validation; BSNR format; generators for synthetic numbers |
| `reference.py` | loads `data/reference/*.yaml` (payers, HKP tariff, SGB XI LK + Punktwert, SGB XI amounts) |
| `tariffs.py` | price lookup by service date; `build_claim(visit_log)` → `Claim` in integer cents |
| `text.py` | DE/EN rendering of dates, date runs, cents and localized values in messages |

## How a run works

1. **Pack by service date.** `pack_for(first day of case.month)` picks the non-draft pack
   with the latest `valid_from` on or before that day. Today's date is never used. Drafts
   (e.g. a future PNOG pack) are used only when asked for by id. Within a pack, a rule runs
   if its own `valid_from`/`valid_to` overlaps the month.
2. **Claims.** One claim per Leistungsnachweis of the billing month (`claim id = C-<log id>`,
   `line id = <log id>#<index>`), priced with the tariff version valid on each line's date.
   Codes missing from the tariff get price 0 and an `HKP-POSITION-PRICE` finding. Logs for
   other months are history and are not billed.
3. **Calendar.** From `provider.bundesland` + `provider.municipality` and the pack's
   `calendar:` policy (`heiligabend`, `silvester`: `working_day` | `closed`).
4. **Rules → findings.** Each rule yields `Hit`s; the engine adds the stable id
   (`<rule>:<key>`), severity and Kasse codes (variant overrides the default), DE/EN messages,
   affected `claim_line_ids`, `amount_at_risk_cents` and evidence.

**Evidence** comes from the domain objects' `document_id` plus a `field_path` in the
`schemas.paths.flatten()` key space (`period_to`, `practice_stamp`,
`entries[12].staff_initials`). The engine doesn't know pages or pixel boxes: the
localize step resolves them from the extraction by `document_id` + `field_path`.
Objects without a `document_id` give no evidence, so their block findings can't turn a
claim red (ADR-3).

**Money at risk.** Usually the full amount of the affected lines. Partial cases put the
risk on the lines that cause it: frequency excess (the day's/week's later units),
XI budget overflow (the month's last services, the last one partially), wrong price
(the difference). `EngineResult.at_risk_cents()` takes the maximum per line across
findings, so two rules hitting the same line don't count it twice.

## Pack format

```yaml
- id: HKP-SUBMIT-4WD
  version: 2
  valid_from: 2021-12-24
  valid_to: null
  domain: hkp                 # hkp | stay | sgbxi | md | doc
  severity: warn              # default; a variant may override
  kasse_codes: []             # TA HKP / TA5 rejection codes (auditor vocabulary)
  defects: [D07]
  params: {working_days_after_issue: 4}
  sources: ["HKP-RL §6(5) (…)", "https://…"]
  evidence_required: [prescription.issue_date, prescription.submitted_to_payer_at]
  message_de: "Verordnung vom {issue_date} … (Frist: {deadline}) …"
  message_en: "Prescription issued {issue_date} … (deadline {deadline}) …"
  variants:
    no_approval: {severity: block, message_de: "…", message_en: "…"}
```

Every message can use `{n_lines}`, `{dates}` (compact runs) and `{amount}`, plus the
rule's own values. A new pack = copy the directory, change `valid_from` and what changed.

## Rules (pack `2026-01`)

| Rule | Defect | Severity | Kasse codes | Params | Source |
|---|---|---|---|---|---|
| `HKP-RX-REQUIRED` | D01 | block | 42002, 42003 | – | HKP-RL §3(4) |
| `HKP-RX-SIGNED` | D09 | block | – | – | Muster 12 (Anlage 2 BMV-Ä): signature + Vertragsarztstempel |
| `HKP-ERST-14D` | D11 | warn | – | `max_days: 14` | HKP-RL §5(1) |
| `HKP-FOLGE-WINDOW` | D08 | warn; `missing_gap`/`late_gap` block, `due`/`early` info | 42003 (gap) | `window_working_days: 3`<br>`proactive_lookahead_days: 14` | HKP-RL §5(2) |
| `HKP-SUBMIT-4WD` | D07 | warn; `no_approval` block, `no_proof` info | – | `working_days_after_issue: 4` (+ pack `calendar`) | HKP-RL §6(5), since 2021-12-24 |
| `HKP-APPROVAL-EXISTS` | D02 | block; `pending` (submitted in time) / `no_ref` warn | 42002, 42003; 42004 (`no_ref`) | – (provisional cover uses `HKP-SUBMIT-4WD` params) | HKP-RL §6(1), §6(5) |
| `HKP-APPROVAL-SCOPE` | D03 | block | 43001 | – | TA HKP 1.3.0 §10.1 |
| `HKP-FREQ-RX` | D10 | block (Blankoverordnung exempt) | 43001 | – | Muster 12; HKP-RL §5a |
| `HKP-LN-SIGNATURE` | D04 | warn; `reason` (Kennzeichen 1–4) info | – | – | Rahmenvertrag §132a HH §30 [L]; TA HKP §9.8 |
| `HKP-STAFF-INITIALS` | D05 | warn | – | – | Rahmenempfehlungen §132a Abs. 1 (18.12.2023) §8 |
| `HKP-DUPLICATE` | D18 | block | 42007 | – | TA HKP 1.3.0 §10.1 |
| `HKP-POSITION-PRICE` | – | block | 44001 (unknown), 44003 (price) | – (tariff in `data/reference/hkp_services.yaml`) | TA HKP §10.1; Positionsnummernverzeichnis HKP (18.05.2026) |
| `STAY-HKP` | D06 | block; `edge_unclear` warn | 41003 | `stay_kinds: [hospital, rehab, hospice, nursing_home]`<br>`admission_day_policy: timestamp` | HKP-RL §1(6) |
| `STAY-XI-SACH` | D06 | block; `edge_unclear` warn | 41003 | `stay_kinds: [… + short_term_care]`<br>`admission_day_policy: timestamp` | §34 Abs. 2 SGB XI |
| `XI-36-BUDGET` | D12 | warn | – | `pflegegrad_change_policy: max_in_month` (amounts in `sgbxi_amounts.yaml`) | §36, §120 Abs. 3–4 SGB XI |
| `XI-LN-SIGNATURE` | D04 | warn; `reason` info | – | – | §105 SGB XI; Vereinbarung 05.10.2023 |
| `MD-KVNR-CHECK` | D16 | block | – | – | KVNR check digit (§290 SGB V) |
| `MD-DECEASED` | D15 | block; `unclear` (no time on the day of death) warn | – | – | TA HKP §9.8 (Kennzeichen 1) |
| `DOC-READABLE` | D19 | warn | – | `min_confidence: 0.7`<br>`billing_fields:` per doc type | ADR-6 (review queue, never auto-green) |

Policies flagged [L]/[N] in `docs/02` are parameters, not code:

- `admission_day_policy`: `timestamp` (compare visit and admission/discharge times; no time → warn) · `exclude_edge_days` · `include_edge_days`
- `pflegegrad_change_policy`: `max_in_month` (higher grade all month) · `start_of_month` · `prorate` (daily share, rounded down)
- pack `calendar.heiligabend` / `calendar.silvester`: `working_day` (by law) · `closed`
- municipality: Mariä Himmelfahrt only where mainly Catholic (`calendar.ASSUMPTION_DAY_BY_MUNICIPALITY`; unknown Bavarian municipalities default to yes), Augsburg adds the Friedensfest

## Decisions where docs/02 left room (check with a domain reviewer)

- **D04 signature → orange, not red.** `docs/02` says block; the demo story (`docs/05` §4.4)
  shows it orange because a signature can still be obtained before sending. With a reason
  (Kennzeichen 1–4) it's info.
- **Folgeverordnung window** = the last 3 working days *up to and including* the expiry day.
  Issued earlier → info; issued after expiry → warn, or block for uncovered gap days.
- **4-working-day deadline**: lines dated before the approval letter lose provisional cover
  (warn); with no approval at all, all covered lines (block). No submission proof → info.
- **Positions vs. measures.** A Verordnung measure covers every position of its category
  (`hkp_services.yaml: category`) unless it names a `position_no`. Frequencies count units
  per day / ISO week / calendar month; the latest units are the excess.
  Ancillary positions (Wegepauschale) need a Verordnung on the day but no approval/frequency.
- **Duplicates** need a start time; two untimed rows on one day may be two real visits.
- **Lines without a Verordnung** are reported by `HKP-RX-REQUIRED` only, not again as
  "no approval".

## Not covered here

- `MD-IK-CHECK`, `MD-INSURED`, `HKP-LN-MATCH`, `HKP-302-FIELDS`, `XI-PRICE`, `XI-45B-*`,
  `XI-PG-VALID` and the other P1/P2 rules in `docs/02` (Tier B/C). The §45b carry-over
  expiry is implemented as a helper (`sgbxi.entlastung_carryover_valid`) for the §8 boundary.
- The PNOG 2027 draft pack (`RUL-07/09`); the SGB XI draft amounts are already in
  `sgbxi_amounts.yaml` behind `draft: true`.
