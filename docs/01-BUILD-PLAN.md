# Kassenfest — Build Plan & Master Task List

> Agent that checks every home-care bill (HKP / SGB V and Pflegeversicherung / SGB XI) **before** it goes to the insurer.
> Built on Meta Muse Spark (document reading, tool calling, adversarial auditor) + SAM 3.1 (visual evidence).
> Synthetic data only.

Companion docs:
- [02-RULES-CATALOG.md](02-RULES-CATALOG.md) — every billing rule the engine must encode, with sources, parameters, test cases
- [03-DATA-AND-INPUTS.md](03-DATA-AND-INPUTS.md) — everything to gather, generate, decide, or get access to
- [04-RESEARCH-NOTES.md](04-RESEARCH-NOTES.md) — Meta model facts, hackathon rules, problem evidence, competitors (with sources)
- [05-EXECUTION-PLAN.md](05-EXECUTION-PLAN.md) — **hackathon execution plan: stack, scope tiers, day-by-day. Supersedes §2 (architecture) and §5 (schedule) below for the hackathon build.**

### Hard dates (Meta Global AI Developer Hackathon, Meta × Cerebral Valley — all ET, Meta may change them)

| When (ET) | When (Germany) | What |
|---|---|---|
| Oct 25, 23:59 | Oct 26, 05:59 CET | Applications close |
| Oct 26, 09:00 | Oct 26, 14:00 CET | Approval emails + kickoff livestream; **Official Rules published → read before coding** |
| Oct 27 – Nov 4 | | Workshops + Discord office hours |
| **Nov 4, 21:00** | **Nov 5, 03:00 CET** | **Submission deadline** (EU leaves summer time Oct 25, US Nov 1) — plan to submit by **Nov 4, 18:00 CET** |
| Nov 4 – 8 | | Judging |
| Nov 9 | | Finals and winners |

Track: **Indie developer track**, judged on *creativity, technical ambition, and whether it works*. Theme fit: **"Build for Your World"**.

> ⚠️ **Pre-existing code:** the rules on this aren't published yet. Until you've read the Official Rules on Oct 26, limit prep to research, docs, reference data, blank-form collection, handwriting sessions and accounts. Keep any early code throwaway, or wait. See `ADM-01`.

Priority legend: **P0** = needed for the demo to work · **P1** = makes the demo convincing · **P2** = stretch / post-hackathon.
Checkbox IDs (e.g. `ING-03`) are stable so you can reference them in commits and issues.

---

## 1. What the demo must prove (acceptance criteria)

The judges should see, in one ~3-minute flow:

1. **Upload a month of messy paperwork** for a small synthetic Pflegedienst (≈10–15 patients): scans, phone photos, handwriting.
2. **Kassenfest reads it**: classifies each page, extracts fields into structured data, links documents to patient + payer + billing period.
3. **The rules engine decides** bill by bill: 🟢 ready / 🟠 fixable / 🔴 blocked — with a rule ID, plain-German explanation and legal source for every finding. **No amount ever comes from the LLM.**
4. **Evidence on the scan**: click a finding → the exact region is highlighted by SAM 3.1 (empty signature box, expired date, missing stamp).
5. **Fix it**: the agent drafts a renewal request to the doctor (Folgeverordnung), a note to the patient for a missing signature, and shows the countdown to the Verordnung submission deadline.
6. **Auditor attack**: a second Muse Spark agent plays the Krankenkasse auditor and tries to reject each "green" bill; every objection is checked against rules + evidence; only survivors are released.
7. **Receivables view**: what's unpaid, for how long, and why (Absetzung reasons, missing documents).

Measured, shown in the demo or README:
- Field-level extraction accuracy on a held-out synthetic gold set (clean scans vs. phone photos vs. handwriting).
- Defect detection recall / precision on seeded defects (e.g. "caught 47/50 seeded defects, 2 false alarms").
- Localization IoU of SAM evidence boxes vs. generator ground truth.
- Auditor: % of seeded defects it found that the first pass missed; % of its objections that were invalid (hallucinated) and got dismissed.

---

## 2. Architecture

```
               ┌───────────────────────── React (Vite, TS) ──────────────────────────┐
               │ Upload/inbox · Patient timeline · Bill board (🟢🟠🔴) · Evidence viewer │
               │ Actions/letters · Deadlines · Auditor debate · Receivables · Rules admin │
               └───────────────────────────────┬────────────────────────────────────────┘
                                               │ REST + SSE (job progress)
┌──────────────────────────────────────────── NestJS API ───────────────────────────────────────────┐
│ ingest · documents · extraction · entities (patients/payers/doctors) · episodes                      │
│ rules (engine + rule packs + tariffs, versioned by effective date) · claims · findings · actions      │
│ agents (tool-calling orchestrator) · auditor · receivables · audit log                               │
│ BullMQ queues: preprocess → classify → extract → validate → link → localize → evaluate → audit       │
└───────┬───────────────┬────────────────────┬──────────────────────┬─────────────────────────────────┘
        │               │                    │                      │
   PostgreSQL       Redis (BullMQ)     MinIO / S3 (scans,      Meta Model API  https://api.meta.ai/v1
   (Prisma)                            renders, masks)          · muse-spark-1.3  (chat/responses: vision
                                                                  extraction, JSON schema, tools, auditor)
                                                                · sam-3.1  (POST /v1/responses: text/box
                                                                  prompts → boxes + masks)
                                     ┌──────────────────────────────────────────┐
                                     │ Python vision service (FastAPI, CPU)     │
                                     │ preprocessing (deskew, perspective,      │
                                     │ HEIC/PDF→PNG), ink density, crops,       │
                                     │ mask decoding (meta_sam_parser)          │
                                     └──────────────────────────────────────────┘
```

