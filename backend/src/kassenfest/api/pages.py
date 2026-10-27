"""Synthetic page images for the fixture API.

Drawn with Pillow so fixture evidence can point at exact pixel boxes: every draw_*
function returns the page together with the box of each field it drew. Every page
carries the "MUSTER – SYNTHETISCH – KEIN ECHTES DOKUMENT" watermark (DOC-SYNTHETIC).
Stand-in for the Playwright renderer in synth/; swap it out once that lands.
"""

import datetime as dt
import io
import random
from dataclasses import dataclass
from functools import cache
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from kassenfest.schemas.common import PixelBox
from kassenfest.schemas.domain import Domain

WIDTH, HEIGHT = 1240, 1754  # A4 at 150 dpi
WATERMARK = "MUSTER – SYNTHETISCH – KEIN ECHTES DOKUMENT"

PAPER = (251, 250, 246)
PRINT = (34, 34, 38)
FAINT = (118, 118, 124)
RULE = (170, 170, 176)
SHADE = (238, 238, 236)
FORM_RED = (196, 64, 78)
FORM_TINT = (253, 236, 236)
INK = (30, 48, 140)
STAMP_INK = (92, 62, 172)

FontKind = Literal["sans", "bold", "mono", "hand"]

# First font that exists wins: macOS paths, then Debian/Ubuntu DejaVu.
_FONT_PATHS: dict[FontKind, tuple[str, ...]] = {
    "sans": (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    "bold": (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    "mono": (
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ),
    "hand": (
        "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    ),
}

WEEKDAYS_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
MONTHS_DE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)  # fmt: skip


@cache
def font(kind: FontKind, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS[kind]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def de_date(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def de_month(month: str) -> str:
    year, mon = month.split("-")
    return f"{MONTHS_DE[int(mon) - 1]} {year}"


def union(*boxes: PixelBox) -> PixelBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _pad(box: tuple[float, float, float, float], by: float) -> PixelBox:
    return (box[0] - by, box[1] - by, box[2] + by, box[3] + by)


@dataclass
class Page:
    image: Image.Image
    boxes: dict[str, PixelBox]

    def png(self) -> bytes:
        buf = io.BytesIO()
        self.image.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


class Sheet:
    """One A4 page being drawn; records the box of every keyed element."""

    def __init__(self, seed: int):
        self.image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
        self.draw = ImageDraw.Draw(self.image)
        self.rng = random.Random(seed)
        self.seed = seed
        self.boxes: dict[str, PixelBox] = {}

    def text(
        self,
        xy: tuple[float, float],
        s: str,
        *,
        kind: FontKind = "sans",
        size: int = 22,
        fill: tuple[int, int, int] = PRINT,
        key: str | None = None,
    ) -> PixelBox:
        f = font(kind, size)
        box = self.draw.textbbox(xy, s, font=f)
        self.draw.text(xy, s, font=f, fill=fill)
        if key:
            self.boxes[key] = _pad(box, 6)
        return box

    def hand(self, xy: tuple[float, float], s: str, *, size: int = 32, key: str | None = None):
        jitter = (xy[0] + self.rng.uniform(-2, 2), xy[1] + self.rng.uniform(-3, 3))
        return self.text(jitter, s, kind="hand", size=size, fill=INK, key=key)

    def field(
        self,
        key: str,
        box: PixelBox,
        label: str,
        value: str | None,
        *,
        printed: bool = False,
        size: int = 28,
        tint: bool = True,
    ) -> None:
        """A form field: small red label top-left, printed or handwritten value inside."""
        x0, y0, _, _ = box
        self.draw.rectangle(box, fill=FORM_TINT if tint else None, outline=FORM_RED, width=1)
        self.draw.text((x0 + 8, y0 + 4), label, font=font("sans", 14), fill=FORM_RED)
        if value:
            if printed:
                self.text((x0 + 10, y0 + 22), value, kind="mono", size=size - 6)
            else:
                self.hand((x0 + 12, y0 + 16), value, size=size)
        self.boxes[key] = box

    def checkbox(self, x: float, y: float, label: str, checked: bool) -> PixelBox:
        self.draw.rectangle((x, y, x + 22, y + 22), outline=FORM_RED, width=2, fill="white")
        label_box = self.text((x + 32, y), label, size=19, fill=FORM_RED)
        if checked:
            self.hand((x - 1, y - 16), "x", size=38)
        return (x - 4, y - 4, label_box[2] + 4, y + 26)

    def signature(self, area: PixelBox) -> PixelBox:
        """Procedural scribble inside `area` (same idea as smoke.draw_card); returns ink extent."""
        x0, y0, x1, y1 = area
        mid, amp = (y0 + y1) / 2, (y1 - y0) * 0.42
        p = (x0 + self.rng.uniform(15, 40), mid + self.rng.uniform(-amp / 3, amp / 3))
        points: list[tuple[float, float]] = []
        while p[0] < x1 - 60:
            c1 = (p[0] + self.rng.uniform(-25, 35), mid + self.rng.uniform(-amp, amp))
            c2 = (p[0] + self.rng.uniform(10, 60), mid + self.rng.uniform(-amp, amp))
            end = (p[0] + self.rng.uniform(30, 65), mid + self.rng.uniform(-amp / 2, amp / 2))
            for i in range(21):
                t = i / 20
                mt = 1 - t
                points.append(
                    (
                        mt**3 * p[0]
                        + 3 * mt**2 * t * c1[0]
                        + 3 * mt * t**2 * c2[0]
                        + t**3 * end[0],
                        mt**3 * p[1]
                        + 3 * mt**2 * t * c1[1]
                        + 3 * mt * t**2 * c2[1]
                        + t**3 * end[1],
                    )
                )
            p = end
        self.draw.line(points, fill=INK, width=3, joint="curve")
        xs, ys = [q[0] for q in points], [q[1] for q in points]
        return (min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3)

    def stamp(
        self, origin: tuple[int, int], lines: list[str], angle: float, size: int = 24
    ) -> PixelBox:
        width = max(int(font("bold", size).getlength(line)) for line in lines) + 36
        layer = Image.new("RGBA", (width, 22 + len(lines) * (size + 10)), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rectangle((2, 2, layer.width - 3, layer.height - 3), outline=STAMP_INK, width=3)
        for i, line in enumerate(lines):
            d.text((18, 12 + i * (size + 10)), line, font=font("bold", size), fill=STAMP_INK)
        # Ink gaps: knock out random specks so it reads as a rubber stamp, not a print.
        alpha = np.asarray(layer.getchannel("A"), dtype=np.float32)
        gaps = np.random.default_rng(self.seed).random(alpha.shape) < 0.18
        layer.putalpha(Image.fromarray(np.where(gaps, alpha * 0.35, alpha * 0.9).astype(np.uint8)))
        layer = layer.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        self.image.paste(layer, origin, layer)
        bx0, by0, bx1, by1 = layer.getbbox() or (0, 0, *layer.size)
        return (origin[0] + bx0, origin[1] + by0, origin[0] + bx1, origin[1] + by1)

    def finish(self) -> Page:
        # Scanner dust instead of per-pixel grain: grain makes every PNG ~2 MB.
        image = self.image
        dust = ImageDraw.Draw(image)
        for _ in range(140):
            x, y = self.rng.uniform(0, WIDTH), self.rng.uniform(0, HEIGHT)
            r = self.rng.uniform(0.6, 1.6)
            dust.ellipse((x - r, y - r, x + r, y + r), fill=(150, 150, 150))

        mark = Image.new("RGBA", (1500, 90), (0, 0, 0, 0))
        ImageDraw.Draw(mark).text(
            (750, 45), WATERMARK, font=font("bold", 54), fill=(205, 40, 40, 46), anchor="mm"
        )
        mark = mark.rotate(33, expand=True, resample=Image.Resampling.BICUBIC)
        image.paste(mark, ((WIDTH - mark.width) // 2, (HEIGHT - mark.height) // 2), mark)
        ImageDraw.Draw(image).text(
            (WIDTH / 2, 30), WATERMARK, font=font("bold", 15), fill=(190, 60, 60), anchor="mm"
        )
        return Page(image=image, boxes=self.boxes)


# --- Muster 12 ------------------------------------------------------------------


@dataclass
class Muster12Page:
    seed: int
    payer_name: str
    payer_ik: str
    patient_name: str
    patient_address: str
    dob: dt.date
    kvnr: str
    bsnr: str
    lanr: str
    issue_date: dt.date
    kind: Literal["erst", "folge"]
    period_from: dt.date
    period_to: dt.date
    icd: str
    measures: list[tuple[str, str, str]]
    """(Maßnahme, Präparat/Angaben, Häufigkeit)"""
    practice_stamp: list[str] | None
    """Stamp lines; None = no stamp on the form."""
    signed: bool = True


def draw_muster12(spec: Muster12Page) -> Page:
    s = Sheet(spec.seed)
    d = s.draw

    # Personalienfeld, printed by the practice software.
    d.rectangle((70, 70, 640, 330), fill=FORM_TINT, outline=FORM_RED, width=2)
    s.field(
        "payer_name",
        (70, 70, 640, 125),
        "Krankenkasse bzw. Kostenträger",
        spec.payer_name,
        printed=True,
    )
    s.field(
        "patient_name",
        (70, 125, 450, 230),
        "Name, Vorname des Versicherten",
        spec.patient_name,
        printed=True,
    )
    s.text((80, 192), spec.patient_address, kind="mono", size=20)
    s.field("patient_dob", (450, 125, 640, 230), "geb. am", de_date(spec.dob), printed=True)
    s.field("payer_ik", (70, 230, 260, 280), "Kostenträgerkennung", spec.payer_ik, printed=True)
    s.field("kvnr", (260, 230, 470, 280), "Versicherten-Nr.", spec.kvnr, printed=True)
    s.field("status", (470, 230, 640, 280), "Status", "1000000", printed=True)
    s.field("bsnr", (70, 280, 260, 330), "Betriebsstätten-Nr.", spec.bsnr, printed=True)
    s.field("lanr", (260, 280, 470, 330), "Arzt-Nr.", spec.lanr, printed=True)
    s.field("issue_date", (470, 280, 640, 330), "Datum", de_date(spec.issue_date), printed=True)

    s.text((700, 78), "Verordnung häuslicher", kind="bold", size=34, fill=FORM_RED)
    s.text((700, 120), "Krankenpflege", kind="bold", size=34, fill=FORM_RED)
    d.rectangle((1080, 70, 1170, 160), outline=FORM_RED, width=3)
    d.text((1125, 115), "12", font=font("bold", 54), fill=FORM_RED, anchor="mm")
    erst = s.checkbox(700, 200, "Erstverordnung", spec.kind == "erst")
    folge = s.checkbox(700, 240, "Folgeverordnung", spec.kind == "folge")
    s.boxes["prescription_kind"] = union(erst, folge)
    s.checkbox(700, 280, "Unfall / Unfallfolgen", False)

    s.text((70, 352), "Verordnungszeitraum", kind="bold", size=20, fill=FORM_RED)
    s.field("period_from", (70, 380, 400, 445), "vom", de_date(spec.period_from), size=32)
    s.field("period_to", (420, 380, 750, 445), "bis", de_date(spec.period_to), size=32)
    s.field(
        "icd_codes",
        (70, 465, 1170, 530),
        "Verordnungsrelevante Diagnose(n) (ICD-10-Code)",
        spec.icd,
    )

    s.text((70, 560), "Behandlungspflege", kind="bold", size=20, fill=FORM_RED)
    cols = (70, 400, 860, 1170)
    for x, label in zip(cols, ("Maßnahme", "Präparat / Angaben", "Häufigkeit"), strict=False):
        s.text((x + 8, 592), label, size=15, fill=FORM_RED)
    for i in range(5):
        y = 615 + i * 62
        d.rectangle((70, y, 1170, y + 62), outline=FORM_RED, width=1)
        for x in cols[1:-1]:
            d.line((x, y, x, y + 62), fill=FORM_RED, width=1)
        if i < len(spec.measures):
            what, details, freq = spec.measures[i]
            s.hand((82, y + 12), what, size=28)
            s.hand((412, y + 12), details, size=28)
            s.hand((872, y + 12), freq, size=28)
            s.boxes[f"measures.{i}"] = (70, y, 1170, y + 62)

    s.text(
        (70, 945),
        "Grundpflege und hauswirtschaftliche Versorgung",
        kind="bold",
        size=20,
        fill=FORM_RED,
    )
    for i in range(2):
        d.rectangle((70, 975 + i * 50, 1170, 1025 + i * 50), outline=FORM_RED, width=1)
    s.field("further_notes", (70, 1095, 1170, 1170), "Weitere Hinweise", None, tint=False)

    stamp_area: PixelBox = (70, 1210, 620, 1440)
    sign_area: PixelBox = (660, 1210, 1170, 1440)
    d.rectangle(stamp_area, outline=FORM_RED, width=2)
    d.rectangle(sign_area, outline=FORM_RED, width=2)
    s.text((78, 1450), "Vertragsarztstempel", size=16, fill=FORM_RED)
    s.text((668, 1450), "Unterschrift des Arztes", size=16, fill=FORM_RED)
    if spec.practice_stamp:
        s.stamp((105, 1250), spec.practice_stamp, angle=s.rng.uniform(-6, 6))
    if spec.signed:
        s.signature((700, 1250, 1130, 1400))
    s.boxes["practice_stamp"] = stamp_area
    s.boxes["doctor_signature"] = sign_area
    s.text((70, 1660), "Muster 12 – nachgebildet für Testzwecke", size=15, fill=FAINT)
    return s.finish()


# --- Leistungsnachweis (SGB V and SGB XI) ----------------------------------------


@dataclass
class VisitLogPage:
    seed: int
    domain: Domain
    provider_name: str
    provider_address: str
    provider_ik: str
    patient_name: str
    kvnr: str
    payer_name: str
    month: str
    reference: tuple[str, str]
    """(label, value): Genehmigungskennzeichen for SGB V, Pflegegrad for SGB XI."""
    nurse: str
    columns: list[tuple[str, str]]
    """(code, label) per service column."""
    cells: dict[tuple[int, int], str]
    """(day, column index) -> what the nurse wrote, e.g. '7:30' or 'x'."""
    initials: dict[int, str]
    """Day -> Handzeichen; a day with entries but no initials is left blank."""
    holidays: frozenset[dt.date]
    patient_signed: bool
    signed_on: dt.date | None = None
    provider_stamp: tuple[str, ...] = ()


ROW_TOP, ROW_H = 430, 30


def draw_visit_log(spec: VisitLogPage) -> Page:
    s = Sheet(spec.seed)
    d = s.draw
    year, mon = (int(p) for p in spec.month.split("-"))

    s.text((70, 62), spec.provider_name, kind="bold", size=30)
    s.text((70, 104), f"{spec.provider_address}  |  IK {spec.provider_ik}", size=18, fill=FAINT)
    title = (
        "Leistungsnachweis Häusliche Krankenpflege (§ 37 SGB V)"
        if spec.domain == "sgbv"
        else "Leistungsnachweis Pflegesachleistung (§ 36 SGB XI)"
    )
    s.text((70, 160), title, kind="bold", size=27)

    rows = (
        (
            ("patient_name", "Versicherte/r", spec.patient_name, 70, 520),
            ("kvnr", "Versicherten-Nr.", spec.kvnr, 530, 800),
            ("month", "Monat", de_month(spec.month), 810, 1170),
        ),
        (
            ("payer_name", "Kasse", spec.payer_name, 70, 520),
            ("reference", spec.reference[0], spec.reference[1], 530, 800),
            ("responsible_nurse", "verantw. Pflegefachkraft", spec.nurse, 810, 1170),
        ),
    )
    for r, row in enumerate(rows):
        y = 215 + r * 62
        for key, label, value, x0, x1 in row:
            s.field(key, (x0, y, x1, y + 56), label, value, printed=True, size=26, tint=False)

    left, right, day_w, init_w = 70, 1170, 104, 130
    svc_left, svc_right = left + day_w, right - init_w
    col_w = (svc_right - svc_left) / len(spec.columns)
    head_top = ROW_TOP - 66
    d.rectangle((left, head_top, right, ROW_TOP), fill=SHADE, outline=RULE)
    s.text((left + 10, head_top + 22), "Tag", kind="bold", size=17)
    for i, (code, label) in enumerate(spec.columns):
        x = svc_left + i * col_w
        d.line((x, head_top, x, ROW_TOP), fill=RULE)
        s.text((x + 8, head_top + 10), label, kind="bold", size=15)
        s.text((x + 8, head_top + 36), code, size=14, fill=FAINT)
    d.line((svc_right, head_top, svc_right, ROW_TOP), fill=RULE)
    s.text((svc_right + 10, head_top + 22), "Handzeichen", kind="bold", size=15)

    day = dt.date(year, mon, 1)
    while day.month == mon:
        n = day.day
        y = ROW_TOP + (n - 1) * ROW_H
        off = day.weekday() >= 5 or day in spec.holidays
        d.rectangle((left, y, right, y + ROW_H), fill=SHADE if off else None, outline=RULE)
        s.text((left + 10, y + 6), f"{WEEKDAYS_DE[day.weekday()]} {n:02d}.", size=16)
        for x in (svc_left + i * col_w for i in range(len(spec.columns) + 1)):
            d.line((x, y, x, y + ROW_H), fill=RULE)
        for i in range(len(spec.columns)):
            if text := spec.cells.get((n, i)):
                s.hand((svc_left + i * col_w + 12, y + 1), text, size=21)
        if initials := spec.initials.get(n):
            s.hand((svc_right + 30, y + 1), initials, size=21)
        s.boxes[f"day.{n:02d}"] = (left, y, right, y + ROW_H)
        s.boxes[f"initials.{n:02d}"] = (svc_right, y, right, y + ROW_H)
        day += dt.timedelta(days=1)

    sig_top = ROW_TOP + 31 * ROW_H + 50
    patient_area: PixelBox = (70, sig_top, 600, sig_top + 120)
    provider_area: PixelBox = (660, sig_top, 1170, sig_top + 120)
    d.rectangle(patient_area, outline=PRINT, width=2)
    d.rectangle(provider_area, outline=PRINT, width=2)
    s.text((70, sig_top - 30), "Die Leistungen wurden wie angegeben erbracht.", size=17)
    s.text((78, sig_top + 128), "Datum, Unterschrift Versicherte/r bzw. Angehörige/r", size=15)
    s.text((668, sig_top + 128), "Unterschrift / Stempel Pflegedienst", size=15)
    if spec.patient_signed and spec.signed_on:
        s.hand(
            (88, sig_top + 40),
            spec.signed_on.strftime("%d.%m.%y"),
            size=26,
            key="patient_signature_date",
        )
        s.signature((260, sig_top + 15, 590, sig_top + 105))
    if spec.provider_stamp:
        s.stamp((680, sig_top + 22), list(spec.provider_stamp), s.rng.uniform(-4, 4), size=17)
    s.signature((960, sig_top + 15, 1160, sig_top + 105))
    s.boxes["patient_signature"] = patient_area
    s.boxes["provider_signature"] = provider_area

    reason_y = sig_top + 170
    s.text((70, reason_y), "Keine Unterschrift möglich, Grund:", size=16)
    boxes = [
        s.checkbox(x, reason_y - 2, label, False)
        for x, label in (
            (340, "1 verstorben"),
            (520, "2 stationär"),
            (690, "3 nicht möglich"),
            (900, "4 sonstiges"),
        )
    ]
    s.boxes["missing_signature_reason"] = _pad(union(*boxes), 4)
    s.text((70, 1690), "Seite 1 von 1", size=15, fill=FAINT)
    return s.finish()


# --- Entlassbrief ----------------------------------------------------------------


@dataclass
class HospitalLetterPage:
    seed: int
    hospital: str
    department: str
    address: str
    location_id: str
    recipient: tuple[str, ...]
    letter_date: dt.date
    patient_name: str
    dob: dt.date
    kvnr: str
    admitted_at: dt.datetime
    discharged_at: dt.datetime
    diagnoses: list[str]
    summary: list[str]
    recommendation: str
    physician: str


def draw_hospital_letter(spec: HospitalLetterPage) -> Page:
    s = Sheet(spec.seed)
    d = s.draw
    s.text((70, 70), spec.hospital, kind="bold", size=36, fill=(20, 70, 110))
    s.text((70, 118), spec.department, size=20, fill=FAINT)
    s.text((70, 146), spec.address, size=18, fill=FAINT)
    s.text((860, 118), f"Standort-Nr. {spec.location_id}", size=18, fill=FAINT)
    d.line((70, 185, 1170, 185), fill=(20, 70, 110), width=3)

    for i, line in enumerate(spec.recipient):
        s.text((70, 240 + i * 30), line, size=22)
    s.text((860, 330), f"Deggendorf, {de_date(spec.letter_date)}", size=20)

    s.text((70, 410), "Entlassbrief", kind="bold", size=34)
    s.text(
        (70, 468),
        f"Patient: {spec.patient_name}, geb. {de_date(spec.dob)}",
        size=22,
        key="patient_name",
    )
    s.text((70, 500), f"Versicherten-Nr.: {spec.kvnr}", size=22, key="kvnr")

    d.rectangle((70, 545, 1170, 655), outline=RULE, width=2)
    adm, dis = spec.admitted_at, spec.discharged_at
    s.text((92, 562), "Stationäre Aufnahme:", kind="bold", size=23)
    s.text((370, 562), f"{de_date(adm.date())}, {adm:%H:%M} Uhr", size=23, key="admission")
    s.text((92, 606), "Entlassung:", kind="bold", size=23)
    s.text((370, 606), f"{de_date(dis.date())}, {dis:%H:%M} Uhr", size=23, key="discharge")

    s.text((70, 690), "Diagnosen", kind="bold", size=23)
    lines = [s.text((92, 728 + i * 32), dx, size=21) for i, dx in enumerate(spec.diagnoses)]
    s.boxes["discharge_diagnoses"] = _pad(union(*lines), 6)

    y = 760 + len(spec.diagnoses) * 32
    s.text((70, y), "Verlauf", kind="bold", size=23)
    for i, line in enumerate(spec.summary):
        s.text((70, y + 38 + i * 31), line, size=21)
    y += 60 + len(spec.summary) * 31
    s.text((70, y), "Empfehlung", kind="bold", size=23)
    s.text((70, y + 38), spec.recommendation, size=21, key="hkp_recommended")

    s.text((70, y + 130), "Mit freundlichen Grüßen", size=21)
    ink = s.signature((70, y + 165, 420, y + 265))
    name = s.text((70, y + 275), spec.physician, size=20)
    s.boxes["physician_signature"] = _pad(union(ink, name), 6)
    return s.finish()


# --- Fax transmission report -----------------------------------------------------


@dataclass
class FaxReportPage:
    seed: int
    sent_at: dt.datetime
    sender: str
    sender_fax: str
    recipient: str
    pages: int
    duration: str
    subject: str


def draw_fax_report(spec: FaxReportPage) -> Page:
    s = Sheet(spec.seed)
    d = s.draw
    d.rectangle((250, 120, 990, 900), fill=(255, 255, 255), outline=RULE)
    s.text((290, 160), "SENDEBERICHT", kind="mono", size=40)
    s.text((290, 214), "Übertragungsprotokoll Fax", kind="mono", size=22, fill=FAINT)
    d.line((290, 262, 950, 262), fill=PRINT, width=2)
    rows = (
        ("sent_at", "Datum/Zeit", f"{spec.sent_at:%d.%m.%Y  %H:%M}"),
        ("sender", "Absender", spec.sender),
        ("sender_fax", "Absender-Nr.", spec.sender_fax),
        ("recipient", "Empfänger", spec.recipient),
        ("pages", "Seiten", str(spec.pages)),
        ("duration", "Dauer", spec.duration),
        ("mode", "Modus", "ECM"),
        ("result", "Ergebnis", "OK"),
    )
    for i, (key, label, value) in enumerate(rows):
        y = 290 + i * 52
        s.text((290, y), label, kind="mono", size=24)
        value_box = s.text((540, y), value, kind="mono", size=24)
        s.boxes[key] = _pad((280, value_box[1], 950, value_box[3]), 8)
    d.line((290, 720, 950, 720), fill=PRINT, width=2)
    s.text((290, 744), "Dokument:", kind="mono", size=22)
    s.text((290, 780), spec.subject, kind="mono", size=22, key="subject")
    return s.finish()


PageSpec = Muster12Page | VisitLogPage | HospitalLetterPage | FaxReportPage


def draw(spec: PageSpec) -> Page:
    match spec:
        case Muster12Page():
            return draw_muster12(spec)
        case VisitLogPage():
            return draw_visit_log(spec)
        case HospitalLetterPage():
            return draw_hospital_letter(spec)
        case FaxReportPage():
            return draw_fax_report(spec)
