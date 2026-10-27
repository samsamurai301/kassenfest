# Kassenfest — Inputs, Data Gathering & Decisions

Everything you must **decide**, **get access to**, **download**, **generate**, or **collect by hand** to build and demo Kassenfest.
Flags: **[V]** verified source · **[L]** likely, re-check · **[?]** not verified.
Research date: 2026-10-22.

---

## 0. Decisions only you can make (with recommended defaults)

| # | Decision | Recommended default | Why it matters |
|---|---|---|---|
| Q1 | Bundesland for tariffs, holidays, contracts | **Bayern** (Deggendorf) | Holiday calendar, Punktwerte, §132a prices, local story for judges |
| Q2 | Payer scope | **SGB V HKP + SGB XI Sachleistung + §45b Entlastungsbetrag**; skip SGB XII / PKV / Beihilfe | HKP has the sharpest deadline/approval rules; SGB XI shows budget logic |
| Q3 | Demo month | **October 2026**, with 3 months of history (Jul–Sep) for receivables | Includes holidays: Oct 3 (Tag der Deutschen Einheit), Nov 1 (Allerheiligen) |
| Q4 | Demo provider | Fictional "Pflegedienst Sonnenschein GmbH, Deggendorf", 25 patients, 8 nurses | Small service = matches the pitch |
| Q5 | Language | German UI + documents, English toggle and English voice-over | Judges are international |
| Q6 | Prices | **Invented demo prices labelled "illustrative"**; take the *structure* from real contracts | Bavarian §132a prices are only partly public |
| Q7 | Handwriting realism | Synthetic **+ one real handwriting session** (§5) | Most convincing demo + honest eval |
| Q8 | Hosting | Local demo video first; hosted demo only if time allows | Saves a day |
| Q9 | Output format | Show export as **TA HKP 1.3.0 "Elektronischer Leistungsnachweis" XML** (P1/P2) | Strong "why now" story: mandatory electronic visit record is coming (§3.2) |
| Q10 | Model IDs | `muse-spark-1.3` (standard, **not** `-contributor`), `sam-3.1` | Contributor variants may train on inputs |
| Q11 | Open-weight story | "Production: Muse Spark Open in EU data centre; lean option Muse Glimmer 30B (Apache 2.0)" | Muse Spark Open needs ~700 GB VRAM; be honest |
| Q12 | Employer | Written OK from Careville, or at least a clear separation (own laptop, accounts, no company data/code) | Same domain as your job |

---

## 1. Accounts, access & logistics checklist

- [ ] Hackathon acceptance email (by Oct 26, 09:00 ET); accept the Official Rules
- [ ] Meta Model API account at dev.meta.ai, API key, billing/credits visible (**$150 hackathon credits reported [L]**), confirm signup works from Germany
- [ ] Hackathon Discord (link comes at kickoff)
- [ ] Optional partner credits (select participants): Baseten $100, Modal $100, Fireworks $25 [V]
- [ ] GitHub repo (public at submission time; check rules)
- [ ] Hugging Face account (only if you test Muse Glimmer / SAM weights; repos are gated and ask for legal name, DOB, org)
- [ ] Roboflow account (fallback SAM 3 hosting) [V]
- [ ] Screen recorder + mic (OBS / ScreenStudio), video host (YouTube unlisted / Loom; check rules)
- [ ] Printer + paper for the handwriting session; 3–5 volunteers; 2–3 different phones
- [ ] Domain reviewer (PDL / billing clerk outside your Careville work): two 30-minute slots, one now (rules check), one Nov 2 (demo check)

---

## 2. Documents to collect (layout references for the synthetic renderers)

> **No blank fillable Muster 12 is published.** KBV forms are controlled prints. Re-draw look-alikes and watermark every page: **"MUSTER – SYNTHETISCH – KEIN ECHTES DOKUMENT"**.

