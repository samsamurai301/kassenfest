# Kassenfest — Research Notes (sources for pitch, README and design)

Research date: 2026-10-22. Flags: **[V]** primary/near-primary source read · **[L]** likely (secondary, vendor claim) · **[?]** not verified.
Re-check everything marked [L]/[?] before putting it in the video.

---

## 1. Hackathon facts

- **Name:** Meta Global AI Developer Hackathon, hosted by Meta and Cerebral Valley. Meta Superintelligence Labs (MSL) runs the workshops. [V]
  - https://cerebralvalley.ai/e/meta-ai-developer-hackathon
  - https://dev.meta.ai/events/global-hackathon
- **Format:** Virtual and worldwide, free. Up to 20,000 accepted participants. **Germany is eligible.** [V]
- **Dates (ET):**
  - Applications close Oct 25, 23:59.
  - Approvals and kickoff: Oct 26, 09:00.
  - Workshops and Discord office hours: Oct 27 – Nov 4.
  - **Submission deadline: Nov 4, 21:00 ET** (Nov 5, 03:00 CET).
  - Judging: Nov 4–8. Finals: Nov 9. [V]
- **Your track: "Indie developer track"** (official name). For individual builders and students. Judged on **creativity, technical ambition, and whether it works**. [V]
- **Themes:** "Build for Your World" (a problem you know first-hand; Kassenfest fits this) and "Push the Frontier". [V]
- **Prizes:** $1M total cash pool. No per-track split is published. [V]
- **Credits:**
  - $150 Meta Model API credits per selected participant. [L — @MetaforDevs post on X]
  - Baseten $100 + 2M TPM, Modal $100, Fireworks $25 for select participants. [V]
- **Models in scope:** Muse Spark series, Muse Wonder, Muse Image, SAM 3.1 (all via the Model API), Meta open-weight models, and Muse Code. [V]
- **Still unknown until the Official Rules (due before Oct 26):** deliverables (video, length, repo, write-up, URL), judging weights, team size, and **the rules on pre-existing code**. A third-party post mentions "demo video + write-up". [?]

## 2. Meta Model API facts (design-relevant)

