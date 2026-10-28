# Spike results (living log)

Numbers from real API calls. Each entry: what was tested, result, decision. Sample sizes are stated — **n=1 is a signal, not a result.**

---

## 2026-10-27 — `make smoke` (pre-spike, n=1)

**Input:** one clean synthetic card (1400×900 PNG, printed Arial text, procedural Bézier signature in a box, rotated violet stamp). Code: `backend/src/kassenfest/smoke.py`.

| Check | Result |
|---|---|
| Muse Spark 1.3 JSON schema (`reasoning_effort=low`) | schema-valid on first try; 4/4 printed fields exact (name, KVNR, 2 ISO dates) |
| Muse Spark presence: signature / stamp | both `true` ✓ |
| Muse Spark boxes (0–1000 grid → px) | signature IoU **0.74**, stamp IoU **0.63** — right place, loose edges |
| SAM concept `"signature"` | **no match** (empty output) |
| SAM concept `"stamp"` | 1 segment, IoU **0.97**, confidence **0.61** |
| Muse Spark box → SAM box prompt (signature) | IoU **0.99**, mask 445×141 |
| Latency | Muse Spark 3.7 s · SAM 1.3–1.9 s |
| Cost | Muse Spark $0.0049 (2,126 in / 526 out, of which **392 reasoning**) · SAM $0.0025 each · total $0.0124 |
| Replay | 2nd run in `replay` mode: 4/4 cache hits, $0, identical output |

**API facts confirmed:**
- Muse Spark boxes use the 0–1000 grid as documented; the client's `from_norm1000` conversion is correct.
- `usage.completion_tokens` **includes** reasoning tokens (392 ≤ 526, total = prompt + completion) → `chat_cost` is right.
- SAM non-streaming `responses.create` returns the grammar in `output[].content[].output_text`; `meta_sam_parser` parses it (box + lossless mask + `c`).
- SAM confidence on an easy, clean stamp is only 0.61 → **don't hard-threshold at 0.7+**; calibrate on the dev set.

