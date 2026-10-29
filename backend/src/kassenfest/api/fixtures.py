"""Fixture data for the web screens: served until the pipeline has processed a document
(or always, with API_SOURCE=fixtures).

The demo month of docs/05 §4.4: Pflegedienst Sonnenschein GmbH, Deggendorf, October
2026, with the five hero patients (Albers … Eder) and five background patients (Fink …
Jäger). Everything is built from the shared schemas, so the pipeline's world (`api.live`)
sits behind the same endpoints. All people, IDs and documents are synthetic; prices are
illustrative.
"""

import datetime as dt
import mimetypes
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Literal

from kassenfest.api import pages
from kassenfest.api.models import (
    Action,
    ClaimAudit,
    DocumentField,
    DocumentInfo,
    Letter,
    PageInfo,
)
from kassenfest.schemas.common import DocType, FieldStatus, Frequency, PixelBox
from kassenfest.schemas.domain import (
    Approval,
    ApprovedService,
    Claim,
    ClaimLine,
    Domain,
    InsurancePeriod,
    Patient,
    Payer,
    PflegegradPeriod,
    Physician,
    PrescribedService,
    Prescription,
    Provider,
    Staff,
    Stay,
    Visit,
    VisitLog,
)
from kassenfest.schemas.findings import Evidence, Finding, KasseCode, Severity

MONTH = "2026-10"
AS_OF = dt.date(2026, 11, 2)
"""'Today' in the demo world: the Monday the October bills are checked."""
BILLING_RUN = dt.date(2026, 11, 6)
TARIFF_VERSION = "2026-10-illustrative"
TARIFF_NOTE = "Prices are illustrative demo values, not a real §132a or §89 contract."
HOLIDAYS = {dt.date(2026, 10, 3): "Tag der Deutschen Einheit"}
OCTOBER = [dt.date(2026, 10, d) for d in range(1, 32)]


# --- Check digits, so the master data passes MD-KVNR-CHECK / MD-IK-CHECK ----------


def _digit_sum(n: int) -> int:
    return n // 10 + n % 10


def ik(stem: str) -> str:
    """8 digits + check digit: digits 3-8 weighted 2,1,2,1,2,1, digit sums, mod 10."""
    total = sum(_digit_sum(int(c) * w) for c, w in zip(stem[2:8], (2, 1, 2, 1, 2, 1), strict=True))
    return f"{stem}{total % 10}"


def kvnr(letter: str, stem: str) -> str:
    """Letter + 8 digits + check digit: letter as 01-26, weights 1,2,1,2…, digit sums, mod 10."""
    digits = f"{ord(letter) - 64:02d}{stem}"
    total = sum(_digit_sum(int(c) * (1 + i % 2)) for i, c in enumerate(digits))
    return f"{letter}{stem}{total % 10}"


def lanr(stem: str, specialty: str) -> str:
    """6 digits, check digit (weights 4,9 alternating, 10 - sum mod 10), Fachgruppe."""
    total = sum(int(c) * w for c, w in zip(stem, (4, 9, 4, 9, 4, 9), strict=True))
    return f"{stem}{(10 - total % 10) % 10}{specialty}"


# --- Master data ----------------------------------------------------------------

KOELBL = Staff(
    employee_no="401100011", initials="MK", name="Maria Kölbl", qualification="pflegefachkraft"
)
HOFBAUER = Staff(
    employee_no="401100022", initials="SH", name="Stefan Hofbauer", qualification="pflegefachkraft"
)
WIMMER = Staff(
    employee_no="401100033", initials="LW", name="Lena Wimmer", qualification="pflegefachkraft"
)
ZELLNER = Staff(
    employee_no="401100044", initials="AZ", name="Anja Zellner", qualification="pflegefachkraft"
)
BRUNNER = Staff(
    employee_no="401100055", initials="TB", name="Tobias Brunner", qualification="pflegehilfskraft"
)
REITER = Staff(
    employee_no="401100066", initials="JR", name="Julia Reiter", qualification="auszubildende"
)

PROVIDER = Provider(
    name="Pflegedienst Sonnenschein GmbH",
    ik=ik("46999401"),
    municipality="Deggendorf",
    staff=[KOELBL, HOFBAUER, WIMMER, ZELLNER, BRUNNER, REITER],
)
PROVIDER_ADDRESS = "Bahnhofstraße 12, 94469 Deggendorf"
PROVIDER_STAMP = (PROVIDER.name, PROVIDER_ADDRESS, f"IK {PROVIDER.ik}")
SIGN_OFF = "Mit freundlichen Grüßen\n\nMaria Kölbl\nPflegedienstleitung\n" + PROVIDER.name

AOK = Payer(name="AOK Bayern", ik=ik("10999101"), kind="krankenkasse")
AOK_PK = Payer(name="AOK Bayern Pflegekasse", ik=ik("18999101"), kind="pflegekasse")
TK = Payer(name="Techniker Krankenkasse", ik=ik("10999202"), kind="krankenkasse")
TK_PK = Payer(name="TK-Pflegeversicherung", ik=ik("18999202"), kind="pflegekasse")
BARMER = Payer(name="BARMER", ik=ik("10999303"), kind="krankenkasse")
BARMER_PK = Payer(name="BARMER Pflegekasse", ik=ik("18999303"), kind="pflegekasse")
PAYERS = {p.ik: p for p in (AOK, AOK_PK, TK, TK_PK, BARMER, BARMER_PK)}

WEISS = Physician(name="Dr. med. Katharina Weiß", lanr=lanr("999123", "01"), bsnr="719912300")
MOSER = Physician(name="Dr. med. Florian Moser", lanr=lanr("999456", "01"), bsnr="719945600")
RIEGER = Physician(name="Dr. med. Sabine Rieger", lanr=lanr("999789", "03"), bsnr="719978900")
PHYSICIANS = {p.lanr: p for p in (WEISS, MOSER, RIEGER)}
PRACTICE_ADDRESS = {
    WEISS.lanr: ("Praxis Dr. med. Katharina Weiß", "Stadtplatz 9", "94469 Deggendorf"),
    MOSER.lanr: ("Praxis Dr. med. Florian Moser", "Bahnhofplatz 2", "94447 Plattling"),
    RIEGER.lanr: (
        "Hausarztpraxis Dr. med. Sabine Rieger",
        "Graflinger Straße 21",
        "94469 Deggendorf",
    ),
}

# Positionsnummer / Leistungskomplex -> (German label, illustrative price in cents)
HKP_POSITIONS = {
    "032101": ("Medikamentengabe", 980),
    "032104": ("Injektion s.c. (Insulin)", 1140),
    "032105": ("Blutzuckermessung", 560),
    "032110": ("Kompressionsstrümpfe anziehen", 890),
    "032111": ("Kompressionsstrümpfe ausziehen", 620),
    "032120": ("Wundversorgung", 2150),
}
XI_COMPLEXES = {
    "LK 1": ("Ganzwaschung", 2590),
    "LK 2": ("Teilwaschung", 1630),
    "LK 4": ("An- und Auskleiden", 820),
    "LK 7": ("Hilfe bei der Nahrungsaufnahme", 1450),
    "LK 13": ("Hauswirtschaftliche Versorgung", 1980),
}
CODE_LABELS = {code: label for code, (label, _) in (HKP_POSITIONS | XI_COMPLEXES).items()}
PRICES = {code: price for code, (_, price) in (HKP_POSITIONS | XI_COMPLEXES).items()}
XI_CAP_CENTS = {2: 79600, 3: 149700, 4: 185900, 5: 229900}
"""§36 SGB XI Sachleistung per month, 2026 (docs/02 §1.1)."""