| Doc | Best source | Use | Flag |
|---|---|---|---|
| **Muster 12** (Verordnung häuslicher Krankenpflege) specimen + field guide | KVB "Ausfüllhilfe Muster 12" (20.02.2024): https://www.kvb.de/fileadmin/kvb/Mitglieder/Verordnungen/VO-aktuell/2024-DS/KVB-VA-240220-SOP-HKP-Muster-12-Ausfuellhilfe.pdf | Full-page specimen "Muster 12a (10.2020)" with 19 numbered fields → re-draw layout + field coordinates | [V] |
| KBV Vordruckerläuterungen (Anlage 2 BMV-Ä, valid 01.01.2026) | https://www.kbv.de/documents/infothek/rechtsquellen/bundesmantelvertrag/anlage-02-vordruckvereinbarung/02_Erlaeuterungen.pdf (>10 MB) | Check whether the current Muster 12 has a **Blankoverordnung** field the 10.2020 specimen lacks | [L] — open manually |
| KBV HKP overview + Praxisinfo Blankoverordnung (17.10.2025) | https://www.kbv.de/praxis/verordnungen/haeusliche-krankenpflege · https://www.kbv.de/documents/infothek/publikationen/praxisinfo/praxisinfo-blankoverordnung-krankenpflege.pdf | Blankoverordnung rules (nurse decides frequency/duration) | [V] |
| **HKP-Richtlinie** incl. Leistungsverzeichnis (consolidated 16.10.2025, in force 12.12.2025) | https://www.g-ba.de/downloads/62-492-3999/HKP-RL_2025-10-16_iK-2025-12-12.pdf | Measures Nr. 1–31, durations, who may prescribe what | [V] |
| **Leistungsnachweis** (visit sheet) | No official paper template. Use the **TA HKP §9.8 XML fields** + Rahmenempfehlungen §132a §8 + AOK Bayern Frühförderung sheet as a visual analogue: https://www.aok.de/gp/fileadmin/user_upload/Heilmittel/IHF/by_heil_fruehfoerd_anl08c_leistungsnachweis.pdf | Design your own monthly grid (day × service, start time, Handzeichen, signature) | [V] |
| Rahmenempfehlungen §132a Abs. 1 (18.12.2023) | https://www.gkv-spitzenverband.de/media/dokumente/krankenversicherung_1/ambulante_leistungen/haeusliche_krankenpflege/20231218_Rahmenempfehlungen_132a_Abs.1_SGB_V_zur_Versorgung_mit_haeuslicher_Krankenpflege.pdf | Required Leistungsnachweis content (real-time start time, Beschäftigtennummer, position + quantity); note: Verordnung + Genehmigung need **not** be resubmitted with the bill | [V] |
| **Genehmigungsschreiben** (approval letter) | No public example. Synthesize from Muster 12 fields + period + approved positions + Genehmigungskennzeichen (TA HKP §9.7). Approval process: AOK Nordost model contract https://www.aok.de/gp/fileadmin/user_upload/Pflege/Ambulante_Pflege/HKP/brb_hkp_muster_rahmenvertrag.pdf | 3–4 different payer letter styles | [V] |
| **Entlassbrief** (hospital discharge) | No public sample. Build from Rahmenvertrag Entlassmanagement (12th amendment, 01.07.2024): https://gkv-spitzenverband.de/media/dokumente/krankenversicherung_1/amb_stat_vers/entlassmanagement/12._AendVb_Rahmenvertrag_Entlassmanagement_03.06.2024_Lesefassung_ohne_Anlagen.pdf | Admission/discharge dates; hospital may prescribe HKP for **up to 7 days** after discharge; hospital location code "77…" instead of BSNR [L] | [V]/[L] |
| **Abtretungserklärung §45b** (assignment of Entlastungsbetrag) | Niedersachsen https://soziales.niedersachsen.de/download/191137/Abrechnungsvordruck.pdf · Mannheim https://www.mannheim.de/sites/default/files/2022-10/Abrechnungsformular%20Mannheim_Okt_2022_0.pdf · Lebenshilfe Nürnberg (outdated amounts) | Layout reference only (no licence stated) | [V] |
| Pflegegrad-Bescheid, Zuzahlungs-Befreiungsbescheinigung, Zahlungsavis | No public templates needed; invent simple letters | For D14 (Pflegegrad change), Zuzahlung, receivables | — |

---

## 3. Reference & master data to download

### 3.1 Codes, directories, formats

