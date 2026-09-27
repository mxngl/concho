"""Named prefab envelope assemblies, shared by the three Manufacton steps (P3B.8 fix 5).

The original hardcoded three Island assemblies (``SL1-3R``, ``SL1-2R``, ``SL0W-LNEG1C``) in
``parts_import.ASSEMBLIES`` and ``assembly_import.ASSEMBLIES`` and emitted them for every
project. They now come from a CSV (``--prefab-assemblies``; Island example:
``engines/schedule/examples/island/prefab_assemblies.csv``, team configuration, not course
data) with one row per assembly:

``assembly_id, assembly_name, assembly_description, part_name``

- ``assembly_id``: Manufacton assembly id, the one the 4D mapping CSV assigns to walls
  (``manufacton-orders --mapping``), e.g. ``SL1-3R-WALL``;
- ``assembly_name`` / ``assembly_description``: assembly ``Name`` / ``Description`` in
  ``Assembly_Import.xlsx``;
- ``part_name``: name stem of its four parts in ``Parts_Import.xlsx``.

The part ids are ``<part prefix>-<part code>`` with part prefix = ``assembly_id`` without a
trailing ``-WALL`` (the rule ``parts_import.envelope_part_id`` already applies to the
elements of the Revit assembly id map) and part codes ``WALL``, ``MULLION-L``,
``MULLION-B``, ``GLAZED-PANEL``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

COLUMNS = ["assembly_id", "assembly_name", "assembly_description", "part_name"]


def part_prefix(assembly_id: str) -> str:
    return assembly_id.removesuffix("-WALL")


def load_prefab_assemblies(path: Path | None) -> list[dict[str, str]]:
    """Rows of the prefab assembly CSV in file order (empty list without a path)."""
    if path is None:
        return []
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [column for column in COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}; expected {COLUMNS}")
    frame = frame[COLUMNS].apply(lambda column: column.str.strip())
    frame = frame[frame["assembly_id"] != ""]
    duplicated = sorted(set(frame.loc[frame["assembly_id"].duplicated(), "assembly_id"]))
    if duplicated:
        raise ValueError(f"{path}: assembly ids listed twice: {duplicated}")
    empty = frame[(frame[COLUMNS[1:]] == "").any(axis=1)]
    if not empty.empty:
        raise ValueError(f"{path}: empty name/description/part name for {list(empty['assembly_id'])}")
    records = frame.to_dict("records")
    for record in records:
        record["part_prefix"] = part_prefix(record["assembly_id"])
    return records
