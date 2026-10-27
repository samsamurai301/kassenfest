"""Openly licensed fonts from github.com/google/fonts, vendored into data/fonts/.

Handwriting faces are split into dev and test sets so the frozen test set is
written in hands the prompts were never tuned on (docs/05 §4.2).
"""

import json
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from fontTools.ttLib import TTFont

from kassenfest.config import REPO_ROOT

FONT_DIR = REPO_ROOT / "data" / "fonts"
MANIFEST = FONT_DIR / "fonts.json"
_RAW = "https://raw.githubusercontent.com/google/fonts/main"

# Every German form needs these; a face missing any of them is dropped.
REQUIRED_GLYPHS = "äöüÄÖÜß–0123456789.,:/-"

Role = Literal["print", "mono", "hand_dev", "hand_test", "signature"]

CANDIDATES: list[tuple[str, Role, str, str]] = [
    # family, role, repo dir, font file
    ("Arimo", "print", "ofl/arimo", "Arimo[wght].ttf"),
    ("Courier Prime", "mono", "ofl/courierprime", "CourierPrime-Regular.ttf"),
    ("Caveat", "hand_dev", "ofl/caveat", "Caveat[wght].ttf"),
    ("Kalam", "hand_dev", "ofl/kalam", "Kalam-Regular.ttf"),
    ("Patrick Hand", "hand_dev", "ofl/patrickhand", "PatrickHand-Regular.ttf"),
    ("Indie Flower", "hand_dev", "ofl/indieflower", "IndieFlower-Regular.ttf"),
    ("Gochi Hand", "hand_dev", "ofl/gochihand", "GochiHand-Regular.ttf"),
    ("Shadows Into Light", "hand_dev", "ofl/shadowsintolight", "ShadowsIntoLight.ttf"),
    ("Architects Daughter", "hand_dev", "ofl/architectsdaughter", "ArchitectsDaughter-Regular.ttf"),
    ("Reenie Beanie", "hand_test", "ofl/reeniebeanie", "ReenieBeanie.ttf"),
    ("Covered By Your Grace", "hand_test", "ofl/coveredbyyourgrace", "CoveredByYourGrace.ttf"),
    ("Just Another Hand", "hand_test", "apache/justanotherhand", "JustAnotherHand-Regular.ttf"),
    ("Schoolbell", "hand_test", "apache/schoolbell", "Schoolbell-Regular.ttf"),
    ("Sue Ellen Francisco", "hand_test", "ofl/sueellenfrancisco", "SueEllenFrancisco-Regular.ttf"),
    ("Nothing You Could Do", "hand_test", "ofl/nothingyoucoulddo", "NothingYouCouldDo.ttf"),
    ("Homemade Apple", "signature", "apache/homemadeapple", "HomemadeApple-Regular.ttf"),
    ("Mr Dafoe", "signature", "ofl/mrdafoe", "MrDafoe-Regular.ttf"),
    (
        "Herr Von Muellerhoff",
        "signature",
        "ofl/herrvonmuellerhoff",
        "HerrVonMuellerhoff-Regular.ttf",
    ),
    ("La Belle Aurore", "signature", "ofl/labelleaurore", "LaBelleAurore.ttf"),
]


@dataclass(frozen=True)
class FontFace:
    family: str
    role: Role
    path: str  # relative to FONT_DIR
    license: str

    @property
    def file(self) -> Path:
        return FONT_DIR / self.path


def missing_glyphs(path: Path) -> str:
    cmap = TTFont(path).getBestCmap()
    return "".join(ch for ch in REQUIRED_GLYPHS if ord(ch) not in cmap)


def fetch_fonts() -> list[FontFace]:
    """Download candidates, keep those with full German coverage, write the manifest."""
    kept: list[FontFace] = []
    for family, role, repo_dir, filename in CANDIDATES:
        target_dir = FONT_DIR / repo_dir.split("/", 1)[1]
        target_dir.mkdir(parents=True, exist_ok=True)
        license_name = "OFL.txt" if repo_dir.startswith("ofl/") else "LICENSE.txt"
        for name in (filename, license_name):
            dest = target_dir / name
            if not dest.exists():
                urllib.request.urlretrieve(f"{_RAW}/{repo_dir}/{name}", dest)
        font_path = target_dir / filename
        if missing := missing_glyphs(font_path):
            print(f"drop {family}: missing {missing!r}")
            font_path.unlink()
            continue
        kept.append(
            FontFace(
                family=family,
                role=role,
                path=str(font_path.relative_to(FONT_DIR)),
                license=license_name.removesuffix(".txt"),
            )
        )
    MANIFEST.write_text(json.dumps([asdict(f) for f in kept], indent=1) + "\n")
    return kept


def load_fonts(role: Role | None = None) -> list[FontFace]:
    faces = [FontFace(**f) for f in json.loads(MANIFEST.read_text())]
    return [f for f in faces if role is None or f.role == role]
