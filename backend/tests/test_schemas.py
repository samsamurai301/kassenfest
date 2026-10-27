from datetime import date

import pytest

from kassenfest.schemas.common import Box1000, Extracted, Mark
from kassenfest.schemas.domain import (
    CaseFile,
    Claim,
    ClaimLine,
    InsurancePeriod,
    Patient,
    Payer,
    Provider,
)
from kassenfest.schemas.extraction import EXTRACTION_SCHEMAS, Classification, Muster12
from kassenfest.schemas.findings import AuditorOutput, Evidence, Finding, claim_status
from kassenfest.schemas.jsonschema import (
    MAX_DEPTH,
    MAX_PROPERTIES,
    count_properties,
    inline_refs,
    nesting_depth,
    object_nodes,
)
from kassenfest.schemas.paths import FlatField, flatten

LLM_FACING = {**EXTRACTION_SCHEMAS, "classification": Classification, "auditor": AuditorOutput}


@pytest.mark.parametrize("name", sorted(LLM_FACING))
def test_llm_schemas_fit_meta_structured_output_limits(name):
    schema = inline_refs(LLM_FACING[name].model_json_schema())
    assert schema["type"] == "object" and "anyOf" not in schema
    assert nesting_depth(schema) <= MAX_DEPTH
    assert count_properties(schema) < MAX_PROPERTIES
    for node in object_nodes(schema):
        # Every key required + no extras: the strict subset, so the model never omits a field.
        assert node.get("additionalProperties") is False, node.get("title")
        assert set(node.get("required", [])) == set(node.get("properties", {})), node.get("title")


def test_inline_refs_rejects_recursion():
    schema = {"$defs": {"A": {"properties": {"a": {"$ref": "#/$defs/A"}}}}, "$ref": "#/$defs/A"}
    with pytest.raises(ValueError, match="recursive"):
        inline_refs(schema)


def _field(value, status="present"):
    return {"value": value, "status": status, "confidence": 0.9, "page": 0, "box": None}


def _mark(state):
    return {"state": state, "confidence": 0.9, "page": 0, "box": None}


def _muster12(**overrides):
    doc = {
        "doc_type": "muster12",
        "payer_name": _field("AOK Bayern"),
        "payer_ik": _field("108310400"),
        "patient_name": _field("Musterfrau, Erika"),
        "patient_dob": _field("1941-03-12"),
        "kvnr": _field("A123456780"),
        "bsnr": _field("711234500"),
        "lanr": _field("123456601"),
        "issue_date": _field("2026-10-01"),
        "icd_codes": _field(["E11.9"]),
        "prescription_kind": _field("erst"),
        "accident": _field(False),
        "blank_prescription": _field(False),
        "period_from": _field("2026-10-01"),
        "period_to": _field("2026-10-14"),
        "measures": [
            {
                "category": "medikamentengabe",
                "details": "Metformin 1000",
                "frequency": {"count": 2, "per": "day"},
                "duration_from": "2026-10-01",
                "duration_to": "2026-10-14",
                "confidence": 0.8,
                "page": 0,
                "box": {"x_min": 10, "y_min": 400, "x_max": 900, "y_max": 430},
            }
        ],
        "further_notes": _field(None, "empty"),
        "doctor_signature": _mark("present"),
        "practice_stamp": _mark("absent"),
        "corrections_present": False,
        "corrections_initialled": _mark("absent"),
    }
    doc.update(overrides)
    return Muster12.model_validate(doc)


def test_flatten_paths_cover_fields_marks_and_lists():
    flat = flatten(_muster12())
    assert flat["kvnr"] == FlatField("A123456780", "present")
    assert flat["further_notes"] == FlatField(None, "empty")
    assert flat["practice_stamp"] == FlatField("absent", "present")
    assert flat["measures[#]"] == FlatField(1, "present")
    assert flat["measures[0].frequency.count"] == FlatField(2, "present")
    assert flat["icd_codes"].value == ["E11.9"]
    # Row bookkeeping is not a fact about the document.
    assert not any(k.endswith((".confidence", ".page", ".box")) for k in flat)


def test_extracted_generic_is_recognised_and_validates():
    m = _muster12()
    assert isinstance(m.kvnr, Extracted) and isinstance(m.doctor_signature, Mark)
    with pytest.raises(ValueError):
        _muster12(prescription_kind=_field("maybe"))


def test_box1000_and_extra_keys_are_strict():
    Box1000(x_min=0, y_min=0, x_max=1000, y_max=1000)
    with pytest.raises(ValueError):
        _muster12(unexpected="x")


def _patient():
    return Patient(
        id="pat-01",
        name="Musterfrau, Erika",
        dob=date(1941, 3, 12),
        kvnr="A123456780",
        insurance=[
            InsurancePeriod(
                krankenkasse_ik="108310400",
                pflegekasse_ik="108310400",
                valid_from=date(2020, 1, 1),
            )
        ],
    )


def test_casefile_roundtrips_through_json():
    case = CaseFile(
        month="2026-10",
        provider=Provider(
            name="Pflegedienst Sonnenschein", ik="461234567", municipality="Deggendorf"
        ),
        patient=_patient(),
        payers={"108310400": Payer(name="AOK Bayern", ik="108310400", kind="krankenkasse")},
    )
    assert CaseFile.model_validate_json(case.model_dump_json()) == case


def test_claim_totals_are_integer_cents():
    claim = Claim(
        id="c1",
        patient_id="pat-01",
        payer_ik="108310400",
        month="2026-10",
        domain="sgbv",
        tariff_version="by-2026-01-illustrative",
        lines=[
            ClaimLine(
                id="l1", date=date(2026, 10, 1), code="031199", quantity=2, unit_price_cents=1234
            ),
            ClaimLine(
                id="l2", date=date(2026, 10, 2), code="031199", quantity=1, unit_price_cents=1234
            ),
        ],
    )
    assert claim.total_cents == 3702
    assert claim.model_dump()["lines"][0]["amount_cents"] == 2468


def _finding(severity, evidence=True):
    return Finding(
        id="f",
        rule_id="HKP-RX-SIGNED",
        rule_version=1,
        severity=severity,
        patient_id="pat-01",
        message_de="…",
        message_en="…",
        sources=["Muster 12"],
        evidence=[Evidence(document_id="doc-1")] if evidence else [],
    )


def test_claim_status_needs_evidence_to_go_red():
    assert claim_status([]) == "green"
    assert claim_status([_finding("info")]) == "green"
    assert claim_status([_finding("warn")]) == "orange"
    assert claim_status([_finding("block")]) == "red"
    assert claim_status([_finding("block", evidence=False)]) == "orange"
