"""Deterministic rules engine: CaseFile → claims (tariffs) → findings with evidence.

Importing this package registers every rule module with the engine.
"""

from kassenfest.rules import doc, hkp, md, sgbxi, stay  # noqa: F401  (registers the rules)
from kassenfest.rules.engine import EngineResult, evaluate, evaluate_document, run

__all__ = ["EngineResult", "evaluate", "evaluate_document", "run"]
