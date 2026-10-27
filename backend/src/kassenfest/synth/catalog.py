"""Fixed vocabulary of the synthetic world: Kassen, services, prices, names, places.

Payer IKs, HKP Positionsnummern, Leistungskomplexe and prices mirror
`data/reference/*.yaml` from the rules-engine branch, so the rules engine prices and
checks exactly what the generator bills. All IKs and every price are invented
("illustrative"); Kassen names are real, nothing else about them is.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

# --- Kassen ---------------------------------------------------------------------


@dataclass(frozen=True)
class Kasse:
    name: str
    short: str
    krankenkasse_ik: str
    pflegekasse_ik: str
    letter_style: Literal["a", "b"]
    address: tuple[str, str]
    ref_prefix: str  # how this Kasse formats its Genehmigungskennzeichen

    @property
    def pflegekasse_name(self) -> str:
        return f"{self.name} – Pflegekasse"


KASSEN = [
    Kasse("AOK Bayern", "AOK", "109990018", "189990018", "a",
          ("Postfach 99 01 01", "94459 Deggendorf"), "HKP-{y}-{n:06d}"),
    Kasse("Techniker Krankenkasse", "TK", "109990029", "189990029", "b",
          ("Postfach 99 02 02", "20999 Hamburg"), "TK/{y}/{n:07d}"),
    Kasse("BARMER", "BARMER", "109990030", "189990030", "b",
          ("Postfach 99 03 03", "42999 Wuppertal"), "B-HKP {n:08d}"),
    Kasse("DAK-Gesundheit", "DAK", "109990041", "189990041", "b",
          ("Postfach 99 04 04", "20999 Hamburg"), "DAK-{n:09d}"),
    Kasse("IKK classic", "IKK", "109990052", "189990052", "a",
          ("Postfach 99 05 05", "01999 Dresden"), "IKK.{y}.{n:06d}"),
    Kasse("KKH Kaufmännische Krankenkasse", "KKH", "109990063", "189990063", "b",
          ("Postfach 99 06 06", "30999 Hannover"), "KKH-G-{n:07d}"),
    Kasse("Knappschaft", "KBS", "109990096", "189990096", "a",
          ("Postfach 99 09 09", "44999 Bochum"), "KN {y} {n:06d}"),
]  # fmt: skip
KASSE_BY_IK = {
    ik: k for k in KASSEN for ik in (k.krankenkasse_ik, k.pflegekasse_ik)
}  # both roles of a Kasse map to it

# --- HKP (SGB V) services ------------------------------------------------------------


@dataclass(frozen=True)
class HkpService:
    position_no: str
    label: str  # as printed in the visit-log column header
    category: str  # extraction MeasureCategory
    price_cents: int  # HKP-BY-2026-01, illustrative


HKP_SERVICES = {
    s.position_no: s
    for s in [
        HkpService("032101", "Medikamentengabe", "medikamentengabe", 790),
        HkpService("032110", "Injektion s.c.", "injektion", 840),
        HkpService("032120", "Blutzuckermessung", "blutzucker", 520),
        HkpService("032130", "Kompressionsstrümpfe anziehen", "kompression", 890),
        HkpService("032140", "Kompressionsverband anlegen", "kompression", 1340),
        HkpService("032151", "Wundversorgung, chron. Wunde", "wundversorgung", 2190),
    ]
}
HKP_TARIFF = "HKP-BY-2026-01"

# Details the doctor writes next to a measure on Muster 12.
MEASURE_DETAILS = {
    "032101": [
        "Metformin 1000 mg, Ramipril 5 mg",
        "Ramipril 5 mg, Torasemid 10 mg, ASS 100 mg",
        "Marcumar nach INR-Plan",
        "Donepezil 10 mg, Sertralin 50 mg",
        "Bisoprolol 5 mg, Apixaban 5 mg",
    ],
    "032110": [
        "Insulin Lantus 18 IE s.c.",
        "Clexane 40 mg s.c.",
        "Insulin Actrapid nach BZ-Schema",
    ],
    "032120": [None, "BZ vor Insulingabe"],
    "032130": ["Kompressionsstrümpfe Kl. II beidseits"],
    "032140": ["Kompressionsverband li. Unterschenkel"],
    "032151": [
        "Ulcus cruris li. Unterschenkel 3 x 2 cm, Grad 2",
        "Dekubitus sakral 2 x 2 cm, Grad 2",
        "Diabet. Fußulcus re. Ferse 1,5 x 1 cm",
    ],
}

# --- SGB XI Leistungskomplexe ---------------------------------------------------------

PUNKTWERT_EUR = Decimal("0.0947")  # XI-BY-2026-01, illustrative
XI_TARIFF = "XI-BY-2026-01"


@dataclass(frozen=True)
class Leistungskomplex:
    code: str
    label: str
    points: int

    @property
    def price_cents(self) -> int:
        cents = Decimal(self.points) * PUNKTWERT_EUR * 100
        return int(cents.quantize(Decimal(1), rounding=ROUND_HALF_UP))


LK = {
    lk.code: lk
    for lk in [
        Leistungskomplex("LK01", "Ganzkörperwäsche", 420),
        Leistungskomplex("LK02", "Teilwäsche", 250),
        Leistungskomplex("LK03", "Hilfe bei Ausscheidungen", 180),
        Leistungskomplex("LK04", "Hilfe bei der Nahrungsaufnahme", 250),
        Leistungskomplex("LK05", "Lagern und Betten", 100),
        Leistungskomplex("LK06", "Mobilisation", 150),
        Leistungskomplex("LK07", "An- und Auskleiden", 120),
        Leistungskomplex("LK10", "Reinigen der Wohnung", 400),
        Leistungskomplex("LK12", "Einkaufen", 250),
        Leistungskomplex("LK13", "Zubereitung einer warmen Mahlzeit", 300),
    ]
}

# §36 Pflegesachleistung per month, SGBXI-2026-01 (unchanged from 2025).
SACHLEISTUNG_CAP_CENTS = {1: 0, 2: 79600, 3: 149700, 4: 185900, 5: 229900}
ENTLASTUNG_45B_CENTS = 13100

# --- Calendar -----------------------------------------------------------------------

# Bavarian statutory holidays 2026 incl. Mariä Himmelfahrt (Deggendorf is a Catholic
# municipality). Enough for Sep–Nov 2026 billing; the rules engine has the real calendar.
HOLIDAYS_BY_2026 = {
    dt.date(2026, 1, 1), dt.date(2026, 1, 6), dt.date(2026, 4, 3), dt.date(2026, 4, 6),
    dt.date(2026, 5, 1), dt.date(2026, 5, 14), dt.date(2026, 5, 25), dt.date(2026, 6, 4),
    dt.date(2026, 8, 15), dt.date(2026, 10, 3), dt.date(2026, 11, 1),
    dt.date(2026, 12, 25), dt.date(2026, 12, 26),
}  # fmt: skip


def is_working_day(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS_BY_2026


def add_working_days(d: dt.date, n: int) -> dt.date:
    """The n-th working day after d (n >= 1); n <= 0 returns d itself."""
    while n > 0:
        d += dt.timedelta(days=1)
        n -= is_working_day(d)
    return d


# --- People and places ----------------------------------------------------------------

PROVIDER_NAME = "Pflegedienst Sonnenschein GmbH"
PROVIDER_ADDRESS = ("Hengersberger Str. 18", "94469 Deggendorf")

FEMALE = [
    "Erika", "Maria", "Anna", "Theresia", "Rosemarie", "Hildegard", "Käthe", "Walburga",
    "Gertraud", "Ingrid", "Brigitte", "Renate", "Elfriede", "Monika", "Johanna", "Irmgard",
]  # fmt: skip
MALE = [
    "Johann", "Josef", "Franz", "Günther", "Jürgen", "Ludwig", "Alois", "Xaver", "Georg",
    "Helmut", "Manfred", "Rudolf", "Karl", "Siegfried", "Werner", "Max",
]  # fmt: skip
SURNAMES = [
    "Fischer", "Größl", "Hölzl", "Jäger", "Kößler", "Lindner", "Moosbauer", "Nißl", "Obermeier",
    "Pfeffer", "Raith", "Schäfer", "Strauß", "Thalhammer", "Unertl", "Vogl", "Weiß", "Zellner",
    "Aigner", "Bachmeier", "Daxl", "Ebner", "Frisch", "Gruber", "Haslinger", "Kerscher",
    "Loibl", "Mühlbauer", "Paintner", "Reisinger", "Sagstetter", "Wagner", "Zitzelsberger",
]  # fmt: skip

STREETS = [
    "Bahnhofstr.", "Lindenweg", "Am Stadtpark", "Bergstr.", "Donaustr.", "Kirchplatz",
    "Schulstr.", "Ulrichsberger Str.", "Graflinger Str.", "Rosenweg", "Mettener Str.",
    "Pfarrer-Wagner-Weg", "Am Mühlbach", "Feldstr.", "Gartenstr.",
]  # fmt: skip
TOWNS = [
    ("94469", "Deggendorf"), ("94469", "Deggendorf"), ("94469", "Deggendorf"),
    ("94447", "Plattling"), ("94526", "Metten"), ("94491", "Hengersberg"),
    ("94486", "Osterhofen"), ("94481", "Grafling"), ("94560", "Offenberg"),
]  # fmt: skip

NURSES = [
    # name, Handzeichen, qualification
    ("Monika Kraus", "MK", "pflegefachkraft"),
    ("Stefan Bauer", "SB", "pflegefachkraft"),
    ("Andrea Wimmer", "AW", "pflegefachkraft"),
    ("Tobias Huber", "TH", "pflegefachkraft"),
    ("Julia Reiter", "JR", "pflegefachkraft"),
    ("Lena Fuchs", "LF", "pflegehilfskraft"),
    ("Claudia Gruber", "CG", "pflegehilfskraft"),
    ("Petra Mayerhofer", "PMa", "auszubildende"),
]
PDL = "Monika Kraus"  # Pflegedienstleitung, signs as verantwortliche Pflegefachkraft

DOCTORS = [
    # name, specialty, street, (zip, town), LANR Fachgruppe
    ("Dr. med. Sabine Hartl", "Fachärztin für Allgemeinmedizin", "Stadtplatz 12",
     ("94469", "Deggendorf"), "01"),
    ("Dr. med. Thomas Rieger", "Facharzt für Innere Medizin", "Bahnhofstr. 3",
     ("94447", "Plattling"), "23"),
    ("Dr. med. Ursula Fröhlich", "Hausärztliche Versorgung", "Pfleggasse 7",
     ("94469", "Deggendorf"), "01"),
    ("Dr. med. Markus Ederer", "Facharzt für Allgemeinmedizin", "Marktplatz 4",
     ("94491", "Hengersberg"), "01"),
    ("Dr. med. Claudia Wenninger", "Fachärztin für Innere Medizin", "Klosterstr. 9",
     ("94526", "Metten"), "23"),
    ("Dr. med. Florian Aschenbrenner", "Facharzt für Allgemeinmedizin", "Vorstadt 21",
     ("94486", "Osterhofen"), "01"),
]  # fmt: skip

HOSPITAL_NAME = "Klinikum Donautal Deggendorf"  # fictitious
HOSPITAL_LINES = (
    "Klinik für Innere Medizin und Geriatrie",
    "Perlasberger Weg 40",
    "94469 Deggendorf",
)
HOSPITAL_DOCTORS = ["Dr. med. Katrin Seidl, Oberärztin", "Dr. med. Andreas Pöschl, Oberarzt"]

ICD = {
    "E11.9": "Diabetes mellitus Typ 2 ohne Komplikationen",
    "E11.74": "Diabetes mellitus Typ 2 mit diabetischem Fußsyndrom",
    "I83.0": "Varizen der unteren Extremitäten mit Ulzeration",
    "L97": "Ulcus cruris, anderenorts nicht klassifiziert",
    "L89.1": "Dekubitus 2. Grades",
    "I50.13": "Linksherzinsuffizienz NYHA III",
    "I50.9": "Herzinsuffizienz, nicht näher bezeichnet",
    "I48.0": "Vorhofflimmern, paroxysmal",
    "F03": "Nicht näher bezeichnete Demenz",
    "M17.1": "Primäre Gonarthrose, einseitig",
    "I10.00": "Benigne essentielle Hypertonie",
    "J44.19": "COPD mit akuter Exazerbation",
    "N39.0": "Harnwegsinfektion",
    "J18.9": "Pneumonie, nicht näher bezeichnet",
    "S72.00": "Schenkelhalsfraktur",
}
# Diagnoses that fit each HKP service (first ones preferred on the Verordnung).
SERVICE_ICD = {
    "032101": ["I50.9", "I10.00", "F03", "I48.0"],
    "032110": ["E11.9"],
    "032120": ["E11.9"],
    "032130": ["I83.0", "I50.9"],
    "032140": ["I83.0", "L97"],
    "032151": ["L97", "L89.1", "E11.74"],
}
HOSPITAL_DIAGNOSES = [
    ["I50.13", "I48.0"],
    ["J18.9", "I50.9"],
    ["N39.0", "F03"],
    ["J44.19"],
    ["S72.00", "M17.1"],
]
LIMITATIONS = [
    "Pat. kann Medikamente nicht selbst richten (Demenz)",
    "eingeschränkte Feinmotorik und Sehschwäche",
    "Immobilität nach Sturz, lebt allein",
    "kognitive Einschränkung, keine Angehörigen vor Ort",
    "Pat. kann Injektion nicht selbst durchführen (Tremor)",
]
