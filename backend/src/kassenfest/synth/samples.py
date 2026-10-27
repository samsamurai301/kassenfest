"""Plausible random content for spikes and renderer tests.

Not the world model (that's Track A: consistent patients, prescriptions and visits
across documents). Identifiers here are format-correct but not check-digit-valid.
"""

import datetime as dt
import random

from kassenfest.synth.documents import (
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

SURNAMES = [
    "Albers", "Brandl", "Christl", "Dengler", "Eder", "Größl", "Hölzl", "Jäger", "Kößler",
    "Müller", "Schäfer", "Strauß", "Weiß", "Huber", "Bauer", "Wagner", "Maier", "Kühn",
]  # fmt: skip
FIRST_NAMES = [
    "Erika", "Johann", "Maria", "Josef", "Anna", "Franz", "Theresia", "Günther",
    "Rosemarie", "Jürgen", "Hildegard", "Käthe", "Ludwig", "Walburga",
]  # fmt: skip
PAYERS = [
    "AOK Bayern", "Techniker Krankenkasse", "BARMER", "DAK-Gesundheit", "IKK classic",
    "KKH Kaufmännische Krankenkasse", "SBK Siemens-Betriebskrankenkasse", "KNAPPSCHAFT",
]  # fmt: skip
ICD = ["E11.9", "I83.0", "L89.1", "I50.9", "F03", "M17.1", "I10", "E11.74", "L97"]
DOCTORS = [
    ("Dr. med. Sabine Hartl", "Fachärztin für Allgemeinmedizin", "Stadtplatz 12, 94469 Deggendorf"),
    ("Dr. med. Thomas Rieger", "Facharzt für Innere Medizin", "Bahnhofstr. 3, 94447 Plattling"),
    ("Dr. med. Ursula Fröhlich", "Hausärztliche Versorgung", "Pfleggasse 7, 94469 Deggendorf"),
]

# category, row label, possible details, possible (count, per) frequencies
MEASURES = [
    (
        "medikamentengabe",
        "Medikamentengabe",
        [
            "Metformin 1000 mg, Ramipril 5 mg",
            "Marcumar nach Plan",
            "Ramipril 5 mg, Torasemid 10 mg",
        ],
        [(2, "day"), (1, "day"), (3, "day")],
    ),
    (
        "injektion",
        "Injektionen",
        ["Insulin Lantus 18 IE s.c.", "Clexane 40 mg s.c."],
        [(1, "day"), (2, "day")],
    ),
    ("blutzucker", "Blutzuckermessung", [None], [(3, "day"), (2, "day")]),
    (
        "kompression",
        "Kompressionsbehandlung",
        ["Kompressionsstrümpfe Kl. II beidseits an/aus"],
        [(2, "day")],
    ),
    (
        "wundversorgung",
        "Wundversorgung",
        ["Ulcus cruris li. Unterschenkel 3 x 2 cm, Grad 2", "Dekubitus sakral 2 x 2 cm, Grad 2"],
        [(3, "week"), (1, "day")],
    ),
]

HKP_SERVICES = [
    ("031199", "Medikamentengabe"),
    ("032131", "Injektion s.c."),
    ("032151", "Blutzuckermessung"),
    ("032171", "Kompressionsstrümpfe an/aus"),
    ("032201", "Wundversorgung"),
]


def _digits(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(n))


def kvnr(rng: random.Random) -> str:
    return rng.choice("ABCDEFGHKLMNRSTW") + _digits(rng, 9)


def name(rng: random.Random) -> str:
    return f"{rng.choice(SURNAMES)}, {rng.choice(FIRST_NAMES)}"


def muster12(
    rng: random.Random, *, doctor_signed: bool = True, stamp_present: bool = True
) -> Muster12Content:
    issue = dt.date(2026, 10, rng.randint(1, 20))
    start = issue + dt.timedelta(days=rng.randint(0, 2))
    kind = rng.choice(["erst", "folge"])
    end = start + dt.timedelta(days=13 if kind == "erst" else rng.choice([27, 30, 60]))
    picked = rng.sample(MEASURES, rng.randint(1, 3))
    measures = []
    for category, label, details, freqs in sorted(
        picked, key=lambda m: [x[0] for x in MEASURES].index(m[0])
    ):
        count, per = rng.choice(freqs)
        measures.append(
            M12Measure(
                category=category,
                label=label,
                details=rng.choice(details),
                count=count,
                per=per,
                duration_from=start,
                duration_to=end,
            )
        )
    doctor, specialty, address = rng.choice(DOCTORS)
    bsnr = "71" + _digits(rng, 7)
    lanr = _digits(rng, 9)
    return Muster12Content(
        payer_name=rng.choice(PAYERS),
        payer_ik="10" + _digits(rng, 7),
        patient_name=name(rng),
        patient_dob=dt.date(rng.randint(1928, 1962), rng.randint(1, 12), rng.randint(1, 28)),
        kvnr=kvnr(rng),
        bsnr=bsnr,
        lanr=lanr,
        issue_date=issue,
        icd_codes=rng.sample(ICD, rng.randint(1, 2)),
        limitations=rng.choice(
            [
                "Pat. kann Medikamente nicht selbst richten (Demenz)",
                "eingeschränkte Feinmotorik, Sehschwäche",
                "Immobilität nach Sturz",
            ]
        ),
        kind=kind,
        accident=rng.random() < 0.05,
        period_from=start,
        period_to=end,
        measures=measures,
        further_notes=rng.choice(
            [None, None, "Bitte BZ-Werte dokumentieren", "Rücksprache bei Wundverschlechterung"]
        ),
        doctor_name=doctor,
        practice_lines=[doctor, specialty, address, f"BSNR {bsnr}  LANR {lanr}"],
        doctor_signed=doctor_signed,
        stamp_present=stamp_present,
    )


def visit_log_sgbv(
    rng: random.Random, *, patient_signed: bool = True, missing_initials: int = 0
) -> VisitLogContent:
    services = [
        LNService(position_no=pos, label=label, slots=rng.choice([1, 2]))
        for pos, label in rng.sample(HKP_SERVICES, rng.randint(1, 3))
    ]
    staff = [
        LNStaff(initials=i, employee_no=_digits(rng, 9))
        for i in rng.sample(["MK", "SB", "AW", "TH", "JR", "LF", "CG"], rng.randint(2, 4))
    ]
    last_day = rng.choice([31, 31, 31, 14, 22])
    visits = []
    for day in range(1, last_day + 1):
        for si, s in enumerate(services):
            for slot in range(s.slots):
                hour = 7 if slot == 0 else 18
                visits.append(
                    LNVisit(
                        day=day,
                        service=si,
                        slot=slot,
                        time=dt.time(hour + rng.randint(0, 1), rng.choice(range(0, 60, 5))),
                        staff=rng.randrange(len(staff)),
                    )
                )
    for v in rng.sample(visits, min(missing_initials, len(visits))):
        v.staff = None
    return VisitLogContent(
        provider_name="Pflegedienst Sonnenschein GmbH, Deggendorf",
        provider_ik="46" + _digits(rng, 7),
        patient_name=name(rng),
        kvnr=kvnr(rng),
        payer_name=rng.choice(PAYERS),
        year=2026,
        month=10,
        approval_ref=rng.choice([None, f"G-{_digits(rng, 8)}"]),
        responsible_nurse=rng.choice(["Monika Kraus", "Stefan Bauer", "Andrea Wimmer"]),
        services=services,
        staff=staff,
        visits=visits,
        patient_signed=patient_signed,
        patient_signature_date=dt.date(2026, 10, 31) if patient_signed else None,
        missing_signature_reason=None,
    )


def approval_letter(rng: random.Random, *, style: str = "a", partial: bool = False):
    start = dt.date(2026, 10, rng.randint(1, 10))
    end = start + dt.timedelta(days=rng.choice([30, 60, 91]))
    picked = rng.sample(HKP_SERVICES, rng.randint(1, 3))
    approved = [
        ApprovedLine(
            position_no=pos,
            description=label,
            count=rng.choice([1, 2, None]),
            per="day",
            valid_from=start,
            valid_to=end,
        )
        for pos, label in picked
    ]
    for a in approved:
        if a.count is None:
            a.per = None
    rejected = []
    if partial:
        rejected = [
            RejectedLine(
                description="Kompressionsstrümpfe an/aus",
                reason="Medizinische Notwendigkeit nicht ausreichend begründet",
            )
        ]
    return ApprovalLetterContent(
        style=style,  # type: ignore[arg-type]
        payer_name=rng.choice(PAYERS),
        payer_ik="10" + _digits(rng, 7),
        payer_address=["Postfach 99 01 01", "94459 Deggendorf"],
        letter_date=start + dt.timedelta(days=rng.randint(2, 12)),
        approval_ref=f"HKP-2026-{_digits(rng, 6)}",
        patient_name=name(rng),
        patient_dob=dt.date(rng.randint(1930, 1960), rng.randint(1, 12), rng.randint(1, 28)),
        kvnr=kvnr(rng),
        provider_name="Pflegedienst Sonnenschein GmbH",
        provider_address=["Hengersberger Str. 18", "94469 Deggendorf"],
        provider_ik="46" + _digits(rng, 7),
        prescription_issue_date=start - dt.timedelta(days=2),
        decision="partial" if partial else "approved",
        period_from=start,
        period_to=end,
        approved=approved,
        rejected=rejected,
        copay_exempt=rng.random() < 0.3,
        clerk="Frau Gschwendtner",
        phone="0991 999 1234",
    )


LK_SAMPLE = [
    ("LK01", "Ganzkörperwäsche"),
    ("LK02", "Teilwäsche"),
    ("LK07", "An- und Auskleiden"),
    ("LK04", "Hilfe bei der Nahrungsaufnahme"),
    ("LK12", "Einkaufen"),
]


def visit_log_sgbxi(rng: random.Random, *, patient_signed: bool = True) -> VisitLogXIContent:
    einsaetze = [
        XIEinsatz(label="Früh", funding="sachleistung_36", lk=[LK_SAMPLE[0], LK_SAMPLE[2]]),
        XIEinsatz(label="Abend", funding="sachleistung_36", lk=[LK_SAMPLE[1]]),
        XIEinsatz(label="Hauswirtschaft", funding="entlastung_45b", lk=[LK_SAMPLE[4]]),
    ]
    staff = [
        LNStaff(initials=i, employee_no=_digits(rng, 9))
        for i in rng.sample(["MK", "SB", "AW", "TH", "JR", "LF", "CG"], 3)
    ]
    visits = []
    for day in range(1, 32):
        weekday = dt.date(2026, 10, day).weekday()
        for ei, e in enumerate(einsaetze):
            if e.funding == "entlastung_45b" and weekday != 3:
                continue
            hour = {"Früh": 7, "Abend": 18, "Hauswirtschaft": 10}[e.label]
            visits.append(
                XIVisit(
                    day=day,
                    einsatz=ei,
                    time=dt.time(hour, rng.choice(range(0, 60, 5))),
                    staff=rng.randrange(len(staff)),
                    lk=[code for code, _ in e.lk],
                )
            )
    return VisitLogXIContent(
        provider_name="Pflegedienst Sonnenschein GmbH, Deggendorf",
        provider_ik="46" + _digits(rng, 7),
        patient_name=name(rng),
        kvnr=kvnr(rng),
        payer_name=rng.choice(PAYERS) + " – Pflegekasse",
        pflegegrad=rng.randint(2, 4),
        year=2026,
        month=10,
        einsaetze=einsaetze,
        staff=staff,
        visits=visits,
        patient_signed=patient_signed,
        patient_signature_date=dt.date(2026, 10, 31),
    )


def hospital_letter(rng: random.Random, *, signed: bool = True) -> HospitalLetterContent:
    admitted = dt.datetime(2026, 10, 12, 10, 30)
    discharged = dt.datetime(2026, 10, 16, 11, 15)
    return HospitalLetterContent(
        hospital_name="Klinikum Donautal Deggendorf",
        hospital_lines=["Klinik für Innere Medizin", "Perlasberger Weg 40", "94469 Deggendorf"],
        hospital_id="77" + _digits(rng, 7),
        letter_date=discharged.date(),
        recipient_lines=[DOCTORS[0][0], DOCTORS[0][2].split(",")[0], "94469 Deggendorf"],
        patient_name=name(rng),
        patient_sex=rng.choice(["f", "m"]),
        patient_dob=dt.date(1938, 4, 3),
        kvnr=kvnr(rng),
        payer_name=rng.choice(PAYERS),
        admitted_at=admitted,
        discharged_at=discharged,
        diagnoses=[("I50.13", "Linksherzinsuffizienz NYHA III"), ("I48.0", "Vorhofflimmern")],
        hkp_recommended=True,
        hkp_prescription_days=rng.choice([None, 7]),
        medication=["Torasemid 10 mg 1-0-0", "Apixaban 5 mg 1-0-1"],
        physician="Dr. med. Katrin Seidl, Oberärztin",
        signed=signed,
    )
