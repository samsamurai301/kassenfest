"""Deterministic clean-up of an extraction before anything downstream trusts it.

Formats are normalized in place (dates, billing month, times) and every problem is
recorded as an issue instead of being silently fixed or dropped. Which fields are
dates or months is read from the schema's own field descriptions, so the rules
here cannot drift from the contract.
"""

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from kassenfest.schemas.common import Extracted
from kassenfest.schemas.extraction import ISO_DATE, ISO_MONTH

_FORMATS = {
    "kvnr": re.compile(r"[A-Z]\d{9}"),
    "payer_ik": re.compile(r"\d{9}"),
    "provider_ik": re.compile(r"\d{9}"),
    "bsnr": re.compile(r"\d{9}"),
    "lanr": re.compile(r"\d{9}"),
}


def parse_date(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def parse_month(text: str) -> str | None:
    text = text.strip()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", text):
        year, month = int(m[1]), int(m[2])
    elif m := re.fullmatch(r"(\d{1,2})[/.](\d{4})", text):
        year, month = int(m[2]), int(m[1])
    else:
        return None
    return f"{year}-{month:02d}" if 1 <= month <= 12 else None


def parse_time(text: str) -> str | None:
    if m := re.fullmatch(r"(\d{1,2})[:.](\d{2})", text.strip()):
        hour, minute = int(m[1]), int(m[2])
        if hour < 24 and minute < 60:
            return f"{hour:02d}:{minute:02d}"
    return None


def _kind(description: str | None) -> str | None:
    d = description or ""
    if ISO_DATE in d:
        return "date"
    if ISO_MONTH in d:
        return "month"
    if d.startswith("HH:MM"):
        return "time"
    return None


def _clean(value: str, kind: str) -> str | None:
    if kind == "date":
        parsed = parse_date(value)
        return parsed.isoformat() if parsed else None
    if kind == "month":
        return parse_month(value)
    return parse_time(value)


def validate(doc: BaseModel) -> list[str]:
    """Normalize `doc` in place; return human-readable issues (empty = clean)."""
    issues: list[str] = []
    _walk(doc, "", issues)
    _check_order(doc, issues)
    return issues


def _walk(obj: BaseModel, path: str, issues: list[str]) -> None:
    for name, info in type(obj).model_fields.items():
        value = getattr(obj, name)
        here = f"{path}.{name}" if path else name
        kind = _kind(info.description)
        if isinstance(value, Extracted):
            raw = value.value
            if kind and isinstance(raw, str):
                cleaned = _clean(raw, kind)
                if cleaned is None:
                    issues.append(f"{here}: unparseable {kind} {raw!r}")
                    value.value, value.status = None, "unreadable"
                else:
                    value.value = cleaned
            if name in _FORMATS and isinstance(raw, str):
                compact = raw.replace(" ", "").upper()
                value.value = compact
                if not _FORMATS[name].fullmatch(compact):
                    issues.append(f"{here}: unexpected format {raw!r}")
        elif isinstance(value, str) and kind:
            cleaned = _clean(value, kind)
            if cleaned is None:
                issues.append(f"{here}: unparseable {kind} {value!r}")
            else:
                setattr(obj, name, cleaned)
        elif isinstance(value, BaseModel):
            _walk(value, here, issues)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, BaseModel):
                    _walk(item, f"{here}[{i}]", issues)


def _value(doc: BaseModel, name: str) -> Any:
    field = getattr(doc, name, None)
    return field.value if isinstance(field, Extracted) else None


def _check_order(doc: BaseModel, issues: list[str]) -> None:
    start, end = _value(doc, "period_from"), _value(doc, "period_to")
    if isinstance(start, str) and isinstance(end, str) and end < start:
        issues.append(f"period_to {end} is before period_from {start}")
    admitted, discharged = _value(doc, "admission_date"), _value(doc, "discharge_date")
    if isinstance(admitted, str) and isinstance(discharged, str) and discharged < admitted:
        issues.append(f"discharge_date {discharged} is before admission_date {admitted}")