Facts about the Meta API that shape the design (details and sources in `04-RESEARCH-NOTES.md`):
- **OpenAI-compatible.** Use the official `openai` npm package with `baseURL: "https://api.meta.ai/v1"`. There is no Meta SDK. An Anthropic-compatible Messages protocol also exists.
- **Use only the standard model IDs:** `muse-spark-1.3`, never `muse-spark-1.3-contributor`. Contributor variants may train on your inputs. Even with synthetic data, keep the code path clean for real data later.
- **Images:** JPEG/PNG/GIF/WebP, up to 50 per request, 50 MB inline. **HEIC isn't supported**, so convert iPhone photos. PDFs work through the Files API, with page images from the first 50 pages.
- **Structured output:** `response_format: {type: "json_schema"}` uses constrained decoding. No recursive schemas; maximum nesting depth is 10.
- **Tool calling:** `tool_choice` only accepts `"auto"`, so **you cannot force a tool call**. The auditor's verdict therefore goes through structured output, not tool calls. `parallel_tool_calls` defaults to true.
- **`reasoning_effort`:** `minimal` up to `max`. Use `low`/`medium` for extraction and `high` for the auditor. Reasoning tokens are billed as output.
- **SAM 3.1 is on the API** at $2.50 per 1,000 images, with 3,000 RPM. **No GPU is needed.** It takes **one concept per request** (no comma lists), plus box/point prompts for up to 16 objects. No match returns empty output, not an error. Meta's docs recommend this pairing: **Muse Spark gives coordinates, SAM refines them into masks.**
- **Cost estimate:** Muse Spark standard is $1.25 per 1M input tokens and $4.25 per 1M output tokens. You get **$150 in hackathon credits** (reported, not confirmed). 500 pages × a few calls each should cost well under $50. Log spend per call anyway.
- **Rate limit:** `muse-spark-1.3` allows 3,000 RPM / 4M TPM **per team**.

Key design decisions (write these as ADRs in `docs/adr/`):
- **ADR-1 LLM reads, rules decide.** Muse Spark only produces *facts with evidence* (field values + page + location + confidence). Billability and amounts come from a deterministic engine fed by versioned tariff tables.
- **ADR-2 Rules are data.** Rule parameters (amounts, day limits, deadlines) live in versioned YAML/JSON packs with `valid_from`/`valid_to`; rule logic lives in small pure TS functions with unit tests. Updating for a 2026 change = new pack version, not a code rewrite.
- **ADR-3 Every finding carries evidence.** `Finding → rule_id + rule_version + evidence[] (document, page, field, bbox/mask)`. No evidence → it can't block a bill.
- **ADR-4 Auditor objections must be grounded.** The auditor may only object by citing a rule ID or a concrete document fact; the resolver re-checks each objection deterministically; ungrounded objections are dismissed and logged.
- **ADR-5 Synthetic-only, EU-ready.** No real health data. Model provider behind an interface (`VisionLLM`, `ChatLLM`) so the Meta API can be swapped for self-hosted Muse Spark Open in the EU later.
- **ADR-6 Human in the loop.** Low-confidence fields go to a review queue; corrections are stored and reused as few-shot examples / eval data.

### 2.1 Repo layout (pnpm workspaces monorepo)

```
kassenfest/
  apps/web/                React + Vite + TS + Tailwind + shadcn/ui + TanStack Query
  apps/api/                NestJS + Prisma + BullMQ
  services/vision/         Python FastAPI: preprocessing + SAM 3.1
  packages/schemas/        zod schemas per document type (shared by api, web, eval)
  packages/rules/          rules engine, rule packs (YAML), tariff tables, working-day calendar, tests
  packages/llm/            provider interface + Meta Model API client + prompts + tool definitions
  tools/synth/             Python synthetic document generator (forms → filled → degraded) + ground truth
  data/reference/          public reference data (payers, holidays, tariffs, Positionsnummern)
  data/synthetic/          generated cases (small sample committed, rest gitignored)
  data/gold/               hand-checked eval set
  eval/                    extraction / detection / localization / auditor evaluation harness
  docs/                    these docs + ADRs + demo script
  docker-compose.yml       postgres, redis, minio, vision service
```

### 2.2 Core data model (Prisma)