def _patient(
    pid: str, name: str, dob: dt.date, number: str, kk: Payer, pk: Payer, grade: int | None = None
) -> Patient:
    return Patient(
        id=pid,
        name=name,
        dob=dob,
        kvnr=number,
        insurance=[
            InsurancePeriod(
                krankenkasse_ik=kk.ik, pflegekasse_ik=pk.ik, valid_from=dt.date(2020, 1, 1)
            )
        ],
        pflegegrad=[PflegegradPeriod(grade=grade, valid_from=dt.date(2024, 1, 1))] if grade else [],
    )


# --- Building blocks ------------------------------------------------------------

Slot = tuple[str, dt.time]
"""(Positionsnummer or LK, visit time)"""


def at(hour: int, minute: int = 0) -> dt.time:
    return dt.time(hour, minute)


def daily(*slots: Slot) -> Callable[[dt.date], list[Slot]]:
    return lambda _day: list(slots)


def de(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def euro_de(cents: int) -> str:
    return f"{cents / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class World:
    """Everything the endpoints serve, indexed the way the routes need it.

    The defaults describe the fixture month; `api.live` fills one from the pipeline.
    """

    source: Literal["fixtures", "pipeline"] = "fixtures"
    month: str = MONTH
    as_of: dt.date = AS_OF
    provider: Provider = field(default_factory=lambda: PROVIDER)
    payers: dict[str, Payer] = field(default_factory=lambda: dict(PAYERS))
    physicians: dict[str, Physician] = field(default_factory=lambda: dict(PHYSICIANS))
    code_labels: dict[str, str] = field(default_factory=lambda: dict(CODE_LABELS))
    holidays: dict[dt.date, str] = field(default_factory=lambda: dict(HOLIDAYS))
    tariff_note: str = TARIFF_NOTE
    patients: dict[str, Patient] = field(default_factory=dict)
    prescriptions: list[Prescription] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)
    stays: list[Stay] = field(default_factory=list)
    visit_logs: list[VisitLog] = field(default_factory=list)
    claims: dict[str, Claim] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    documents: dict[str, DocumentInfo] = field(default_factory=dict)
    document_fields: dict[str, list[DocumentField]] = field(default_factory=dict)
    page_images: dict[str, list[pages.Page]] = field(default_factory=dict)
    page_files: dict[str, list[Path]] = field(default_factory=dict)
    """Pipeline documents: the stored page images on disk."""
    actions: list[Action] = field(default_factory=list)
    audits: dict[str, ClaimAudit] = field(default_factory=dict)
    """Pipeline claims: what the auditor agent made of each (fixtures have none)."""

    def page_image(self, document_id: str, index: int) -> tuple[bytes, str] | None:
        """(image bytes, media type) of one page, or None."""
        if document_id in self.page_files:
            files = self.page_files[document_id]
            if not 0 <= index < len(files):
                return None
            media = mimetypes.guess_type(files[index].name)[0] or "application/octet-stream"
            return files[index].read_bytes(), media
        if not 0 <= index < len(self.page_images.get(document_id, [])):
            return None
        return page_png(document_id, index), "image/png"

    def visit_log(
        self,
        log_id: str,
        patient: Patient,
        payer: Payer,
        domain: Domain,
        days: Iterable[dt.date],
        slots: Callable[[dt.date], list[Slot]],
        nurse: Callable[[dt.date, dt.time], Staff | None],
        *,
        patient_signed: bool = True,
        document_id: str | None = None,
    ) -> VisitLog:
        visits: list[Visit] = []
        for day in days:
            for code, time in slots(day):
                staff = nurse(day, time)
                visits.append(
                    Visit(
                        date=day,
                        start=time,
                        code=code,
                        funding="hkp" if domain == "sgbv" else "sachleistung_36",
                        employee_no=staff.employee_no if staff else None,
                        staff_initials=staff.initials if staff else None,
                        document_id=document_id,
                        entry_index=len(visits),
                    )
                )
        log = VisitLog(
            id=log_id,
            patient_id=patient.id,
            payer_ik=payer.ik,
            month=MONTH,
            domain=domain,
            visits=visits,
            patient_signed=patient_signed,
            document_id=document_id,
        )
        self.visit_logs.append(log)
        return log

    def claim(self, log: VisitLog) -> Claim:
        claim_id = f"c-{log.patient_id.removeprefix('p-')}-{log.domain}-{MONTH}"
        lines = [
            ClaimLine(
                id=f"{claim_id}.{v.entry_index:03d}",
                date=v.date,
                time=v.start,
                code=v.code,
                quantity=v.quantity,
                unit_price_cents=PRICES[v.code],
                funding=v.funding,
                visit_log_id=log.id,
                entry_index=v.entry_index,
            )
            for v in log.visits
        ]
        claim = Claim(
            id=claim_id,
            patient_id=log.patient_id,
            payer_ik=log.payer_ik,
            month=MONTH,
            domain=log.domain,
            lines=lines,
            tariff_version=TARIFF_VERSION,
        )
        self.claims[claim_id] = claim
        return claim

    def document(
        self,
        doc_id: str,
        doc_type: DocType,
        title: str,
        patient: Patient,
        received_on: dt.date,
        spec: pages.PageSpec,
        fields: list[tuple[str, str, str, str | None, FieldStatus]],
    ) -> dict[str, PixelBox]:
        """Draw the page and register it; `fields` are (box key, path, label, value, status)."""
        page = pages.draw(spec)
        self.page_images[doc_id] = [page]
        self.documents[doc_id] = DocumentInfo(
            id=doc_id,
            doc_type=doc_type,
            title=title,
            patient_id=patient.id,
            received_on=received_on,
            pages=[PageInfo(index=0, width=page.image.width, height=page.image.height)],
        )
        self.document_fields[doc_id] = [
            DocumentField(path=path, label=label, value=value, status=status, box=page.boxes[key])
            for key, path, label, value, status in fields
        ]
        return page.boxes

    def finding(
        self,
        rule_id: str,
        severity: Severity,
        claim: Claim,
        lines: list[ClaimLine],
        *,
        de: str,
        en: str,
        sources: list[str],
        evidence: list[Evidence],
        kasse_codes: list[KasseCode] | None = None,
        version: int = 1,
        amount_cents: int | None = None,
    ) -> Finding:
        f = Finding(
            id=f"f-{claim.patient_id.removeprefix('p-')}-{rule_id.lower()}",
            rule_id=rule_id,
            rule_version=version,
            severity=severity,
            patient_id=claim.patient_id,
            claim_id=claim.id,
            claim_line_ids=[line.id for line in lines],
            message_de=de,
            message_en=en,
            sources=sources,
            evidence=evidence,
            kasse_codes=kasse_codes or [],
            amount_at_risk_cents=(
                sum(line.amount_cents for line in lines) if amount_cents is None else amount_cents
            ),
        )
        self.findings.append(f)
        return f


def evidence(doc_id: str, boxes: dict[str, PixelBox], key: str, path: str, note: str) -> Evidence:
    return Evidence(document_id=doc_id, page=0, field_path=path, box=boxes[key], note=note)


def rows(boxes: dict[str, PixelBox], first: int, last: int) -> PixelBox:
    """One box over the visit-log rows of days first..last."""
    return pages.union(*(boxes[f"day.{d:02d}"] for d in range(first, last + 1)))


def rota(weekday: Staff, weekend: Staff) -> Callable[[dt.date, dt.time], Staff]:
    return lambda day, _time: weekend if day.weekday() >= 5 else weekday


