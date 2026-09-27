"""P4.5: the unit-safe export format of the Revit add-in, read by the current importers.

Since P4.5 the add-in writes quantities as plain invariant decimals in fixed units (ft, SF, CF,
inches for MEP dimensions, kg, m³/s) instead of Revit display strings. The engines are not
changed for this; these tests check that the existing TVD and STV importers read the new
format with the right quantities:

- synthetic Architecture / Structural / MEP rows in the new format,
- the two text columns of the MEP export: ``Length`` (fixed feet-inch format, see
  ``ParameterReader.FormatFeetInches`` in ``revit-addin/ParameterReader.cs``) and ``Size``
  (``3"`` / ``4"x4"``, built by the add-in from the dimensions),
- the Island reference exports converted to the new format give the same STV results and the
  same TVD quantities (needs the reference fixtures, skipped otherwise). Since P3.11 TVD reads
  the display strings exactly too (``9' - 7 3/4"`` = 9.646 ft; before, AutoTVD's parser gave
  9 ft, which TVD still does with ``--legacy-length-parsing``).

The format helpers below mirror the C# formatting; keep them in sync.
"""

from __future__ import annotations

import csv
import io
import math
from pathlib import Path

import pytest

from engines.stv.conversions import (
    _extract_inches,
    _extract_size_pair_inches,
    nominal_diameter_in,
    parse_length_feet,
)
from engines.stv.mapping import load_stv_mapping
from engines.stv.revit_architecture import load_architecture_schedule
from engines.stv.revit_mep import load_mep_schedule
from engines.stv.revit_structural import load_structural_schedule
from engines.tvd.loading import load_csv_text, parse_qty_str
from engines.tvd.quantities import aggregate_quantities

ARCH_COLUMNS = [
    "ElementId", "Category", "Family", "Type", "Original Category", "Original Family",
    "Original Type", "Level", "Mark", "Assembly Code", "Assembly Description", "Length",
    "Width", "Depth", "Height", "Area", "Volume", "Weight", "Unit Weight", "Material",
    "Type Comments", "Base Level", "Top Level", "Base Offset", "Top Offset", "Comments",
    "Parameter Snapshot", "Part Source Id", "Category (local)",
]
REPO_ROOT = Path(__file__).resolve().parents[2]
# Since P3.6 the STV importers map rows with a mapping table; the Island table reproduces the
# former hardcoded importers.
ISLAND_MAPPING = load_stv_mapping(
    REPO_ROOT / "engines" / "stv" / "examples" / "island" / "stv_mapping.csv"
)

MEP_COLUMNS = [
    "ElementId", "Category", "Family", "Type", "Level", "Mark", "System Name", "System Type",
    "Size", "Diameter", "Width", "Height", "Length", "Area", "Volume", "Material", "Weight",
    "Unit Weight", "Airflow", "Flow", "Connector Flow", "Comments", "Parameter Snapshot",
    "Assembly Code", "Category (local)",
]


def fmt(value: float | None) -> str:
    """Mirror of ``ParameterReader.Format``: plain invariant decimal, up to 6 decimals."""
    if value is None:
        return ""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def fmt_feet_inches(feet: float | None) -> str:
    """Mirror of ``ParameterReader.FormatFeetInches``: ``12' - 6.375"``."""
    if feet is None:
        return ""
    total_inches = round(abs(feet) * 12.0, 3)
    whole_feet = math.floor(total_inches / 12.0)
    inches = round(total_inches - whole_feet * 12.0, 3)
    if inches >= 12.0:
        whole_feet += 1
        inches = 0.0
    sign = "-" if feet < 0 and (whole_feet > 0 or inches > 0) else ""
    return f"{sign}{whole_feet}' - {inches:.3f}\""


def fmt_inch_mark(inches: float) -> str:
    """Mirror of ``ParameterReader.FormatInchMark``: ``4"``, ``12.5"``."""
    return f"{inches:.3f}".rstrip("0").rstrip(".") + '"'


