"""Markup helpers templates call to put ink on the form, all seeded and reproducible."""

import random
from dataclasses import dataclass, field

from markupsafe import Markup, escape

INKS = {"blue": "#1f3a93", "black": "#1b1b1f", "royal": "#2643c4"}
STAMP_INKS = ["#5b3fa8", "#3d4fb0", "#6a3a9c"]


def _attrs(**attrs: str | None) -> str:
    return "".join(f' {k.replace("_", "-")}="{escape(v)}"' for k, v in attrs.items() if v)


@dataclass
class Hand:
    """One writer: font, ink, size and how shaky their letters are."""

    family: str
    ink: str
    size_pt: float
    rng: random.Random
    jitter: float = 1.0
    tilt: float = field(default=0.0)

    def write(self, text: str | None, field: str | None = None, min_mm: float = 18) -> Markup:
        if not text:
            return Markup(
                f'<span class="hw empty"{_attrs(data_field=field)} '
                f'style="min-width:{min_mm}mm"></span>'
            )
        rng, j = self.rng, self.jitter
        glyphs = []
        for ch in text:
            if ch == " ":
                glyphs.append('<span class="g sp"> </span>')
                continue
            dy, rot = rng.gauss(0, 0.7 * j), rng.gauss(0, 2.8 * j)
            scale = 1 + rng.gauss(0, 0.045 * j)
            glyphs.append(
                f'<span class="g" style="transform:translateY({dy:.2f}px) '
                f'rotate({rot:.1f}deg) scale({scale:.3f})">{escape(ch)}</span>'
            )
        tilt = self.tilt + rng.gauss(0, 0.8 * j)
        style = (
            f"font-family:'{self.family}';color:{self.ink};font-size:{self.size_pt:.1f}pt;"
            f"transform:rotate({tilt:.2f}deg)"
        )
        return Markup(
            f'<span class="hw"{_attrs(data_field=field)} style="{style}">{"".join(glyphs)}</span>'
        )

    def tick(self, checked: bool, field: str | None = None) -> Markup:
        """A checkbox, crossed by hand when checked."""
        mark = self.write("X") if checked else ""
        return Markup(f'<span class="cb"{_attrs(data_field=field)}>{mark}</span>')


def printed(text: str | None, field: str | None = None, min_mm: float = 18) -> Markup:
    """Practice-software print (monospace) into a form field."""
    if not text:
        return Markup(
            f'<span class="pr empty"{_attrs(data_field=field)} style="min-width:{min_mm}mm"></span>'
        )
    return Markup(f'<span class="pr"{_attrs(data_field=field)}>{escape(text)}</span>')


def printed_tick(checked: bool, field: str | None = None) -> Markup:
    return Markup(f'<span class="cb"{_attrs(data_field=field)}>{"X" if checked else ""}</span>')


def scribble_path(rng: random.Random, width: float, height: float) -> str:
    """Procedural signature: a chain of cubic Béziers drifting left to right."""
    x, y = width * 0.04, height * rng.uniform(0.45, 0.7)
    parts = [f"M{x:.1f},{y:.1f}"]
    strokes = rng.randint(4, 7)
    step = width * 0.9 / strokes
    for _ in range(strokes):
        c1 = (x + step * rng.uniform(0.1, 0.6), height * rng.uniform(0.05, 0.95))
        c2 = (x + step * rng.uniform(0.4, 1.1), height * rng.uniform(0.05, 0.95))
        x = min(x + step * rng.uniform(0.7, 1.15), width * 0.97)
        y = height * rng.uniform(0.25, 0.8)
        parts.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {x:.1f},{y:.1f}")
    if rng.random() < 0.6:  # underline flourish
        y = height * rng.uniform(0.8, 0.92)
        parts.append(
            f"M{width * 0.08:.1f},{y:.1f} Q{width * 0.5:.1f},{y + 4:.1f} {x:.1f},{y - 3:.1f}"
        )
    return " ".join(parts)


def signature(
    present: bool,
    region: str,
    rng: random.Random,
    *,
    ink: str = INKS["blue"],
    name: str | None = None,
    font: str | None = None,
    width_mm: float = 55,
    height_mm: float = 16,
) -> Markup:
    """Signature field: procedural scribble, or the name in a signature font."""
    if not present:
        return Markup(f'<div class="sig"{_attrs(data_region=region)}></div>')
    if font and name:
        rot = rng.gauss(-3, 2)
        mark = (
            f'<span class="sigfont"{_attrs(data_ink=region)} style="font-family:\'{font}\';'
            f'color:{ink};transform:rotate({rot:.1f}deg)">{escape(name)}</span>'
        )
    else:
        w, h = width_mm * 4, height_mm * 4  # SVG user units, 4 per mm
        stroke = rng.uniform(1.6, 2.6)
        mark = (
            f'<svg class="sigsvg"{_attrs(data_ink=region)} viewBox="0 0 {w:.0f} {h:.0f}" '
            f'preserveAspectRatio="none"><path d="{scribble_path(rng, w, h)}" fill="none" '
            f'stroke="{ink}" stroke-width="{stroke:.2f}" stroke-linecap="round" '
            f'stroke-linejoin="round"/></svg>'
        )
    return Markup(f'<div class="sig"{_attrs(data_region=region)}>{mark}</div>')


def stamp(present: bool, region: str, lines: list[str], rng: random.Random) -> Markup:
    """Practice stamp: violet/blue ink, rotated, speckled by an SVG turbulence filter."""
    if not present:
        return Markup(f'<div class="stampbox"{_attrs(data_region=region)}></div>')
    ink = rng.choice(STAMP_INKS)
    seed = rng.randint(1, 9999)
    rot = rng.uniform(-8, 8)
    dx, dy = rng.uniform(-3, 3), rng.uniform(-2, 2)
    w, h = 240, 34 + 22 * len(lines)
    texts = "".join(
        f'<text x="{w / 2}" y="{30 + i * 22}" text-anchor="middle" '
        f'font-size="{18 if i == 0 else 15}" font-weight="{700 if i == 0 else 400}">'
        f"{escape(line)}</text>"
        for i, line in enumerate(lines)
    )
    svg = (
        f'<svg class="stampsvg"{_attrs(data_ink=region)} viewBox="0 0 {w} {h}" '
        f'style="transform:translate({dx:.1f}mm,{dy:.1f}mm) rotate({rot:.1f}deg)">'
        f'<defs><filter id="ink{seed}"><feTurbulence type="fractalNoise" baseFrequency="0.9" '
        f'numOctaves="2" seed="{seed}" result="n"/><feColorMatrix in="n" type="matrix" '
        f'values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -2.2 1.6" result="mask"/>'
        f'<feComposite in="SourceGraphic" in2="mask" operator="in"/></filter></defs>'
        f'<g filter="url(#ink{seed})" fill="{ink}" stroke="{ink}" font-family="Arimo">'
        f'<rect x="3" y="3" width="{w - 6}" height="{h - 6}" fill="none" '
        f'stroke-width="2.5" rx="4"/>'
        f'<g stroke="none">{texts}</g></g></svg>'
    )
    return Markup(f'<div class="stampbox"{_attrs(data_region=region)}>{svg}</div>')
