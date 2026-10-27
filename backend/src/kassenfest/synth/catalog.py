"""Fixed vocabulary of the synthetic world: Kassen, services, prices, names, places.

Payer IKs, HKP Positionsnummern, Leistungskomplexe, prices and the §36 caps come from
`data/reference/*.yaml` via `kassenfest.rules.reference`, and working days from
`kassenfest.rules.calendar`, so the rules engine prices and checks exactly what the
generator bills. This module only adds what paperwork needs: letter layouts, addresses,
reference-number formats, column labels. All IKs and every price are invented
("illustrative"); Kassen names are real, nothing else about them is.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from kassenfest.rules import calendar
from kassenfest.rules.reference import load_reference, valid_on
from kassenfest.rules.tariffs import hkp_price, lk_price

REF = load_reference()
PRICE_DAY = dt.date(2026, 10, 1)  # the billing month's tariff
CALENDAR = calendar.calendar_for("BY", "Deggendorf")

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


# short -> (letter style, postal address, Genehmigungskennzeichen format)
_LETTERS = {
    "AOK": ("a", ("Postfach 99 01 01", "94459 Deggendorf"), "HKP-{y}-{n:06d}"),
    "TK": ("b", ("Postfach 99 02 02", "20999 Hamburg"), "TK/{y}/{n:07d}"),
    "BARMER": ("b", ("Postfach 99 03 03", "42999 Wuppertal"), "B-HKP {n:08d}"),
    "DAK": ("b", ("Postfach 99 04 04", "20999 Hamburg"), "DAK-{n:09d}"),
    "IKK": ("a", ("Postfach 99 05 05", "01999 Dresden"), "IKK.{y}.{n:06d}"),
    "KKH": ("b", ("Postfach 99 06 06", "30999 Hannover"), "KKH-G-{n:07d}"),
    "KBS": ("a", ("Postfach 99 09 09", "44999 Bochum"), "KN {y} {n:06d}"),
}
KASSEN = [
    Kasse(k.name, k.short, k.krankenkasse_ik, k.pflegekasse_ik, *_LETTERS[k.short])
    for k in REF.kassen
    if k.short in _LETTERS
]
KASSE_BY_IK = {ik: k for k in KASSEN for ik in (k.krankenkasse_ik, k.pflegekasse_ik)}

# --- HKP (SGB V) services ------------------------------------------------------------


@dataclass(frozen=True)
class HkpService:
    position_no: str
    label: str  # label_de, as printed in the visit-log column and on approval letters
    category: str  # extraction MeasureCategory
    price_cents: int


def _hkp(position_no: str) -> HkpService:
    pos = REF.hkp_positions[position_no]
    price = hkp_price(REF, position_no, PRICE_DAY)
    assert pos.category and price, position_no
    return HkpService(position_no, pos.label_de, pos.category, price.unit_cents)


# The positions the world uses: one per measure category, so a Verordnung's frequency
# for a category is the frequency of exactly one position.
HKP_SERVICES = {p: _hkp(p) for p in ("032101", "032110", "032120", "032130", "032140", "032151")}
HKP_TARIFF = valid_on(REF.hkp_tariffs, PRICE_DAY).version  # type: ignore[union-attr]

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


@dataclass(frozen=True)
class Leistungskomplex:
    code: str
    label: str
    points: int
    price_cents: int


LK = {
    code: Leistungskomplex(code, lk.label_de, lk.points, lk_price(REF, code, PRICE_DAY).unit_cents)  # type: ignore[union-attr]
    for code, lk in REF.leistungskomplexe.items()
}
XI_TARIFF = valid_on(REF.punktwerte, PRICE_DAY).version  # type: ignore[union-attr]

_AMOUNTS = REF.amounts_on(PRICE_DAY)
SACHLEISTUNG_CAP_CENTS = dict(_AMOUNTS.sachleistung_36_cents)
ENTLASTUNG_45B_CENTS = _AMOUNTS.entlastungsbetrag_45b_cents

# --- Calendar -----------------------------------------------------------------------


def is_working_day(d: dt.date) -> bool:
    return CALENDAR.is_working_day(d)


def add_working_days(d: dt.date, n: int) -> dt.date:
    """The n-th working day after d; negative n goes back."""
    return CALENDAR.add_working_days(d, n)


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