| Data | Source | Notes | Flag |
|---|---|---|---|
| **HKP Positionsnummernverzeichnis** (18.05.2026) | https://www.gkv-datenaustausch.de/media/dokumente/leistungserbringer_1/sonstige_leistungserbringer/positionsnummernverzeichnisse/Haeusliche-Krankenpflege_20260518.pdf | 6-digit key: pos 1–2 legal basis (01 = §37(1) ≤4 wk, 03 = §37(2) S.1, 10 = §37(1a) ≤4 wk); pos 3 care type (1 Grund-, 2 Behandlungspflege, 3 Hauswirtschaft); pos 4–6 service (e.g. 188 Wegepauschale, 199 Medikamentengabe Deckelungspauschale). **No prices.** | [V] |
| §302 Technische Anlagen (TA1 V21, TA3 V21) | prefix `https://www.gkv-datenaustausch.de/media/dokumente/leistungserbringer_1/sonstige_leistungserbringer/technische_anlagen_aktuell_4/` + `Anlage_1_TP5_V21_20260115.pdf`, `Anlage_3_TP5_V21_20250919.pdf` | Key directories (Schlüsselverzeichnisse) | [V] |
| **TA HKP 1.3.0** (electronic HKP billing over KIM, XML) + **XSD** | same prefix + `TA_HKP_1.3.0_20260625.pdf`, `TA_HKP_Anhang_1_XSD_1.3.0_20260605.zip` | Valid from **01.02.2027**. §9.7 Genehmigung, §9.8 **Elektronischer Leistungsnachweis** → use as your canonical internal schema + export target | [V] |
| §105 SGB XI Technische Anlagen (TA1 6.4.0, TA3 6.4.0, **TA5 1.2.0** TI transmission from 01.02.2027) + XSD | prefix `https://www.gkv-datenaustausch.de/media/dokumente/leistungserbringer_1/pflege/technische_anlagen_aktuell_2/` | SGB XI side of the same story | [V] |
| **Kostenträgerdateien** (payers with IK + routing) | §302: https://www.gkv-datenaustausch.de/leistungserbringer/sonstige_leistungserbringer/kostentraegerdateien_sle/kostentraegerdateien.jsp · Pflege: https://www.gkv-datenaustausch.de/leistungserbringer/pflege/kostentraegerdateien_pflege/kostentraegerdateien.jsp | Quarterly KE0–KE3 files per Kassenart; format in TA1 Anhang 3. Read-only lookup; no licence stated | [V] |
| **IK rules** — Gemeinsames Rundschreiben IK 02/2026 | https://www.gkv-datenaustausch.de/media/dokumente/leistungserbringer_1/GR-IK-2026-02.pdf | 9 digits: 1–2 class (10 KK, 18 Pflegekasse, 46 Pflegedienste, 50 Sozialstationen), 3–4 region, 5–8 serial, 9 check digit = digits 3–8 weighted 2,1,2,1,2,1, digit-sum products, sum **mod 10** (no "10 −"). Example 26032682 → **2** | [V] |
| **KVNR** | https://de.wikipedia.org/wiki/Krankenversichertennummer | Letter + 8 digits + check digit; letter → 01–26, weights 1,2,1,2…, digit-sum products, mod 10. Example A12345678 → **0**. No reserved test range → mark synthetic data clearly | [V] |
| **LANR / BSNR** | https://de.wikipedia.org/wiki/Lebenslange_Arztnummer · …/Betriebsst%C3%A4ttennummer | LANR: 6 digits + check + 2 specialty; weights 4,9,4,9,4,9, plain products, `(10 − sum mod 10) mod 10`. Example 123456 → **6**. BSNR: 9 digits, first two = KV region (Bayern = 71…), no documented check digit | [L] |
| **ICD-10-GM 2026** | BfArM: https://www.bfarm.de/EN/Code-systems/Classifications/ICD/ICD-10-GM/_node.html | Free but creates a usage contract; **don't commit the original files** — commit only your small derived subset | [V] |
| Holidays | npm `date-holidays` (`new Holidays('DE','by')`, region variants for Augsburg / Catholic municipalities) · Python `holidays.Germany(subdiv='BY')` | Make the municipality configurable: **Mariä Himmelfahrt (Aug 15)** is only a holiday in mainly Catholic Bavarian municipalities (Deggendorf is), and Augsburg has the Friedensfest | [V] |

### 3.2 Tariffs (prices) — structure from real sources, numbers labelled illustrative