| Entity | Key fields |
|---|---|
| `CareProvider` (Pflegedienst) | name, IK, address, Bundesland, contract types (SGB V / SGB XI), billing center |
| `Payer` | name, IK (Kranken- vs Pflegekasse), fax/KIM address, payment-term days |
| `Physician` | name, LANR, BSNR, practice address, fax/KIM |
| `Patient` | synthetic name, DOB, KVNR, payer, Pflegegrad history (`from`,`grade`), Zuzahlungsbefreiung, status (active/deceased) |
| `Document` | file key, sha256, source (scan/photo/fax/PDF), type, pages, status, received_at |
| `DocumentPage` | image key, width/height, quality score, rotation/deskew applied |
| `ExtractedField` | doc, page, key, value (typed JSON), confidence, bbox, mask key, source (`llm`/`human`) |
| `Prescription` (Verordnung, Muster 12) | first/follow-up, issued_at, period from/to, services[] (code, frequency, duration), ICD-10, doctor, doctor_signed, stamp_present, patient_signed, submitted_to_payer_at |
| `Approval` (Genehmigung) | payer, prescription, decision (full/partial/rejected), approved services & frequency, period, decision date |
| `VisitLog` (Leistungsnachweis) | patient, month, entries[] (date, time, service/LK, staff Handzeichen), patient_signature, provider signature |
| `StayEvent` | patient, type (hospital/reha/short-term care), admitted_at, discharged_at, source document |
| `Claim` | payer, patient, period, legal basis (SGB V/XI), lines[], computed total (from tariff), status |
| `ClaimLine` | date, service/Positionsnummer/LK, quantity, unit price (tariff version), source visit entry |
| `RuleResult` / `Finding` | claim/line, rule_id, rule_version, severity, message_de, message_en, evidence[] |
| `Action` | type (doctor renewal / patient signature / payer submission / internal), draft content, status, due_at |
| `Deadline` | kind, due_at (working-day calculated), related entity, reminder state |
| `AuditRun` / `Objection` | claim, round, objection text, cited rule/fact, verdict (upheld/dismissed), reason |
| `Payment` | claim, sent_at, paid_at, amount_paid, Absetzung code/reason, dunning stage |
| `RulePack` / `TariffTable` | version, valid_from, valid_to, Bundesland, checksum |
| `AuditLog` | who/what/when for every decision (shows traceability to judges) |

### 2.3 Processing pipeline (BullMQ jobs)

1. **ingest** — upload (drag & drop / mobile photo), store original, sha256 dedupe.
2. **preprocess** (vision service) — HEIC/PDF → PNG @ 200–300 dpi, page split, orientation, deskew, perspective correction for phone photos, quality score (blur/glare) → warn "please re-photograph".
3. **classify** (Muse Spark) — doc type: `muster12` · `approval_letter` · `visit_log_sgbv` · `visit_log_sgbxi` · `hospital_letter` · `other`; also detect multi-document scans.
4. **extract** (Muse Spark, JSON schema per type) — values + per-field confidence + approximate location (page + rough box if the model provides it) + "field present but unreadable" vs "field empty".
5. **validate** (deterministic) — KVNR / IK / LANR / BSNR check digits, date sanity, ICD-10-GM code exists, service codes known.
6. **link** — entity resolution: match patient (KVNR → name+DOB fuzzy), doctor (LANR/BSNR), payer (IK); attach to episode/period; flag conflicts.
7. **localize** (SAM 3.1) — for every field that a rule cares about (signatures, dates, stamp, checkbox), get a mask/box; prompt with a concept text ("signature", "stamp") and/or the rough box from step 4; store mask + crop.
8. **evaluate** (rules engine) — build claims from visit logs + tariffs, run rule pack valid for the service dates, write findings.
9. **act** (agent) — create actions & deadlines from findings (drafts only; nothing is sent automatically).
10. **audit** (auditor agent) — adversarial pass on 🟢 claims; resolver verifies each objection; update status.
11. **export** (P2) — bundle per payer: claim summary + required Belege (PDF) in the order the payer expects; optional §302/§105 data skeleton.

---

## 3. Master task list

### 3.0 Admin, access & decisions (do first — some have lead time)
- [ ] `ADM-01` P0 Read the full hackathon rules: deadline (+ timezone), required deliverables, judging criteria, model-usage requirements, pre-existing-code policy. Put them in `04-RESEARCH-NOTES.md`.
- [ ] `ADM-02` P0 Create a Meta Model API account at dev.meta.ai **from your German account now**: access is "where Meta has enabled access", so confirm signup works. Create a key and run a 5-line smoke test: one image → `muse-spark-1.3` with a JSON schema, and one image → `sam-3.1` with the prompt "signature". Check that the $150 hackathon credits land after you're accepted.
- [ ] `ADM-03` P0 SAM 3.1 runs through the API, so no GPU is needed. Test early whether SAM understands form concepts ("signature", "stamp", "checkbox", "table") on 10 synthetic pages. If not, use Muse Spark coordinates → SAM box prompt. Fallback: Roboflow Serverless SAM 3.
- [ ] `ADM-10` P1 Join the hackathon Discord on Oct 26. Attend the MSL workshops on Muse Spark vision + SAM. Ask in office hours about German handwriting and form segmentation.
- [ ] `ADM-11` P1 Optional credits: Baseten / Modal / Fireworks (for select participants). Only useful if you try Muse Glimmer 30B for the EU-self-host story.
- [ ] `ADM-04` P0 Check your Careville employment contract for side-project / IP / non-compete clauses (same domain!). Build on your own laptop, own accounts, no Careville code, data, customer names or documents. Ideally get a short written OK.
- [ ] `ADM-05` P0 Decide scope: one Bundesland (**Bayern** recommended — you live there; use Bavarian tariffs) and one billing month for the demo (e.g. Oct 2026).
- [ ] `ADM-06` P1 Recruit 1–2 domain reviewers (a PDL / billing person you know outside Careville work) for a 30-min rules sanity check and a 30-min demo feedback. No real patient documents.
- [ ] `ADM-07` P1 Create public GitHub repo (license: MIT or Apache-2.0), README skeleton, issue labels by task ID prefix.
- [ ] `ADM-08` P1 Name/brand check: "Kassenfest" domain + GitHub org availability; logo (simple wordmark).
- [ ] `ADM-09` P2 Decide demo hosting (Vercel/Netlify for web, Fly.io/Render/Railway for API, GPU host for SAM) vs. local-only demo video.

