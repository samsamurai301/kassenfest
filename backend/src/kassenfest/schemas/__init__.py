"""Shared contracts. Change these only on main: every track builds on them (docs/05 §2.2).

- extraction:   what Muse Spark returns per document type (paper, with status + location)
- ground_truth: what the synthetic generator writes next to each document
- domain:       typed facts the rules engine evaluates (CaseFile is its input)
- findings:     rule findings, evidence, auditor objections and verdicts
- paths:        flatten() — the dotted-path key space shared by extraction and truth
"""