| Data | Source | Notes | Flag |
|---|---|---|---|
| Bavarian SGB XI Leistungskomplexe + Punktwerte | AOK §89 contracts, e.g. BRK 2026: https://www.aok.de/gp/fileadmin/user_upload/Pflege/Ambulante_Pflege/Verguetung/BRK/20260101_by_pflege_brk_vertrag.pdf · old LK catalog: https://www.aok.de/gp/fileadmin/user_upload/Pflege/Ambulante_Pflege/Leistungskomplexe_ab_200201.pdf | 2025 Punktwerte: €0.0909 (AWO/BRK), €0.0803 (Arbeitskreis), €0.0789 (Home Instead). AOK site was in maintenance on Oct 22 → retry | [L] |
| Bavarian §132a HKP prices | AOK Bayern HKP fee agreement Arbeitskreis (from 01.08.2023): https://www.aok.de/gp/fileadmin/user_upload/20230801_by_pflege_hkp_kv_gebuehren_arbeitskreis_ohne_bah.pdf | No 2025/26 version found; other payers don't publish → **invent demo prices, label "illustrative"** | [L] |
| SGB XI amounts 2025/2026 (Sachleistung, Entlastungsbetrag, Gemeinsamer Jahresbetrag, Beratungseinsatz) | See `02-RULES-CATALOG.md` | Put into `data/reference/sgbxi_amounts.yaml` with `valid_from` | — |

### 3.3 Reference-data task list
- [ ] `DAT-01` Download the KVB Muster 12 guide + HKP-Richtlinie + Positionsnummernverzeichnis + TA HKP 1.3.0 PDF + XSD + TA5 → `data/sources/` (commit only where licences allow; otherwise a `SOURCES.md` with links + hashes)
- [ ] `DAT-02` Open the KBV Vordruckerläuterungen PDF manually; note any **Blankoverordnung** field differences vs. the 10.2020 specimen
- [ ] `DAT-03` Build `payers.yaml`: ~10 Kassen (AOK Bayern, TK, Barmer, DAK, IKK classic, KKH, SBK, BKK firmus, Knappschaft, HEK) with role (Kranken-/Pflegekasse), **fake but check-digit-valid IKs** flagged `synthetic: true`, fax, payment term
- [ ] `DAT-04` Build `hkp_services.yaml`: the ~10 positions used in the demo (Medikamentengabe, Injektion s.c., Blutzuckermessung, Kompressionsstrümpfe an/aus, Kompressionsverband, Wundversorgung, Wegepauschale, …) with Positionsnummer pattern, unit, **illustrative price**
- [ ] `DAT-05` Build `sgbxi_lk_bayern.yaml`: ~12 Leistungskomplexe with points + Punktwert → price (illustrative)
- [ ] `DAT-06` Build `icd10_subset.yaml`: ~30 typical HKP diagnoses (E11.x diabetes, I83.x varicose veins/ulcer, L89.x pressure ulcer, I50.x heart failure, F03 dementia, M17 gonarthrosis, C-codes for palliative cases …)
- [ ] `DAT-07` Implement + unit-test check digits: IK, KVNR, LANR (with the worked examples above as test vectors)
- [ ] `DAT-08` Working-day calendar for Deggendorf 2025–2027, configurable municipality

---

## 4. Synthetic data specification (`tools/synth`)

### 4.1 World model (per seed)
- **Provider:** 1 Pflegedienst (IK class 46), Bayern, 8 nurses with Beschäftigtennummer + Handzeichen (2–3 letters), 1 PDL.
- **Doctors:** 8 Hausärzte (LANR + BSNR 71…, practice stamp), 1 hospital (location code 77…).
- **Patients:** 25 (age 62–96), each with: name (Faker de_DE), DOB, address in/around Deggendorf, KVNR (valid check digit), Kasse, Pflegegrad history (PG 1–5), diagnoses (ICD subset), Zuzahlung status (exempt yes/no), care plan:
  - ~15 HKP (SGB V) patients: 1–3 services each (e.g. Medikamentengabe 2×/day, Kompressionsstrümpfe an + aus 1×/day, Wundversorgung 3×/week, Insulin injection 3×/day)
  - ~18 SGB XI patients (overlap with HKP): LK bundles 1–3×/day, §45b Entlastungsbetrag use for ~8
