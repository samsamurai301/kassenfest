# Evaluation

The numbers behind Kassenfest's claims, each with how to reproduce it. Synthetic data only.

---

## Auditor agent: subtle defects (AUD-05, EVL-04), 2026-10-29

**What it measures:** of the defects the rules engine does not check, how many the Kasse auditor agent finds, how many of those its resolver passes on to a person, and what the auditor objects to that isn't there.

**Reproduce:**
```bash
cd backend && uv run kassenfest synth --set audit && uv run kassenfest eval-auditor --mode replay
```
`eval-auditor` writes every objection with its score to `var/eval/audit/report.json`.

**Setup:**
- **The set** (`synth/subtle.py`, `kassenfest synth --set audit`): 25 patient-months of October 2026 with 67 documents.
  - 20 of them carry one seeded defect each: 10 kinds, two bills per kind.
  - 5 are clean controls.
  - Every bill is green on the 19 rules (a test checks this), so the auditor attacks all 25.
  - Pages are degraded as usual (scan, fax, phone photo), with test-split handwriting.
- **Perfect readings:** every page is read by `synth/oracle.py`, so no mistake below is a reading error.
- **Model settings:** auditor prompt v4 and resolver v3, unchanged by this eval; Muse Spark 1.3, `reasoning_effort=high`, at most 2 rounds.
- **Cost:** one run, 43 calls, $2.31; median 44 s per call, the longest 153 s.
- **Scoring** (`eval/auditor.py`): a catch is an objection on the seeded bill that names its defect by Kasse code, by a FACT on its field, or in words. Everything else is unseeded. Three word patterns were tightened after reading every objection by hand, because they had counted a misread date and a qualification objection as catches and missed two real ones.

### Results

| Defect (no rule checks it) | Caught | Reached a person | How |
|---|---|---|---|
| S01 Genehmigungskennzeichen on the Leistungsnachweis one digit off the Genehmigung | 2/2 | 2/2 upheld | 42004; the resolver's approval-number check confirms |
| S02 Verordnung carries another person's valid Versicherten-Nr. | 2/2 | 0/2 | 41002/42002; **dismissed** by the identity check as "most likely misread" |
| S03 Verordnung carries a wrong date of birth | 2/2 | 0/2 | 41002/FACT; **dismissed** the same way |
| S04 Erstverordnung issued days after its period began (retroactive) | 0/2 | 0/2 | not seen |
| S05 Medikamentengabe prescribed without naming the drugs | 0/2 | 0/2 | not seen |
| S06 Entries signed with a Handzeichen of nobody on the staff | 2/2 | 2/2 upheld | 43005; the staff check confirms |
| S07 Leistungsnachweis signed mid-month, before the later visits | 2/2 | 2/2 noted | INFO |
| S08 Every visit of the month at the same minute | 0/2 | 0/2 | not seen |
| S09 Evening dose logged 4–14 minutes after the morning dose | 2/2 | 1/2 noted | INFO noted once. Once as 42007 (7 times), **dismissed**: HKP-DUPLICATE needs the same minute |
| S10 The whole log in one hand and one pen, under several Handzeichen | 0/2 | 0/2 | not seen |
| **All** | **12/20 (60%)** | **7/20 (35%)** | |
| facts across documents (S01–S05) | 6/10 | 2/10 | |
| soft signals (S06–S10) | 6/10 | 5/10 | |

**Objections that name no seeded defect:** 27 on 25 bills, about one per bill. The clean controls drew 5 of them.

| Verdict | How many | What they were |
|---|---|---|
| dismissed | 18 | 8× "billed time ≠ the Leistungsnachweis": the auditor misread handwritten times on the image. 6× "a Pflegehilfskraft or trainee lacks the qualification" for SGB XI personal care, which they may give. 3× "no practice stamp" or a misread date on fax copies. 1× a misread approval number. |
| noted | 7 | 5× "signed on 30.10, before the month ended": the last visit was on 30.10, so no defect. 1× stamp not discernible on a fax. 1× "signed after today's date", where the model took its own date for today. |
| upheld | 2 | On both S04 bills the Leistungsnachweis gives only the Folgeverordnung's Genehmigungskennzeichen, although the Erstverordnung's approval covers the first half of October. Real: our generator prints one reference when two approvals cover the month. |

### What it shows

- **Precision on the board is good:** every upheld objection was a real problem (6/6). The resolver dismissed all 18 inventions and misreadings.
- **The resolver throws away correct catches** where no rule or record check backs them (5 of 12 catches):
  - **Identity (S02, S03):** the check reasons that the other documents and the Kasse's Genehmigung agree, so the deviant value must be our misreading. It was built for the demo's misread Versicherten-Nr. Here our reader and the auditor both saw the deviant value on the paper, and it really is there. A wrong identity on a Verordnung should go to a person, not be dismissed.
  - **Near-duplicate doses (S09):** 42007 is checked only by HKP-DUPLICATE, which needs the same minute.
- **The auditor misses what needs knowledge of the paperwork's required content** (S04 retroactive Verordnung, S05 no drug names), and **statistical or visual cues** (S08 identical times, S10 one hand). S04 and S05 are rules in the catalog not yet implemented (HKP-RX-NO-RETRO, HKP-RX-CONTENT, both P1). S08 is a cheap deterministic check.
- **Its INFO notes cost a person's time:** 7 of 10 were nothing. The "signed on the last visit day" pattern accounts for 5 and could be dropped by the resolver.

**Limits:**
- Two bills per defect and one run, so no run-to-run variance is measured.
- Perfect readings; with real readings, misreads add their own objections (see SPIKES.md, the Weiß and Eder bills).
- Synthetic handwriting and pages.
- Matching INFO objections to defects relies on word patterns, checked by hand for this run.
