"""Read-only endpoints behind the web screens.

They serve one `World`: the pipeline's evaluated month once it has processed documents
(`api.live`), the hand-built fixtures before that or when API_SOURCE=fixtures.
"""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from kassenfest.api import fixtures, live
from kassenfest.api.fixtures import World
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
from kassenfest.config import get_settings
from kassenfest.schemas.domain import Claim
from kassenfest.schemas.findings import ClaimStatus, Finding, claim_status

router = APIRouter(prefix="/api")

STATUS_ORDER: tuple[ClaimStatus, ...] = ("red", "orange", "green")
SEVERITY_RANK = {"block": 0, "warn": 1, "info": 2}


def current_world() -> World:
    settings = get_settings()
    if settings.api_source != "fixtures":
        w = live.pipeline_world(settings)
        if w is not None:
            return w
        if settings.api_source == "pipeline":
            raise HTTPException(503, "The pipeline has not processed any documents yet")
    return fixtures.world()


Current = Annotated[World, Depends(current_world)]


def _month(w: World, month: str) -> World:
    if month != w.month:
        raise HTTPException(404, f"No bills for {month} yet: the month on file is {w.month}")
    return w


def _claim_findings(w: World, claim: Claim) -> list[Finding]:
    """The claim's own findings, and claim-less ones that hit any of its lines."""
    lines = {line.id for line in claim.lines}
    found = [
        f
        for f in w.findings
        if f.claim_id == claim.id or (f.claim_id is None and lines & set(f.claim_line_ids))
    ]
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
def month_board(month: str, world: Current) -> MonthBoard:
    w = _month(world, month)
    cards = []
    for claim in w.claims.values():
        findings = _claim_findings(w, claim)
        patient = w.patients[claim.patient_id]
        cards.append(
            BoardCard(
                claim_id=claim.id,
                patient_id=patient.id,
                patient_name=patient.name,
                payer=w.payers[claim.payer_ik],
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
        as_of=w.as_of,
        provider=w.provider,
        total_cents=sum(c.total_cents for c in cards),
        at_risk_cents=sum(c.at_risk_cents for c in cards),
        by_status=by_status,
        cards=cards,
    )


@router.get("/months/{month}/actions")
def month_actions(month: str, world: Current) -> ActionList:
    w = _month(world, month)
    actions = sorted(w.actions, key=lambda a: (a.due_date, -a.amount_cents))
    return ActionList(month=month, as_of=w.as_of, actions=actions)


@router.get("/claims/{claim_id}")
def claim_detail(claim_id: str, w: Current) -> ClaimDetail:
    claim = w.claims.get(claim_id)
    if claim is None:
        raise HTTPException(404, f"Unknown claim {claim_id}")
    findings = _claim_findings(w, claim)
    doc_ids = {e.document_id for f in findings for e in f.evidence}
    doc_ids |= {d.id for d in w.documents.values() if d.patient_id == claim.patient_id}
    return ClaimDetail(
        claim=claim,
        as_of=w.as_of,
        status=claim_status(findings),
        at_risk_cents=at_risk_cents(claim, findings),
        patient=w.patients[claim.patient_id],
        payer=w.payers[claim.payer_ik],
        findings=findings,
        documents=[w.documents[d] for d in sorted(doc_ids)],
        actions=[a for a in w.actions if a.claim_id == claim_id],
        code_labels={line.code: w.code_labels.get(line.code, line.code) for line in claim.lines},
        tariff_note=w.tariff_note,
    )


@router.get("/patients/{patient_id}/timeline")
def patient_timeline(patient_id: str, w: Current, month: str | None = None) -> PatientTimeline:
    month = _month(w, month or w.month).month
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
        holidays=[Holiday(date=d, name=n) for d, n in w.holidays.items()],
        physicians=[
            w.physicians[lanr]
            for lanr in dict.fromkeys(rx.physician_lanr for rx in prescriptions)
            if lanr in w.physicians
        ],
        payers=[w.payers[ik] for ik in dict.fromkeys(c.payer_ik for c in claims)],
        prescriptions=prescriptions,
        approvals=[a for a in w.approvals if a.patient_id == patient_id],
        stays=[s for s in w.stays if s.patient_id == patient_id],
        visit_logs=[v for v in w.visit_logs if v.patient_id == patient_id],
        claims=claims,
        findings=[f for f in w.findings if f.patient_id == patient_id],
        documents=[d for d in w.documents.values() if d.patient_id == patient_id],
        code_labels=w.code_labels,
    )


@router.get("/documents/{document_id}")
def document_detail(document_id: str, w: Current) -> DocumentDetail:
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
    responses={
        200: {"content": {"image/png": {}, "image/jpeg": {}}, "description": "The page image"}
    },
)
def document_page(document_id: str, index: int, w: Current) -> Response:
    image = w.page_image(document_id, index)
    if image is None:
        raise HTTPException(404, f"No page {index} in document {document_id}")
    data, media_type = image
    return Response(data, media_type=media_type, headers={"Cache-Control": "public, max-age=600"})