def approval_for(rx: Prescription, payer: Payer, ref: str, letter_date: dt.date) -> Approval:
    return Approval(
        id=f"ap-{rx.id.removeprefix('rx-')}",
        patient_id=rx.patient_id,
        payer_ik=payer.ik,
        provider_ik=PROVIDER.ik,
        approval_ref=ref,
        letter_date=letter_date,
        decision="approved",
        period_from=rx.period_from,
        period_to=rx.period_to,
        approved=[
            ApprovedService(
                position_no=s.position_no or "",
                frequency=s.frequency,
                valid_from=rx.period_from,
                valid_to=rx.period_to,
            )
            for s in rx.services
        ],
        prescription_id=rx.id,
    )


def hkp_rx(
    rx_id: str,
    patient: Patient,
    doctor: Physician,
    issued: dt.date,
    period: tuple[dt.date, dt.date],
    services: list[tuple[str, str, str, int]],
    **kw,
) -> Prescription:
    """services: (category, Positionsnummer, details, times per day)."""
    return Prescription(
        id=rx_id,
        patient_id=patient.id,
        physician_lanr=doctor.lanr,
        kind=kw.pop("kind", "folge"),
        issue_date=issued,
        period_from=period[0],
        period_to=period[1],
        services=[
            PrescribedService(
                category=cat,
                position_no=pos,
                details=details,
                frequency=Frequency(count=n, per="day"),
            )
            for cat, pos, details, n in services
        ],
        doctor_signed=kw.pop("doctor_signed", True),
        stamp_present=kw.pop("stamp_present", True),
        **kw,
    )


def muster12_spec(
    seed: int,
    rx: Prescription,
    patient: Patient,
    payer: Payer,
    address: str,
    measures: list[tuple[str, str, str]],
) -> pages.Muster12Page:
    doctor = PHYSICIANS[rx.physician_lanr]
    practice = PRACTICE_ADDRESS[doctor.lanr]
    return pages.Muster12Page(
        seed=seed,
        payer_name=payer.name,
        payer_ik=payer.ik,
        patient_name=patient.name,
        patient_address=address,
        dob=patient.dob,
        kvnr=patient.kvnr,
        bsnr=doctor.bsnr,
        lanr=doctor.lanr,
        issue_date=rx.issue_date,
        kind=rx.kind,
        period_from=rx.period_from,
        period_to=rx.period_to,
        icd=", ".join(rx.icd_codes),
        measures=measures,
        practice_stamp=[practice[0], f"{practice[1]}, {practice[2]}", f"BSNR {doctor.bsnr}"]
        if rx.stamp_present
        else None,
        signed=rx.doctor_signed,
    )


def visit_log_spec(
    seed: int,
    log: VisitLog,
    patient: Patient,
    payer: Payer,
    reference: tuple[str, str],
    nurse: Staff,
    columns: list[tuple[str, str, dt.time | None]],
    signed_on: dt.date | None = None,
) -> pages.VisitLogPage:
    """columns: (code, label, only visits at this time or None for any time)."""
    cells: dict[tuple[int, int], str] = {}
    initials: dict[int, str] = {}
    for v in log.visits:
        for i, (code, _, slot) in enumerate(columns):
            if v.code == code and v.start and slot in (None, v.start):
                cells[(v.date.day, i)] = (
                    "x" if log.domain == "sgbxi" else f"{v.start.hour}:{v.start.minute:02d}"
                )
        if v.staff_initials:
            initials.setdefault(v.date.day, v.staff_initials)
    return pages.VisitLogPage(
        seed=seed,
        domain=log.domain,
        provider_name=PROVIDER.name,
        provider_address=PROVIDER_ADDRESS,
        provider_ik=PROVIDER.ik,
        patient_name=patient.name,
        kvnr=patient.kvnr,
        payer_name=payer.name,
        month=MONTH,
        reference=reference,
        nurse=nurse.name,
        columns=[(code, label) for code, label, _ in columns],
        cells=cells,
        initials=initials,
        holidays=frozenset(HOLIDAYS),
        patient_signed=log.patient_signed,
        signed_on=signed_on,
        provider_stamp=PROVIDER_STAMP,
    )


def visit_log_fields(
    log: VisitLog,
    patient: Patient,
    payer: Payer,
    reference: tuple[str, str],
) -> list[tuple[str, str, str, str | None, FieldStatus]]:
    signed: FieldStatus = "present" if log.patient_signed else "empty"
    ref_path = "approval_ref" if log.domain == "sgbv" else "pflegegrad"
    return [
        ("patient_name", "patient_name", "Versicherte/r", patient.name, "present"),
        ("kvnr", "kvnr", "Versicherten-Nr.", patient.kvnr, "present"),
        ("payer_name", "payer_name", "Kasse", payer.name, "present"),
        ("month", "month", "Monat", log.month, "present"),
        ("reference", ref_path, reference[0], reference[1], "present"),
        (
            "patient_signature",
            "patient_signature",
            "Unterschrift Versicherte/r",
            "present" if log.patient_signed else None,
            signed,
        ),
        (
            "missing_signature_reason",
            "missing_signature_reason",
            "Grund ohne Unterschrift",
            None,
            "empty",
        ),
        (
            "provider_signature",
            "provider_signature",
            "Unterschrift / Stempel Pflegedienst",
            "present",
            "present",
        ),
    ]


def letter(
    channel: Literal["fax", "post", "handover", "internal"],
    recipient: Iterable[str],
    subject: str,
    body: str,
) -> Letter:
    return Letter(channel=channel, recipient=list(recipient), subject=subject, body=body.strip())


# --- Hero patients (docs/05 §4.4) -------------------------------------------------


