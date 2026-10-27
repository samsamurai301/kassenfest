"""Timeline -> the paper pile for one patient-month: what each document shows.

Doctors, Kassen and the hospital print the KVNR from the patient's card; the
Pflegedienst prints the one in its own software (they differ only for defect D16).
Document keys ("muster12:<rx id>", "visit_log_sgbv", …) tie defect labels to documents
before document ids exist.
"""

import datetime as dt
import random
from dataclasses import dataclass

from pydantic import BaseModel

from kassenfest.schemas.common import DocType
from kassenfest.synth import catalog
from kassenfest.synth.catalog import LK
from kassenfest.synth.documents import (
    M12_ROWS,
    ApprovalLetterContent,
    ApprovedLine,
    HospitalLetterContent,
    LNService,
    LNStaff,
    LNVisit,
    M12Measure,
    Muster12Content,
    RejectedLine,
    VisitLogContent,
    VisitLogXIContent,
    XIEinsatz,
    XIVisit,
)
from kassenfest.synth.world import (
    CLERKS,
    MONTH,
    MONTH_END,
    YEAR,
    Timeline,
    World,
    sheet_services,
    slot_rank,
    visit_order,
)

ROW_LABEL = dict(M12_ROWS)
FURTHER_NOTES = [
    None,
    None,
    None,
    "Bitte BZ-Werte dokumentieren",
    "Rücksprache bei Wundverschlechterung",
    "Medikamente nach beiliegendem Plan",
]


@dataclass
class DocPlan:
    key: str
    doc_type: DocType
    content: BaseModel


def doc_keys(tl: Timeline) -> list[str]:
    keys = [f"muster12:{rx.id}" for rx in tl.in_month(tl.prescriptions)]
    keys += [f"approval_letter:{a.id}" for a in tl.in_month(tl.approvals)]
    keys += [f"visit_log_{d}" for d in tl.domains]
    keys += [f"hospital_letter:{s.id}" for s in tl.stays]
    return keys


def _rng(world: World, tl: Timeline, key: str) -> random.Random:
    return random.Random(f"{world.seed}:{tl.record.id}:{key}")


def muster12(world: World, tl: Timeline, rx_id: str) -> Muster12Content:
    rx = next(p for p in tl.prescriptions if p.id == rx_id)
    rng = _rng(world, tl, rx_id)
    rec = tl.record
    kasse = rec.kasse_at(rx.period_from)
    doctor = world.doctor(rx.physician_lanr)
    return Muster12Content(
        payer_name=kasse.name,
        payer_ik=kasse.krankenkasse_ik,
        patient_name=rec.name,
        patient_dob=rec.dob,
        kvnr=rec.card_kvnr,
        status="5000000" if rng.random() < 0.8 else "1000000",
        bsnr=doctor.bsnr,
        lanr=doctor.lanr,
        issue_date=rx.issue_date,
        icd_codes=rx.icd_codes,
        limitations=rec.limitations,
        kind=rx.kind,
        blank=rx.blank,
        period_from=rx.period_from,
        period_to=rx.period_to,
        measures=[
            M12Measure(
                category=s.category,
                label=ROW_LABEL.get(s.category, s.category),
                details=s.details,
                count=s.frequency.count if s.frequency else None,
                per=s.frequency.per if s.frequency else None,
                duration_from=rx.period_from,
                duration_to=rx.period_to,
            )
            for s in rx.services
        ],
        further_notes=rng.choice(FURTHER_NOTES),
        doctor_name=doctor.name,
        practice_lines=doctor.stamp_lines,
        doctor_signed=rx.doctor_signed,
        stamp_present=rx.stamp_present,
    )


