"""P3.9 (decision D15): one rule for elements in several exports and for Revit Parts.

Used by TVD (``engines/tvd/engine.py``) and STV (``engines/stv/cli.py``) before anything is
counted. Input: the rows of every export of one run, each export with its discipline
(``architecture`` / ``structural`` / ``mep``). Output: the rows to count and a report of the
dropped rows (the ``deduplication`` block of both results JSONs).

Rule 1, Parts: count Parts, never a Part and its host together. A row whose ElementId is the
``Part Source Id`` of some Part row (same or another export) is dropped (``host_of_parts``);
its Parts are kept. The Revit add-in (since concho #18) already skips a floor/ceiling with
Parts inside one export, so this only acts across exports. Old exports have no
``Part Source Id`` column: nothing happens there.

Rule 2, one row per ElementId: rows with the same ElementId (after rule 1) are reduced to one
by these steps, in order; the first step that decides is the reason of each dropped row:

a. a row with an Assembly Code wins over one without (``duplicate_without_code``);
b. STV only (``is_mapped`` given): a row the STV mapping can map wins over an unmapped one
   (``duplicate_unmapped``). TVD prices by code and skips this step;
c. the export whose discipline owns the category wins (``duplicate_other_discipline``), see
   :func:`owner_discipline`;
d. still more than one (e.g. two exports of the same discipline): the first in input order
   wins (``duplicate_same_discipline``).

ElementIds are unique only inside one Revit model. Exports of different models (e.g. the
architecture and the structural model) could share an ElementId by chance; the rule would
treat them as one element. The Island exports have no such case (docs/engines/stv.md).

The report holds ElementIds, categories, export names and disciplines only, no quantities.
Team-neutral engine logic, not course data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

ARCHITECTURE, STRUCTURAL, MEP = "architecture", "structural", "mep"
DISCIPLINES = (ARCHITECTURE, STRUCTURAL, MEP)
PARTS = "parts"

# Owner discipline per Revit category (English names, lower case; see
# docs/model-requirements.md "Categories"). Every category not listed is architectural.
# Structural: the categories named in D15. Parts count with their ``Original Category``.
STRUCTURAL_CATEGORIES = frozenset({
    "floors", "structural framing", "structural columns", "structural foundations",
})
# MEP: the categories the add-in's MEP export writes (plumbing fixtures included, which the
# architecture export also writes), plus the Revit MEP categories it may write in future.
MEP_CATEGORIES = frozenset({
    "air terminals", "cable tray fittings", "cable trays", "communication devices",
    "conduit fittings", "conduits", "data devices", "duct accessories", "duct fittings",
    "duct insulations", "duct linings", "ducts", "electrical equipment",
    "electrical fixtures", "fire alarm devices", "flex ducts", "flex pipes",
    "lighting devices", "lighting fixtures", "mechanical equipment", "pipe accessories",
    "pipe fittings", "pipe insulations", "pipes", "plumbing equipment", "plumbing fixtures",
    "security devices", "sprinklers",
})

HOST_OF_PARTS = "host_of_parts"
WITHOUT_CODE = "duplicate_without_code"
UNMAPPED = "duplicate_unmapped"
OTHER_DISCIPLINE = "duplicate_other_discipline"
SAME_DISCIPLINE = "duplicate_same_discipline"
REASONS = (HOST_OF_PARTS, WITHOUT_CODE, UNMAPPED, OTHER_DISCIPLINE, SAME_DISCIPLINE)

Row = Mapping[str, Any]


def _get(row: Row, name: str) -> str:
    return str(row.get(name) or "").strip()


def is_part(row: Row) -> bool:
    return _get(row, "Category").lower() == PARTS


def effective_category(row: Row) -> str:
    """The category that decides ownership and mapping: a Part's ``Original Category``
    (``Parts`` if that is empty, as in the old exports), else ``Category``."""
    category = _get(row, "Category")
    if category.lower() == PARTS:
        return _get(row, "Original Category") or category
    return category


def owner_discipline(category: str) -> str:
    """Discipline whose export counts an element of ``category`` when all else is equal."""
    name = category.strip().lower()
    if name in STRUCTURAL_CATEGORIES:
        return STRUCTURAL
    if name in MEP_CATEGORIES:
        return MEP
    return ARCHITECTURE


@dataclass(frozen=True)
class Export:
    """One export of a run: ``label`` names it in the report (file name, no local path)."""

    label: str
    discipline: str
    rows: list[Any]


@dataclass(frozen=True)
class Occurrence:
    export: Export
    index: int  # row position in the export
    order: int  # position over all exports (input order)

    @property
    def row(self) -> Any:
        return self.export.rows[self.index]


@dataclass(frozen=True)
class Dropped:
    element_id: str
    category: str
    kept_export: str
    kept_discipline: str
    dropped_export: str
    dropped_discipline: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "element_id": self.element_id,
            "category": self.category,
            "kept_export": self.kept_export,
            "kept_discipline": self.kept_discipline,
            "dropped_export": self.dropped_export,
            "dropped_discipline": self.dropped_discipline,
            "reason": self.reason,
        }


@dataclass
class DedupResult:
    """``kept[i]``: the rows of ``exports[i]`` to count, in their original order."""

    exports: list[Export]
    kept: list[list[Any]]
    dropped: list[Dropped] = field(default_factory=list)
    mapping_aware: bool = False
    parts: dict[str, int] = field(default_factory=dict)

    @property
    def kept_rows(self) -> list[Any]:
        return [row for rows in self.kept for row in rows]

    def counts(self) -> dict[str, int]:
        found = Counter(d.reason for d in self.dropped)
        reasons = REASONS if self.mapping_aware else tuple(r for r in REASONS if r != UNMAPPED)
        return {reason: found[reason] for reason in reasons}

    def block(self) -> dict[str, Any]:
        """The ``deduplication`` block of the results JSON (docs/model-requirements.md)."""
        rows_in = sum(len(e.rows) for e in self.exports)
        return {
            "rule": "D15 (docs/decisions.md): Parts over their host; per ElementId, with "
                    "Assembly Code > "
                    + ("mapped by the STV mapping > " if self.mapping_aware else "")
                    + "export of the owning discipline > first export",
            "exports": [{"export": e.label, "discipline": e.discipline, "rows": len(e.rows)}
                        for e in self.exports],
            "rows_in": rows_in,
            "rows_kept": rows_in - len(self.dropped),
            "dropped": len(self.dropped),
            "by_reason": self.counts(),
            "parts": dict(self.parts),
            "dropped_rows": [d.to_dict() for d in self.dropped],
        }


def _row_of(item: Any) -> Row:
    """Rows are dicts (TVD) or objects with a ``row`` dict (STV mapping elements)."""
    return item if isinstance(item, Mapping) else item.row


def deduplicate(
    exports: list[Export],
    *,
    is_mapped: Callable[[Any, str], bool] | None = None,
) -> DedupResult:
    """Apply rules 1 and 2 to ``exports``.

    ``is_mapped(item, discipline)`` (STV) says whether the STV mapping maps a row of that
    discipline; without it step b is skipped (TVD). Rows without an ElementId are kept.
    """
    occurrences: list[Occurrence] = []
    for export in exports:
        for index in range(len(export.rows)):
            occurrences.append(Occurrence(export, index, len(occurrences)))
    dropped_at: set[int] = set()
    dropped: list[Dropped] = []

    def drop(occ: Occurrence, kept: Occurrence, reason: str) -> None:
        dropped_at.add(occ.order)
        row = _row_of(occ.row)
        dropped.append(Dropped(
            element_id=_get(row, "ElementId"), category=effective_category(row),
            kept_export=kept.export.label, kept_discipline=kept.export.discipline,
            dropped_export=occ.export.label, dropped_discipline=occ.export.discipline,
            reason=reason,
        ))

    # Rule 1: hosts of Parts.
    first_part: dict[str, Occurrence] = {}
    n_parts = n_with_source = 0
    for occ in occurrences:
        row = _row_of(occ.row)
        if not is_part(row):
            continue
        n_parts += 1
        source = _get(row, "Part Source Id")
        if source:
            n_with_source += 1
            first_part.setdefault(source, occ)
    for occ in occurrences:
        row = _row_of(occ.row)
        element_id = _get(row, "ElementId")
        if element_id in first_part and not is_part(row):
            drop(occ, first_part[element_id], HOST_OF_PARTS)

    # Rule 2: one row per ElementId.
    by_id: dict[str, list[Occurrence]] = defaultdict(list)
    for occ in occurrences:
        element_id = _get(_row_of(occ.row), "ElementId")
        if element_id and occ.order not in dropped_at:
            by_id[element_id].append(occ)
    for group in by_id.values():
        if len(group) < 2:
            continue
        steps: list[tuple[str, Callable[[Occurrence], bool]]] = [
            (WITHOUT_CODE, lambda o: bool(_get(_row_of(o.row), "Assembly Code"))),
        ]
        if is_mapped is not None:
            steps.append((UNMAPPED, lambda o: is_mapped(o.row, o.export.discipline)))
        steps.append((OTHER_DISCIPLINE, lambda o: o.export.discipline == owner_discipline(
            effective_category(_row_of(o.row)))))
        losers: list[tuple[Occurrence, str]] = []
        for reason, wins in steps:
            better = [o for o in group if wins(o)]
            if better and len(better) < len(group):
                losers += [(o, reason) for o in group if o not in better]
                group = better
        winner = group[0]
        losers += [(o, SAME_DISCIPLINE) for o in group[1:]]
        for occ, reason in sorted(losers, key=lambda x: x[0].order):
            drop(occ, winner, reason)

    kept = [[row for index, row in enumerate(export.rows)
             if (base + index) not in dropped_at]
            for export, base in zip(exports, _bases(exports), strict=True)]
    return DedupResult(
        exports=list(exports), kept=kept,
        dropped=sorted(dropped, key=lambda d: (REASONS.index(d.reason), len(d.element_id),
                                               d.element_id, d.dropped_export)),
        mapping_aware=is_mapped is not None,
        parts={"rows": n_parts, "with_part_source_id": n_with_source,
               "hosts": len(first_part)},
    )


def _bases(exports: list[Export]) -> list[int]:
    out, base = [], 0
    for export in exports:
        out.append(base)
        base += len(export.rows)
    return out
