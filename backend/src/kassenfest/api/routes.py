"""Read-only endpoints behind the web screens, served from fixtures for now.

The pipeline replaces `fixtures.world()` later; the response models stay the same.
"""

import datetime as dt

from fastapi import APIRouter, HTTPException, Response

from kassenfest.api import fixtures
from kassenfest.api.models import (
    ActionList,
    BoardCard,
    ClaimDetail,
    DocumentDetail,
    Holiday,
    MonthBoard,
    PatientTimeline,
    StatusTotal,
)
from kassenfest.schemas.domain import Claim
from kassenfest.schemas.findings import ClaimStatus, Finding, claim_status

router = APIRouter(prefix="/api")

STATUS_ORDER: tuple[ClaimStatus, ...] = ("red", "orange", "green")
SEVERITY_RANK = {"block": 0, "warn": 1, "info": 2}


def _month(month: str) -> fixtures.World:
    if month != fixtures.MONTH:
        raise HTTPException(404, f"No bills for {month} yet: the demo month is {fixtures.MONTH}")
    return fixtures.world()


def _claim_findings(w: fixtures.World, claim_id: str) -> list[Finding]:
    found = [f for f in w.findings if f.claim_id == claim_id]
    return sorted(found, key=lambda f: (SEVERITY_RANK[f.severity], -f.amount_at_risk_cents))


def at_risk_cents(claim: Claim, findings: list[Finding]) -> int:
    """Money the Kasse would cut: each flagged line counts once, however many rules hit it.

    Info findings never put money at risk. A finding without lines (e.g. a budget cap)
    carries its own amount.
    """
    risky = [f for f in findings if f.severity != "info"]
    flagged = {line_id for f in risky for line_id in f.claim_line_ids}
    from_lines = sum(line.amount_cents for line in claim.lines if line.id in flagged)
    from_claim = sum(f.amount_at_risk_cents for f in risky if not f.claim_line_ids)
    return min(claim.total_cents, from_lines + from_claim)


@router.get("/months/{month}/board")
def month_board(month: str) -> MonthBoard:
    w = _month(month)
    cards = []
    for claim in w.claims.values():
        findings = _claim_findings(w, claim.id)
        patient = w.patients[claim.patient_id]
        cards.append(
            BoardCard(
                claim_id=claim.id,
                patient_id=patient.id,
                patient_name=patient.name,
                payer=fixtures.PAYERS[claim.payer_ik],
                domain=claim.domain,
                status=claim_status(findings),
                total_cents=claim.total_cents,
                at_risk_cents=at_risk_cents(claim, findings),
                line_count=len(claim.lines),
                finding_count=len(findings),
                top_finding=findings[0] if findings else None,
            )
        )
    cards.sort(key=lambda c: (STATUS_ORDER.index(c.status), -c.at_risk_cents, c.patient_name))
    by_status = [
        StatusTotal(
            status=status,
            count=len(group := [c for c in cards if c.status == status]),
            total_cents=sum(c.total_cents for c in group),
            at_risk_cents=sum(c.at_risk_cents for c in group),
        )
        for status in STATUS_ORDER
    ]
    return MonthBoard(
        month=month,
        as_of=fixtures.AS_OF,
        provider=fixtures.PROVIDER,
        total_cents=sum(c.total_cents for c in cards),
        at_risk_cents=sum(c.at_risk_cents for c in cards),
        by_status=by_status,
        cards=cards,
    )


@router.get("/months/{month}/actions")
def month_actions(month: str) -> ActionList:
    w = _month(month)
    actions = sorted(w.actions, key=lambda a: (a.due_date, -a.amount_cents))
    return ActionList(month=month, as_of=fixtures.AS_OF, actions=actions)


@router.get("/claims/{claim_id}")
def claim_detail(claim_id: str) -> ClaimDetail:
    w = fixtures.world()
    claim = w.claims.get(claim_id)
    if claim is None:
        raise HTTPException(404, f"Unknown claim {claim_id}")
    findings = _claim_findings(w, claim_id)
    doc_ids = {e.document_id for f in findings for e in f.evidence}
    doc_ids |= {d.id for d in w.documents.values() if d.patient_id == claim.patient_id}
    return ClaimDetail(
        claim=claim,
        status=claim_status(findings),
        at_risk_cents=at_risk_cents(claim, findings),
        patient=w.patients[claim.patient_id],
        payer=fixtures.PAYERS[claim.payer_ik],
        findings=findings,
        documents=[w.documents[d] for d in sorted(doc_ids)],
        actions=[a for a in w.actions if a.claim_id == claim_id],
        code_labels={line.code: fixtures.CODE_LABELS[line.code] for line in claim.lines},
        tariff_note=fixtures.TARIFF_NOTE,
    )


@router.get("/patients/{patient_id}/timeline")
def patient_timeline(patient_id: str, month: str = fixtures.MONTH) -> PatientTimeline:
    w = _month(month)
    patient = w.patients.get(patient_id)
    if patient is None:
        raise HTTPException(404, f"Unknown patient {patient_id}")
    prescriptions = [rx for rx in w.prescriptions if rx.patient_id == patient_id]
    claims = [c for c in w.claims.values() if c.patient_id == patient_id]
    year, mon = (int(part) for part in month.split("-"))
    first = dt.date(year, mon, 1)
    last = dt.date(year + mon // 12, mon % 12 + 1, 1) - dt.timedelta(days=1)
    return PatientTimeline(
        patient=patient,
        month=month,
        first_day=first,
        last_day=last,
        holidays=[Holiday(date=d, name=n) for d, n in fixtures.HOLIDAYS.items()],
        physicians=[fixtures.PHYSICIANS[rx.physician_lanr] for rx in prescriptions],
        payers=[fixtures.PAYERS[c.payer_ik] for c in claims],
        prescriptions=prescriptions,
        approvals=[a for a in w.approvals if a.patient_id == patient_id],
        stays=[s for s in w.stays if s.patient_id == patient_id],
        visit_logs=[v for v in w.visit_logs if v.patient_id == patient_id],
        claims=claims,
        findings=[f for f in w.findings if f.patient_id == patient_id],
        documents=[d for d in w.documents.values() if d.patient_id == patient_id],
        code_labels=fixtures.CODE_LABELS,
    )


@router.get("/documents/{document_id}")
def document_detail(document_id: str) -> DocumentDetail:
    w = fixtures.world()
    doc = w.documents.get(document_id)
    if doc is None:
        raise HTTPException(404, f"Unknown document {document_id}")
    findings = [f for f in w.findings if any(e.document_id == document_id for e in f.evidence)]
    return DocumentDetail(
        document=doc,
        fields=w.document_fields[document_id],
        findings=findings,
        claim_ids=sorted({f.claim_id for f in findings if f.claim_id}),
    )


@router.get(
    "/documents/{document_id}/pages/{index}",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "The page as PNG"}},
)
def document_page(document_id: str, index: int) -> Response:
    pages = fixtures.world().page_images.get(document_id, [])
    if not 0 <= index < len(pages):
        raise HTTPException(404, f"No page {index} in document {document_id}")
    return Response(
        fixtures.page_png(document_id, index),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=600"},
    )