- **Timeline Jul–Oct 2026:** prescriptions (Erst → Folge chains, some Blankoverordnung), approvals (full / partial / late), visits, 4–6 hospital stays, 1 death, 1 Kassenwechsel, 1 Pflegegrad upgrade.
- **Payments history:** sent/paid dates, 10–15% partial cuts with reason codes for the receivables view.

### 4.2 Document types & extraction fields (= zod schemas in `packages/schemas`)

**`muster12`** (follow KVB field numbering):
`payer_name, payer_ik (Kostenträgerkennung), patient_name, patient_dob, kvnr, status, bsnr, lanr, issue_date, icd_codes[], limitations_text, prescription_kind (erst|folge), accident, blank_prescription (Blankoverordnung yes/no), period_from, period_to, measures[] {category (medikamentengabe|injektion|blutzucker|kompression|wundversorgung|positionswechsel|sonstige|anleitung|grundpflege|hauswirtschaft|unterstuetzungspflege|krankenhausvermeidungspflege), details (Präparat/Wundart/Lokalisation/Größe/Grad/Seite), frequency {count, per: day|week|month}, duration_from, duration_to}, further_notes, doctor_stamp_present, doctor_signature_present, corrections_present (crossed-out/overwritten fields), corrections_initialled`

**`approval_letter`**:
`payer_name, payer_ik, letter_date, approval_ref (Genehmigungskennzeichen), patient_name, kvnr, provider_name, provider_ik, prescription_issue_date, decision (approved|partial|rejected), period_from, period_to, approved_items[] {position_no?, description, frequency, from, to}, rejected_items[] {description, reason}, zuzahlung_note`

**`visit_log_sgbv`** (HKP Leistungsnachweis, mirror TA HKP §9.8):
`provider_ik, patient_name, kvnr, payer_name, month, approval_ref, responsible_nurse, entries[] {date, start_time, end_time?, position_no|service, quantity, staff_initials|employee_no}, patient_signature_present, patient_signature_date, missing_signature_reason, provider_signature_present`

**`visit_log_sgbxi`**:
`provider_ik, patient_name, kvnr, payer_name, pflegegrad, month, entries[] {date, lk_code, count, staff_initials, time?}, entlastung_entries[], patient_signature_present, provider_signature_present`

**`hospital_letter`** (Entlassbrief / Aufnahmeanzeige):
`hospital_name, hospital_ik_or_77_code, patient_name, patient_dob, admission_date, discharge_date, discharge_diagnoses[], hkp_recommended, hospital_hkp_prescription_days, physician_signature_present`

**Also:** `assignment_45b`, `pflegegrad_notice`, `zuzahlung_exemption`, `payment_advice`. P1 for these.

### 4.3 Rendering variants (per document)

| Variant | Share | How |
|---|---|---|
| Clean digital PDF | 15% | HTML template → PDF (pdf-lib / WeasyPrint) |
| Clean scan | 25% | rasterize 300 dpi + light noise + 0.5–1.5° skew + JPEG |
| Fax | 15% | binarize, 200×100 dpi look, streaks, header line "Fax von …" |
| Phone photo | 35% | perspective warp, desk background, shadow, glare, motion blur, varied lighting (Augraphy + albumentations) |
| Bad photo | 10% | heavy blur/cropped corner → should trigger "re-photograph" |

Handwritten fields: OFL handwriting fonts with umlauts and ß (Caveat, Kalam, Patrick Hand, Indie Flower), per-character jitter, blue/black ink colours, ticks and crosses in boxes. Signatures: **procedural Bézier scribbles** with variable width plus signature fonts (Herr Von Muellerhoff, Mr Dafoe). **Don't use GPDS-Synthetic** (non-commercial licence). Stamps: Pillow/OpenCV text block in blue-violet, rotated, noisy ink mask, multiply blend.

### 4.4 Ground truth format (one JSON per document)

```json
{
  "doc_id": "syn-2026-10-p07-muster12-01",
  "doc_type": "muster12",
  "variant": "phone_photo",
  "pages": [{"index": 0, "image": "p07_m12_01_p0.jpg", "width": 2480, "height": 3508}],
  "fields": {
    "kvnr": {"value": "A123456780", "page": 0, "bbox": [412, 233, 690, 270], "handwritten": false},
    "period_to": {"value": "2026-10-14", "page": 0, "bbox": [1610, 820, 1890, 862], "handwritten": true}
  },
  "evidence_regions": {
    "doctor_signature": {"page": 0, "bbox": [1500, 3100, 2300, 3330], "state": "empty"},
    "doctor_stamp":     {"page": 0, "bbox": [180, 3080, 1100, 3360], "state": "present"}
  },
  "defects": ["D09"],
  "synthetic": true,
  "seed": 4211
}
```