**Provisional decisions (to confirm in S3/S4 on Wednesday with ≥20 pages incl. photos + handwriting):**
1. **Evidence boxes = Muse Spark box → SAM refine** for signatures (Meta's recommended pairing). Muse Spark alone is too loose for an evidence overlay; SAM concept prompt missed the signature.
2. **Stamps: try SAM concept `"stamp"` first**, fall back to box refine.
3. S3 must still try other concept phrasings for signatures (`"handwritten signature"`, `"handwriting"`, `"scribble"`, `"ink"`) on realistic signatures before we drop concept mode for them.
4. At ~$0.005 per Muse Spark page call + ~$0.005 SAM, the whole plan (≈155 docs × a few runs) stays **< $10** — cost is not a constraint; latency (≈4 s/page) is what to parallelize.

## 2026-10-27 — shared schemas vs. the live API (n=1 per schema)

Each model-facing schema in `kassenfest.schemas` sent once with the smoke card, `reasoning_effort=minimal`. Total **$0.057**.

| Schema | Inlined depth / props | Accepted | Latency | Cost | Behaviour on the smoke card |
|---|---|---|---|---|---|
| `Muster12` | 4 / 194 | ✓ | 4.0 s | $0.014 | 6 fields `present` (incl. **BSNR read from the stamp**), signature + stamp `present`, nothing invented |
| `ApprovalLetter` | 4 / 146 | ✓ | 3.4 s | $0.009 | all `empty`, 0 items — no hallucination on the wrong doc type |
| `VisitLogSGBV` | 4 / 126 | ✓ | 3.1 s | $0.009 | all `empty`, 0 entries, signatures `absent` |
| `VisitLogSGBXI` | 4 / 95 | ✓ | 2.7 s | $0.008 | all `empty`, 0 entries |
| `HospitalLetter` | 3 / 130 | ✓ | 3.2 s | $0.010 | all `empty` |
| `Classification` | 3 / 6 | ✓ | 2.0 s | $0.003 | `muster12`, conf 1.0, **synthetic watermark detected** |
| `AuditorOutput` | — | ✓ | 2.1 s | $0.002 | ⚠️ given an *empty* claim, still objected with **41002** ("no valid insurance") |

**Decisions:**
- The strict-subset shape (all keys required, `additionalProperties: false`, no numeric constraints) is accepted as-is; keep it. Unit test `test_llm_schemas_fit_meta_structured_output_limits` guards it.
- `Mark.state = absent` on a document type that has no such field is expected — rules must only read marks from the right `doc_type`.
- **The auditor invents objections when there is nothing to object to** → the deterministic resolver (AUD-02) is mandatory, and the auditor prompt must say an empty list is a valid answer. Track this rate in AUD-05.

---

## 2026-10-27 — Spikes S1–S4 (`kassenfest spike all`)

**Inputs** (`var/spikes/docs/`, regenerate with the command): 8 Muster 12 × {clean, scan, photo} = 24 images, mixed printed/handwritten modes, 2 without stamp and 2 without doctor signature; 4 HKP Leistungsnachweise × {clean, photo} = 8 images with 62–186 visits each, 3 missing Handzeichen each, 2 without patient signature. Handwriting = `hand_dev` fonts with per-glyph jitter. Prompt `EXTRACT_SYSTEM v1` (`llm/prompts.py`). Total spend for all spikes ≈ **$3.3**.

### S1 — Muster 12 extraction (24 images, field-level, values normalized)

| | printed (n=195) | handwritten (n=165) | marks (n=48) | measures (n=306) | median latency | cost / doc |
|---|---|---|---|---|---|---|
| `low` | **100%** | **98.8%** | **100%** | 97.4% | **5.8 s** | $0.011 |
| `medium` | 100% | 99.4% | 100% | 98.7% | 10.7 s | $0.017 |

By variant (`low`, all fields): clean 100% · scan 99.3% · photo 99.3%. Misses were single fields (one ICD list, one `period_to`, one KVNR at medium). No invented values on absent stamps/signatures.

### S2 — Leistungsnachweis grid (8 images, entries matched by date + service + time)

| | recall | precision | time exact | Handzeichen present/absent | latency | cost / doc |
|---|---|---|---|---|---|---|
| **full page, `medium`** | **100%** (8/8 docs) | **100%** | 96–100% | 99–100% | 25–65 s | $0.06–0.13 |
| 3 row bands + full page as context | 100% | 97–100% | 79–100% | 99–100% | 26–58 s | $0.08–0.24 |

Header fields 100% once the billing month is normalized (model writes `10/2026`, schema asks `YYYY-MM`). Patient signature present/absent correct on all 8.

### S3 — SAM 3.1 on marks (24 Muster 12 images)

| Prompt | signature (18 present) | stamp (18 present) | false positives on absent (6 + 6) |
|---|---|---|---|
| concept `"signature"` / `"handwritten signature"` | **0/18** | — | 0 |
| concept `"stamp"` | — | **18/18**, IoU ≈ 0.90–0.93 | 0 |
| concept `"rubber stamp"` | — | 0/18 | 0 |
| Muse Spark mark box alone | IoU 0.70 / 0.58 / **0.31** (clean / scan / photo) | 0.86 / 0.80 / 0.62 | — |
| **Muse Spark box → SAM box refine** | IoU 0.53 / 0.53 / **0.55** | **0.93 / 0.91 / 0.89** | — |

Caveat: signature truth boxes are currently the whole SVG frame / text line box, looser than the ink; SAM's refined box is ~55–60% of that area, i.e. tight to the ink, so the signature IoUs above *understate* refine. Reported to the synth track to fix in `render.py`.

### S4 — Muse Spark boxes (24 images, `medium`) and S4b — SAM refine on text fields

| Box source | printed fields | handwritten fields | marks |
|---|---|---|---|
| Muse Spark (0–1000 grid → px) | IoU 0.41, centre hit 67% | IoU 0.43, centre hit 66% | IoU 0.70, centre hit 88% |

S4b, text fields `kvnr`, `issue_date`, `period_from`, `period_to` (n=32 per variant):

| | clean | scan | photo |
|---|---|---|---|
| Muse Spark box | IoU 0.40, hit 62% | 0.54, 78% | 0.48, 81% |
| Muse box padded 15% | 0.38, 81% | 0.47, 81% | 0.48, 91% |
| **Muse box → SAM refine** | **0.60, 72%** | **0.71, 78%** | **0.63, 91%** |

### Decisions

1. **Extraction granularity:** one whole-page call per document; **`reasoning_effort=low` for Muster 12** (same accuracy within noise, half the latency). Re-run at `medium` only for documents with low-confidence or failed-validation fields (EXT-07).
2. **Grid strategy:** **full page wins**; row banding is dropped (never better, 1.5–1.9× cost, one photo run lost 20 pts of time accuracy). Visit logs are the latency bottleneck (25–65 s at `medium`) → run them first and in parallel; try `low` for visit logs during prompt iteration (Fri).
3. **SAM prompt mode:** **stamps → concept `"stamp"`**; **signatures → Muse Spark box → SAM box refine** (concept prompts never hit a signature). No SAM call for marks the model reports `absent`: evidence is the empty field box, confirmed by the ink-density check (SAM-04).
4. **Evidence boxes:** **Muse Spark box → SAM refine for every field a finding cites** (text fields included): +0.15–0.20 IoU over Muse Spark alone. Template registration (`ING-03`) stays Tier B — not needed for the demo.
5. **Normalization belongs in the validate step:** billing month `MM/YYYY` → `YYYY-MM` (and the same tolerant parsing the scorer uses) before rules see the value.

### Honest limits of these numbers
- Synthetic handwriting (jittered fonts) is **near the ceiling** (98.8–100%): it can't separate prompt variants any more and certainly overstates real handwriting. This raises the value of the optional real-handwriting set (`docs/05` §4.2) and of harder synthetic variants (`bad_photo`, messier hands) for the frozen test set.
- n = 24 / 8 images; differences of ±1–2 pts between `low` and `medium` are noise.

**Not tested yet:** real handwriting, `bad_photo` and fax variants, empty-vs-unreadable on genuinely illegible ink, multi-page input, the other three document types (rendered by the synth track).

---

## 2026-10-27 — first pipeline run (`kassenfest ingest var/spikes/docs`)

All 32 spike images through ingest → classify → extract → validate → localize → SQLite: **32/32 classified correctly**, 32/32 `done`, 20 s wall time (extraction served from the spike cache), **$0.25** for the new calls (32 classify + 30 SAM refine).

**Ink-density check (SAM-04) calibration**, using Muse Spark's mark boxes as the pipeline does:

| | n | min | median | max |
|---|---|---|---|---|
| truly empty fields | 16 | 0.000 | 0.010 | **0.048** (printed label inside the visit-log cell, scan noise) |
| signed / stamped fields | 48 | **0.000** (model box missed the ink) | 0.057 | 0.287 |

The distributions overlap, while the model's own present/absent call was right **64/64** → **the model decides; ink is a second opinion** that only raises a review issue on strong disagreement (empty but ink > 0.08, or present but ink < 0.0005). Two guards came out of the run:
- **SAM refine is rejected when it grows the box past 1.4×** or lands on blank paper. In every growth case the model's rough box was already wrong (IoU ≤ 0.3); good refinements shrink to 0.44–1.14×.
- **Stamps found by SAM's `"stamp"` concept skip the ink veto**: pale, speckled stamp ink on photos scores ~0.002 even inside the true box.

Result: 3 review flags, all the same document (seed 05) where Muse Spark puts the doctor's signature box on blank paper in every variant — a genuine localization miss, now routed to a human instead of drawn wrong. Present marks never trigger findings; the evidence the demo shows is the **empty** field box, which is unaffected.

---

## 2026-10-28 — walking skeleton on the demo set

`kassenfest ingest data/synthetic/demo/pages`: 42 pages (14 patient-months, 16 defect kinds planted) through classify → extract → validate → link → localize, then `pipeline/month.py` builds one CaseFile per patient and runs the rules. **$1.55** for 141 calls, **90 s** wall time; `LLM_MODE=replay` reproduces it with no API key.

**Case builder first, model second.** Perfect readings (`synth.oracle`) through link → case builder → rules give *exactly* the truth's findings: same rules, severities and billed lines in all 14 cases (`tests/test_casefile.py`). Facts a page can't show come from the Pflegedienst's records, as in real life: the fax server's send reports (when a Verordnung reached the Kasse, HKP-SUBMIT-4WD), claims already sent (HKP-DUPLICATE), and the death date (Kennzeichen 1 on an unsigned SGB XI log, a box that form doesn't have).

**Live readings:**

| | result |
|---|---|
| classification | 42/42 |
| patient link | 42/42 (40 by KVNR; 2 by name + birth date after a misread KVNR) |
| claims | 15/15 with the truth's line count and total |
| block/warn rules per case | 14/14 cases identical to the rules on the truth |
| affected lines | identical except 5 rules where a misread handwritten time (07:11 → 07:08) moves a line; no finding changes |
| demo story | Albers 🔴 Brandl 🔴 Christl 🟠 Dengler 🔴 Eder 🟢🟢 |

- **D19 (blurred photo)** was read with confidence ≥ 0.85, overconfident, but both 9-digit IKs came back with 8 digits. `validate` now makes a value that can't be on the paper `unreadable`, and DOC-READABLE sends the page to a human. Check digits stay out of this: a wrong number in the provider's records (D16) is read correctly and must stay readable for MD-KVNR-CHECK.
- **DOC-READABLE also fires on 3 visit logs** for rows the model itself rated 0.55–0.65; on Christl's log those are exactly the rows with the misread times. Honest review flags, not noise.
- **Evidence boxes are the weak part.** Field boxes served to the viewer vs. truth: median IoU 0.54 scan, 0.48 clean, 0.27 photo, 0.07 fax (54% ≥ 0.3 overall). Centres are within 2–36 px; the rest is a per-page perspective warp and cell-sized boxes against tight text boxes. 4 signature boxes on photos/faxes sit 50–130 px off the ink, so the ink check flags them for review. Next: SAM refine for every field a finding cites (decision 4 above), measured with the same script.

### Evidence boxes, same day: grid rows and batched SAM refine (`kassenfest eval-boxes`)

Most evidence is visit-log rows (220 of 256 evidence items in the month), and the row boxes were the real problem. Muse Spark's rows drift down a 31-row grid: right at the top, a row or more off by the bottom, and every row one off on two photos. Only **29%** of rows contained their own entry's ink. SAM can't fix that: refining a box on the wrong row tightens the wrong row's ink.

**Rows → the printed grid** (`vision/grid.py`): find the horizontal ruling lines in narrow strips (each strip on its own, so tilted photos still line up), take the longest regularly spaced run, count the day rows up from the table's bottom line, and tighten to the pen ink inside the day's band, within the model's columns. Rejected (model box kept) when the grid isn't clean or disagrees with the model by more than 3 rows. **No model call.**

**Fields → SAM refine, batched** (`pipeline/evidence.py`): up to 16 boxes per SAM call, so every read field costs about one call per page, $0.12 for the month. A padded retry for boxes on blank paper was tested and dropped: median IoU 0.12 → 0.21, but fewer boxes ≥ 0.3 (27% → 23%) and 25 got worse.

| served boxes vs truth | before | after |
|---|---|---|
| visit-log rows on the right entry, scans | 24% | **100%** (193/193) |
| visit-log rows on the right entry, photos | 32% | **99%** (369/373) |
| fields, median IoU (≥ 0.3), clean | 0.48 (69%) | **0.72** (73%) |
| fields, scan | 0.53 (76%) | **0.64** (77%) |
| fields, photo | 0.27 (45%) | 0.31 (51%) |
| fields, fax | 0.07 (28%) | 0.04 (40%) |
| fields, all 518 | 0.34 (54%) | **0.44** (58%) |

Findings are unchanged (14/14 cases still match the truth), and a fresh replay rebuild (`LLM_MODE=replay kassenfest ingest`) reproduces every box with no cache miss: the refine requests depend on the extraction alone.

**Still weak:** text fields on photos and faxes where Muse Spark's box misses the ink entirely (e.g. Frau Albers' "bis 14.10.2026", drawn just below the handwriting); SAM rightly refuses to refine blank paper. Candidate fix: re-ask Muse Spark on a crop around the box for the few cited fields SAM couldn't tighten. SGB XI logs (days as columns) have no row boxes at all yet.

### Crop re-ask, same day: what SAM couldn't tighten

After the SAM pass, 134 read fields with a truth box still had the model's own box (median IoU 0.12): mostly text and signatures on photos and faxes, where Muse Spark's box sits next to the ink. Each now gets a second question (`find_on_crops` in `pipeline/localize.py`). Muse Spark looks at a crop around its first box (1.5 box heights or 6% of the page up and down, half a box or 4% sideways) and boxes the value it already read. SAM then refines that box. It costs one Muse call per field (about $0.004), plus batched SAM.

On those 134 fields:

| variant | median IoU | ≥ 0.3 | better / worse |
|---|---|---|---|
| model's box | 0.12 | 28% | |
| crop at its natural size (~350 px), usual SAM guards | 0.27 | 49% | 53 / 22 |
| crop upscaled to ~1000 px, usual SAM guards | 0.52 | 69% | 73 / 5 |
| upscaled, SAM may grow the box 2×, no ink check | **0.63** | **83%** | 108 / 11 |

- **Upscaling is what works.** On a small crop, Muse's box missed the value by about a text line a quarter of the time (Frau Albers' date was boxed between "vom" and "bis").
- **No ink check on this path.** `ink_ratio` reads 0.000 inside tight text boxes on most photo pages, because its 31 px median-blur paper estimate sees mostly ink. It threw away good boxes, e.g. SAM's 0.79 on 017's issue date. It stays unchanged for marks, whose boxes are larger and where it is calibrated.
- **The read-back doesn't work as a guard.** The answer's `text` didn't separate good boxes from bad: Muse reads the right value even when its box is a line off. It stays in the schema only because the measured requests include it.