def _albers(w: World) -> None:
    """Verordnung ended 14 Oct, visits continued to 31 Oct, no Folgeverordnung (D01, D08)."""
    p = _patient(
        "p-albers",
        "Albers, Margarete",
        dt.date(1938, 3, 14),
        kvnr("A", "99183746"),
        AOK,
        AOK_PK,
        grade=2,
    )
    rx = hkp_rx(
        "rx-albers-2609",
        p,
        WEISS,
        dt.date(2026, 9, 11),
        (dt.date(2026, 9, 15), dt.date(2026, 10, 14)),
        [
            ("medikamentengabe", "032101", "Ramipril 5 mg, Metformin 1000 mg", 1),
            ("kompression", "032110", "Kompressionsstrümpfe anziehen, KKL II", 1),
        ],
        icd_codes=["I10.90", "E11.9"],
        submitted_to_payer_at=dt.date(2026, 9, 14),
        document_id="doc-albers-m12",
    )
    log = w.visit_log(
        "vl-albers-2610",
        p,
        AOK,
        "sgbv",
        OCTOBER,
        daily(("032101", at(7, 40)), ("032110", at(7, 40))),
        rota(WIMMER, ZELLNER),
        document_id="doc-albers-ln",
    )
    claim = w.claim(log)
    w.patients[p.id] = p
    w.prescriptions.append(rx)
    w.approvals.append(approval_for(rx, AOK, "AOK-HKP-26-40112", dt.date(2026, 9, 18)))

    m12 = w.document(
        "doc-albers-m12",
        "muster12",
        "Muster 12, Folgeverordnung of 11 Sep",
        p,
        dt.date(2026, 9, 12),
        muster12_spec(
            11,
            rx,
            p,
            AOK,
            "Lindenweg 7, 94469 Deggendorf",
            [
                ("Medikamentengabe", "Ramipril 5 mg, Metformin", "1x tgl."),
                ("Kompressionsstrümpfe", "anziehen, KKL II", "1x tgl."),
            ],
        ),
        [
            ("issue_date", "issue_date", "Datum", "2026-09-11", "present"),
            ("prescription_kind", "prescription_kind", "Folgeverordnung", "folge", "present"),
            ("period_from", "period_from", "Verordnungszeitraum vom", "2026-09-15", "present"),
            ("period_to", "period_to", "Verordnungszeitraum bis", "2026-10-14", "present"),
            ("measures.0", "measures[0]", "Medikamentengabe", "1x tgl.", "present"),
            ("measures.1", "measures[1]", "Kompressionsstrümpfe anziehen", "1x tgl.", "present"),
            ("practice_stamp", "practice_stamp", "Vertragsarztstempel", "present", "present"),
            (
                "doctor_signature",
                "doctor_signature",
                "Unterschrift des Arztes",
                "present",
                "present",
            ),
        ],
    )
    ref = ("Genehmigungskennzeichen", "AOK-HKP-26-40112")
    ln = w.document(
        "doc-albers-ln",
        "visit_log_sgbv",
        "Leistungsnachweis, October",
        p,
        dt.date(2026, 11, 1),
        visit_log_spec(
            12,
            log,
            p,
            AOK,
            ref,
            WIMMER,
            [("032101", "Medikamentengabe", None), ("032110", "Kompressionsstrümpfe an", None)],
            signed_on=dt.date(2026, 10, 31),
        ),
        visit_log_fields(log, p, AOK, ref),
    )
    ln["rows.15-31"] = rows(ln, 15, 31)

    uncovered = [line for line in claim.lines if line.date > rx.period_to]
    w.finding(
        "HKP-RX-REQUIRED",
        "block",
        claim,
        uncovered,
        de=f"Keine gültige Verordnung für 15.10.–31.10.2026: Die Folgeverordnung endete am "
        f"14.10.2026. {len(uncovered)} Positionen sind nicht gedeckt.",
        en=f"No valid Verordnung for 15–31 Oct 2026: the last one ended on 14 Oct. "
        f"{len(uncovered)} lines are not covered.",
        sources=["HKP-RL §3(4)"],
        kasse_codes=["42002", "42003"],
        evidence=[
            evidence(
                "doc-albers-m12",
                m12,
                "period_to",
                "period_to",
                "Verordnungszeitraum bis 14.10.2026",
            ),
            evidence(
                "doc-albers-ln",
                ln,
                "rows.15-31",
                "entries",
                "Einsätze vom 15.10. bis 31.10. weiter eingetragen",
            ),
        ],
    )
    w.finding(
        "HKP-FOLGE-WINDOW",
        "warn",
        claim,
        uncovered,
        de="Keine Folgeverordnung angefordert. Sie hätte zwischen dem 12.10. und dem 14.10.2026 "
        "ausgestellt werden müssen (letzte 3 Arbeitstage vor Ablauf).",
        en="No Folgeverordnung was requested. It was due between 12 and 14 Oct 2026, "
        "the last 3 working days before the old one expired.",
        sources=["HKP-RL §5(2)"],
        kasse_codes=["42003"],
        evidence=[
            evidence("doc-albers-m12", m12, "period_to", "period_to", "Ablauf 14.10.2026, Mi")
        ],
    )
    w.actions.append(
        Action(
            id="act-albers-folge",
            kind="folgeverordnung_request",
            title="Request a Folgeverordnung from Dr. Weiß",
            why="Every visit since 15 Oct is unbillable until a new Verordnung is issued.",
            patient_id=p.id,
            patient_name=p.name,
            claim_id=claim.id,
            finding_ids=["f-albers-hkp-folge-window", "f-albers-hkp-rx-required"],
            due_date=rx.period_to,
            amount_cents=sum(line.amount_cents for line in uncovered),
            status="draft",
            letter=letter(
                "fax",
                PRACTICE_ADDRESS[WEISS.lanr],
                f"Bitte um Folgeverordnung häusliche Krankenpflege – Frau Margarete Albers, "
                f"geb. {de(p.dob)}",
                f"""
Sehr geehrte Frau Dr. Weiß,

die Verordnung häuslicher Krankenpflege für Ihre Patientin Frau Margarete Albers \
(Versicherten-Nr. {p.kvnr}, AOK Bayern) ist am 14.10.2026 abgelaufen. Wir versorgen \
Frau Albers unverändert weiter:

– Medikamentengabe 1x täglich (Ramipril 5 mg, Metformin 1000 mg)
– Kompressionsstrümpfe anziehen 1x täglich (KKL II)

Bitte stellen Sie eine Folgeverordnung (Muster 12) aus und senden Sie sie uns per Fax. \
Für die Zeit ab dem 15.10.2026 liegt uns bisher keine Verordnung vor.

{SIGN_OFF}""",
            ),
        )
    )


