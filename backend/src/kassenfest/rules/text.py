"""Message template values that render differently in German and English."""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal

Lang = Literal["de", "en"]


class Cents(int):
    """An amount in cents; renders as '1.234,56 €' / '€1,234.56'."""


@dataclass(frozen=True)
class Loc:
    """A value with its own German and English wording."""

    de: str
    en: str


class DateList(list[dt.date]):
    """Dates rendered as compact runs: '15.10.–31.10.2026' / '15–31 Oct 2026'."""


def _date(d: dt.date, lang: Lang) -> str:
    return f"{d:%d.%m.%Y}" if lang == "de" else f"{d.day} {d:%b %Y}"


def _cents(c: int, lang: Lang) -> str:
    sign = "-" if c < 0 else ""
    euros, cents = divmod(abs(c), 100)
    if lang == "de":
        return f"{sign}{euros:,}".replace(",", ".") + f",{cents:02d} €"
    return f"{sign}€{euros:,}.{cents:02d}"


def _run(a: dt.date, b: dt.date, lang: Lang) -> str:
    if a == b:
        return _date(a, lang)
    if lang == "de":
        start = f"{a:%d.%m.}" if a.year == b.year else _date(a, lang)
        return f"{start}–{_date(b, lang)}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{_date(b, lang)}"
    start = f"{a.day} {a:%b}" if a.year == b.year else _date(a, lang)
    return f"{start} – {_date(b, lang)}"


def _dates(days: list[dt.date], lang: Lang) -> str:
    days = sorted(set(days))
    runs: list[tuple[dt.date, dt.date]] = []
    for d in days:
        if runs and d - runs[-1][1] == dt.timedelta(days=1):
            runs[-1] = (runs[-1][0], d)
        else:
            runs.append((d, d))
    return ", ".join(_run(a, b, lang) for a, b in runs)


def fmt(value: Any, lang: Lang) -> str:
    match value:
        case Loc():
            return value.de if lang == "de" else value.en
        case Cents():
            return _cents(value, lang)
        case DateList():
            return _dates(value, lang)
        case dt.datetime():
            return f"{_date(value.date(), lang)} {value:%H:%M}"
        case dt.date():
            return _date(value, lang)
        case dt.time():
            return f"{value:%H:%M}"
        case float():
            return f"{value:g}".replace(".", ",") if lang == "de" else f"{value:g}"
        case list() | tuple():
            return ", ".join(fmt(v, lang) for v in value)
        case None:
            return "–"
    return str(value)


def render(template: str, values: dict[str, Any], lang: Lang) -> str:
    return template.format(**{k: fmt(v, lang) for k, v in values.items()})