def approval_letter(world: World, tl: Timeline, ap_id: str) -> ApprovalLetterContent:
    ap = next(a for a in tl.approvals if a.id == ap_id)
    rx = next(p for p in tl.prescriptions if p.id == ap.prescription_id)
    rng = _rng(world, tl, ap_id)
    kasse = catalog.KASSE_BY_IK[ap.payer_ik]
    return ApprovalLetterContent(
        style=kasse.letter_style,
        payer_name=kasse.name,
        payer_ik=ap.payer_ik,
        payer_address=list(kasse.address),
        letter_date=ap.letter_date,
        approval_ref=ap.approval_ref,
        patient_name=tl.record.name,
        patient_dob=tl.record.dob,
        kvnr=tl.record.card_kvnr,
        provider_name=world.provider.name,
        provider_address=list(catalog.PROVIDER_ADDRESS),
        provider_ik=ap.provider_ik,
        prescription_issue_date=rx.issue_date,
        decision=ap.decision,
        period_from=ap.period_from,
        period_to=ap.period_to,
        approved=[
            ApprovedLine(
                position_no=a.position_no,
                description=catalog.HKP_SERVICES[a.position_no].label,
                count=a.frequency.count if a.frequency else None,
                per=a.frequency.per if a.frequency else None,
                valid_from=a.valid_from,
                valid_to=a.valid_to,
            )
            for a in ap.approved
        ],
        rejected=[
            RejectedLine(description=catalog.HKP_SERVICES[pos].label, reason=reason)
            for pos, reason in tl.rejected.get(ap.id, [])
        ],
        copay_exempt=tl.record.copay_exempt,
        clerk=rng.choice(CLERKS),
        phone=f"0991 999 {rng.randint(1000, 1999)}",
    )


def _staff_index(world: World, tl: Timeline, domain: str) -> tuple[list[LNStaff], dict[int, int]]:
    """Staff appearing on the sheet, in order of first appearance."""
    order: dict[int, int] = {}
    for r in visit_order(tl, domain):  # type: ignore[arg-type]
        if r.staff is not None and r.staff not in order:
            order[r.staff] = len(order)
    staff = [
        LNStaff(initials=world.staff[i].initials, employee_no=world.staff[i].employee_no)
        for i in order
    ]
    return staff, order


def _signature_date(tl: Timeline, domain: str) -> dt.date | None:
    if not tl.signed.get(domain):
        return None
    recs = tl.october_of(domain)  # type: ignore[arg-type]
    return max(r.date for r in recs) if recs else MONTH_END


def _approval_ref(tl: Timeline) -> str | None:
    covering = sorted(tl.in_month(tl.approvals), key=lambda a: a.period_from)
    return covering[-1].approval_ref if covering else None


def visit_log_sgbv(world: World, tl: Timeline) -> VisitLogContent:
    columns = sheet_services(tl)
    rank = slot_rank(tl)
    recs = visit_order(tl, "sgbv")
    staff, index = _staff_index(world, tl, "sgbv")
    slots = {c: 1 for c in columns}
    for r in recs:
        slots[r.code] = max(slots[r.code], rank[id(r)] + 1)
    kasse = tl.record.kasse_at(MONTH_END)
    reason = tl.missing_reason.get("sgbv")
    return VisitLogContent(
        provider_name=f"{world.provider.name}, Deggendorf",
        provider_ik=world.provider.ik,
        patient_name=tl.record.name,
        kvnr=tl.record.kvnr,
        payer_name=kasse.name,
        year=YEAR,
        month=MONTH,
        approval_ref=_approval_ref(tl),
        responsible_nurse=catalog.PDL,
        services=[
            LNService(position_no=c, label=catalog.HKP_SERVICES[c].label, slots=slots[c])
            for c in columns
        ],
        staff=staff,
        visits=[
            LNVisit(
                day=r.date.day,
                service=columns.index(r.code),
                slot=rank[id(r)],
                time=r.when.time(),
                staff=index[r.staff] if r.staff is not None else None,
            )
            for r in recs
        ],
        patient_signed=tl.signed["sgbv"],
        patient_signature_date=_signature_date(tl, "sgbv"),
        missing_signature_reason=str(reason) if reason else None,  # type: ignore[arg-type]
        provider_signed=True,
    )


