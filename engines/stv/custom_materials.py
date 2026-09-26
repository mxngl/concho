"""Custom materials CSV (``stv.custom_materials_file``): load and validate only.

P3.2 checks the file named in ``project_config``; the engine does not use custom materials
in the calculation yet (roadmap P3.7). The columns follow the course ``LCA Data`` sheet
(assembly, material type, total / materials / transport / construction impacts, unit
multiplier) plus ``source`` (EPD reference) and ``is_course_data`` (must be false). The
column names are provisional until P3.7.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .models import IMPACT_KEYS, ImpactVector
from .reference import ASSEMBLY_ALIASES, ASSEMBLY_COLUMN_MAP, MaterialRecord

PHASES = ("total", "materials", "transport", "construction")
IMPACT_COLUMNS = [f"{phase}_{key}" for phase in PHASES for key in IMPACT_KEYS]
REQUIRED_COLUMNS = [
    "assembly",
    "material_type",
    *IMPACT_COLUMNS,
    "unit_multiplier",
    "source",
    "is_course_data",
]
KNOWN_ASSEMBLIES = set(ASSEMBLY_COLUMN_MAP) | set(ASSEMBLY_ALIASES.values())
_FALSE = {"false", "0", "no"}

# Relative tolerance for total = materials + transport + construction.
SUM_TOLERANCE = 1e-6


class CustomMaterialsError(ValueError):
    def __init__(self, path: Path | str, errors: list[str]):
        self.errors = errors
        super().__init__(
            f"invalid custom materials file {path}:\n" + "\n".join(f"  - {e}" for e in errors)
        )


@dataclass
class CustomMaterials:
    path: Path
    records: list[MaterialRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _vector(phase: str, values: dict[str, float]) -> ImpactVector:
    return ImpactVector(**{key: values[f"{phase}_{key}"] for key in IMPACT_KEYS})


def load_custom_materials(path: Path | str) -> CustomMaterials:
    """Read and validate a custom materials CSV; raise :class:`CustomMaterialsError`."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = [h.strip() for h in reader.fieldnames or []]
            rows = [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in reader]
    except OSError as exc:
        raise CustomMaterialsError(path, [f"cannot read file ({exc.strerror})"]) from exc

    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise CustomMaterialsError(path, [f"missing columns: {', '.join(missing)}"])

    result = CustomMaterials(path=path)
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for line, row in enumerate(rows, start=2):
        if not any(row.values()):
            continue
        where = f"line {line}"
        assembly, material_type = row["assembly"], row["material_type"]
        if assembly not in KNOWN_ASSEMBLIES:
            errors.append(
                f"{where}: unknown assembly '{assembly}' "
                f"(expected one of: {', '.join(sorted(KNOWN_ASSEMBLIES))})"
            )
        if not material_type:
            errors.append(f"{where}: material_type is empty")
        key = (assembly, material_type)
        if key in seen:
            errors.append(f"{where}: duplicate material {assembly} / {material_type}")
        seen.add(key)
        if not row["source"]:
            errors.append(f"{where}: source is empty (give the EPD reference)")
        if row["is_course_data"].lower() not in _FALSE:
            errors.append(f"{where}: is_course_data must be false (custom materials are "
                          "team data)")

        values: dict[str, float] = {}
        for column in [*IMPACT_COLUMNS, "unit_multiplier"]:
            try:
                values[column] = float(row[column])
            except ValueError:
                errors.append(f"{where}: {column} is not a plain number: '{row[column]}'")
        if len(values) != len(IMPACT_COLUMNS) + 1:
            continue

        record = MaterialRecord(
            assembly=assembly,
            material_type=material_type,
            embodied_total=_vector("total", values),
            materials=_vector("materials", values),
            transport=_vector("transport", values),
            construction=_vector("construction", values),
            unit_multiplier=values["unit_multiplier"],
        )
        parts = record.materials + record.transport + record.construction
        for key in IMPACT_KEYS:
            total, summed = record.embodied_total.get(key), parts.get(key)
            if abs(total - summed) > SUM_TOLERANCE * max(abs(total), abs(summed), 1e-12):
                result.warnings.append(
                    f"{where}: total_{key} ({total:g}) is not materials + transport + "
                    f"construction ({summed:g})"
                )
        result.records.append(record)

    if errors:
        raise CustomMaterialsError(path, errors)
    return result
