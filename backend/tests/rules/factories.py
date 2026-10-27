"""Small CaseFile builders. `case()` is a clean October 2026 month that passes every rule;
each test breaks one thing. Everything is synthetic (IKs from data/reference/payers.yaml).
"""

import datetime as dt
from typing import Any

from kassenfest.rules import run
from kassenfest.rules.engine import EngineResult
from kassenfest.rules.reference import load_reference
from kassenfest.schemas.common import Frequency
from kassenfest.schemas.domain import (
    Approval,
    ApprovedService,
    CaseFile,
    InsurancePeriod,
    Patient,
    PflegegradPeriod,
    PrescribedService,
    Prescription,
    Provider,
    Staff,
    Stay,
    Visit,
    VisitLog,
)
from kassenfest.schemas.extraction import Muster12
from kassenfest.schemas.findings import Finding

D = dt.date
KK_IK = "109990018"  # AOK Bayern, synthetic Krankenkasse IK
PK_IK = "189990018"  # AOK Bayern, synthetic Pflegekasse IK
PROVIDER_IK = "469990018"
KVNR = "A123456780"
MEDIKAMENTE = "032101"
STRUEMPFE_AN = "032130"
WUNDE = "032150"
WEGE = "032188"
OCT_1 = D(2026, 10, 1)
DEC_31 = D(2026, 12, 31)


def t(hhmm: str) -> dt.time:
    return dt.time.fromisoformat(hhmm)


def ts(day: dt.date, hhmm: str) -> dt.datetime:
    return dt.datetime.combine(day, t(hhmm))