| Item | Fact | Source |
|---|---|---|
| Status | Generally available globally since Connect (Sep 24, 2026); the July 2026 preview was US-only | [V] https://developers.meta.com/blog/meta-connect-recap/ |
| Base URL / auth | `https://api.meta.ai/v1`, `Authorization: Bearer $MODEL_API_KEY` | [V] https://dev.meta.ai/docs/ |
| SDK | No Meta SDK. Use the `openai` package with a custom `baseURL`. Protocols: Chat Completions, Responses, Messages (Anthropic-compatible). SAM parsers: `@meta-sam/parser`, `meta_sam_parser` | [V] https://dev.meta.ai/docs/sdks |
| Models | `muse-spark-1.3`, `muse-spark-1.3-contributor`, `muse-spark-1.2(-contributor)`, `muse-spark-1.1`, `muse-wonder-1.0` (preview), `muse-image-1.0`, `muse-voice-transcribe-1.0`, `sam-3.1` | [V] https://dev.meta.ai/docs/models |
| Muse Spark 1.x | Input: text, image, video, audio, PDF. Output: text. Context: **1,048,576 tokens** | [V] |
| Contributor variants | Cheaper, but **may train on your data**. Don't use them for anything resembling real data | [V] |
| Reasoning | `reasoning_effort`: minimal / low / medium / high / xhigh / max. Reasoning tokens are billed as output | [V] https://dev.meta.ai/docs/reasoning |
| Images | JPEG, PNG, GIF, WebP, ICO (**no HEIC**). Up to 50 images per request. 50 MB inline, 1 GiB via Files API | [V] https://dev.meta.ai/docs/image-understanding |
| PDFs | Files API or inline. Text from the first 100 pages; page images from the first 50 | [V] https://dev.meta.ai/docs/file-handling |
| Structured output | `response_format: {type: "json_schema"}` with constrained decoding. No recursive schemas; max depth 10 | [V] https://dev.meta.ai/docs/structured-output |
| Tool calling | OpenAI-style. `parallel_tool_calls` defaults to true. **`tool_choice` only accepts `"auto"`**. Built-in tools: `web_search`, `tool_search` | [V] https://dev.meta.ai/docs/tool-calling |
| Pricing | Muse Spark standard: $1.25 per 1M input, $0.15 per 1M cached, $4.25 per 1M output. Contributor: $0.10 / $0.002 / $0.20. **SAM 3.1: $2.50 per 1,000 images** | [V] https://dev.meta.ai/docs/pricing-rate-limits |
| Rate limits (per team) | `muse-spark-1.3`: 3,000 RPM / 4M TPM. Contributor: 150 RPM. `sam-3.1`: 3,000 RPM | [V] |
| Privacy | "Meta does not use your Content from Standard Services to train Meta Models." No fixed retention period. Zero Data Retention via sales only (excludes files and web search). **No EU data residency or DPA documented** | [V] https://dev.meta.ai/legal/commitments · [?] residency |
| Geography | DE/EU are not on the restricted-territory list, but access is limited to "where Meta has enabled access". Test signup | [V] https://dev.meta.ai/legal/geographic-use-policy |
| Agents | No Meta agents SDK. The docs point to the Claude Agent SDK (via Messages API) or the Codex app-server. The cookbook has "Multi-agent orchestration" and "Agent fan-out" recipes | [V] https://dev.meta.ai/docs/agent-frameworks · https://dev.meta.ai/docs/cookbook |
| Safety | Llama Guard 4, Prompt Guard 2, LlamaFirewall (Llama-era; no Muse-era guard found) | [V] https://github.com/meta-llama/PurpleLlama |

### Model family
- **Muse Spark releases:** 1.0 on Apr 8, 2026 (first MSL model, proprietary). 1.1 on Jul 9. **1.3 on Sep 2, 2026**, focused on agentic work and coding, with claimed better prompt-injection resistance. [L]
- **OCR and handwriting:** no published benchmarks. At launch Meta reported CharXiv-Reasoning 86.4 and MMMU-Pro 80.4 for 1.0. **Test German handwriting yourself.** [L]
- **Muse Spark Open** (Oct 15, 2026) [V]
  - Mixture-of-experts: 816B total parameters, 42B active, 1M context. Not on the Model API.
  - Hugging Face repos (gated): `meta-models/Muse-Spark-Open-816B-A42B` (BF16, ~1.65 TB) and `-NVFP4` (~537 GB; needs at least 700 GB VRAM: 4×B300 or 8×MI355X).
  - **Muse Model License:**
    - Commercial use is allowed.
    - You must show "Built with Muse Spark Open".
    - Model-as-a-service above $20M revenue in 12 months needs a separate agreement.
    - No EU exclusion; the EU licensor is Meta Platforms Ireland.
  - Third-party hosting: Together, Fireworks, Groq, OpenRouter. [L]
  - Links: https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B · https://dev.meta.ai/docs/muse-spark-open
- **Muse Glimmer 30B** [V] https://dev.meta.ai/docs/muse-glimmer
  - Dense model distilled from Muse Spark, **Apache 2.0**. Text and image input, 128K context.
  - Fits one large GPU. **This is the realistic EU self-host option.**
