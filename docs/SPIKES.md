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

**Not tested yet (Wednesday):** handwriting, phone-photo degradation, the visit grid (S2), empty-vs-unreadable behaviour, multi-page input, `reasoning_effort=medium` vs `low` accuracy/latency trade-off.