def _brandl(w: World) -> None:
    """Hospital stay 12–16 Oct (Entlassbrief in the pile), visits logged on those days (D06)."""
    p = _patient(
        "p-brandl", "Brandl, Josef", dt.date(1941, 5, 3), kvnr("B", "99234561"), TK, TK_PK, grade=3
    )
    rx = hkp_rx(
        "rx-brandl-2610",
        p,
        RIEGER,
        dt.date(2026, 9, 25),
        (dt.date(2026, 10, 1), dt.date(2026, 12, 31)),
        [
            ("injektion", "032104", "Insulin glargin, nach Schema", 2),
            ("blutzucker", "032105", "vor Insulingabe", 2),
        ],
        icd_codes=["E11.9"],
        submitted_to_payer_at=dt.date(2026, 9, 28),
    )
    stay = Stay(
        id="st-brandl-2610",
        patient_id=p.id,
        kind="hospital",
        admitted_at=dt.datetime(2026, 10, 12, 10, 30),
        discharged_at=dt.datetime(2026, 10, 16, 14, 0),
        document_id="doc-brandl-eb",
    )
    morning, evening = at(7, 30), at(18, 0)
    log = w.visit_log(
        "vl-brandl-2610",
        p,
        TK,
        "sgbv",
        OCTOBER,
        daily(("032105", morning), ("032104", morning), ("032105", evening), ("032104", evening)),
        lambda _day, time: HOFBAUER if time == morning else ZELLNER,
        document_id="doc-brandl-ln",
    )
    claim = w.claim(log)
    w.patients[p.id] = p
    w.prescriptions.append(rx)
    w.approvals.append(approval_for(rx, TK, "TK-HKP-2026-0815", dt.date(2026, 9, 30)))
    w.stays.append(stay)

    eb = w.document(
        "doc-brandl-eb",
        "hospital_letter",
        "Entlassbrief, Kreisklinik Donautal",
        p,
        dt.date(2026, 10, 19),
        pages.HospitalLetterPage(
            seed=21,
            hospital="Kreisklinik Donautal",
            department="Klinik für Innere Medizin",
            address="Klinikumstraße 1, 94469 Deggendorf",
            location_id="779990100",
            recipient=(PROVIDER.name, "Bahnhofstraße 12", "94469 Deggendorf"),
            letter_date=dt.date(2026, 10, 16),
            patient_name=p.name,
            dob=p.dob,
            kvnr=p.kvnr,
            admitted_at=stay.admitted_at,
            discharged_at=stay.discharged_at or stay.admitted_at,
            diagnoses=[
                "J18.9  Pneumonie, nicht näher bezeichnet",
                "E11.9  Diabetes mellitus Typ 2 ohne Komplikationen",
            ],
            summary=[
                "Aufnahme über die Notaufnahme mit Fieber und Belastungsdyspnoe.",
                "Unter Antibiose rasche Besserung, Blutzucker stabil eingestellt.",
                "Entlassung in gebessertem Allgemeinzustand nach Hause.",
            ],
            recommendation="Häusliche Krankenpflege weiter wie bisher "
            "(Insulin s.c. 2x tgl., BZ-Kontrolle).",
            physician="Dr. med. Lena Hartl, Oberärztin",
        ),
        [
            ("patient_name", "patient_name", "Patient", p.name, "present"),
            ("admission", "admission_date", "Stationäre Aufnahme", "2026-10-12 10:30", "present"),
            ("discharge", "discharge_date", "Entlassung", "2026-10-16 14:00", "present"),
            ("discharge_diagnoses", "discharge_diagnoses", "Diagnosen", "J18.9, E11.9", "present"),
            ("hkp_recommended", "hkp_recommended", "Empfehlung HKP", "ja", "present"),
            ("physician_signature", "physician_signature", "Unterschrift", "present", "present"),
        ],
    )
    ref = ("Genehmigungskennzeichen", "TK-HKP-2026-0815")
    ln = w.document(
        "doc-brandl-ln",
        "visit_log_sgbv",
        "Leistungsnachweis, October",
        p,
        dt.date(2026, 11, 1),
        visit_log_spec(
            22,
            log,
            p,
            TK,
            ref,
            HOFBAUER,
            [
                ("032105", "BZ morgens", morning),
                ("032104", "Insulin morgens", morning),
                ("032105", "BZ abends", evening),
                ("032104", "Insulin abends", evening),
            ],
            signed_on=dt.date(2026, 10, 31),
        ),
        visit_log_fields(log, p, TK, ref),
    )
    ln["rows.12-16"] = rows(ln, 12, 16)

    discharged = stay.discharged_at or stay.admitted_at
    inside = [
        line
        for line in claim.lines
        if line.time and stay.admitted_at <= dt.datetime.combine(line.date, line.time) <= discharged
    ]
    visits = len({(line.date, line.time) for line in inside})
    w.finding(
        "STAY-HKP",
        "block",
        claim,
        inside,
        de=f"{len(inside)} Positionen ({visits} Einsätze) fallen in den Krankenhausaufenthalt "
        "vom 12.10.2026, 10:30 Uhr bis 16.10.2026, 14:00 Uhr. Während stationärer Behandlung "
        "ist häusliche Krankenpflege nicht abrechenbar.",
        en=f"{len(inside)} lines ({visits} visits) fall inside the hospital stay from 12 Oct "
        "10:30 to 16 Oct 14:00. Home care can't be billed during inpatient treatment. The "
        "07:30 visit on 12 Oct and the 18:00 visit on 16 Oct are outside the stay and stay "
        "billable.",
        sources=["HKP-RL §1(6)"],
        kasse_codes=["41003"],
        evidence=[
            evidence(
                "doc-brandl-eb", eb, "admission", "admission_date", "Aufnahme 12.10.2026, 10:30 Uhr"
            ),
            evidence(
                "doc-brandl-eb",
                eb,
                "discharge",
                "discharge_date",
                "Entlassung 16.10.2026, 14:00 Uhr",
            ),
            evidence(
                "doc-brandl-ln", ln, "rows.12-16", "entries", "Einsätze 12.–16.10. eingetragen"
            ),
        ],
    )
    w.actions.append(
        Action(
            id="act-brandl-correction",
            kind="claim_correction",
            title="Remove the hospital-stay visits from Herr Brandl's bill",
            why="The TK rejects lines that overlap an inpatient stay (code 41003).",
            patient_id=p.id,
            patient_name=p.name,
            claim_id=claim.id,
            finding_ids=["f-brandl-stay-hkp"],
            due_date=BILLING_RUN,
            amount_cents=sum(line.amount_cents for line in inside),
            status="open",
            letter=letter(
                "internal",
                ["Abrechnung", PROVIDER.name],
                f"Rechnung Oktober 2026, Herr Josef Brandl: {len(inside)} Positionen streichen",
                """
Herr Brandl war vom 12.10.2026, 10:30 Uhr bis 16.10.2026, 14:00 Uhr stationär in der \
Kreisklinik Donautal (Entlassbrief vom 16.10.2026). Diese Einsätze bitte nicht abrechnen:

– 12.10.2026, 18:00 Uhr (Insulin s.c., Blutzuckermessung)
– 13.10. bis 15.10.2026, alle Einsätze
– 16.10.2026, 07:30 Uhr (Insulin s.c., Blutzuckermessung)

Die Einträge im Leistungsnachweis für diese Tage bitte mit Stefan Hofbauer und Anja \
Zellner klären.""",
            ),
        )
    )


def _christl(w: World) -> None:
    """Leistungsnachweis without the patient's signature (D04)."""
    p = _patient(
        "p-christl",
        "Christl, Anna",
        dt.date(1935, 11, 22),
        kvnr("C", "99345672"),
        BARMER,
        BARMER_PK,
        grade=2,
    )
    rx = hkp_rx(
        "rx-christl-2610",
        p,
        WEISS,
        dt.date(2026, 9, 24),
        (dt.date(2026, 10, 1), dt.date(2026, 12, 31)),
        [
            ("kompression", "032110", "Kompressionsstrümpfe anziehen, KKL II", 1),
            ("kompression", "032111", "Kompressionsstrümpfe ausziehen", 1),
        ],
        icd_codes=["I87.2"],
        submitted_to_payer_at=dt.date(2026, 9, 25),
    )
    log = w.visit_log(
        "vl-christl-2610",
        p,
        BARMER,
        "sgbv",
        OCTOBER,
        daily(("032110", at(7, 50)), ("032111", at(19, 10))),
        rota(KOELBL, HOFBAUER),
        patient_signed=False,
        document_id="doc-christl-ln",
    )
    claim = w.claim(log)
    w.patients[p.id] = p
    w.prescriptions.append(rx)
    w.approvals.append(approval_for(rx, BARMER, "BAR-26-HKP-7731", dt.date(2026, 9, 29)))

    ref = ("Genehmigungskennzeichen", "BAR-26-HKP-7731")
    ln = w.document(
        "doc-christl-ln",
        "visit_log_sgbv",
        "Leistungsnachweis, October",
        p,
        dt.date(2026, 11, 1),
        visit_log_spec(
            31,
            log,
            p,
            BARMER,
            ref,
            KOELBL,
            [
                ("032110", "Kompressionsstrümpfe an", None),
                ("032111", "Kompressionsstrümpfe aus", None),
            ],
        ),
        visit_log_fields(log, p, BARMER, ref),
    )
    w.finding(
        "HKP-LN-SIGNATURE",
        "warn",
        claim,
        claim.lines,
        de="Leistungsnachweis Oktober 2026 ohne Unterschrift der Versicherten und ohne "
        "Grund-Kennzeichen (1–4). Unterschrift vor der Abrechnung einholen.",
        en="The October visit log has no patient signature and no reason code (1–4). "
        "Get it signed before the bill goes out.",
        sources=["TA HKP Anlage 9.8", "Rahmenvertrag §132a SGB V, §30"],
        evidence=[
            evidence(
                "doc-christl-ln",
                ln,
                "patient_signature",
                "patient_signature",
                "Unterschriftsfeld leer (SAM 3.1, Tintenanteil 0,2 %)",
            ),
            evidence(
                "doc-christl-ln",
                ln,
                "missing_signature_reason",
                "missing_signature_reason",
                "Kein Grund angekreuzt",
            ),
        ],
    )
    w.actions.append(
        Action(
            id="act-christl-signature",
            kind="signature_request",
            title="Get Frau Christl's signature on the October Leistungsnachweis",
            why="Without the signature the BARMER can reject the whole month.",
            patient_id=p.id,
            patient_name=p.name,
            claim_id=claim.id,
            finding_ids=["f-christl-hkp-ln-signature"],
            due_date=BILLING_RUN,
            amount_cents=claim.total_cents,
            status="draft",
            letter=letter(
                "handover",
                ["Frau Anna Christl", "Am Mühlbach 3", "94469 Deggendorf"],
                "Ihre Unterschrift auf dem Leistungsnachweis Oktober 2026",
                f"""
Sehr geehrte Frau Christl,

für die Abrechnung mit Ihrer Krankenkasse benötigen wir Ihre Unterschrift auf dem \
Leistungsnachweis für Oktober 2026. Damit bestätigen Sie, dass wir die eingetragenen \
Leistungen bei Ihnen erbracht haben.

Unsere Pflegekraft bringt den Leistungsnachweis bei ihrem nächsten Besuch mit. Wenn Sie \
nicht selbst unterschreiben können, darf auch eine Angehörige oder ein Angehöriger \
unterschreiben.

{SIGN_OFF}""",
            ),
        )
    )