def _csv(columns: list[str], rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return out.getvalue()


def _write(tmp_path: Path, name: str, columns: list[str], rows: list[dict[str, str]]) -> Path:
    path = tmp_path / name
    path.write_text("﻿" + _csv(columns, rows), encoding="utf-8")
    return path


def _items(report) -> dict[tuple[str, str], float]:
    return {(item.assembly, item.material_type): item.amount for item in report.construction_items}


# --- MEP text columns: Length (feet-inch) and Size -------------------------------------------


@pytest.mark.parametrize(
    "feet", [0.0, 0.001, 0.0417, 0.5, 0.999, 1.0, 3.88, 12.53125, 20.234567, 123.456789, 1999.99999]
)
def test_mep_length_format_round_trips_through_stv_parser(feet):
    text = fmt_feet_inches(feet)
    assert parse_length_feet(text) == pytest.approx(feet, abs=1e-4)


def test_plain_decimal_feet_also_parse_since_p36():
    """Since P3.6 STV reads a bare number as feet, so MEP Length can switch to plain decimals
    (planned with the engine part of P4.5)."""
    assert parse_length_feet(fmt(12.53125)) == pytest.approx(12.53125)
    assert parse_length_feet(fmt(0.75)) == pytest.approx(0.75)


def test_mep_length_format_examples():
    assert fmt_feet_inches(12.53125) == "12' - 6.375\""
    assert fmt_feet_inches(0.0) == "0' - 0.000\""
    assert fmt_feet_inches(0.5) == "0' - 6.000\""
    # Rounding up to a full foot carries over instead of writing 12.000".
    assert fmt_feet_inches(0.99999999) == "1' - 0.000\""
    assert fmt_feet_inches(None) == ""


@pytest.mark.parametrize("inches", [0.5, 3.0, 4.0, 12.5, 15.0, 18.0, 23.625])
def test_mep_size_round_diameter_round_trips(inches):
    size = fmt_inch_mark(inches)
    assert _extract_inches(size) == pytest.approx(inches, abs=1e-3)
    row = {"Size": size}
    assert nominal_diameter_in(row) == pytest.approx(inches, abs=1e-3)


@pytest.mark.parametrize(("width", "height"), [(4.0, 4.0), (12.0, 8.0), (24.5, 10.25)])
def test_mep_size_rectangular_round_trips(width, height):
    size = f"{fmt_inch_mark(width)}x{fmt_inch_mark(height)}"
    assert _extract_size_pair_inches(size) == pytest.approx((width, height), abs=1e-3)
    assert _extract_inches(size) == pytest.approx(max(width, height), abs=1e-3)


def test_size_examples():
    assert fmt_inch_mark(3.0) == '3"'
    assert f"{fmt_inch_mark(4.0)}x{fmt_inch_mark(4.0)}" == '4"x4"'


# --- Synthetic exports in the new numeric format --------------------------------------------


ARCH_ROWS = [
    # Exterior wall: B2010, 312.5 SF, 1'-0" thick, 25.25' long.
    {"ElementId": "1", "Category": "Walls", "Category (local)": "Wände", "Family": "Basic Wall",
     "Type": "Exterior - Brick",
     "Assembly Code": "B2010", "Length": fmt(25.25), "Width": fmt(1.0), "Height": fmt(12.375),
     "Area": fmt(312.5), "Volume": fmt(312.5), "Material": "Brick"},
    # Interior wall, same code as a second one to test the sum.
    {"ElementId": "2", "Category": "Walls", "Family": "Basic Wall", "Type": "Interior - Stud",
     "Assembly Code": "C1010", "Length": fmt(10.0), "Width": fmt(0.40625), "Area": fmt(95.123456),
     "Volume": fmt(38.6439), "Material": "Gypsum"},
    {"ElementId": "3", "Category": "Walls", "Family": "Basic Wall", "Type": "Interior - Stud",
     "Assembly Code": "C1010", "Length": fmt(4.5), "Area": fmt(40.0), "Volume": fmt(16.25),
     "Material": "Gypsum"},
    # Door without area: STV falls back to Width × Height (both in feet).
    {"ElementId": "4", "Category": "Doors", "Family": "Single-Flush", "Type": "36\" x 84\"",
     "Assembly Code": "C1020", "Width": fmt(3.0), "Height": fmt(7.0), "Material": "Wood"},
    # Floor with a code, and one excluded category (Furniture) that TVD only counts.
    {"ElementId": "5", "Category": "Floors", "Family": "Floor", "Type": "Concrete 6\"",
     "Assembly Code": "B1010", "Area": fmt(6847.99), "Volume": fmt(3423.995),
     "Material": "Concrete"},
    {"ElementId": "6", "Category": "Furniture", "Family": "Desk", "Type": "Desk",
     "Assembly Code": "E2020", "Area": fmt(12.0)},
    # Ceiling part (P4.5): English category, code and quantities of the source ceiling 99.
    {"ElementId": "8", "Category": "Parts", "Category (local)": "Bauteile",
     "Original Category": "Ceilings", "Part Source Id": "99", "Assembly Code": "C3030",
     "Area": fmt(123.0), "Volume": fmt(15.375), "Height": fmt(0.125), "Material": "Gypsum"},
    # No Assembly Code: unmapped in TVD.
    {"ElementId": "7", "Category": "Roofs", "Family": "Basic Roof", "Type": "Green Roof",
     "Area": fmt(1500.5), "Volume": fmt(750.25), "Material": "Green"},
]

STRUCT_ROWS = [
    {"ElementId": "11", "Category": "Structural Columns", "Family": "Concrete-Rectangular-Column",
     "Type": "24 x 24", "Assembly Code": "B1010", "Length": fmt(12.0), "Volume": fmt(48.0),
     "Material": "Concrete"},
    {"ElementId": "12", "Category": "Structural Framing", "Family": "Glulam Beam",
     "Type": "GL 6x18", "Assembly Code": "B1010", "Length": fmt(20.5), "Volume": fmt(15.375),
     "Material": "Glulam"},
    {"ElementId": "13", "Category": "Structural Foundations", "Family": "Footing-Rectangular",
     "Type": "Footing", "Assembly Code": "A1010", "Volume": fmt(27.0), "Material": "Concrete"},
    {"ElementId": "14", "Category": "Floors", "Family": "Floor", "Type": "CLT 7-ply",
     "Assembly Code": "B1010", "Area": fmt(2000.25), "Volume": fmt(1200.15), "Material": "CLT"},
]


def test_tvd_reads_numeric_architecture_export():
    rows = load_csv_text(_csv(ARCH_COLUMNS, ARCH_ROWS))
    code_qtys, unmapped, all_counts, _, dnc = aggregate_quantities(rows)

    assert code_qtys["B2010"]["area_sf"] == pytest.approx(312.5)
    assert code_qtys["B2010"]["length_lf"] == pytest.approx(25.25)
    assert code_qtys["B2010"]["volume_cf"] == pytest.approx(312.5)
    assert code_qtys["C1010"]["area_sf"] == pytest.approx(135.123456)
    assert code_qtys["C1010"]["length_lf"] == pytest.approx(14.5)
    assert code_qtys["C1010"]["volume_cf"] == pytest.approx(54.8939)
    assert code_qtys["C1010"]["count"] == 2
    assert code_qtys["B1010"]["area_sf"] == pytest.approx(6847.99)
    assert "E2020" not in code_qtys  # Furniture excluded from quantities ...
    assert all_counts["E2020"] == 1  # ... but counted for count_codes
    assert code_qtys["C3030"]["area_sf"] == pytest.approx(123.0)
    assert code_qtys["C3030"]["volume_cf"] == pytest.approx(15.375)
    assert unmapped == 1
    assert dnc == 0


def test_tvd_reads_numeric_structural_export():
    rows = load_csv_text(_csv(ARCH_COLUMNS, STRUCT_ROWS))
    code_qtys, unmapped, _, _, _ = aggregate_quantities(rows)
    assert code_qtys["B1010"]["volume_cf"] == pytest.approx(48.0 + 15.375 + 1200.15)
    assert code_qtys["B1010"]["length_lf"] == pytest.approx(32.5)
    assert code_qtys["B1010"]["area_sf"] == pytest.approx(2000.25)
    assert code_qtys["A1010"]["volume_cf"] == pytest.approx(27.0)
    assert unmapped == 0


def test_tvd_quantity_parser_plain_decimals():
    cases = [("0", 0.0), ("312.5", 312.5), ("6847.99", 6847.99), ("0.000123", 0.000123)]
    for text, expected in cases:
        assert parse_qty_str(text) == pytest.approx(expected)


def test_stv_reads_numeric_architecture_export(tmp_path):
    path = _write(tmp_path, "m_Architecture_TakeOff.csv", ARCH_COLUMNS, ARCH_ROWS)
    report = load_architecture_schedule(path, ISLAND_MAPPING)
    items = _items(report)
    assert items[("Exterior Wall", "Brick on Metal Stud (sf)")] == pytest.approx(312.5)
    interior = items[("Interior Wall", "Steel Studs and Painted Gypsum (sf)")]
    assert interior == pytest.approx(135.123456)
    # Door: no Area → Width × Height = 3 ft × 7 ft.
    assert items[("Interior Wall", "Timber Studs and Painted Gypsum (sf)")] == pytest.approx(21.0)
    assert items[("Floor", "Concrete (sf)")] == pytest.approx(6847.99)
    assert items[("Roof", "Green Roof (sf)")] == pytest.approx(1500.5)


def test_stv_door_fallback_same_as_display_strings():
    assert parse_length_feet(fmt(3.0)) == pytest.approx(3.0)
    assert parse_length_feet("3' - 0\"") == pytest.approx(3.0)
    old = parse_length_feet("6' - 8 1/4\"")
    assert parse_length_feet(fmt(6.6875)) == pytest.approx(old)


def test_stv_reads_numeric_structural_export(tmp_path):
    path = _write(tmp_path, "m_Structural_Schedule.csv", ARCH_COLUMNS, STRUCT_ROWS)
    report = load_structural_schedule(path, ISLAND_MAPPING)
    items = _items(report)
    assert items[("Columns", "Reinforced Concrete Column (cy)")] == pytest.approx(48.0 / 27.0)
    assert items[("Foundation", "Strip Foundation (cy)")] == pytest.approx(1.0)
    assert ("Beams", "Glulam Beam (kg)") in items
    assert ("Floor", next(k[1] for k in items if k[0] == "Floor")) in items


MEP_ROWS = [
    # Rectangular duct 12"x8", 20' - 2.813" long → Steel Duct 12"D (ft) by length.
    {"ElementId": "21", "Category": "Ducts", "Category (local)": "Luftkanäle", "Family": "",
     "Type": "Rectangular Duct",
     "Size": '12"x8"', "Width": fmt(12.0), "Height": fmt(8.0), "Length": fmt_feet_inches(20.234375),
     "Area": fmt(33.72), "Volume": fmt(13.49), "Material": "Galvanized"},
    # Round duct Ø18" → Steel Duct 18"D (ft).
    {"ElementId": "22", "Category": "Ducts", "Family": "", "Type": "Round Duct",
     "Size": '18"', "Diameter": fmt(18.0), "Length": fmt_feet_inches(0.75),
     "Material": "Galvanized"},
    # Supply diffuser, airflow 30 m³/h = 0.008333 m³/s (plain decimal = m³/s).
    {"ElementId": "23", "Category": "Air Terminals", "Family": "Supply Diffuser", "Type": "600x600",
     "Airflow": fmt(30.0 / 3600.0), "Flow": fmt(30.0 / 3600.0)},
    # Copper pipe: weight in kg.
    {"ElementId": "24", "Category": "Pipes", "Family": "", "Type": "Copper",
     "Size": '1"', "Diameter": fmt(1.0), "Length": fmt_feet_inches(10.0), "Weight": fmt(12.5),
     "Material": "Copper"},
]


def test_stv_reads_numeric_mep_export(tmp_path):
    report = load_mep_schedule(
        _write(tmp_path, "m_MEP_TakeOff.csv", MEP_COLUMNS, MEP_ROWS), ISLAND_MAPPING
    )
    items = _items(report)
    assert items[("MEP", 'Steel Duct 12"D (ft)')] == pytest.approx(20.234375, abs=1e-4)
    assert items[("MEP", 'Steel Duct 18"D (ft)')] == pytest.approx(0.75, abs=1e-4)
    assert items[("MEP", "Air Handling Unit (m^3/s)")] == pytest.approx(30.0 / 3600.0, rel=1e-4)
    assert items[("MEP", "Copper Pipe (kg)")] == pytest.approx(12.5)
    assert report.mapped_rows == 4


def test_stv_mep_airflow_same_as_display_string(tmp_path):
    """Old display string ``30 m³/h`` and new plain m³/s give the same STV amount."""
    old = dict(MEP_ROWS[2], Airflow="30 m³/h", Flow="30 m³/h")
    new_path = _write(tmp_path, "new_MEP_TakeOff.csv", MEP_COLUMNS, [MEP_ROWS[2]])
    old_path = _write(tmp_path, "old_MEP_TakeOff.csv", MEP_COLUMNS, [old])
    new_items = _items(load_mep_schedule(new_path, ISLAND_MAPPING))
    old_items = _items(load_mep_schedule(old_path, ISLAND_MAPPING))
    assert new_items[("MEP", "Air Handling Unit (m^3/s)")] == pytest.approx(
        old_items[("MEP", "Air Handling Unit (m^3/s)")], rel=1e-4
    )


# --- Island reference exports converted to the new format -----------------------------------


SCHEDULES = "revit_schedules/Current"
LENGTH_COLUMNS = ("Length", "Width", "Depth", "Height", "Base Offset", "Top Offset")
MEASURE_COLUMNS = ("Area", "Volume")


def _convert_building_row(row: dict[str, str]) -> dict[str, str]:
    """Display strings (imperial project) → new numeric format."""
    converted = dict(row)
    for column in LENGTH_COLUMNS:
        if row.get(column):
            converted[column] = fmt(parse_length_feet(row[column]))
    for column in MEASURE_COLUMNS:
        if row.get(column):
            converted[column] = fmt(parse_qty_str(row[column]))
    return converted


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _exact_lengths(rows: list[dict[str, str]]) -> dict[str, float]:
    """LF per Assembly Code with exact feet-inch parsing (same filters as TVD)."""
    totals: dict[str, float] = {}
    for row in rows:
        code = row.get("Assembly Code", "").strip()
        fields = ("Family", "Type", "Mark", "Comments")
        marked = any("DNC" in row.get(field, "").upper() for field in fields)
        if not code or marked or row.get("Category", "").strip() == "Furniture":
            continue
        totals[code] = totals.get(code, 0.0) + parse_length_feet(row.get("Length", ""))
    return totals


@pytest.mark.parametrize(
    ("name", "loader"),
    [
        ("04_Island_ARCH_Concept2_Architecture_TakeOff.csv", load_architecture_schedule),
        ("STR_Wall_Bamboo_Concept2_amd03_Architecture_TakeOff.csv", load_architecture_schedule),
        ("04_Island_ARCH_Concept2_Structural_Schedule.csv", load_structural_schedule),
        ("STR_Wall_Bamboo_Concept2_amd03_Structural_Schedule.csv", load_structural_schedule),
    ],
)
def test_island_exports_in_numeric_format_give_same_results(
    ipd_challenge_dir, tmp_path, name, loader
):
    source = ipd_challenge_dir / SCHEDULES / name
    columns, rows = _read_rows(source)
    converted = [_convert_building_row(row) for row in rows]
    target = _write(tmp_path, name, columns, converted)

    # TVD: same areas, volumes, counts; lengths exact in both formats (P3.11).
    old_qtys, old_unmapped, old_counts, _, old_dnc = aggregate_quantities(rows)
    new_rows = load_csv_text(target.read_text("utf-8"))
    new_qtys, new_unmapped, new_counts, _, new_dnc = aggregate_quantities(new_rows)
    assert (new_unmapped, new_counts, new_dnc) == (old_unmapped, old_counts, old_dnc)
    assert new_qtys.keys() == old_qtys.keys()
    exact_lengths = _exact_lengths(rows)
    for code, quantities in old_qtys.items():
        for key in ("area_sf", "volume_cf", "count"):
            assert new_qtys[code][key] == pytest.approx(quantities[key], rel=1e-6, abs=1e-6), (
                code,
                key,
            )
        assert new_qtys[code]["length_lf"] == pytest.approx(exact_lengths[code], abs=1e-3), code
        assert quantities["length_lf"] == pytest.approx(exact_lengths[code], abs=1e-9), code

    # STV: same construction items.
    old_items = _items(loader(source, ISLAND_MAPPING))
    new_items = _items(loader(target, ISLAND_MAPPING))
    assert new_items.keys() == old_items.keys()
    for key, value in old_items.items():
        assert new_items[key] == pytest.approx(value, rel=1e-6, abs=1e-6), key