Whole month, served boxes for all 518 fields with a truth box (the model's own boxes: 0.34, 54% ≥ 0.3):

| median IoU (≥ 0.3) | before the crop re-ask | after |
|---|---|---|
| clean | 0.72 (73%) | **0.78** (79%) |
| scan | 0.64 (77%) | **0.71** (82%) |
| photo | 0.31 (51%) | **0.56** (70%) |
| fax | 0.04 (40%) | **0.50** (62%) |
| bad photo | 0.01 (25%) | 0.18 (42%) |
| all 518 | 0.44 (58%) | **0.61** (73%) |

**Cited fields:**

| Field | Before (IoU) | After (IoU) |
|---|---|---|
| Frau Albers' "bis 14.10.2026" | 0.00 | 0.80 |
| 017's issue date | 0.59 | 0.79 |
| The fax KVNR | 0.35 | 0.86 |
| The bad photo's IK | 0.00 | 0.31 (0.68 with single-box SAM calls in the experiment) |

The 7 signatures that SAM missed at ingest went from about 0 to 0.43–0.98 in the experiment.

The Muse calls ($0.51) were recorded during the experiment and replayed by the pipeline; the batched SAM calls cost $0.07. Findings and the board are unchanged. A fresh replay rebuild reproduces all 1,099 stored boxes exactly.

**Still weak:** 11 fields got worse, where Muse pointed at a neighbouring value on the crop (a payer name, the label line above a KVNR). No cheap guard tells those apart. SGB XI rows still have no boxes.