- **SAM 3** came out Nov 19, 2025. **SAM 3.1** came out Mar 27, 2026. [V] https://github.com/facebookresearch/sam3 · https://huggingface.co/facebook/sam3.1
  - **What's new:** "Object Multiplex", about 7× faster at 128 objects, a gain mainly for video and multi-object tracking.
  - **Prompts:** noun-phrase text, points, boxes, masks. **One concept per request** on the API. Concrete nouns work best. [V] https://dev.meta.ai/docs/sam/segmenting
  - **API:** returns boxes plus masks (lossless or `one_bit`) and optional confidence. Empty output means no match.
  - **Self-host:** SAM License; ~848M parameters; Python 3.12+, PyTorch 2.7+, CUDA 12.6+.
  - **Fallback host:** Roboflow Serverless SAM 3 [V].
  - **Meta's recommended pairing:** Muse Spark gives text coordinates; SAM returns masks. [V] https://dev.meta.ai/docs/media-segmentation

---

## 2b. ⚠️ HKP rules that differ from what's in your application

These have **primary sources** (G-BA HKP-Richtlinie as amended 16.10.2025, in force 12.12.2025: https://www.g-ba.de/downloads/62-492-3999/HKP-RL_2025-10-16_iK-2025-12-12.pdf [V]):
- **4-day deadline:** this is correct. The Kasse covers costs until its decision only if the Verordnung reaches it **by the 4th working day after issue**. It was the 3rd day before Dec 2021 (KV BaWü), and the BSG 2016 ruling still cites the 3rd day.
- **Erstverordnung:** normally **≤ 14 days**.
- **Folgeverordnung:** issued in the **last 3 working days** before the current one expires.
- **Retroactive Verordnungen:** "grundsätzlich nicht zulässig". **Changes** need a new doctor signature, stamp and date.
- **Blankoverordnung** (since 07/2024): the nurse decides frequency and duration. KBV Praxisinfo 17.10.2025.
- **LBNR:** a lifelong staff ID number on billing documents is required **since 01.10.2025**. [V via LfP Bayern]

---

## 3. Problem evidence — what you can and can't claim

### ⚠️ Correct the application's claim
> Your application says: *"Recent studies show missing documents are the main cause of late payments."*

**This is not supported for ambulante Pflegedienste.** I found no 2023–2026 study of home care that ranks missing documents as the main cause.
- **Closest support:** PwC/Strategy& (Jun 2026). 60% cite "incomplete/missing documents" as a cause of delayed payment, but this is **Pflegeheime**, mostly Sozialhilfe applications, with a sample of about 100 managers. [L] https://www.medi-karriere.de/magazin/pflegeheime-kaempfen-mit-liquiditaetsproblemen/
- **Contradicting:** a VKAD/Caritas ambulant survey (Jan 2025) doesn't list documents as a cause. A factoring CEO (2026) blames the Kassen' "Prüf- und Freigabeprozesse", not provider workflows.

**Use this sourced framing instead (README and video):**
1. **Payment delays are threatening home-care services.** Diakonie 2023: about 73% call their situation "angespannt" and about one third have reserves of 3 months or less. Distress is "vorrangig durch Zahlungsverzug der Kranken- und Pflegekassen". [V]
   - https://www.sonntagsblatt.de/artikel/epd/diakonie-umfrage-lage-der-pflegedienste-spitzt-sich-zu
2. **Insolvencies are rising.** 1,264 care facilities had an insolvency or closure from early 2024 to Apr 2025. The Arbeitgeberverband Pflege calls late payment by Kassen the main cause, with arrears of "sechs- bis siebenstelligen Summen". [V]
   - https://www.cash-online.de/a/ueber-1-200-pflegeeinrichtungen-insolvent-oder-geschlossen-695525/
   - ETL counted **143 ambulante Pflegedienste insolvencies in 2023** (GmbHs only). [V]
3. **Paperwork queries are routine.** Kassen query about **every third HKP Verordnung**, and about 1,200 nurses are tied up in Verordnung bureaucracy (Caritas/VKAD 2019, dated; mark it as such). [V]
4. **Kassen are being told to audit harder, and they're automating.**
   - The **BAS Rundschreiben (03.02.2022)** orders Kassen to check SGB XI bills for overlaps with "Krankenhaus, Rehabilitation… Kurzzeitpflege", and to demand completeness and machine-readable visit records. [V]
     - https://www.bundesamtsozialesicherung.de/fileadmin/redaktion/Pflegeversicherung/Rundschreiben/20220203_Rundschreiben_Pruefung_Abrechnung_Pflegesachleistungen_Krankenpflege.pdf
   - KKH uses AI for fraud detection; 395 of 605 new tips in 2025 came from Pflege. [L] https://www.kkh.de/presse/pressemeldungen/einfallstor-pflege
5. **Providers have no equivalent.** That gap is Kassenfest: **"Kassen already have auditors and AI. Small Pflegedienste don't. Kassenfest is the auditor on your side, before you send."**
6. **Rules keep changing:**
   - HKP-Richtlinie amended **16.10.2025** (in force 12.12.2025)
   - Blankoverordnung (2024/25)
   - LBNR required since **01.10.2025**
   - Gemeinsamer Jahresbetrag from **01.07.2025**
   - Electronic SGB XI billing possible since **01.04.2025**
   - TA HKP 1.3.0 and TA5 from **01.02.2027**
   - KIM transmission mandatory **01.10.2027** [V/L]

Optional supporting numbers:
- **VKAD 2025:** 61–62% of Sozialstationen are "nicht stabil". Causes: staff 33%, patient structure 28%, fleet 15%, rate negotiations 7%, Sozialamt delays 6%. 18% want more digitalisation, including **recognition of digital signatures**. [V]
  - https://www.altenheim.net/wp-content/uploads/sites/2/2025/02/2025_CK7_VKAD_Umfrageergebnisse_Wirtschaftliche_Situation_Zusammenfassung.pdf
- **ETL 2025:** the personnel-cost ratio improved to 70.74%, credited partly to "**gezielteres Abrechnungsmanagement**" (more targeted billing management, which supports the idea that billing quality matters). [V]
  - https://www2.etl.de/wp-content/uploads/2025/11/051125_Pressemitteilung_ETL-ADVISION_-Wirtschaftsmonitor_2025_final.pdf
- **Time to payment:** "bis zu 70 Tage" (factoring company, 2020) [L]. "Rückläufer gehören zum Alltag" (Ecovis, Jul 2026) [V]. **No reliable national average exists**, so don't invent one.

### Hospital stays — a real information gap (great demo story)
- Hospitals must report admissions to the **Kasse** electronically (§301 SGB V) [V], but **no standard channel informs the Pflegedienst** [?].
- During an inpatient stay, SGB XI home-care benefits **ruhen** (are suspended). Pflegegeld continues for 8 weeks (§34 SGB XI) [V].
- So the Kasse knows and the provider often doesn't. The Kasse cuts the bill weeks later.

---

## 4. Market size

- **About 15,500 ambulante Pflegedienste** (15,549 on 15.12.2023). [L] https://www.destatis.de/DE/Themen/Gesellschaft-Umwelt/Gesundheit/Pflege/_inhalt.html
- **About 50%** care for **fewer than 50 clients**; about 11% care for more than 150. [V] https://www.kbv.de/infothek/zahlen-und-fakten/gesundheitsdaten/ambulante-pflegedienste
- **5.7M** people need care; **1.1M** are cared for by ambulante Dienste (Dec 2023). [V] https://www.presseportal.de/pm/32102/5933248
- **About 446k staff** in ambulante Dienste. [L]
- **SGB XI spending 2025:** Pflegesachleistung **€6.92bn**, Entlastungsleistungen €3.87bn, Verhinderungspflege €4.46bn. [V]
- **GKV "Medizinische Behandlungspflege"** (formerly HKP, incl. intensive care): **€11.95bn in 2025**, up 12.6% year on year. [V]
- **Rough addressable flow:** about €15–25bn per year of ambulant SGB V/XI billing, or roughly €1–1.5M per service. This is my own estimate, so label it as such.

## 5. Competitors and the gap

| Player | What they do | AI / document checks | Flag |
|---|---|---|---|
| MEDIFOX DAN (MD Ambulant) | Market-leading Pflege software. The e-Verordnung module needs manual typing; approval details "müssen manuell überprüft … werden"; Wiedervorlage lists | AI tour planning (adiutaByte), voice (VEA, Care.One). No billing-document AI found | [V] manual 11/2023 |
| Connext Vivendi | Pflege software, VIVA KI-Assistent for documentation | Nothing in billing | [L] |
| euregon .snap, myneva | Pflege software | Voice (.snap Speech) | [L] |
| DMRZ | Billing centre with formal plausibility check, pre-financing with SozialFactoring | "OCR of Verordnungen" claimed by a comparison site | [L]/[?] |
| opta data | Billing centre: DTA, open items, Rückläufer, dunning | Corrections visible after the fact in a portal | [L] |
| Noventi/azh | Absetzung focus lists for Heilmittel only | — | [?] |
| TK, Barmer (Kassen) | Syntax pre-check tool (TK); online HKP applications (Barmer) | — | [V]/[L] |
| **voize** ($50M Series A, Nov 2025) | Voice documentation | Not billing | [L] |
| **Recare** (€37M, Jan 2026) | Hospital discharge platform; AI agent extracts data from PDFs and scans; reaches about two thirds of German hospitals | **Possible partner** for hospital-stay signals | [L] |
| **calliora** (Munich, $6M pre-seed, Oct 2026) | AI that finds billing gaps **before hospitals invoice Kassen** | **Closest analogue, for hospitals rather than Pflege** → validates the idea | [L] |

**Gap Kassenfest can credibly claim** (absence of features is based on public material only; say "to our knowledge"):
1. **Cross-document checks:** Verordnung ↔ Genehmigung ↔ signed Leistungsnachweis ↔ hospital letter.
2. **Paper → structured data:** Muster 12 and approval letters read automatically instead of retyped.
3. **Provider-side detection of hospital-stay overlaps.**
4. **A pre-submission auditor that simulates the Kasse.**
- Incumbents today do syntax checks, deadline reminders, and e-approval where the Kasse supports it.

### Risk to address in the pitch: "Isn't everything going electronic anyway?"
- Electronic SGB XI billing has been *possible* since 01.04.2025, and HKP goes electronic over KIM in 2027 (mandatory 01.10.2027).
- But **Muster 12 is still mostly paper**: the HKP e-prescription has been required by law since **01.07.2026** (§360(5) SGB V [V]), yet the rollout is practically delayed into 2027 (opta data [L]). Approval letters, hospital letters and many signatures are still paper or fax.
- **Answer:** Kassenfest converts today's paper into the **TA HKP 1.3.0 XML** format (`EXP-01`). The cross-document rules and the auditor are format-independent; they matter more, not less, once Kassen can check machine-readable data automatically.

---

## 6. Pitch skeleton (≈ 2–3 min video)

1. **Hook (15 s):** "A home-care nurse in Deggendorf did every visit in October. The Kasse will cut €2,340 of it in December, because a prescription expired on the 14th and a patient was in hospital for 4 days nobody told them about."
2. **Problem (20 s):** Most German home-care services are small (half have fewer than 50 clients). Payment delays push them toward insolvency (Diakonie, Arbeitgeberverband Pflege). Kassen audit with AI; providers don't.
3. **Demo (90 s):** upload → read → 🟢🟠🔴 → SAM evidence on the empty signature box → drafted renewal letter + 4th-working-day countdown → auditor attack → receivables.
4. **How it's built (20 s):** Muse Spark 1.3 for vision extraction, tool calling and the auditor; SAM 3.1 for evidence masks; a deterministic, versioned rules engine (no AI-invented amounts); eval numbers.
5. **Why now and next (15 s):** rule changes in 2025/2026, electronic visit records in 2027, an EU-hosted path (Muse Spark Open / Muse Glimmer).