### 3.1 Project setup
- [ ] `SET-01` P0 pnpm monorepo, TS config, ESLint/Prettier, Husky/lint-staged.
- [ ] `SET-02` P0 `docker-compose.yml`: Postgres 16, Redis 7, MinIO, vision service.
- [ ] `SET-03` P0 NestJS app skeleton: config module (zod-validated env), health check, Prisma, BullMQ module, S3 client, logging (pino), global error filter.
- [ ] `SET-04` P0 React app skeleton: Vite, routing, Tailwind + shadcn/ui, TanStack Query, API client generated from OpenAPI (Nest Swagger → `openapi-typescript`).
- [ ] `SET-05` P0 Python vision service skeleton (FastAPI, uv/poetry, Dockerfile with CUDA base for GPU host; CPU/MPS path for local dev).
- [ ] `SET-06` P1 CI (GitHub Actions): lint, typecheck, unit tests for `packages/rules`, eval smoke test on 5 docs.
- [ ] `SET-07` P1 Secrets handling: `.env.example`, never commit keys; rate-limit + retry wrapper for Meta API.
- [ ] `SET-08` P1 i18n: German UI primary, English toggle (judges!).

### 3.2 Reference data (see `03-DATA-AND-INPUTS.md` §3 for sources)
- [ ] `REF-01` P0 Payer list (≈10 real Krankenkassen names + IK format; use clearly fake IKs or flag "demo").
- [ ] `REF-02` P0 Public holidays Bayern 2025–2027 → working-day calculator (`isWorkingDay`, `addWorkingDays`) with tests (Allerheiligen, Fronleichnam, Mariä Himmelfahrt nuance in Bavaria).
- [ ] `REF-03` P0 SGB XI amounts table 2025/2026 (Sachleistung per Pflegegrad, Entlastungsbetrag, Gemeinsamer Jahresbetrag, Beratungseinsatz).
- [ ] `REF-04` P0 HKP service catalog for the demo (subset: Medikamentengabe, Injektion, Blutzuckermessung, Kompressionsstrümpfe an/aus, Wundversorgung) with demo prices (mark as illustrative if Bavarian §132a prices aren't public).
- [ ] `REF-05` P0 SGB XI Leistungskomplexe subset (Bayern) with points/prices (illustrative if not public).
- [ ] `REF-06` P1 ICD-10-GM subset (diagnoses used in synthetic cases) for validation.
- [ ] `REF-07` P1 Check-digit algorithms: KVNR, IK, LANR, BSNR — implement + tests.
- [ ] `REF-08` P2 §302 / §105 Positionsnummern & data-exchange skeleton for export.

### 3.3 Synthetic data generator (`tools/synth`) — the backbone of demo + eval
- [ ] `SYN-01` P0 Case model: synthetic provider, 15–30 patients with Pflegegrad, payer, doctor, diagnoses, care plan; deterministic seed.
- [ ] `SYN-02` P0 Scenario engine: for each patient-month generate the "true" world (prescriptions, approvals, visits, hospital stays) + inject defects from the defect catalog (§4) with labels.
- [ ] `SYN-03` P0 Form renderers (lookalike, watermarked "SYNTHETISCH – KEIN ECHTES DOKUMENT"): Muster 12 front (+ back if needed), Genehmigung letter (3–4 payer letter styles), Leistungsnachweis SGB V and SGB XI (monthly grid), Krankenhaus-Entlassbrief / Aufnahmeanzeige.
- [ ] `SYN-04` P0 Ground truth export per document: all field values + bounding boxes (in page pixel coords) + signature/stamp boxes + defect labels (JSON).
- [ ] `SYN-05` P0 Handwriting: handwriting fonts with umlauts + jitter (baseline, size, slant) for names, dates, Handzeichen, ticks/crosses in checkboxes; signature generator (strokes/bezier scribbles or font).
- [ ] `SYN-06` P0 Stamps: Praxisstempel generator (rotated, partial ink, blue/purple).
- [ ] `SYN-07` P0 Degradation: print-scan (noise, JPEG, slight skew), fax (binarize, 200×100 dpi look), phone photo (perspective warp, shadow, blur, background table texture, glare) via Augraphy/albumentations.
- [ ] `SYN-08` P1 **Real handwriting set**: print 20–40 blank forms, have 3–5 people fill them with fake data from the generator, photograph with phones → most convincing demo + honest eval (see `03` §4).
- [ ] `SYN-09` P1 Splits: `dev` (iterate prompts), `test` (never look), `demo` (curated story).
- [ ] `SYN-10` P2 Corrections/overwrites on forms (crossed-out dates, Tipp-Ex) as hard cases.

### 3.4 Ingestion & preprocessing
- [x] `ING-01` P0 Upload API (multipart, multi-file, ZIP) + inbox UI with per-file status (SSE).
- [ ] `ING-02` P0 HEIC/JPEG/PNG/PDF → normalized PNG pages (vision service: pdf2image/PyMuPDF, pillow-heif).
- [ ] `ING-03` P0 Deskew + auto-rotate + perspective correction (OpenCV document-corner detection; reuse your GreyChess homography experience).
- [ ] `ING-04` P1 Quality gate: blur (Laplacian variance), glare, resolution → "re-photograph" warning.
- [ ] `ING-05` P1 Mobile capture page (phone browser camera, guides the user to fill the frame).
- [ ] `ING-06` P2 Fax/KIM inbox simulation (drop folder watcher).

### 3.5 Document understanding with Muse Spark
- [ ] `EXT-01` P0 `packages/llm`: provider interface; Meta Model API client (images as base64/URL, JSON-schema output, tool calls, retries, timeouts, token/cost logging).
- [ ] `EXT-02` P0 Classifier prompt + schema; test on all synthetic types; handle multi-page and mixed scans.
- [ ] `EXT-03` P0 Extraction schemas (zod → JSON Schema) for `muster12`, `approval_letter`, `visit_log_sgbv`, `visit_log_sgbxi`, `hospital_letter` (field lists in `03` §2).
- [ ] `EXT-04` P0 Extraction prompts in German with explicit instructions: distinguish **empty** vs **unreadable** vs **present**; never guess; return `null` + reason; dates as ISO; per-field confidence.
- [ ] `EXT-05` P0 Signature/stamp presence questions as separate focused calls on crops (higher accuracy than one giant prompt).
- [ ] `EXT-06` P0 Visit-log table extraction (day × service grid with Handzeichen) — hardest part; consider tiling the page into row bands and extracting per band, then merging.
- [ ] `EXT-07` P1 Self-consistency: extract twice (or full page + crop) and compare; disagreement → lower confidence → review queue.
- [ ] `EXT-08` P1 Review UI: side-by-side image + fields, accept/correct, keyboard-driven; corrections stored as `source=human`.
- [ ] `EXT-09` P1 Few-shot library from corrections (dynamic examples per doc type).
- [ ] `EXT-10` P1 Prompt-injection hygiene: document text is data; system prompt says so; strip/ignore instructions found on scans (also a nice judge talking point).
- [ ] `EXT-11` P2 Cost/latency dashboard per document.

### 3.6 Evidence localization with SAM 3.1
- [ ] `SAM-01` P0 Call `sam-3.1` through the Meta API on sample pages. Record latency and the hit rate for each concept noun. Decode output with `@meta-sam/parser` / `meta_sam_parser`.
- [ ] `SAM-02` P0 Internal endpoint `POST /segment` (image + one concept or box/points) → masks + boxes + scores. Request `include_confidence`. Treat empty output as "not found".
- [ ] `SAM-03` P0 Strategy per evidence type: (a) concept prompt ("signature", "stamp", "checkbox", "date field"); (b) box prompt from Muse Spark's rough location; (c) fallback: template anchor (known form layout) → box. Pick the best by score + overlap with expected region.
- [ ] `SAM-04` P0 "Empty signature box" detection: segment the box region, compute ink density inside the mask → empty/present (deterministic, explainable) — combine with Muse Spark's judgement.
- [ ] `SAM-05` P0 Render evidence overlay (mask outline + label) in the viewer; store crop PNG for the finding card and auditor.
- [ ] `SAM-06` P1 Eval: IoU vs synthetic ground truth boxes; precision of "empty vs signed" classification.
- [ ] `SAM-07` P2 Cache masks by page hash; batch pages.

### 3.7 Rules engine (`packages/rules`)
- [ ] `RUL-01` P0 Engine core: `Rule { id, version, appliesTo, severity, evaluate(ctx) → Finding[] }`, rule pack loader (YAML params + effective dates), result explanation templates (DE/EN) with legal source links.
- [ ] `RUL-02` P0 Context builder: from DB entities → normalized `ClaimContext` (patient, period, prescriptions, approvals, visits, stays, tariffs, calendar).
- [ ] `RUL-03` P0 Implement the P0 rules from `02-RULES-CATALOG.md` (~25 rules):
  - **HKP prescriptions:** `HKP-RX-REQUIRED`, `HKP-RX-SIGNED`, `HKP-ERST-14D`, `HKP-FOLGE-WINDOW`, `HKP-SUBMIT-4WD`
  - **HKP approval and matching:** `HKP-APPROVAL-EXISTS`, `HKP-APPROVAL-SCOPE`, `HKP-FREQ-RX`, `HKP-LN-MATCH`, `HKP-DUPLICATE`, `HKP-POSITION-PRICE`
  - **HKP visit records:** `HKP-302-FIELDS`, `HKP-LN-SIGNATURE`, `HKP-STAFF-INITIALS`
  - **Hospital stays:** `STAY-HKP`, `STAY-XI-SACH`
  - **SGB XI:** `XI-PG-VALID`, `XI-36-BUDGET`, `XI-45B-ENTL`, `XI-45B-ABTRETUNG`, `XI-105-FIELDS`, `XI-LN-SIGNATURE`, `XI-PRICE`
  - **Master data:** `MD-KVNR-CHECK`, `MD-IK-CHECK`, `MD-INSURED`, `MD-DECEASED`
  - **Document quality:** `DOC-READABLE`, `DOC-LINKED`, `DOC-SYNTHETIC`
- [ ] `RUL-09` P1 Rule packs by effective date (`2025-01`, `2025-07`, `2026-01`, …) and a clearly labelled **`2027-01-draft` (PNOG, not law)** pack. Demo: switch the pack, re-run October and show the diff.
- [ ] `RUL-04` P0 Tariff calculator: claim lines × tariff version → amounts (pure function, unit-tested, cents as integers).
- [ ] `RUL-05` P0 Unit tests per rule: one passing + one failing fixture each, plus boundary dates (deadline on Friday before a holiday, period end on the 31st, leap year).
- [ ] `RUL-06` P1 Rules admin page: list rules, parameters, versions, valid_from; toggle; "what changed in 2025 / 2026" view (sells the "easy to update" claim).
- [ ] `RUL-07` P1 Simulation: re-run a past month under a new rule pack → diff of findings.
- [ ] `RUL-08` P2 Decision-table editor (e.g. GoRules ZEN/JDM) for non-developers.

### 3.8 Agent: fix problems (Muse Spark tool calling)
- [ ] `AGT-01` P0 Tool definitions: `get_claim_findings`, `get_patient_context`, `get_document_evidence`, `compute_deadline`, `draft_letter(type, recipient, facts)`, `create_task`, `schedule_reminder`. Tools are thin wrappers over the API — the agent never writes DB state except drafts/tasks.
- [ ] `AGT-02` P0 Letter templates (German, formal): Folgeverordnung request to doctor (fax/KIM style), request for missing doctor signature/stamp, patient/relative signature request for Leistungsnachweis, cover letter to Kasse for late-submitted Verordnung, Rückfrage on partial approval.
- [ ] `AGT-03` P0 Deadline service: Verordnung submission deadline, Folgeverordnung window, Entlastungsbetrag carry-over expiry, billing/limitation deadlines → countdown chips + reminder list.
- [ ] `AGT-04` P1 Agent run trace in UI (tool calls with inputs/outputs) — shows judges real tool use.
- [ ] `AGT-05` P1 Export letter as PDF (pdf-lib) with provider letterhead; "copy for fax".
- [ ] `AGT-06` P2 KIM / e-mail sending (out of scope for demo — drafts only).

### 3.9 Auditor agent ("Prüfer der Kasse")
- [ ] `AUD-01` P0 Auditor system prompt: role = strict Krankenkasse/MD billing auditor; goal = find any reason to reject or cut the claim; must cite `rule_id` or a concrete document fact with page reference; output JSON objections via `response_format: json_schema` (not tool calls, because `tool_choice` can't be forced); `reasoning_effort: high`. Follow Meta's cookbook "Multi-agent orchestration" recipe.
- [ ] `AUD-01b` P0 Give the auditor the **official Kasse rejection codes** (TA HKP 10.1 / TA5: 41002, 41003, 42002–42009, 43001–43005, 44001–44004) as its *only* vocabulary, plus `FACT` with document/page/field. Map codes → rules (`02-RULES-CATALOG.md` §9). Soft "experience" signals (identical Handzeichen, impossible travel times) may only be raised as `info`.
- [ ] `AUD-02` P0 Resolver: for each objection → if it cites a rule, re-run that rule; if it cites a fact, check against extracted fields/evidence; mark `upheld` / `dismissed (reason)`.
- [ ] `AUD-03` P0 Loop: up to N rounds (e.g. 2); claim status = 🟢 only if no upheld objection.
- [ ] `AUD-04` P1 "Debate" UI: objections, evidence crops, verdicts.
- [ ] `AUD-05` P1 Auditor eval: seeded "subtle" defects the rules engine doesn't cover (e.g. Handzeichen pattern identical on all days, implausible visit times, same pen/ink for a whole month) → measure catches vs hallucinations.
- [ ] `AUD-06` P2 Different model temperature/persona per payer.

### 3.10 Receivables (open payments)
- [ ] `REC-01` P0 Claim lifecycle: draft → checked → sent → paid / partially paid (Absetzung) / rejected → resubmitted.
- [ ] `REC-02` P0 Synthetic payment history (last 6 months) incl. Absetzungen with reasons.
- [ ] `REC-03` P0 Dashboard: open amount by payer & age bucket (0–30/31–60/61–90/90+), top reasons, "money at risk this month" from current findings.
- [ ] `REC-04` P1 Import of a payment advice/Zahlungsavis (CSV) to mark payments.
- [ ] `REC-05` P2 Dunning reminders / Zahlungserinnerung drafts.

### 3.10b Export to the coming electronic format ("why now")
- [ ] `EXP-01` P1 Map the internal `VisitLog` to **TA HKP 1.3.0 §9.8 "Elektronischer Leistungsnachweis"** XML (valid from 01.02.2027). Fields: Leistungserbringer_IK, KVNR, Verantwortliche_Fachkraft, Einsatz{Beginn_Datum_Uhrzeit, Ende_Uhrzeit, Positions_Nr, Menge, Beschaeftigtennummer}, Unterschrift_Versicherter or fehlende_Unterschrift + Kennzeichen_Grund, UUID. Validate against the official XSD. Pitch line: "Kassenfest turns today's paper into the format Kassen will soon require."
- [ ] `EXP-02` P2 Same for SGB XI via TA5 1.2.0 (TI transmission, from 01.02.2027).
- [ ] `EXP-03` P2 Per-payer PDF bundle (claim summary + Belege) for paper-based Kassen.

### 3.11 Frontend screens
- [ ] `UI-01` P0 Inbox / upload with live pipeline status.
- [ ] `UI-02` P0 Bill board for the month: cards per patient×payer with 🟢🟠🔴, money amount, top finding.
- [ ] `UI-03` P0 Claim detail: lines, findings (rule, explanation, source link), evidence thumbnails, actions.
- [ ] `UI-04` P0 Evidence viewer: page image, zoom/pan, mask overlay, field list hover ↔ highlight.
- [ ] `UI-05` P0 Patient timeline: prescriptions, approvals, visits, hospital stays on one time axis (overlaps visible at a glance).
- [ ] `UI-06` P0 Actions & deadlines list with countdowns.
- [ ] `UI-07` P1 Auditor debate view; agent trace view.
- [ ] `UI-08` P1 Receivables dashboard.
- [ ] `UI-09` P1 Rules admin / "what changed" page.
- [ ] `UI-10` P1 Metrics page (eval results) — great for judges.
- [ ] `UI-11` P2 Mobile capture page.

### 3.12 Evaluation harness (`eval/`)
- [ ] `EVL-01` P0 Extraction metrics per field and doc type (exact match, normalized match for dates/names, F1 for list fields), split by clean/fax/photo/real-handwriting.
- [ ] `EVL-02` P0 Defect detection: per defect type recall/precision vs seeded labels.
- [ ] `EVL-03` P1 Localization IoU / hit rate (center of mask inside GT box).
- [ ] `EVL-04` P1 Auditor: valid catches, invalid objections, rounds needed.
- [ ] `EVL-05` P1 Latency + cost per document and per claim.
- [ ] `EVL-06` P1 Regression run in CI on a 10-doc smoke set.

### 3.13 Security, privacy, compliance story (judges will ask)
- [ ] `SEC-01` P0 README section "Data protection": synthetic-only; why real data would need DSGVO Art. 9 basis, AVV/DPA, §203 StGB considerations, EU hosting → Muse Spark Open roadmap.
- [ ] `SEC-02` P1 Audit log of every automated decision (who/what/rule version/model version).
- [ ] `SEC-03` P1 Basic auth for the hosted demo (single demo user); no open upload endpoint on the internet.
- [ ] `SEC-04` P2 PII redaction before LLM calls (crop only needed regions) — design note for production.

### 3.14 Demo, video & submission
- [ ] `DEM-01` P0 Demo story (`docs/DEMO-SCRIPT.md`): "Pflegedienst Sonnenschein, Deggendorf, end of October 2026 — €X of €Y would have been cut." 5 hero patients, each showing one failure type + 1 clean.
- [ ] `DEM-02` P0 Seed script that resets the demo DB to the exact story state (repeatable recording).
- [ ] `DEM-03` P0 Record demo video (length per hackathon rules), voice-over in English, German UI with English toggle shown once.
- [ ] `DEM-04` P0 README: problem, solution, architecture diagram, how Muse Spark + SAM 3.1 are used (explicitly), eval numbers, how to run, limitations, roadmap.
- [ ] `DEM-05` P0 Submission form + repo link + video link before deadline (with buffer).
- [ ] `DEM-00` P0 **Fix the problem claim.** Your application says "studies show missing documents are the main cause of late payments". That isn't supported for home-care services. Use the sourced framing in `04-RESEARCH-NOTES.md` §3: payment delays push services toward insolvency, and Kassen audit with AI while providers don't.
- [ ] `DEM-06` P1 Slide/one-pager: problem numbers (with sources), market size, why now (2025/2026 rule changes, TI), business model (per-claim or per-patient SaaS), EU/open-weight roadmap.
- [ ] `DEM-07` P1 Dry-run with someone who doesn't know the domain — can they follow in 3 minutes?
- [ ] `DEM-08` P2 Live deployed demo link.

---

## 4. Defect catalog (seed these into synthetic data; each maps to rules in `02`)

| ID | Defect | Doc where it shows | Expected outcome | Evidence shown |
|---|---|---|---|---|
| D01 | Visits after Verordnung end date | Muster 12 + Leistungsnachweis | 🔴 lines after end date | date field on Muster 12 |
| D02 | No Genehmigung for HKP period | (missing doc) | 🟠 until approval arrives | "no approval found" + timeline gap |
| D03 | Approval covers fewer services / lower frequency than billed | Genehmigung | 🔴 excess lines | approved-services table region |
| D04 | Patient signature missing on Leistungsnachweis | Leistungsnachweis | 🟠 → signature request | **empty signature box (SAM)** |
| D05 | Staff Handzeichen missing on some days | Leistungsnachweis | 🟠 lines for those days | empty cells |
| D06 | Visits during hospital stay | Entlassbrief + Leistungsnachweis | 🔴 overlapping days | admission/discharge dates |
| D07 | Verordnung reached the Kasse after the **4th working day** after issue → no provisional payment until approval | Muster 12 issue date + submission log (fax report / KIM receipt) | 🟠/🔴 (days before approval at risk) | issue date + submission date |
| D08 | Folgeverordnung not requested in time | Muster 12 | 🟠 action + countdown | period end date |
| D09 | Doctor signature or practice stamp missing | Muster 12 | 🔴 | empty stamp/signature area |
| D10 | Prescribed/approved frequency < billed frequency (n/a for **Blankoverordnung**, where the nurse sets the frequency, but then check against the approval) | Muster 12 + Leistungsnachweis | 🔴 excess | frequency field |
| D11 | Erstverordnung longer than allowed | Muster 12 | 🟠 | period fields |
| D12 | SGB XI Sachleistung budget exceeded | tariffs + Pflegegrad | 🟠 → private Eigenanteil invoice | budget calc |
| D13 | Entlastungsbetrag carry-over expired / no Abtretung | Abtretungserklärung | 🔴 | missing doc |
| D14 | Pflegegrad changed mid-month | approval letter / Bescheid | 🟠 split month | Bescheid date |
| D15 | Patient deceased / Kassenwechsel | master data | 🔴 lines after date | — |
| D16 | Wrong / invalid KVNR or IK | any | 🔴 | field |
| D17 | Corrected date on Verordnung without doctor initials | Muster 12 | 🟠 | crossed-out area |
| D18 | Duplicate billing (same service, same day, twice) | Leistungsnachweis | 🔴 | duplicate rows |
| D19 | Unreadable photo | any | review queue | blur score |
| D20 | Clean case | — | 🟢 survives auditor | — |

---

## 5. Schedule (real dates; submission deadline Nov 4, 21:00 ET = Nov 5, 03:00 CET)

| Date | Focus | Exit criterion |
|---|---|---|
| **Oct 22–25** (before kickoff) | No product code until the rules are known. ADM-02 API smoke test, ADM-04 employer check, ADM-05 scope. Collect blank forms and reference data (`03` §1–3). Finalize the rules catalog with a domain reviewer. Print forms for the handwriting session. Write the demo story. | API key works; rules catalog reviewed; forms + reference data in `data/` |
| **Oct 26** | Read the Official Rules (deliverables, video length, pre-existing code). Watch the kickoff. Join Discord. Update this plan. | Constraints written into `04-RESEARCH-NOTES.md` |
| **Oct 27** | SET-01..05, REF-02/03/07, EXT-01 | Muse Spark returns valid JSON for one synthetic Muster 12 |
| **Oct 28–29** | SYN-01..07, EXT-02..06, SAM-01..03 | 150+ synthetic docs with ground truth; extraction end-to-end; SAM concept hit rates known |
| **Oct 30** | RUL-01..05, AGT-03, SAM-04..05 | Findings with evidence overlays for D01–D10 |
| **Oct 31 – Nov 1** | AGT-01..02, AUD-01..03, REC-01..03, UI-01..06; **SYN-08 handwriting session (weekend!)** | Letters drafted; auditor loop working; real-photo docs captured |
| **Nov 2** | EVL-01..04, UI-07..10, fix the worst extraction failures | Metrics table, auditor eval |
| **Nov 3** | DEM-01..02, DEM-04, README, freeze features at 18:00 | Repeatable demo seed, README done |
| **Nov 4** | DEM-03 video, DEM-05 submit **by 18:00 CET**, buffer | Submitted |

**Cut order if time runs out:** P2 → mobile capture → rules admin → receivables import → auditor UI polish. Never cut: evidence overlay, deterministic rules, auditor grounding, eval numbers.

---

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Muse Spark struggles with the visit-log grid / handwriting | Row-band tiling, crops, self-consistency, human review queue; report honest per-condition accuracy |
| SAM 3.1 doesn't understand form concepts ("signature box" isn't a natural-image noun) | Muse Spark coordinates → SAM box prompt; template-anchor fallback; ink-density check is deterministic anyway |
| Muse Spark Open is too big to self-host (816B MoE, ~700 GB VRAM for NVFP4) | Pitch the EU story honestly: Muse Spark Open on EU GPU cloud for production, or **Muse Glimmer 30B (Apache 2.0, fits on one GPU)** as the lean EU option |
| Official Rules forbid pre-existing code | Code nothing that ships before Oct 26; keep prep to docs/data |
| API rate limits / outages during recording | Cache all model responses for demo docs (record/replay mode keyed by image hash + prompt version) |
| Rules wrong or outdated | Every rule cites its source + effective date; domain reviewer pass (ADM-06); label demo prices "illustrative" |
| Judges see "just OCR + if-statements" | Emphasize: evidence localization, adversarial auditor with grounding, measurable eval, rule versioning for 2025/2026 changes |
| Employer conflict | ADM-04 before writing code |
| Scope creep | P0 list is the contract; everything else is optional |
