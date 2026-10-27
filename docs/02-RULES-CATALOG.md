# Kassenfest — Rules Catalog (what the rules engine must encode)

Status: research as of **2026-10-22**. Flags: **[V]** primary text read (statute, G-BA, GKV-SV, KBV) · **[L]** secondary / regional contract / inference · **[N]** not verified → make it a **parameter**, not hard-coded logic.

> **Not legal advice.** Every rule cites its source and effective date so a domain reviewer can check it (`ADM-06`). Regional contracts (§132a Rahmenverträge, §89 Vergütung) differ by Land and payer. Anything marked [L]/[N] is a **per-contract parameter**.

---

## 0. How rules are modelled

```yaml
# packages/rules/packs/2026-01/hkp.yaml
- id: HKP-SUBMIT-4WD
  version: 2
  valid_from: 2021-12-24        # G-BA 21.10.2021 changed 3 -> 4 working days
  valid_to: null
  domain: hkp
  severity: warn                 # block | warn | info
  kasse_codes: []                # matching TA HKP rejection codes, if any
  params:
    working_days_after_issue: 4
    working_days: [MO, TU, WE, TH, FR]
    exclude_public_holidays: true
    holiday_region: DE-BY        # configurable municipality (Mariä Himmelfahrt)
  source:
    - "HKP-RL §6(5) (G-BA, i.d.F. 16.10.2025, in Kraft 12.12.2025)"
    - https://www.g-ba.de/downloads/62-492-3999/HKP-RL_2025-10-16_iK-2025-12-12.pdf
  evidence_required: [prescription.issue_date, prescription.submitted_to_payer_at]
  message_de: "Verordnung vom {issue_date} ist erst am {submitted} bei der Kasse eingegangen (Frist: {deadline}). Bis zur Genehmigung keine vorläufige Kostenübernahme."
  message_en: "Prescription issued {issue_date} reached the payer on {submitted} (deadline {deadline}). No provisional payment until approval."
```

