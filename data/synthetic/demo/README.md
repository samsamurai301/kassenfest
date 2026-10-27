# Synthetic set `demo` — generated, do not edit

Regenerate with `make synth SET=demo`
(seed 4211, hand_dev fonts).
Everything here is synthetic: Pflegedienst Sonnenschein GmbH, its patients, doctors and
the hospital are invented; Kassen names are real, their IKs are not. Every page carries
the watermark "MUSTER – SYNTHETISCH – KEIN ECHTES DOKUMENT".

42 documents, 14 patient-months (2026-10).
Variants: bad_photo 1, clean 5, fax 5, photo 18, scan 13.

| Path | What |
|---|---|
| `pages/` | page images, the only input for the pipeline |
| `truth/<doc_id>.json` | `GroundTruth`: field values, pixel boxes, mark regions, defect labels |
| `cases/<case_id>.json` | `CaseFile` truth for one patient-month |
| `cases/<case_id>.manifest.json` | defects with rules, documents and affected visit-log lines |
| `master_data.json` | the Pflegedienst's own records (staff, patients, doctors, Kassen) |
| `manifest.json` | all of the above in one index, plus coverage |

## Hero patients

| Patient | Case | Defects | Documents |
|---|---|---|---|
| Frau Albers | `p01-2026-10` | D01, D08 | `syn-demo-013` visit_log_sgbv (scan), `syn-demo-021` muster12 (photo), `syn-demo-023` approval_letter (clean) |
| Herr Brandl | `p02-2026-10` | D06 | `syn-demo-006` approval_letter (photo), `syn-demo-037` hospital_letter (photo), `syn-demo-039` visit_log_sgbv (photo), `syn-demo-042` muster12 (photo) |
| Frau Christl | `p03-2026-10` | D04 | `syn-demo-008` visit_log_sgbv (photo), `syn-demo-022` approval_letter (scan), `syn-demo-026` muster12 (photo) |
| Herr Dengler | `p04-2026-10` | D07, D09 | `syn-demo-010` approval_letter (scan), `syn-demo-011` muster12 (photo), `syn-demo-017` muster12 (photo), `syn-demo-031` approval_letter (fax), `syn-demo-040` visit_log_sgbv (photo) |
| Frau Eder | `p05-2026-10` | D20 | `syn-demo-001` visit_log_sgbxi (scan), `syn-demo-003` approval_letter (scan), `syn-demo-009` visit_log_sgbv (scan), `syn-demo-027` muster12 (photo), `syn-demo-028` hospital_letter (photo) |
| Herr Fischer (second SGB XI patient) | `p06-2026-10` | D12 | `syn-demo-016` visit_log_sgbxi (scan) |

## Defect coverage

| Defect | Rules | Patient-months | Documents |
|---|---|---|---|
| D01 | `HKP-RX-REQUIRED` | 1 | 2 |
| D02 | `HKP-APPROVAL-EXISTS` | 1 | 2 |
| D03 | `HKP-APPROVAL-SCOPE` | 1 | 2 |
| D04 | `HKP-LN-SIGNATURE`, `XI-LN-SIGNATURE` | 1 | 1 |
| D05 | `HKP-STAFF-INITIALS` | 1 | 1 |
| D06 | `STAY-HKP`, `STAY-XI-SACH` | 1 | 2 |
| D07 | `HKP-SUBMIT-4WD` | 1 | 1 |
| D08 | `HKP-FOLGE-WINDOW` | 1 | 1 |
| D09 | `HKP-RX-SIGNED` | 1 | 1 |
| D10 | `HKP-FREQ-RX` | 1 | 2 |
| D11 | `HKP-ERST-14D` | 1 | 1 |
| D12 | `XI-36-BUDGET` | 1 | 1 |
| D15 | `MD-DECEASED` | 1 | 1 |
| D16 | `MD-KVNR-CHECK` | 1 | 1 |
| D18 | `HKP-DUPLICATE` | 1 | 1 |
| D19 | `DOC-READABLE` | 1 | 1 |
| D20 | — (clean) | 4 | 14 |
