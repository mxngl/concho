"""P3.4: Uniformat reference list for cost DB codes.

Two files next to this module:

- ``uniformat.csv``: UNIFORMAT II levels 1-3 from NISTIR 6389 (public domain, source in the
  file header);
- ``uniformat_extensions.csv``: codes beyond that list that a cost DB may use (the course's
  cluster H codes), with our own titles and an ``origin`` column. Not NIST, not copied from
  course data.

A cost DB code is valid when its base code (the part before a ``.``, so ``B2010.CW`` is
checked as ``B2010``) is

- a NIST level-3 code (``B2010``),
- a NIST level-2 code in the course's 4-digit form (``B2000`` = ``B20``, ``F1000`` = ``F10``),
  accepted by rule, or
- listed in the extensions file (``H4000``).
"""

from __future__ import annotations

import csv
import difflib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
UNIFORMAT_CSV = HERE / "uniformat.csv"
EXTENSIONS_CSV = HERE / "uniformat_extensions.csv"

# Letter + 4 digits, optionally followed by a sub-code suffix (".CW", ".PW", ".1").
CODE_PATTERN = r"^[A-Z][0-9]{4}(\.[A-Za-z0-9_-]+)?$"
_CODE_RE = re.compile(CODE_PATTERN)
_LEVEL2_FORM = re.compile(r"^([A-Z][0-9]{2})00$")


@dataclass(frozen=True)
class UniformatEntry:
    code: str
    level: int
    title: str
    origin: str = "nist"  # nist | course | concho


def _read(path: Path, origin: str | None) -> list[UniformatEntry]:
    with path.open(encoding="utf-8", newline="") as f:
        lines = [line for line in f if line.strip() and not line.lstrip().startswith("#")]
    return [
        UniformatEntry(
            code=row["code"].strip(),
            level=int(row["level"]),
            title=row["title"].strip(),
            origin=origin or row["origin"].strip(),
        )
        for row in csv.DictReader(lines)
    ]


@lru_cache(maxsize=1)
def reference() -> dict[str, UniformatEntry]:
    """All reference entries by code: NIST levels 1-3, then the extensions."""
    entries = _read(UNIFORMAT_CSV, "nist") + _read(EXTENSIONS_CSV, None)
    return {e.code: e for e in entries}


def base_code(code: str) -> str:
    """``B2010.CW`` → ``B2010``."""
    return code.split(".", 1)[0]


def is_well_formed(code: str) -> bool:
    return bool(_CODE_RE.match(code))


def lookup(code: str) -> UniformatEntry | None:
    """Reference entry for a cost DB code (sub-codes via their base), or None if unknown.

    Course 4-digit forms of NIST level-2 codes resolve to the level-2 entry (``B2000`` →
    ``B20``). Only level-3 codes, those forms and the extensions are valid cost DB codes;
    bare level-1/2 codes (``B``, ``B20``) are not.
    """
    base = base_code(code)
    if not _CODE_RE.match(base):
        return None
    ref = reference()
    entry = ref.get(base)
    if entry is not None:
        return entry if entry.level == 3 or entry.origin != "nist" else None
    m = _LEVEL2_FORM.match(base)
    if m and m.group(1) in ref and ref[m.group(1)].level == 2:
        return ref[m.group(1)]
    return None


def valid_codes() -> list[str]:
    """Cost DB codes that are valid by themselves (for suggestions), sorted."""
    ref = reference()
    codes = {c for c, e in ref.items() if e.level == 3 or e.origin != "nist"}
    codes |= {f"{c}00" for c, e in ref.items() if e.level == 2 and e.origin == "nist"}
    return sorted(codes)


def suggest(code: str, n: int = 3) -> list[str]:
    """Closest valid codes: same letter, nearest number (then any letter by edit distance)."""
    base = base_code(code).upper()
    candidates = valid_codes()
    same_letter = [c for c in candidates if base[:1] and c[0] == base[0]]
    digits = re.sub(r"\D", "", base[1:5])
    if same_letter and digits:
        num = int(digits.ljust(4, "0"))
        return sorted(same_letter, key=lambda c: (abs(int(c[1:5]) - num), c))[:n]
    return difflib.get_close_matches(base, candidates, n=n, cutoff=0.4)


def group_letter(code: str) -> str:
    """Major group letter of a code (``D5030`` → ``D``)."""
    return code[:1]


def level2(code: str) -> str:
    """Level-2 group of a code (``D5030`` → ``D50``)."""
    return base_code(code)[:3]


def title(code: str) -> str | None:
    entry = lookup(code)
    return entry.title if entry else None