def visit_log_sgbxi(world: World, tl: Timeline) -> VisitLogXIContent:
    staff, index = _staff_index(world, tl, "sgbxi")
    visits: dict[tuple[int, int], XIVisit] = {}
    for r in visit_order(tl, "sgbxi"):
        key = (r.date.day, r.einsatz or 0)
        if key not in visits:
            visits[key] = XIVisit(
                day=r.date.day,
                einsatz=r.einsatz or 0,
                time=r.when.time(),
                staff=index[r.staff] if r.staff is not None else None,
                lk=[],
            )
        visits[key].lk.append(r.code)
    kasse = tl.record.kasse_at(MONTH_END)
    return VisitLogXIContent(
        provider_name=f"{world.provider.name}, Deggendorf",
        provider_ik=world.provider.ik,
        patient_name=tl.record.name,
        kvnr=tl.record.kvnr,
        payer_name=kasse.pflegekasse_name,
        pflegegrad=tl.record.pflegegrad_at(MONTH_END) or 0,
        year=YEAR,
        month=MONTH,
        einsaetze=[
            XIEinsatz(label=e.label, funding=e.funding, lk=[(c, LK[c].label) for c in e.lk])
            for e in tl.record.xi
        ],
        staff=staff,
        visits=list(visits.values()),
        patient_signed=tl.signed["sgbxi"],
        patient_signature_date=_signature_date(tl, "sgbxi"),
        provider_signed=True,
    )


def hospital_letter(world: World, tl: Timeline, stay_id: str) -> HospitalLetterContent:
    stay = next(s for s in tl.stays if s.id == stay_id)
    info = tl.stay_info[stay_id]
    assert stay.discharged_at is not None
    rec = tl.record
    doctor = world.doctor(rec.doctor_lanr)
    services = ", ".join(dict.fromkeys(catalog.HKP_SERVICES[s.position_no].label for s in rec.hkp))
    return HospitalLetterContent(
        hospital_name=catalog.HOSPITAL_NAME,
        hospital_lines=list(catalog.HOSPITAL_LINES),
        hospital_id=world.hospital_id,
        letter_date=stay.discharged_at.date(),
        recipient_lines=[doctor.name, doctor.street, " ".join(doctor.zip_town)],
        patient_name=rec.name,
        patient_sex=rec.sex,
        patient_dob=rec.dob,
        kvnr=rec.card_kvnr,
        payer_name=rec.kasse_at(stay.admitted_at.date()).name,
        admitted_at=stay.admitted_at,
        discharged_at=stay.discharged_at,
        diagnoses=[(code, catalog.ICD[code]) for code in info.diagnoses],
        hkp_recommended=info.hkp_recommended,
        hkp_text=f"Fortführung der häuslichen Krankenpflege ({services}) durch den bekannten "
        "Pflegedienst empfohlen."
        if info.hkp_recommended
        else None,
        hkp_prescription_days=info.hkp_days,
        medication=info.medication,
        physician=info.physician,
        signed=info.signed,
    )


def documents(world: World, tl: Timeline) -> list[DocPlan]:
    out = []
    for key in doc_keys(tl):
        kind, _, ref = key.partition(":")
        if kind == "muster12":
            out.append(DocPlan(key, "muster12", muster12(world, tl, ref)))
        elif kind == "approval_letter":
            out.append(DocPlan(key, "approval_letter", approval_letter(world, tl, ref)))
        elif kind == "visit_log_sgbv":
            out.append(DocPlan(key, "visit_log_sgbv", visit_log_sgbv(world, tl)))
        elif kind == "visit_log_sgbxi":
            out.append(DocPlan(key, "visit_log_sgbxi", visit_log_sgbxi(world, tl)))
        else:
            out.append(DocPlan(key, "hospital_letter", hospital_letter(world, tl, ref)))
    return out
