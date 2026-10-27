"""Loads the versioned reference tables in data/reference/ (payers, tariffs, SGB XI amounts)."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import BaseModel

from kassenfest.config import REPO_ROOT
from kassenfest.schemas.domain import Payer

REFERENCE_DIR = REPO_ROOT / "data" / "reference"


class Dated(Protocol):
    valid_from: dt.date

    @property
    def valid_to(self) -> dt.date | None: ...


def valid_on[T: Dated](versions: Sequence[T], day: dt.date) -> T | None:
    """The version with the latest valid_from <= day that hasn't expired by `day`."""
    live = [
        v for v in versions if v.valid_from <= day and (v.valid_to is None or day <= v.valid_to)
    ]
    return max(live, key=lambda v: v.valid_from, default=None)


class Kasse(BaseModel):
    name: str
    short: str
    krankenkasse_ik: str
    pflegekasse_ik: str
    fax: str
    payment_term_days: int = 21


class HkpPosition(BaseModel):
    label_de: str
    label_en: str
    category: str | None
    ancillary: bool = False


class PriceList(BaseModel):
    version: str
    valid_from: dt.date
    valid_to: dt.date | None = None
    prices_cents: dict[str, int]


class Leistungskomplex(BaseModel):
    label_de: str
    label_en: str
    points: int


class Punktwert(BaseModel):
    version: str
    valid_from: dt.date
    valid_to: dt.date | None = None
    punktwert_eur: Decimal


class SgbxiAmounts(BaseModel):
    version: str
    valid_from: dt.date
    valid_to: dt.date | None = None
    draft: bool = False
    label: str | None = None
    sources: list[str] = []
    sachleistung_36_cents: dict[int, int]
    pflegegeld_37_cents: dict[int, int]
    entlastungsbetrag_45b_cents: int
    entlastung_carryover_until: str | None = None
    umwandlung_45a_max_share: Decimal
    gemeinsamer_jahresbetrag_cents: int | None = None
    pflegegeld_during_stay_weeks: int


@dataclass(frozen=True)
class Reference:
    kassen: list[Kasse]
    hkp_positions: dict[str, HkpPosition]
    hkp_tariffs: list[PriceList]
    leistungskomplexe: dict[str, Leistungskomplex]
    punktwerte: list[Punktwert]
    sgbxi_amounts: list[SgbxiAmounts]

    def amounts_on(self, day: dt.date, version: str | None = None) -> SgbxiAmounts:
        """Statutory amounts for `day`; drafts only when named explicitly."""
        if version is not None:
            return next(a for a in self.sgbxi_amounts if a.version == version)
        found = valid_on([a for a in self.sgbxi_amounts if not a.draft], day)
        if found is None:
            raise LookupError(f"no SGB XI amounts valid on {day}")
        return found

    def payers(self) -> dict[str, Payer]:
        """Every Kasse twice: as Krankenkasse and as Pflegekasse, keyed by IK."""
        out: dict[str, Payer] = {}
        for k in self.kassen:
            for ik, kind in (
                (k.krankenkasse_ik, "krankenkasse"),
                (k.pflegekasse_ik, "pflegekasse"),
            ):
                out[ik] = Payer(
                    name=k.name, ik=ik, kind=kind, payment_term_days=k.payment_term_days
                )
        return out


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache
def load_reference(directory: Path = REFERENCE_DIR) -> Reference:
    payers = _read(directory / "payers.yaml")
    hkp = _read(directory / "hkp_services.yaml")
    lk = _read(directory / "sgbxi_lk_bayern.yaml")
    amounts = _read(directory / "sgbxi_amounts.yaml")
    return Reference(
        kassen=[Kasse.model_validate(k) for k in payers["kassen"]],
        hkp_positions={k: HkpPosition.model_validate(v) for k, v in hkp["positions"].items()},
        hkp_tariffs=[PriceList.model_validate(t) for t in hkp["tariffs"]],
        leistungskomplexe={
            k: Leistungskomplex.model_validate(v) for k, v in lk["leistungskomplexe"].items()
        },
        punktwerte=[Punktwert.model_validate(p) for p in lk["punktwerte"]],
        sgbxi_amounts=[SgbxiAmounts.model_validate(a) for a in amounts["versions"]],
    )
