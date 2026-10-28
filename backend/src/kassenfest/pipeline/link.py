"""Which patient a document belongs to, by the Pflegedienst's own records.

The KVNR decides when it matches the records exactly. Otherwise name (and birth date,
where the form has one) must match exactly one patient: doctors and Kassen print the
KVNR from the insurance card, which can differ from what the Pflegedienst typed in.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from kassenfest.schemas.common import Extracted
from kassenfest.schemas.domain import Patient
from kassenfest.schemas.records import MasterData

_TITLES = re.compile(r"\b(frau|herr|hr|fr|dr|med|prof)\b\.?", re.IGNORECASE)
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


@dataclass
class Link:
    patient_id: str | None
    method: Literal["kvnr", "name_dob", "name"] | None
    issues: list[str] = field(default_factory=list)


def value(doc: BaseModel, name: str) -> Any:
    """A field's value if it was read, else None."""
    got = getattr(doc, name, None)
    if isinstance(got, Extracted) and got.status == "present":
        return got.value
    return None


def _letters(text: str) -> str:
    return " ".join(re.findall(r"[a-z]+", text))


def name_key(name: str) -> tuple[str, str]:
    """'Albers, Erika', 'Erika Albers' and 'Frau Erika Albers' → ('albers', 'erika')."""
    text = _TITLES.sub(" ", name).casefold().translate(_FOLD)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    if "," in text:
        last, first = text.split(",", 1)
    else:
        *firsts, last = text.split() or [""]
        first = " ".join(firsts)
    return _letters(last), _letters(first)


def _same_name(written: str, patient: Patient) -> bool:
    last, first = name_key(written)
    p_last, p_first = name_key(patient.name)
    return last == p_last and (not first or first == p_first)


def link(doc: BaseModel, records: MasterData) -> Link:
    kvnr, name, dob = value(doc, "kvnr"), value(doc, "patient_name"), value(doc, "patient_dob")
    for patient in records.patients:
        if kvnr and kvnr == patient.kvnr:
            return Link(patient.id, "kvnr")

    matches = [p for p in records.patients if name and _same_name(name, p)]
    method: Literal["name_dob", "name"] = "name"
    if dob and (with_dob := [p for p in matches if p.dob.isoformat() == dob]):
        matches, method = with_dob, "name_dob"
    if len(matches) != 1:
        what = f"name {name!r}" if name else "no readable name"
        found = "several patients" if matches else "no patient"
        return Link(None, None, [f"{what}, KVNR {kvnr or 'unreadable'}: {found} in the records"])
    patient = matches[0]
    issues = []
    if kvnr:
        issues.append(f"KVNR {kvnr} on the document, {patient.kvnr} in the records")
    return Link(patient.id, method, issues)