def days(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def month_days(month: str) -> list[dt.date]:
    year, m = map(int, month.split("-"))
    start = D(year, m, 1)
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return days(start, end)


def freq(count: int, per: str = "day") -> Frequency:
    return Frequency(count=count, per=per)


def provider(**kw: Any) -> Provider:
    staff = [
        Staff(
            employee_no="100000001",
            initials="AB",
            name="Anna Berger",
            qualification="pflegefachkraft",
        ),
        Staff(
            employee_no="100000002",
            initials="CD",
            name="Carl Dorn",
            qualification="pflegefachkraft",
        ),
    ]
    defaults = dict(
        name="Pflegedienst Sonnenschein GmbH",
        ik=PROVIDER_IK,
        municipality="Deggendorf",
        staff=staff,
    )
    return Provider(**{**defaults, **kw})


def patient(**kw: Any) -> Patient:
    defaults = dict(
        id="p01",
        name="Muster, Erika",
        dob=D(1938, 5, 2),
        kvnr=KVNR,
        insurance=[
            InsurancePeriod(krankenkasse_ik=KK_IK, pflegekasse_ik=PK_IK, valid_from=D(2020, 1, 1))
        ],
        pflegegrad=[PflegegradPeriod(grade=3, valid_from=D(2025, 1, 1))],
    )
    return Patient(**{**defaults, **kw})


def service(
    category: str = "medikamentengabe",
    count: int | None = 2,
    per: str = "day",
    position_no: str | None = None,
) -> PrescribedService:
    return PrescribedService(
        category=category,
        position_no=position_no,
        frequency=freq(count, per) if count is not None else None,
    )


def prescription(**kw: Any) -> Prescription:
    rx_id = kw.get("id", "rx1")
    defaults = dict(
        id=rx_id,
        patient_id="p01",
        physician_lanr="123456601",
        kind="folge",
        issue_date=D(2026, 9, 28),
        period_from=D(2026, 10, 1),
        period_to=D(2026, 12, 31),
        services=[service()],
        doctor_signed=True,
        stamp_present=True,
        submitted_to_payer_at=D(2026, 9, 29),
        document_id=f"doc-{rx_id}",
    )
    return Prescription(**{**defaults, **kw})


def approved(
    code: str = MEDIKAMENTE,
    count: int | None = 2,
    per: str = "day",
    valid_from: dt.date = OCT_1,
    valid_to: dt.date = DEC_31,
) -> ApprovedService:
    return ApprovedService(
        position_no=code,
        frequency=freq(count, per) if count is not None else None,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def approval(**kw: Any) -> Approval:
    ap_id = kw.get("id", "ap1")
    defaults = dict(
        id=ap_id,
        patient_id="p01",
        payer_ik=KK_IK,
        provider_ik=PROVIDER_IK,
        approval_ref="GEN-2026-0001",
        letter_date=D(2026, 10, 5),
        decision="approved",
        period_from=D(2026, 10, 1),
        period_to=D(2026, 12, 31),
        approved=[approved()],
        prescription_id="rx1",
        document_id=f"doc-{ap_id}",
    )
    return Approval(**{**defaults, **kw})


def visit(day: dt.date, hhmm: str | None = "08:00", code: str = MEDIKAMENTE, **kw: Any) -> Visit:
    defaults = dict(
        date=day,
        start=t(hhmm) if hhmm else None,
        code=code,
        staff_initials="AB",
        employee_no="100000001",
    )
    return Visit(**{**defaults, **kw})


def daily_visits(
    month: str = "2026-10",
    times: tuple[str, ...] = ("08:00", "18:00"),
    code: str = MEDIKAMENTE,
    **kw: Any,
) -> list[Visit]:
    return [visit(d, hhmm, code, **kw) for d in month_days(month) for hhmm in times]


def hkp_log(visits: list[Visit] | None = None, **kw: Any) -> VisitLog:
    defaults = dict(
        id="ln-v",
        patient_id="p01",
        payer_ik=KK_IK,
        month="2026-10",
        domain="sgbv",
        visits=daily_visits() if visits is None else visits,
        patient_signed=True,
        document_id="doc-ln-v",
    )
    return VisitLog(**{**defaults, **kw})


def xi_log(visits: list[Visit] | None = None, **kw: Any) -> VisitLog:
    month = kw.get("month", "2026-10")
    default_visits = daily_visits(month, ("09:00",), "LK01", funding="sachleistung_36")
    defaults = dict(
        id="ln-xi",
        patient_id="p01",
        payer_ik=PK_IK,
        month=month,
        domain="sgbxi",
        visits=default_visits if visits is None else visits,
        patient_signed=True,
        document_id="doc-ln-xi",
    )
    return VisitLog(**{**defaults, **kw})


def stay(admitted: dt.datetime, discharged: dt.datetime | None, kind: str = "hospital") -> Stay:
    return Stay(
        id="st1",
        patient_id="p01",
        kind=kind,
        admitted_at=admitted,
        discharged_at=discharged,
        document_id="doc-st1",
    )


def case(**kw: Any) -> CaseFile:
    defaults = dict(
        month="2026-10",
        provider=provider(),
        patient=patient(),
        payers=load_reference().payers(),
        prescriptions=[prescription()],
        approvals=[approval()],
        visit_logs=[hkp_log(), xi_log()],
    )
    return CaseFile(**{**defaults, **kw})


def evaluate(c: CaseFile, rule_id: str | None = None, **kw: Any) -> list[Finding]:
    findings = run(c, **kw).findings
    return [f for f in findings if rule_id is None or f.rule_id == rule_id]


def result(c: CaseFile, **kw: Any) -> EngineResult:
    return run(c, **kw)


def one(c: CaseFile, rule_id: str, **kw: Any) -> Finding:
    found = evaluate(c, rule_id, **kw)
    assert len(found) == 1, [f.id for f in found]
    return found[0]


# --- extraction fixtures for document rules ---------------------------------------


def field(value: Any, status: str = "present", confidence: float = 0.95) -> dict[str, Any]:
    return {"value": value, "status": status, "confidence": confidence, "page": 0, "box": None}


def mark(state: str, confidence: float = 0.95) -> dict[str, Any]:
    return {"state": state, "confidence": confidence, "page": 0, "box": None}


def muster12(**overrides: Any) -> Muster12:
    doc = {
        "doc_type": "muster12",
        "payer_name": field("AOK Bayern"),
        "payer_ik": field(KK_IK),
        "patient_name": field("Muster, Erika"),
        "patient_dob": field("1938-05-02"),
        "kvnr": field(KVNR),
        "bsnr": field("711234500"),
        "lanr": field("123456601"),
        "issue_date": field("2026-09-28"),
        "icd_codes": field(["E11.9"]),
        "prescription_kind": field("folge"),
        "accident": field(False),
        "blank_prescription": field(False),
        "period_from": field("2026-10-01"),
        "period_to": field("2026-12-31"),
        "measures": [
            {
                "category": "medikamentengabe",
                "details": "Metformin 1000",
                "frequency": {"count": 2, "per": "day"},
                "duration_from": "2026-10-01",
                "duration_to": "2026-12-31",
                "confidence": 0.9,
                "page": 0,
                "box": None,
            }
        ],
        "further_notes": field(None, "empty"),
        "doctor_signature": mark("present"),
        "practice_stamp": mark("present"),
        "corrections_present": False,
        "corrections_initialled": mark("absent"),
    }
    return Muster12.model_validate({**doc, **overrides})