### 4.5 Volumes
- [ ] `GEN-01` **dev** set: ~250 documents (iterate prompts here)
- [ ] `GEN-02` **test** set: ~150 documents, different seed + different handwriting fonts (never tune on it)
- [ ] `GEN-03` **demo** set: ~40 curated documents telling the story (5 hero patients + background)
- [ ] `GEN-04` Every defect D01–D20 appears **≥5×** in dev and **≥3×** in test; ~40% of claims clean

---

## 5. Real handwriting session (highest-value manual input)

Goal: 30–50 genuinely handwritten, phone-photographed documents with known ground truth.

- [ ] `HW-01` Generate 40 "fill-in sheets": the generator prints a blank look-alike form + a separate instruction card with the synthetic values to write (incl. intentional defects: leave signature empty, write the wrong date, cross out and overwrite).
- [ ] `HW-02` Recruit 3–5 people with different handwriting (friends/family; **not** patients, **not** Careville colleagues during work time). Short written consent: "my handwriting samples of fake data may be published in a hackathon repo/video".
- [ ] `HW-03` Pens: blue ballpoint, black gel, a thick felt-tip; a self-made "Praxisstempel" (rubber stamp kit or a printed stamp sticker).
- [ ] `HW-04` Photograph with 2–3 phones (iPhone → **convert HEIC**, Android), on different surfaces and lighting; also scan 10 on a flatbed and fax/print-scan 5 if possible.
- [ ] `HW-05` File naming `hw_<form>_<writer>_<phone>_<nn>.jpg`; ground truth = the instruction card values + manually drawn boxes (Label Studio / CVAT) for the signature/stamp regions.
- [ ] `HW-06` Keep these as a **separate eval split** ("real handwriting") and report it separately; use 5–8 of them in the demo.

---

## 6. Evaluation inputs