def _dengler(w: World) -> None:
    """Muster 12 without practice stamp (D09); reached the Kasse after the 4th working day (D07).

    Issued Thu 1 Oct; working days Fri 2, Mon 5, Tue 6, Wed 7 (Sat 3 Oct is also a holiday
    and must not count twice) -> deadline Wed 7 Oct; the fax report says Thu 8 Oct.
    """
    p = _patient(
        "p-dengler", "Dengler, Franz", dt.date(1950, 7, 9), kvnr("D", "99456783"), AOK, AOK_PK
    )
    rx = hkp_rx(
        "rx-dengler-2610",
        p,
        MOSER,
        dt.date(2026, 10, 1),
        (dt.date(2026, 10, 1), dt.date(2026, 10, 14)),
        [("wundversorgung", "032120", "Ulcus cruris li. Unterschenkel, 3 x 2 cm, Grad 2", 1)],
        kind="erst",
        icd_codes=["L97"],
        stamp_present=False,
        submitted_to_payer_at=dt.date(2026, 10, 8),
        document_id="doc-dengler-m12",
    )
    log = w.visit_log(
        "vl-dengler-2610",
        p,
        AOK,
        "sgbv",
        OCTOBER[:14],
        daily(("032120", at(9, 15))),
        rota(KOELBL, WIMMER),
    )
    claim = w.claim(log)
    w.patients[p.id] = p
    w.prescriptions.append(rx)

    m12 = w.document(
        "doc-dengler-m12",
        "muster12",
        "Muster 12, Erstverordnung of 1 Oct",
        p,
        dt.date(2026, 10, 2),
        muster12_spec(
            41,
            rx,
            p,
            AOK,
            "Hengersberger Str. 40, 94469 Deggendorf",
            [("Wundversorgung", "Ulcus cruris li., 3x2 cm, Gr. 2", "1x tgl.")],
        ),
        [
            ("issue_date", "issue_date", "Datum", "2026-10-01", "present"),
            ("prescription_kind", "prescription_kind", "Erstverordnung", "erst", "present"),
            ("period_from", "period_from", "Verordnungszeitraum vom", "2026-10-01", "present"),
            ("period_to", "period_to", "Verordnungszeitraum bis", "2026-10-14", "present"),
            ("measures.0", "measures[0]", "Wundversorgung", "1x tgl.", "present"),
            ("practice_stamp", "practice_stamp", "Vertragsarztstempel", None, "empty"),
            (
                "doctor_signature",
                "doctor_signature",
                "Unterschrift des Arztes",
                "present",
                "present",
            ),
        ],
    )
    fax = w.document(
        "doc-dengler-fax",
        "other",
        "Fax report to AOK Bayern, 8 Oct",
        p,
        dt.date(2026, 10, 8),
        pages.FaxReportPage(
            seed=42,
            sent_at=dt.datetime(2026, 10, 8, 9, 14),
            sender=PROVIDER.name,
            sender_fax="0991 0000-10",
            recipient="AOK Bayern, HKP-Genehmigung",
            pages=2,
            duration="00:41",
            subject="Verordnung HKP, Dengler, Franz",
        ),
        [
            ("sent_at", "sent_at", "Datum/Zeit", "2026-10-08 09:14", "present"),
            ("recipient", "recipient", "Empfänger", "AOK Bayern, HKP-Genehmigung", "present"),
            ("result", "result", "Ergebnis", "OK", "present"),
        ],
    )
    w.finding(
        "HKP-RX-SIGNED",
        "block",
        claim,
        claim.lines,
        de="Verordnung vom 01.10.2026 ohne Vertragsarztstempel. Ohne Stempel ist sie "
        "unvollständig, die Kasse lehnt sie ab.",
        en="The Verordnung of 1 Oct 2026 has no practice stamp. Without it the prescription "
        "is incomplete and the payer will reject it.",
        sources=["Muster 12 (KBV), Vertragsarztstempel", "HKP-RL §3(5)"],
        evidence=[
            evidence(
                "doc-dengler-m12",
                m12,
                "practice_stamp",
                "practice_stamp",
                "Stempelfeld leer (SAM 3.1: kein Stempel gefunden)",
            )
        ],
    )
    w.finding(
        "HKP-SUBMIT-4WD",
        "warn",
        claim,
        claim.lines,
        version=2,
        de="Verordnung vom 01.10.2026 ist erst am 08.10.2026 bei der Kasse eingegangen "
        "(Frist: 07.10.2026, 4. Arbeitstag; der 03.10. fiel auf einen Samstag). Bis zur "
        "Genehmigung keine vorläufige Kostenübernahme.",
        en="The Verordnung issued Thu 1 Oct reached the payer on Thu 8 Oct. The deadline was "
        "Wed 7 Oct, the 4th working day (3 Oct was a Saturday and a holiday). No provisional "
        "payment until the payer approves.",
        sources=["HKP-RL §6(5)"],
        evidence=[
            evidence(
                "doc-dengler-m12", m12, "issue_date", "issue_date", "Ausgestellt Do 01.10.2026"
            ),
            evidence(
                "doc-dengler-fax",
                fax,
                "sent_at",
                "sent_at",
                "Gesendet Do 08.10.2026, 09:14 – Frist war Mi 07.10.2026",
            ),
        ],
    )
    w.actions.append(
        Action(
            id="act-dengler-stamp",
            kind="stamp_request",
            title="Ask Dr. Moser to stamp and countersign the Verordnung",
            why="The AOK rejects a Verordnung without a practice stamp.",
            patient_id=p.id,
            patient_name=p.name,
            claim_id=claim.id,
            finding_ids=["f-dengler-hkp-rx-signed"],
            due_date=BILLING_RUN,
            amount_cents=claim.total_cents,
            status="draft",
            letter=letter(
                "fax",
                PRACTICE_ADDRESS[MOSER.lanr],
                "Verordnung vom 01.10.2026 – fehlender Vertragsarztstempel – Herr Franz Dengler",
                f"""
Sehr geehrter Herr Dr. Moser,

auf der Verordnung häuslicher Krankenpflege vom 01.10.2026 für Herrn Franz Dengler \
(Versicherten-Nr. {p.kvnr}, AOK Bayern) fehlt der Vertragsarztstempel. Ohne Stempel \
erkennt die Krankenkasse die Verordnung nicht an.

Wir senden Ihnen die Verordnung in Kopie mit. Bitte ergänzen Sie den Stempel, zeichnen \
Sie die Ergänzung mit Datum und Unterschrift ab und faxen Sie sie an uns zurück.

{SIGN_OFF}""",
            ),
        )
    )
    w.actions.append(
        Action(
            id="act-dengler-kasse",
            kind="kasse_letter",
            title="Ask the AOK to decide on the late Verordnung",
            why="Sent one working day late: no provisional payment until the AOK approves.",
            patient_id=p.id,
            patient_name=p.name,
            claim_id=claim.id,
            finding_ids=["f-dengler-hkp-submit-4wd"],
            due_date=dt.date(2026, 11, 4),
            amount_cents=claim.total_cents,
            status="draft",
            letter=letter(
                "fax",
                ["AOK Bayern", "HKP-Genehmigung", "Direktion Deggendorf"],
                "Verordnung HKP vom 01.10.2026 – Herr Franz Dengler – Bitte um Entscheidung",
                f"""
Sehr geehrte Damen und Herren,

die Verordnung häuslicher Krankenpflege vom 01.10.2026 für Herrn Franz Dengler \
(Versicherten-Nr. {p.kvnr}) haben wir Ihnen am 08.10.2026 per Fax übermittelt. Die \
verordnete Wundversorgung haben wir vom 01.10. bis 14.10.2026 täglich erbracht.

Wir bitten um Ihre Entscheidung über die Kostenübernahme für diesen Zeitraum. Die vom \
Arzt ergänzte Verordnung reichen wir nach.

{SIGN_OFF}""",
            ),
        )
    )


