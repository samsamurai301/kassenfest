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

**Not tested yet (Wednesday):** handwriting, phone-photo degradation, the visit grid (S2), empty-vs-unreadable behaviour, multi-page input, `reasoning_effort=medium` vs `low` accuracy/latency trade-off.
