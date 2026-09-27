"""Custom materials: ``custom_materials.csv`` (P3.7). Team data, not course data.

A custom material is a material the course LCA catalog (``LCA Data`` rows 8-107 of the
course STV workbook) does not have, with values taken from an EPD. One CSV row per
material, with the columns of a course ``LCA Data`` row plus ``source`` and
``is_course_data``:

- ``assembly`` / ``material_type`` (``LCA Data`` B / C): a course assembly and a new name
  that ends with its unit in brackets, like the course names (``Bamboo Beam (kg)``);
- ``embodied_*`` (D-G), ``materials_*`` (H-K), ``transport_*`` (L-O), ``construction_*``
  (P-S): per unit of ``material_type``, GWP kgCO2e / energy MJ / water kg / ODP kgCFC11e;
  ``embodied_*`` = materials + transport + construction;
- ``life_units`` (T, 'Life Units No.'): the course unit multiplier (1 = no replacement);
- ``source``: the EPD reference (document, page, declared unit, conversion), required;
- ``is_course_data``: always ``false``.

The engine uses a custom material like a catalog entry (``STVReferenceData.
add_custom_materials``); a custom material may not reuse a course catalog name. Format and
checks: ``docs/engines/stv.md``; JSON Schema of one row: ``concho custmat schema``.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .models import IMPACT_KEYS, ImpactVector
from .reference import ASSEMBLY_ALIASES, ASSEMBLY_COLUMN_MAP, MaterialRecord

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://github.com/mxngl/concho/docs/schema/custom_materials.schema.json"

# Course 'LCA Data' column groups and the indicator suffixes of the CSV columns.
PHASES = ("embodied", "materials", "transport", "construction")
INDICATORS = {  # ImpactVector key -> column suffix (unit in the name)
    "carbon": "gwp_kgco2e",
    "energy": "energy_mj",
    "water": "water_kg",
    "ozone": "odp_kgcfc11e",
}
IMPACT_COLUMNS = [f"{phase}_{INDICATORS[key]}" for phase in PHASES for key in IMPACT_KEYS]
COLUMNS = [
    "assembly",
    "material_type",
    *IMPACT_COLUMNS,
    "life_units",
    "source",
    "is_course_data",
]
# Assemblies as in the course 'Lists' sheet; 'LCA Data' writes Columns/Beams as Column/Beam.
ASSEMBLIES = list(ASSEMBLY_COLUMN_MAP)
LCA_ASSEMBLY = {**{a: a for a in ASSEMBLIES}, **ASSEMBLY_ALIASES}
LIST_ASSEMBLY = {**{a: a for a in ASSEMBLIES}, **{v: k for k, v in ASSEMBLY_ALIASES.items()}}
UNIT_RE = re.compile(r"\(([^()]+)\)\s*$")
# Relative tolerance for embodied = materials + transport + construction.
SUM_TOLERANCE = 1e-6


class CustomMaterialRow(BaseModel):
    """One row of ``custom_materials.csv``. Team data (EPD values), not course data."""

    model_config = ConfigDict(
        extra="forbid",
        title="custom_materials.csv row",
        json_schema_extra={
            "$schema": SCHEMA_DIALECT,
            "$id": SCHEMA_ID,
            "x-csv-columns": COLUMNS,
            "x-csv-notes": (
                "One CSV row per material, header row with these column names (order free). "
                "Lines starting with '#' are comments. Columns mirror a course 'LCA Data' row "
                "(B-T) plus source and is_course_data. Values per unit of material_type. "
                "material_type must not be a course catalog name. See docs/engines/stv.md."
            ),
        },
    )

    assembly: str = Field(
        pattern="^(" + "|".join(sorted(LCA_ASSEMBLY)) + ")$",
        description="Course assembly ('LCA Data' B / 'Lists'): " + ", ".join(ASSEMBLIES)
                    + " (Column / Beam are accepted for Columns / Beams).",
    )
    material_type: str = Field(
        pattern=r"^.*\S.*\([^()]+\)\s*$",
        description="New material name ending with its unit in brackets, like the course "
                    "names ('LCA Data' C), e.g. 'Bamboo Beam (kg)'. Must not be a course "
                    "catalog name.",
    )
    source: str = Field(
        min_length=1,
        description="EPD reference: document, registration number, page, declared unit and "
                    "how the values were converted to the unit of material_type.",
    )
    is_course_data: bool = Field(
        description="Always false: custom materials are team data.", json_schema_extra={
            "const": False},
    )
    embodied_gwp_kgco2e: float = Field(
        description="Embodied GWP (kgCO2e) per unit of material_type ('LCA Data' D)."
                    " Must equal materials + transport + construction."
    )
    embodied_energy_mj: float = Field(
        ge=0, description="Embodied energy (MJ) per unit of material_type ('LCA Data' E)."
                    " Must equal materials + transport + construction."
    )
    embodied_water_kg: float = Field(
        ge=0, description="Embodied water (kg) per unit of material_type ('LCA Data' F)."
                    " Must equal materials + transport + construction."
    )
    embodied_odp_kgcfc11e: float = Field(
        ge=0, description="Embodied ODP (kgCFC11e) per unit of material_type ('LCA Data' G)."
                    " Must equal materials + transport + construction."
    )
    materials_gwp_kgco2e: float = Field(
        description="Materials GWP (kgCO2e) per unit of material_type ('LCA Data' H)."
    )
    materials_energy_mj: float = Field(
        ge=0, description="Materials energy (MJ) per unit of material_type ('LCA Data' I)."
    )
    materials_water_kg: float = Field(
        ge=0, description="Materials water (kg) per unit of material_type ('LCA Data' J)."
    )
    materials_odp_kgcfc11e: float = Field(
        ge=0, description="Materials ODP (kgCFC11e) per unit of material_type ('LCA Data' K)."
    )
    transport_gwp_kgco2e: float = Field(
        description="Transport GWP (kgCO2e) per unit of material_type ('LCA Data' L)."
    )
    transport_energy_mj: float = Field(
        ge=0, description="Transport energy (MJ) per unit of material_type ('LCA Data' M)."
    )
    transport_water_kg: float = Field(
        ge=0, description="Transport water (kg) per unit of material_type ('LCA Data' N)."
    )
    transport_odp_kgcfc11e: float = Field(
        ge=0, description="Transport ODP (kgCFC11e) per unit of material_type ('LCA Data' O)."
    )
    construction_gwp_kgco2e: float = Field(
        description="Construction GWP (kgCO2e) per unit of material_type ('LCA Data' P)."
    )
    construction_energy_mj: float = Field(
        ge=0, description="Construction energy (MJ) per unit of material_type ('LCA Data' Q)."
    )
    construction_water_kg: float = Field(
        ge=0, description="Construction water (kg) per unit of material_type ('LCA Data' R)."
    )
    construction_odp_kgcfc11e: float = Field(
        ge=0, description="Construction ODP (kgCFC11e) per unit of material_type ('LCA Data' S)."
    )
    life_units: float = Field(
        gt=0, description="Course 'Life Units No.' ('LCA Data' T): unit multiplier over the "
                          "building life (1 = no replacement).",
    )


def json_schema() -> dict[str, Any]:
    schema = CustomMaterialRow.model_json_schema()
    schema["properties"] = {c: schema["properties"][c] for c in COLUMNS}
    schema["required"] = COLUMNS
    return schema


def json_schema_text() -> str:
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"


class Catalog(Protocol):
    """What the validator needs from the course LCA catalog (``STVReferenceData``)."""

    materials: dict[tuple[str, str], MaterialRecord]


@dataclass(slots=True)
class CustomMaterial:
    record: MaterialRecord
    source: str
    line: int


@dataclass
class CustomMaterials:
    """A validated custom materials file."""

    path: Path | None
    materials: list[CustomMaterial] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def records(self) -> list[MaterialRecord]:
        return [m.record for m in self.materials]


class CustomMaterialsError(ValueError):
    def __init__(self, path: Path | str, errors: list[str]):
        self.errors = errors
        super().__init__(
            f"invalid custom materials file {path}:\n" + "\n".join(f"  - {e}" for e in errors)
        )


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def _records(text: str) -> tuple[list[str] | None, list[tuple[int, list[str]]]]:
    """Header and (line number, cells) of the data rows; comments and blank lines skipped."""
    header = None
    rows: list[tuple[int, list[str]]] = []
    for line_no, cells in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not cells or not any(c.strip() for c in cells) or cells[0].lstrip().startswith("#"):
            continue
        if header is None:
            header = [c.strip() for c in cells]
        else:
            rows.append((line_no, [c.strip() for c in cells]))
    return header, rows


def _vector(values: dict[str, float], phase: str) -> ImpactVector:
    return ImpactVector(**{key: values[f"{phase}_{INDICATORS[key]}"] for key in IMPACT_KEYS})


def _number(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def validate_custom_materials_text(
    text: str, *, catalog: Catalog | None = None, path: Path | None = None
) -> CustomMaterials:
    """Validate the CSV text; collect every error (the result is ``ok`` without errors)."""
    result = CustomMaterials(path=path)
    errors = result.errors
    header, rows = _records(text)
    if header is None:
        errors.append("empty file (no header row)")
        return result
    unknown = [c for c in header if c not in COLUMNS]
    dupes = sorted({c for c in header if header.count(c) > 1})
    missing = [c for c in COLUMNS if c not in header]
    if unknown:
        errors.append(f"unknown column(s): {', '.join(unknown)}")
    if dupes:
        errors.append(f"duplicated column(s): {', '.join(dupes)}")
    if missing:
        errors.append(f"missing column(s): {', '.join(missing)}")
    if errors:
        return result
    if not rows:
        result.warnings.append("no materials in the file")

    course_names: dict[str, tuple[str, str]] = {}
    if catalog is None:
        result.warnings.append(
            "no course workbook given: custom material names were not checked against the "
            "course catalog"
        )
    else:
        course_names = {_norm(m): (a, m) for a, m in catalog.materials}

    seen: dict[str, int] = {}
    for line, cells in rows:
        where = f"line {line}"
        if len(cells) > len(header):
            errors.append(f"{where}: {len(cells)} cells but {len(header)} columns")
            continue
        rec = dict(zip(header, cells + [""] * (len(header) - len(cells)), strict=True))
        row_errors: list[str] = []

        assembly, material_type = rec["assembly"], rec["material_type"]
        if assembly not in LCA_ASSEMBLY:
            row_errors.append(
                f"unknown assembly '{assembly}' (expected one of: {', '.join(ASSEMBLIES)})"
            )
        if not material_type:
            row_errors.append("material_type is empty")
        else:
            if not UNIT_RE.search(material_type):
                row_errors.append(
                    f"material_type '{material_type}' has no unit: end it with the unit in "
                    "brackets, like the course names, e.g. 'Bamboo Beam (kg)'"
                )
            course = course_names.get(_norm(material_type))
            if course is not None:
                row_errors.append(
                    f"material_type '{material_type}' is a course catalog name ({course[0]} / "
                    f"{course[1]}); give the custom material its own name"
                )
            key = _norm(material_type)
            if key in seen:
                row_errors.append(
                    f"duplicate material_type '{material_type}' (first on line {seen[key]})"
                )
            else:
                seen[key] = line
        if not rec["source"]:
            row_errors.append("source is empty (give the EPD reference: document, page, "
                              "declared unit)")
        if rec["is_course_data"].strip().lower() != "false":
            row_errors.append(
                f"is_course_data must be false (custom materials are team data), got "
                f"'{rec['is_course_data']}'"
            )

        values: dict[str, float] = {}
        for column in [*IMPACT_COLUMNS, "life_units"]:
            number = _number(rec[column])
            if number is None:
                row_errors.append(f"{column} is not a plain number: '{rec[column]}'")
                continue
            if column == "life_units" and number <= 0:
                row_errors.append(f"life_units must be > 0, got {number:g}")
            elif (column != "life_units" and number < 0
                  and not column.endswith(INDICATORS["carbon"])):
                row_errors.append(f"{column} must be >= 0, got {number:g}")
            values[column] = number

        if len(values) == len(IMPACT_COLUMNS) + 1:
            record = MaterialRecord(
                assembly=LCA_ASSEMBLY.get(assembly, assembly),
                material_type=material_type,
                embodied_total=_vector(values, "embodied"),
                materials=_vector(values, "materials"),
                transport=_vector(values, "transport"),
                construction=_vector(values, "construction"),
                unit_multiplier=values["life_units"],
            )
            parts = record.materials + record.transport + record.construction
            for key in IMPACT_KEYS:
                total, summed = record.embodied_total.get(key), parts.get(key)
                if abs(total - summed) > SUM_TOLERANCE * max(abs(total), abs(summed), 1e-12):
                    row_errors.append(
                        f"embodied_{INDICATORS[key]} ({total:g}) is not materials + transport "
                        f"+ construction ({summed:g})"
                    )
            if not row_errors:
                result.materials.append(CustomMaterial(record, rec["source"], line))
        errors += [f"{where}: {e}" for e in row_errors]
    return result


def validate_custom_materials_file(
    path: Path | str, *, catalog: Catalog | None = None
) -> CustomMaterials:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return CustomMaterials(path=path, errors=[f"cannot read file ({exc.strerror})"])
    return validate_custom_materials_text(text, catalog=catalog, path=path)


def load_custom_materials(
    path: Path | str, *, catalog: Catalog | None = None
) -> CustomMaterials:
    """Read and validate a custom materials CSV; raise :class:`CustomMaterialsError`."""
    result = validate_custom_materials_file(path, catalog=catalog)
    if not result.ok:
        raise CustomMaterialsError(path, result.errors)
    return result