- [ ] `EV-01` Own synthetic gold sets (§4.5) are the primary benchmark.
- [ ] `EV-02` Optional sanity check: **XFUND German** split (199 forms, key-value; **CC BY-NC-SA 4.0** → eval only, don't redistribute) https://github.com/doc-analysis/XFUND
- [ ] `EV-03` Metric definitions: normalized exact match per field (dates → ISO, ICD upper-case, KVNR check-digit validated); ANLS for free text (Präparate); checkbox accuracy; micro/macro F1; **straight-through rate** (documents with every billing-relevant field correct); defect recall/precision; evidence IoU / "hit" (predicted box contains GT centre, à la DocILE).
- [ ] `EV-04` Labeling tool for hand-checked items: Label Studio (Apache-2.0) or CVAT (MIT).

---

## 7. Questions for your domain reviewer (30 min, no real patient data)

1. Which 5 reasons for Absetzungen / late payment do you see most often? (validate the defect catalog's priorities)
2. In practice, how do you learn about hospital stays: relatives' calls, hospital fax, a nurse finding an empty flat, the Kasse?
3. How are Verordnungen sent to the Kasse today: fax, post, KIM, Kasse portal? Which proof of submission date do you keep?
4. Is the **4th-working-day** provisional-payment rule applied strictly by Kassen in Bayern? What happens if you're late?
5. How common are Blankoverordnungen now, and how do Kassen treat frequency then?
6. How do Kassen react to a missing patient signature on the Leistungsnachweis: cut the whole month, or ask for it later?
7. Which Kassen are slowest / most strict? (anonymized, for the auditor personas)
8. What does a typical Genehmigung letter look like (which fields)? Partial approvals: how often?
9. What would make you trust an AI that blocks a bill? (→ evidence UI, rule source links)
10. Would a Pflegedienst pay for this? Per patient/month, per claim, or as part of the billing-centre fee?

---

## 8. Privacy & compliance notes (for the README and judges' questions)

- **Synthetic only.** Real HKP/SGB XI documents are health data (**DSGVO Art. 9**) and Sozialdaten (**SGB X §§67 ff.**). Nurses are professional secret-holders (**§203 StGB**); disclosure to IT providers is allowed only under §203 Abs. 3–4 with confidentiality obligations. [L]
- **Cloud for SGB V providers:** **§393 SGB V** limits cloud processing of health data to Germany / EU / adequacy countries and requires a **BSI C5 Type 2** attestation. [V for the statute; L that it applies to §132a Pflegedienste] → explains the "Muse Spark Open in the EU" roadmap.
- Meta Model API: Meta says it doesn't use Standard Services content for training [V]; no EU data residency or DPA documented [?]; Zero Data Retention only via sales [V] → fine for synthetic data, **not** for production with real data.
- DSK "Orientierungshilfe KI und Datenschutz" (06.05.2024): https://datenschutzkonferenz-online.de/media/pm/2024_05_06_DSK_PM_OH_KI_und_Datenschutz.pdf [V]
- Synthetic KVNRs with valid check digits **could collide with real people** → watermark all documents, add `synthetic: true` everywhere, use obviously fake names (e.g. themed surnames) if you want extra safety.

### EU hosting options (roadmap slide; prices from third-party trackers, re-check)

| Option | What | Approx. price | Flag |
|---|---|---|---|
| IONOS AI Model Hub | hosted open models | Llama 3.3 70B ≈ €0.65 / 1M tokens | [L] |
| STACKIT AI Model Serving (eu01, Germany) | hosted open models | ≈ €0.45 in / €0.65 out / 1M | [L] |
| OVHcloud AI Endpoints / GPU | hosted models; H100 PCIe | ≈ $2.99/h | [L] |
| Scaleway | H100 SXM / H100 PCIe / L40S | ≈ $3.2/h / €2.73/h / €1.47/h | [L] |
| Hetzner GEX131 (RTX PRO 6000, 96 GB) | dedicated | €889/mo at launch (one source: ~€1,499/mo) | [?] |
| Muse Spark Open (816B MoE, A42B) | self-host | NVFP4 ≥ ~700 GB VRAM (4× B300 / GB300) — production only | [V] |
| **Muse Glimmer 30B** (Apache 2.0, text+image, 128K) | self-host | fits one large GPU (BF16 on one B300; quantized on smaller) | [V] |

---

## 9. Licence watch-list

| Item | Licence | OK for |
|---|---|---|
| GPDS-Synthetic signatures | non-commercial, no redistribution | ❌ avoid |
| XFUND / FUNSD | non-commercial | eval only, don't commit |
| ICD-10-GM originals | BfArM contract, no redistribution | commit derived subset only |
| Kostenträgerdateien | no stated licence | read-only lookup |
| KBV forms | controlled Vordrucke | re-drawn look-alikes with watermark only |
| Google handwriting fonts | OFL | ✅ |
| Augraphy / albumentations | MIT | ✅ |
| DocCreator | LGPL-3.0 | ✅ as a tool |
| PyMuPDF | AGPL (or commercial) | ⚠️ prefer pdf-lib / reportlab / pypdfium2 if you might commercialize |
| date-holidays | ISC code, CC BY-SA 3.0 data | ✅ with attribution |
| SAM 3.1 weights | SAM License (commercial OK, no military/ITAR) | ✅ |
| Muse Spark Open | Muse Model License ("Built with Muse Spark Open" notice; MaaS > $20M needs agreement) | ✅ |
| Muse Glimmer | Apache 2.0 | ✅ |

---

## 10. Open unknowns to resolve

| Unknown | How to resolve | When |
|---|---|---|
| Official deliverables (video length, repo, write-up, deployed URL), judging weights, pre-existing-code rule | Official Rules page | **Oct 26** |
| Does SAM 3.1 segment "signature", "stamp", "checkbox" on forms? | 10-page test (ADM-03) | Oct 22–25 (API test, no product code) |
| Muse Spark 1.3 accuracy on German handwriting + visit-log grids | 20-doc spike after kickoff | Oct 27 |
| Current Muster 12 layout (Blankoverordnung field?) | DAT-02 | before rendering |
| Is the electronic Leistungsnachweis really mandatory from 01.10.2027 (Verbraucherzentrale, 14.10.2026)? Legal basis? | Search BMG / GKV-SV | for the pitch |
| 2025/26 Bavarian price levels | AOK Bayern site when back from maintenance | optional |