def _eder(w: World) -> None:
    """Clean HKP and SGB XI bills (D20)."""
    p = _patient(
        "p-eder",
        "Eder, Theresia",
        dt.date(1939, 1, 30),
        kvnr("E", "99567894"),
        AOK,
        AOK_PK,
        grade=3,
    )
    rx = hkp_rx(
        "rx-eder-2610",
        p,
        RIEGER,
        dt.date(2026, 9, 28),
        (dt.date(2026, 10, 1), dt.date(2026, 12, 31)),
        [("medikamentengabe", "032101", "Metoprolol 47,5 mg, Torasemid 10 mg", 2)],
        icd_codes=["I50.13"],
        submitted_to_payer_at=dt.date(2026, 9, 29),
    )
    hkp = w.visit_log(
        "vl-eder-2610",
        p,
        AOK,
        "sgbv",
        OCTOBER,
        daily(("032101", at(8)), ("032101", at(19))),
        lambda _day, time: WIMMER if time.hour < 12 else ZELLNER,
    )
    xi = w.visit_log(
        "vl-eder-xi-2610",
        p,
        AOK_PK,
        "sgbxi",
        OCTOBER,
        lambda day: [("LK 1", at(8))] + ([("LK 13", at(10))] if day.weekday() in (1, 4) else []),
        lambda _day, time: BRUNNER if time.hour == 8 else REITER,
    )
    w.claim(hkp)
    w.claim(xi)
    w.patients[p.id] = p
    w.prescriptions.append(rx)
    w.approvals.append(approval_for(rx, AOK, "AOK-HKP-26-40391", dt.date(2026, 10, 2)))


# --- Background patients ---------------------------------------------------------


def _fink(w: World) -> None:
    """SGB XI over the §36 cap for Pflegegrad 2 (D12)."""
    p = _patient(
        "p-fink",
        "Fink, Helmut",
        dt.date(1944, 9, 17),
        kvnr("F", "99678905"),
        BARMER,
        BARMER_PK,
        grade=2,
    )
    log = w.visit_log(
        "vl-fink-xi-2610",
        p,
        BARMER_PK,
        "sgbxi",
        OCTOBER,
        lambda day: (
            [("LK 2", at(7, 30)), ("LK 4", at(7, 30))]
            + ([("LK 13", at(10))] if day.weekday() == 3 else [])
        ),
        lambda _day, _time: BRUNNER,
        document_id="doc-fink-ln",
    )
    claim = w.claim(log)
    w.patients[p.id] = p
    cap = XI_CAP_CENTS[2]
    excess = claim.total_cents - cap

    ref = ("Pflegegrad", "2")
    ln = w.document(
        "doc-fink-ln",
        "visit_log_sgbxi",
        "Leistungsnachweis SGB XI, October",
        p,
        dt.date(2026, 11, 1),
        visit_log_spec(
            61,
            log,
            p,
            BARMER_PK,
            ref,
            KOELBL,
            [
                ("LK 2", "LK 2 Teilwaschung", None),
                ("LK 4", "LK 4 An-/Auskleiden", None),
                ("LK 13", "LK 13 Hauswirtschaft", None),
            ],
            signed_on=dt.date(2026, 10, 31),
        ),
        visit_log_fields(log, p, BARMER_PK, ref),
    )
    w.finding(
        "XI-36-BUDGET",
        "warn",
        claim,
        [],
        amount_cents=excess,
        de=f"Pflegesachleistungen Oktober: {euro_de(claim.total_cents)} bei Pflegegrad 2 "
        f"(Höchstbetrag {euro_de(cap)}). {euro_de(excess)} als Eigenanteil privat in Rechnung "
        "stellen; vorher schriftliche Kosteninformation nötig.",
        en=f"October care services total €{claim.total_cents / 100:,.2f} under Pflegegrad 2 "
        f"(cap €{cap / 100:,.2f}). Invoice €{excess / 100:,.2f} privately as Eigenanteil; "
        "written cost information has to go out first.",
        sources=["§36 SGB XI", "§120(3)–(4) SGB XI"],
        evidence=[
            evidence(
                "doc-fink-ln",
                ln,
                "reference",
                "pflegegrad",
                f"Pflegegrad 2: Höchstbetrag {euro_de(cap)} im Monat",
            )
        ],
    )
    w.actions.append(
        Action(
            id="act-fink-eigenanteil",
            kind="eigenanteil_notice",
            title="Send Herr Fink the cost information for his Eigenanteil",
            why="The amount above the cap can only be invoiced after written cost information.",
            patient_id=p.id,
            patient_name=p.name,
            claim_id=claim.id,
            finding_ids=["f-fink-xi-36-budget"],
            due_date=dt.date(2026, 11, 10),
            amount_cents=excess,
            status="draft",
            letter=letter(
                "post",
                ["Herrn Helmut Fink", "Schachinger Straße 15", "94469 Deggendorf"],
                "Kosteninformation: Eigenanteil Pflegesachleistungen Oktober 2026",
                f"""
Sehr geehrter Herr Fink,

im Oktober 2026 haben wir für Sie Pflegesachleistungen im Wert von \
{euro_de(claim.total_cents)} erbracht. Ihre Pflegekasse übernimmt bei Pflegegrad 2 \
höchstens {euro_de(cap)} im Monat. Es bleibt ein Eigenanteil von {euro_de(excess)}.

Bevor wir Ihnen diesen Betrag in Rechnung stellen, möchten wir Sie darüber informieren. \
Gerne besprechen wir mit Ihnen, ob wir den Leistungsumfang anpassen oder andere \
Leistungen wie den Entlastungsbetrag nutzen.

{SIGN_OFF}""",
            ),
        )
    )