- **Rule logic** lives in a pure TS function per `id` (`evaluate(ctx, params) → Finding[]`) with unit tests.
- **Rule packs** are versioned by effective date, so you can choose the pack by the **service date**, not today's date.
- **Severity**: `block` (the Kasse will reject; don't send) · `warn` (risk; fixable or needs a human look) · `info`.
- **`kasse_codes`** link each rule to the official **TA HKP / TA5 rejection codes**. The auditor agent uses the same vocabulary, so its objections map 1:1 to rules (§9).

---

## 1. Parameter tables (put in `data/reference/*.yaml`)

### 1.1 SGB XI amounts

| Parameter | 2025-01-01 → | 2026-01-01 → | PNOG draft 2027-01-01 (not law yet) | Source |
|---|---|---|---|---|
| §36 Sachleistung PG2 / PG3 / PG4 / PG5 (per month) | €796 / €1,497 / €1,859 / €2,299 | **unchanged** | €890 / €1,590 / €2,090 / €2,530 | §36 SGB XI [V]; PNOG [L] |
| §36 Sachleistung PG1 | none | none | — | [V] |
| §37 Pflegegeld PG2–5 | €347 / €599 / €800 / €990 | unchanged | — | [V] |
| §45b Entlastungsbetrag | €131/month (PG1–5) | unchanged | replaced by **€175 Sozialraumbudget**, no PG1, no carry-over | [V]; PNOG [L] |
| §45b carry-over | unused → until **30 June** of next year | unchanged | none | [V] |
| §45a Umwandlung | max **40%** of unused §36 budget | unchanged | — | [V] |
| §39/§42a Gemeinsamer Jahresbetrag | **€3,539** per calendar year from **2025-07-01** | unchanged + claim deadline: end of the year after care (BEEP) | replaced by €2,285 Überbrückungsbudget | [V]; PNOG [L] |
| Next statutory increase | — | **2028-01-01** (core inflation, §30) | yearly from 2029 | [V] |

> 💡 **Demo idea:** load the **PNOG 2027 draft** as a separate pack. Re-running a month under it shows the "easy to update" claim live (`RUL-07`). Label it clearly *"Entwurf – nicht in Kraft"* (draft, not in force).

### 1.2 HKP parameters

| Parameter | Value | Source |
|---|---|---|
| Submission deadline for provisional payment | **4th working day after issue** (Mon–Fri, excl. statutory holidays; Saturday never counts) | HKP-RL §6(5) [V]; changed 3→4 in Dec 2021 [V] |
| Erstverordnung max | **14 days** ("soll", so warn rather than block) | HKP-RL §5(1) [V] |
| Folgeverordnung issue window | last **3 working days** before expiry | HKP-RL §5(2) [V] |
| Hospital/rehab discharge prescription | up to **7 calendar days** after discharge | HKP-RL §7(5) [V] |
| Krankenhausvermeidungs- / Unterstützungspflege | max **4 weeks** per illness (longer only after MD) | §37(1),(1a) SGB V [V] |
| Blutzuckermessung (Erst-/Neueinstellung) | max **4 weeks**, max **3× daily** | Muster 12 / HKP-RL [V] |
| Blankoverordnung doctor contact | within **3 months** | HKP-RL §5a [V] |
| Zuzahlung (co-payment) | 10% + €10 per Verordnung, 10% only for the first **28 days per calendar year**, adults only; collected by the **Kasse** (Hamburg verified) | §61, §37(5) SGB V [V]; collection [L] |
| Billing cadence / payment term / objection window | monthly; Kasse pays in **21 days**; objections within **12 months**; rebuttal within **3 months** (Hamburg) | [L] per contract → parameter |
| Limitation period | **4 years** from end of calendar year | §45 SGB I by analogy, BSG case law [L] |
| Placeholder staff IDs | 999999998 new hire · 999999997 other reason · 999999996 trainee | TA HKP 10.11 [V] |
| Tariff area Bayern | `02` | TA HKP 10.x [V] |

### 1.3 Stay parameters

| Parameter | Value | Source |
|---|---|---|
| SGB XI Sachleistung during hospital/rehab | **suspended** (ruht) from the admission day | §34 SGB XI [V] |
| Pflegegeld during stay | continues for **8 weeks** (BEEP, since 2026-01-01; previously 4 weeks) | §34 SGB XI [V] |
| HKP during hospital/rehab/hospice/nursing home | **not billable** | HKP-RL §1(6) [V] |
| Admission/discharge day | no explicit exclusion; visits actually delivered at home before admission / after discharge are billable → compare **timestamps** | [L]/[N] → parameter `admission_day_policy` |

---

## 2. HKP rules (SGB V §37)

| ID | P | Rule (plain English) | Source | Evidence needed | Severity | Kasse code | Defect |
|---|---|---|---|---|---|---|---|
| `HKP-RX-REQUIRED` | P0 | Every billed HKP service needs a valid Verordnung covering the service date | HKP-RL §3(4) [V] | Muster 12 period ⊇ service date | block | 42002/42003 | D01 |
| `HKP-RX-NO-RETRO` | P1 | A Verordnung issued *after* the service start is invalid for earlier days (retroactive "grundsätzlich nicht zulässig") | HKP-RL §3(4) [V] | issue_date vs first visit | block | — | — |
| `HKP-RX-SIGNED` | P0 | The Muster 12 front must carry the **doctor's signature + practice stamp** | Muster 12 [V] | SAM: signature + stamp regions | block | — | D09 |
| `HKP-RX-AMEND-SIGNED` | P1 | Any change on the Verordnung needs a new doctor signature, stamp and date | HKP-RL §3(5) [V] | corrections_present ∧ ¬corrections_initialled | warn | — | D17 |
| `HKP-RX-CONTENT` | P1 | Required content is present: ICD-10 + Einschränkungen; medication **names the Präparate**; wound care has Wundart, location, size, grade | Muster 12 / KVB guide [V] | extracted fields | warn | — | — |
| `HKP-RX-PATIENT-ANTRAG` | P1 | The back of Muster 12a ("Antrag des Versicherten") is signed by the insured or their representative | Muster 12a back [V] | SAM: signature region on back | warn | — | — |
| `HKP-ERST-14D` | P0 | Erstverordnung > 14 days → warn (soft rule) | HKP-RL §5(1) [V] | period_from/to, prescription_kind | warn | — | D11 |
| `HKP-FOLGE-WINDOW` | P0 | The Folgeverordnung should be issued in the last 3 working days before expiry. **Proactive:** create the doctor-renewal action when entering that window; **reactive:** gap between periods → uncovered days | HKP-RL §5(2) [V] | period_to, next prescription issue_date, calendar | warn → block for gap days | 42003 | D08 |
| `HKP-SUBMIT-4WD` | P0 | The Verordnung must reach the Kasse by the 4th working day after issue; otherwise there's **no provisional payment** for the days until approval | HKP-RL §6(5) [V] | issue_date, submission proof (fax report / KIM receipt / upload log) | warn (block for days before approval if approval is missing) | — | D07 |
| `HKP-APPROVAL-EXISTS` | P0 | An approval (or provisional cover via `HKP-SUBMIT-4WD`) exists for the billing period | HKP-RL §6(1) [V] | approval letter / Genehmigungskennzeichen | block / warn | 42002, 42003, 42004 | D02 |
| `HKP-APPROVAL-IK` | P1 | The approval is for **this** provider's IK | TA HKP 10.1 [V] | approval.provider_ik | block | 42006 | — |
| `HKP-APPROVAL-SCOPE` | P0 | Billed services and quantities ≤ approved services and quantities (partial approvals!) | TA HKP 10.1 [V] | approval.approved_items vs claim lines | block (excess) | 43001 | D03 |
| `HKP-FREQ-RX` | P0 | Billed frequency ≤ prescribed frequency (`n/a` if Blankoverordnung → nurse-set frequency, documented) | Muster 12; HKP-RL §5a [V] | measures[].frequency vs visits | block (excess) | 43001 | D10 |
| `HKP-BLANKO` | P1 | Blankoverordnung: the nurse documents frequency and duration, informs the doctor, and a doctor contact happens within 3 months | HKP-RL §5a [V] | blank_prescription flag, nurse documentation | warn | — | — |
| `HKP-LN-MATCH` | P0 | Billed positions = positions on the Leistungsnachweis (same days, quantities) | TA HKP 10.1 [V] | visit log ↔ claim lines | block | 43002 | — |
| `HKP-DUPLICATE` | P0 | No duplicate line (same patient, position, day and time) and no overlap with an already-sent bill | TA HKP 10.1 [V] | claim history | block | 42007 | D18 |
| `HKP-SURCHARGE-ONCE` | P2 | Sunday/holiday surcharge at most once per visit | TA HKP 10.1 [V] | lines | block | 44004 | — |
| `HKP-POSITION-PRICE` | P0 | Position number exists in the Positionsnummernverzeichnis **and** the price = contract tariff for the date (amount computed by the engine, never by the LLM) | TA HKP 10.1 [V] | tariff table | block | 44001/44003 | — |
| `HKP-QUALIFICATION` | P2 | Staff on the visit have the required qualification for the service | TA HKP 10.1 [V] | staff table | block | 43005 | — |
| `HKP-302-FIELDS` | P0 | Each line has date **+ time**, position, quantity, price, prescriber LANR and the **Beschäftigtennummer** of the delivering nurse (or a placeholder) | §302(1) SGB V [V]; TA HKP 10.11 [V] | visit log entries | block | — | D05 |
| `HKP-LN-SIGNATURE` | P0 | Leistungsnachweis is signed by the patient/relative **once per month**, or the missing signature has a reason (1 deceased, 2 inpatient, 3 impairment, 4 other) | Rahmenvertrag HH §30 [L]; TA HKP 9.8 [V] | SAM: patient signature box + ink density | block (warn if a reason is given) | — | D04 |
| `HKP-STAFF-INITIALS` | P0 | Every visit entry has Handzeichen / Beschäftigtennummer | Rahmenempfehlungen §132a §8 [V] | visit grid cells | warn | — | D05 |
| `HKP-SCOPE-PG` | P1 | Unterstützungspflege §37(1a) **not** for PG 2–5; Satzung Grundpflege / Hauswirtschaft never with PG ≥ 2 | §37 SGB V; HKP-RL §6 [V] | Pflegegrad history | block | — | — |
| `HKP-4WEEKS` | P1 | Krankenhausvermeidungs- / Unterstützungspflege ≤ 4 weeks per illness without an MD finding | §37(1),(1a) [V] | prescriptions chain | warn | — | — |
| `HKP-BZ-LIMIT` | P2 | Blutzuckermessung Erst-/Neueinstellung ≤ 4 weeks, ≤ 3× daily | Muster 12 [V] | measures | block (excess) | 43001 | — |
| `HKP-DISCHARGE-7D` | P1 | A hospital-issued prescription covers ≤ 7 days after discharge (billing key 4 Entlassmanagement) | HKP-RL §7(5) [V] | hospital prescription (code 77…) + discharge date | block (after day 7) | — | — |
| `HKP-COPAY-NOT-INVOICED` | P1 | Never put the HKP Zuzahlung on the patient's private invoice (the Kasse collects it) | HH §16 [L] | patient invoice lines | block | — | — |
| `HKP-KOSTENERSTATTUNG` | P2 | Patient chose Kostenerstattung → don't bill the Kasse directly | TA HKP 10.1 [V] | master data | block | 42009 | — |
| `HKP-LIMITATION` | P1 | Line older than the limitation period → can't be billed | §45 SGB I analog. [L] | service date | block | 42008 | — |
| `HKP-EVO` | P2 | Accept paper Muster 12 **or** an eVerordnung ID (statutory from 2026-07-01, practically delayed into 2027) | §360(5) SGB V [V]; rollout [L] | eVO_ID | info | — | — |
| `HKP-NURSE-RX` | P2 | A nurse as prescriber is valid only once the §73d catalogue exists (due 2026-12-31) | §15a, §73d SGB V [V] | prescriber type | block until active | — | — |

## 3. Stay rules

| ID | P | Rule | Source | Evidence | Severity | Kasse code | Defect |
|---|---|---|---|---|---|---|---|
| `STAY-HKP` | P0 | No HKP visit while the patient is in hospital / rehab / hospice / nursing home | HKP-RL §1(6) [V] | hospital letter admission/discharge vs visit timestamps | block | 41003 | D06 |
| `STAY-XI-SACH` | P0 | No SGB XI Sachleistung during a §71(4) stay (entitlement suspended) | §34 SGB XI [V] | same | block | 41003 | D06 |
| `STAY-KZP` | P1 | No §37(1)/(1a) HKP during SGB XI Kurzzeitpflege or full inpatient care | TA HKP 10.1 [V] | stay type | block | 42005 | — |
| `STAY-EDGE-DAYS` | P1 | On admission/discharge days, compare visit time vs admission/discharge time (policy configurable) | [L]/[N] | timestamps | warn | — | — |
| `STAY-SIGNAL` | P1 | Visit log shows a gap of ≥ 2 days, or a "nicht angetroffen" (not found at home) note, without a known reason → ask "hospital stay?" (proactive detection) | heuristic | visit pattern | info | — | — |

## 4. SGB XI rules (ambulant)

| ID | P | Rule | Source | Evidence | Severity | Kasse code | Defect |
|---|---|---|---|---|---|---|---|
| `XI-PG-VALID` | P0 | Patient has a recognised Pflegegrad in the period; for Sachleistung **PG ≥ 2** | §36 SGB XI [V] | Pflegegrad history | block | 43003 | — |
| `XI-PG-MATCH` | P1 | Services match the approved Pflegegrad | TA5 [V] | Pflegegrad, LK | block | 43004 | — |
| `XI-36-BUDGET` | P0 | Sum of LK prices in the month ≤ Sachleistung cap → the excess becomes a **private Eigenanteil** invoice (needs prior written cost information, §120) or SGB XII | §36, §120(3)–(4) SGB XI [V] | tariff × visits | warn | — | D12 |
| `XI-ORDER` | P1 | Billing order: Sachleistung → §45a Umwandlung (≤ 40% of unused) → §45b Entlastungsbetrag → Pflegegeld share (Kombileistung) | §§36, 38, 45a, 45b [V] | budget calculator | info | — | — |
| `XI-45B-ENTL` | P0 | Entlastungsbetrag ≤ available balance (€131/month + carry-over, valid until **30 June next year**); for PG 2–5 **not for Selbstversorgung** (self-care) services | §45b SGB XI [V] | balance ledger, LK type | block (excess) | — | D13 |
| `XI-45B-ABTRETUNG` | P0 | Direct billing of §45b needs a signed **Abtretungserklärung** (assignment) | practice [L] | assignment doc + SAM signature | block | — | D13 |
| `XI-39-JAHRESBETRAG` | P2 | Verhinderungs- + Kurzzeitpflege ≤ €3,539 per calendar year (from 2025-07-01); claim filed by the end of the following year (from 2026-01-01) | §39, §42a SGB XI [V] | ledger | block (excess) | — | — |
| `XI-37-3-BERATUNG` | P1 | Pflegegeld recipients PG 2–5: Beratungseinsatz (advice visit) **half-yearly** (PG 4–5 may do quarterly) since 2026-01-01; every 2nd visit may be by video until 2027-03-31; confirmation sent electronically | §37(3)–(4) SGB XI (BEEP) [V] | schedule | info → action | — | — |
| `XI-105-FIELDS` | P0 | Each entry has date + time, LK, quantity, price, **Beschäftigtennummer** (since 2023-01-01) | §105(1) SGB XI [V] | visit log | block | — | D05 |
| `XI-LN-SIGNATURE` | P0 | Leistungsnachweis signed once a month (patient / representative / family app) | §105 Vereinbarung 05.10.2023 [V] | SAM signature | block | — | D04 |
| `XI-PRICE` | P0 | Price = points × Punktwert of **this provider's** §89 contract for the date | §89 SGB XI [V]; Bayern values [L] | tariff table | block | — | — |
| `XI-PFLEGEVERTRAG` | P2 | A Pflegevertrag exists, and cost information was given before above-cap services | §120 SGB XI [V] | contract doc | warn | — | — |
| `XI-PG-CHANGE` | P1 | Pflegegrad changed mid-month → which cap applies is **configurable** (prorate vs. higher grade for the whole month); a retroactive upgrade triggers correction bills (code 05) and refunds of above-cap private invoices | §33, §48 SGB X [L]/[N] | Bescheid date | warn | — | D14 |

## 5. Master-data & eligibility rules

| ID | P | Rule | Source | Severity | Kasse code | Defect |
|---|---|---|---|---|---|---|
| `MD-KVNR-CHECK` | P0 | KVNR format + check digit valid | KVNR spec [V] | block | — | D16 |
| `MD-IK-CHECK` | P0 | IK format + check digit valid; payer IK is in the Kostenträgerdatei | GR IK 02/2026 [V] | block | — | D16 |
| `MD-LANR-CHECK` | P1 | LANR check digit valid (BSNR: format only; hospital location code 77…) | [L] | warn | — | — |
| `MD-INSURED` | P0 | Patient insured with **this** Kasse on each service day (Kassenwechsel splits the month; the new Kasse needs a new Verordnung + approval) | TA HKP 10.1 [V] | block | 41002 / 42006 | D15 |
| `MD-DECEASED` | P0 | No services after the date/time of death; the missing signature gets reason key 1 | TA HKP 9.8 [V] | block | — | D15 |
| `MD-ICD-VALID` | P1 | ICD-10-GM codes exist in the version for the issue year | BfArM [V] | warn | — | — |

## 6. Document-quality rules (the "AI-side" checks)

| ID | P | Rule | Severity |
|---|---|---|---|
| `DOC-READABLE` | P0 | Billing-relevant field unreadable or below the confidence threshold → human review, never auto-🟢 | warn |
| `DOC-LINKED` | P0 | Each document is linked to exactly one patient + period; conflicts (two KVNRs, name mismatch) → review | warn |
| `DOC-CONSISTENT` | P1 | The same fact differs across documents (DOB on Muster 12 ≠ master data; approval period ≠ Verordnung period) → finding with both evidence crops | warn |
| `DOC-SYNTHETIC` | P0 | Demo safety: any document without the synthetic watermark/flag is rejected at ingest | block |

## 7. Other payers (P2 — mention in the pitch, implement minimally)

| ID | Rule | Source |
|---|---|---|
| `SOZ-NOTICE` | SGB XII Hilfe zur Pflege only starts once the Sozialamt **knows** about the need → notify it *before* billing above-cap amounts | §18(1) SGB XII [V] |
| `PKV-INVOICE` | Privately insured patients: invoice the patient, not the Kasse; Beihilfe patients get 50% from the PKV | §23, §28(2) SGB XI [L] |
| `EIGENANTEIL-PRICE` | Private above-cap invoices ≤ the agreed §89 prices, with prior written cost information | §120(3)–(4) SGB XI [V] |

---

## 8. Test fixtures (minimum per rule)

For **every** rule: 1 passing fixture + 1 failing fixture + boundary cases. Boundary cases that must be in `packages/rules/test`:

| Case | Why |
|---|---|
| Verordnung issued **Thu 2026-10-01** → 4th working day = **Wed 2026-10-07** (Oct 3 is a Saturday that's also Tag der Deutschen Einheit; check it doesn't count twice) | weekend + holiday logic |
| Issued **Thu 2026-10-29** → Oct 30 (Fri), Nov 2, Nov 3, **Nov 4** (Nov 1 Allerheiligen is a Sunday) | month boundary |
| Issued **Wed 2026-12-23** → Dec 24 (working day by law, often closed!), Dec 28, 29, **30** (25/26 Dec are holidays) | Christmas; configurable "Heiligabend" policy |
| Issued Fri **2026-08-14** in Deggendorf vs Nürnberg → Aug 15 is a Saturday, but test the municipality switch with 2025-08-15 (a Friday) | Mariä Himmelfahrt municipality rule |
| Issued **Tue 2026-06-02** → Jun 3, (Jun 4 Fronleichnam = Bavarian holiday), Jun 5, Jun 8, **Jun 9**; in Berlin the deadline is **Jun 8** | Land-specific holidays |
| Erstverordnung exactly 14 days vs 15 days | boundary |
| Folgeverordnung issued 4 working days before expiry (too early?) vs 3 vs on the expiry day | window semantics: decide warn or info |
| Hospital admission 2026-10-12 10:30, visit 2026-10-12 07:45 → billable; visit 18:00 → not | edge-day timestamps |
| SGB XI budget exactly at the cap vs €0.01 over | integer cents |
| Entlastungsbetrag carry-over from 2025 used on 2026-06-30 vs 2026-07-01 | expiry |
| Pflegegrad change on the 15th | configurable policy |
| Death at 14:00, visit at 16:00 same day | timestamp |
| Leap-year February 2028 billing month | calendar |

---

## 9. Auditor agent vocabulary (official Kasse rejection codes)

The auditor agent must object **only** by citing one of these codes (or a rule ID). The resolver maps code → rules → re-evaluates.

| Code | Meaning (TA HKP 10.1 / TA5) | Rules |
|---|---|---|
| 41002 | no valid insurance in the period | `MD-INSURED` |
| 41003 | entitlement suspended (ruhend) | `STAY-HKP`, `STAY-XI-SACH` |
| 42002 | no approval | `HKP-APPROVAL-EXISTS`, `HKP-RX-REQUIRED` |
| 42003 | no approval for the billing period | `HKP-APPROVAL-EXISTS`, `HKP-FOLGE-WINDOW` |
| 42004 | approval number invalid / missing | `HKP-APPROVAL-EXISTS` |
| 42005 | HKP during Kurzzeitpflege / full inpatient care | `STAY-KZP` |
| 42006 | approval issued to another IK | `HKP-APPROVAL-IK`, `MD-INSURED` |
| 42007 | overlaps an existing bill | `HKP-DUPLICATE` |
| 42008 | outside the limitation period | `HKP-LIMITATION` |
| 42009 | Kostenerstattung chosen | `HKP-KOSTENERSTATTUNG` |
| 43001 | quantity exceeds approval | `HKP-APPROVAL-SCOPE`, `HKP-FREQ-RX`, `HKP-BZ-LIMIT` |
| 43002 | positions don't match the Leistungsnachweis | `HKP-LN-MATCH` |
| 43003 | no recognised Pflegegrad (SGB XI) | `XI-PG-VALID` |
| 43004 | service doesn't match the approved Pflegegrad | `XI-PG-MATCH` |
| 43005 | staff lack the qualification | `HKP-QUALIFICATION` |
| 44001 / 44003 | position or price wrong | `HKP-POSITION-PRICE`, `XI-PRICE` |
| 44004 | Sunday/holiday surcharge more than once per visit | `HKP-SURCHARGE-ONCE` |
| `FACT` | free-form objection; must cite document + page + field | resolver checks it against extracted fields + evidence |

The auditor also gets an **"experience" persona**: soft signals a human auditor notices that the rules don't cover. It may raise them only as `info` and never as a block:
- identical Handzeichen strokes every day
- the same pen and ink for a whole month
- visit times that are physically impossible given travel
- a signature date before the end of the month

---

## 10. Change log the engine must know (rule pack versions)

| Pack | Effective | Changes | Flag |
|---|---|---|---|
| `2021-12` | 2021-12-24 | Submission deadline 3 → **4** working days | [V] |
| `2023-01` | 2023-01-01 | SGB XI: Beschäftigtennummer mandatory | [V] |
| `2024-07` | 2024-07-01 | Muster 12 version 7.2024 mandatory (old forms invalid); **Blankoverordnung** (HKP-RL §5a) | [V] |
| `2025-01` | 2025-01-01 | SGB XI amounts +4.5% (Entlastungsbetrag €125 → €131; Sachleistung €796/1,497/1,859/2,299) | [V] |
| `2025-07` | 2025-07-01 | Gemeinsamer Jahresbetrag €3,539; Vorpflegezeit removed; Verhinderungspflege 8 weeks; **TI connection mandatory** for HKP providers | [V] |
| `2025-10` | 2025-10-01 | §302 TA1 v21; staff ID (LBNR) required on billing documents | [V]/[L] |
| `2025-12` | 2025-12-12 | HKP-RL amendment (parenteral nutrition, Bronchiallavage, "übertragen", COVID rules removed) | [V] |
| `2026-01` | 2026-01-01 | **BEEP**: §34 Pflegegeld 8 weeks during stays; §37(3) PG4/5 half-yearly; §39 no prior application + filing deadline; §15a/§73d nurse prescribing (catalogue due 2026-12-31); no benefit increase | [V] |
| `2026-07` | 2026-07-01 | HKP e-prescription statutory (practically delayed) | [V]/[L] |
| `2026-07b` | 2026-07-30 | §132a(4) rewritten (tariff pass-through capped at 50% until 2028-07-29) — contract negotiation, not per-bill | [V] |
| `2027-01-draft` | 2027-01-01 | **PNOG draft** (not passed): new budgets, Sozialraumbudget €175, Überbrückungsbudget €2,285 | [L] |
| `2027-02` | 2027-02-01 | TA HKP 1.3.0 / TA5 1.2.0 pilot; §302 TA1 v22 | [V] |
| `2027-10` | 2027-10-01 | HKP + SGB XI billing **via TI/KIM only** | [V] |

## 11. Open uncertainties (→ parameters + questions for the domain reviewer)

1. Payment / billing / objection deadlines in **Bavarian** §132a contracts (Hamburg values used as defaults).
2. Is the HKP Zuzahlung always collected by the Kasse (verified only for Hamburg)?
3. Sachleistung cap when the Pflegegrad changes mid-month (prorate vs. higher grade).
4. Admission/discharge-day billing policy.
5. How strictly Bavarian Kassen apply `HKP-SUBMIT-4WD`, and whether fax proof is enough.
6. Actual go-live of the HKP eVerordnung and of nurse prescribing.
7. Bavarian 2026 LK Punktwerte and the §132a price levels → use **illustrative** prices in the demo.