def _gruber(w: World) -> None:
    p = _patient("p-gruber", "Gruber, Alois", dt.date(1946, 2, 8), kvnr("G", "99789016"), TK, TK_PK)
    rx = hkp_rx(
        "rx-gruber-2610",
        p,
        WEISS,
        dt.date(2026, 9, 22),
        (dt.date(2026, 10, 1), dt.date(2026, 12, 31)),
        [("kompression", "032110", "Kompressionsstrümpfe anziehen, KKL II", 1)],
        icd_codes=["I83.9"],
        submitted_to_payer_at=dt.date(2026, 9, 23),
    )
    log = w.visit_log(
        "vl-gruber-2610",
        p,
        TK,
        "sgbv",
        OCTOBER,
        daily(("032110", at(7, 20))),
        rota(KOELBL, HOFBAUER),
    )
    w.claim(log)
    w.patients[p.id] = p
    w.prescriptions.append(rx)
    w.approvals.append(approval_for(rx, TK, "TK-HKP-2026-0774", dt.date(2026, 9, 26)))


def _huber(w: World) -> None:
    p = _patient(
        "p-huber", "Huber, Rosa", dt.date(1932, 6, 25), kvnr("H", "99890127"), AOK, AOK_PK, grade=4
    )
    log = w.visit_log(
        "vl-huber-xi-2610",
        p,
        AOK_PK,
        "sgbxi",
        OCTOBER,
        lambda day: (
            [("LK 1", at(7)), ("LK 7", at(12))]
            + ([("LK 13", at(10))] if day.weekday() in (0, 3) else [])
        ),
        lambda _day, time: REITER if time.hour == 12 else BRUNNER,
    )
    w.claim(log)
    w.patients[p.id] = p


def _igl(w: World) -> None:
    """Handzeichen missing on two days (D05)."""
    p = _patient(
        "p-igl",
        "Igl, Walburga",
        dt.date(1937, 12, 1),
        kvnr("I", "99901238"),
        BARMER,
        BARMER_PK,
        grade=2,
    )
    rx = hkp_rx(
        "rx-igl-2610",
        p,
        RIEGER,
        dt.date(2026, 9, 21),
        (dt.date(2026, 10, 1), dt.date(2026, 12, 31)),
        [("medikamentengabe", "032101", "Levodopa/Benserazid 100/25 mg", 1)],
        icd_codes=["G20.90"],
        submitted_to_payer_at=dt.date(2026, 9, 22),
    )
    missing = {6, 21}
    log = w.visit_log(
        "vl-igl-2610",
        p,
        BARMER,
        "sgbv",
        OCTOBER,
        daily(("032101", at(8, 30))),
        lambda day, _time: None if day.day in missing else WIMMER,
        document_id="doc-igl-ln",
    )
    claim = w.claim(log)
    w.patients[p.id] = p
    w.prescriptions.append(rx)
    w.approvals.append(approval_for(rx, BARMER, "BAR-26-HKP-7702", dt.date(2026, 9, 25)))

    ref = ("Genehmigungskennzeichen", "BAR-26-HKP-7702")
    ln = w.document(
        "doc-igl-ln",
        "visit_log_sgbv",
        "Leistungsnachweis, October",
        p,
        dt.date(2026, 11, 1),
        visit_log_spec(
            81,
            log,
            p,
            BARMER,
            ref,
            WIMMER,
            [("032101", "Medikamentengabe", None)],
            signed_on=dt.date(2026, 10, 30),
        ),
        visit_log_fields(log, p, BARMER, ref),
    )
    unsigned = [line for line in claim.lines if line.date.day in missing]
    w.finding(
        "HKP-STAFF-INITIALS",
        "warn",
        claim,
        unsigned,
        de="Handzeichen fehlt am 06.10. und 21.10.2026 (2 Einsätze). Von der Pflegekraft "
        "nachtragen lassen.",
        en="Staff initials are missing on 6 and 21 Oct 2026 (2 visits). Ask the nurse to add them.",
        sources=["Rahmenempfehlungen §132a Abs. 1 SGB V, §8", "§302 SGB V"],
        evidence=[
            evidence(
                "doc-igl-ln",
                ln,
                "initials.06",
                "entries[5].staff_initials",
                "06.10.: kein Handzeichen",
            ),
            evidence(
                "doc-igl-ln",
                ln,
                "initials.21",
                "entries[20].staff_initials",
                "21.10.: kein Handzeichen",
            ),
        ],
    )
    w.actions.append(
        Action(
            id="act-igl-initials",
            kind="staff_followup",
            title="Ask Lena Wimmer to add her initials for 6 and 21 Oct",
            why="Visits without Handzeichen or Beschäftigtennummer are cut from the bill.",
            patient_id=p.id,
            patient_name=p.name,
            claim_id=claim.id,
            finding_ids=["f-igl-hkp-staff-initials"],
            due_date=dt.date(2026, 11, 4),
            amount_cents=sum(line.amount_cents for line in unsigned),
            status="open",
            letter=letter(
                "internal",
                ["Lena Wimmer", "Pflegefachkraft"],
                "Handzeichen nachtragen: Frau Walburga Igl, 06.10. und 21.10.2026",
                """
Hallo Lena,

im Leistungsnachweis Oktober von Frau Igl fehlt das Handzeichen am 06.10. und am \
21.10.2026 (Medikamentengabe, jeweils 08:30 Uhr). Laut Tourenplan warst du an beiden \
Tagen bei ihr. Bitte bis Mittwoch nachtragen, damit die Abrechnung am Freitag rausgehen \
kann.

Danke, Maria""",
            ),
        )
    )


def _jaeger(w: World) -> None:
    """Three days without visits and no known reason: an info-only hint (STAY-SIGNAL)."""
    p = _patient(
        "p-jaeger", "Jäger, Ludwig", dt.date(1943, 4, 19), kvnr("J", "99012349"), AOK, AOK_PK
    )
    rx = hkp_rx(
        "rx-jaeger-2610",
        p,
        MOSER,
        dt.date(2026, 9, 24),
        (dt.date(2026, 10, 1), dt.date(2026, 12, 31)),
        [("medikamentengabe", "032101", "Apixaban 5 mg, Bisoprolol 2,5 mg", 1)],
        icd_codes=["I48.0"],
        submitted_to_payer_at=dt.date(2026, 9, 25),
    )
    gap = {23, 24, 25}
    log = w.visit_log(
        "vl-jaeger-2610",
        p,
        AOK,
        "sgbv",
        [d for d in OCTOBER if d.day not in gap],
        daily(("032101", at(9))),
        rota(HOFBAUER, ZELLNER),
    )
    claim = w.claim(log)
    w.patients[p.id] = p
    w.prescriptions.append(rx)
    w.approvals.append(approval_for(rx, AOK, "AOK-HKP-26-40217", dt.date(2026, 9, 29)))
    w.finding(
        "STAY-SIGNAL",
        "info",
        claim,
        [],
        de="Vom 23.10. bis 25.10.2026 keine Einsätze und kein bekannter Grund. "
        "War Herr Jäger im Krankenhaus?",
        en="No visits from 23 to 25 Oct 2026 and no known reason. Was Herr Jäger in hospital?",
        sources=["Kassenfest heuristic, no legal source"],
        evidence=[],
    )


@cache
def world() -> World:
    """Built once per process; drawing the pages takes about a second."""
    w = World()
    for build in (
        _albers,
        _brandl,
        _christl,
        _dengler,
        _eder,
        _fink,
        _gruber,
        _huber,
        _igl,
        _jaeger,
    ):
        build(w)
    return w


@cache
def page_png(document_id: str, index: int) -> bytes:
    return world().page_images[document_id][index].png()
