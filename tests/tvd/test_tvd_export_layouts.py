"""P4.5: TVD on an old-layout and a new-layout export with the same quantities.

Old layout: the 44 columns of the Island exports from the add-in before concho #18 (display
strings in an imperial project, e.g. ``9' - 7 3/4"``, ``6590 SF``). New layout: the 58 columns
the add-in writes since P4.5 (plain decimals in ft / SF / CF), see
``docs/model-requirements.md``, "Old vs new export layout". All rows invented.

TVD reads columns by name, and every column it reads (``ElementId``, ``Category``, ``Family``,
``Type``, ``Level``, ``Mark``, ``Assembly Code``, ``Length``, ``Area``, ``Volume``,
``Material``, ``Comments``) exists in both layouts, so no alias is needed; a missing column
reads as empty. The last test pins that tolerance.
"""

import csv
from pathlib import Path

import pytest

from engines.tvd.engine import run_files
from engines.tvd.loading import load_csv_file
from engines.tvd.quantities import aggregate_quantities

REPO_ROOT = Path(__file__).resolve().parents[2]
COST_DB = REPO_ROOT / "tests" / "fixtures" / "tvd_synthetic" / "cost_db.csv"

_SPATIAL = [
    "Location Type", "Position X (ft)", "Position Y (ft)", "Position Z (ft)",
    "Start X (ft)", "Start Y (ft)", "Start Z (ft)", "End X (ft)", "End Y (ft)", "End Z (ft)",
    "Rotation (deg)",
    "Bounding Box Min X (ft)", "Bounding Box Min Y (ft)", "Bounding Box Min Z (ft)",
    "Bounding Box Max X (ft)", "Bounding Box Max Y (ft)", "Bounding Box Max Z (ft)",
    "Bounding Box Center X (ft)", "Bounding Box Center Y (ft)", "Bounding Box Center Z (ft)",
]
_ROOM = [
    "Room Id", "Room Number", "Room Name", "Room Level", "Room Area (SF)", "Room Volume (CF)",
    "Room Location X (ft)", "Room Location Y (ft)", "Room Location Z (ft)",
]
_QUANTITY_AND_TEXT = [
    "Length", "Width", "Depth", "Height", "Area", "Volume", "Weight", "Unit Weight", "Material",
    "Type Comments", "Base Level", "Top Level", "Base Offset", "Top Offset",
]

# Island exports before concho #18 (AutoTVD qto/, 44 columns).
OLD_COLUMNS = [
    "ElementId", "Category", "Family", "Type", "Level", "Mark", "Assembly Code",
    "Assembly Description", *_QUANTITY_AND_TEXT, *_SPATIAL, "Comments", "Parameter Snapshot",
]
# Add-in since P4.5 (revit-addin/Architecture_TakeOff.cs, 58 columns).
NEW_COLUMNS = [
    "ElementId", "Category", "Family", "Type", "Original Category", "Original Family",
    "Original Type", "Level", "Mark", "Assembly Code", "Assembly Description",
    *_QUANTITY_AND_TEXT, *_SPATIAL, *_ROOM, "Comments", "Parameter Snapshot",
    "Part Source Id", "Category (local)",
]

# (ElementId, Category, Family, Type, Assembly Code, Mark, Length, Area, Volume) per layout.
# Same element, same quantity: old display string / new plain decimal.
ARCH = [
    ("1", "Walls", "", "Invented wall", "B2010", "",
     ("9' - 7 3/4\"", "9.645833"), ("88 SF", "88"), ("44.00 CF", "44")),
    ("2", "Walls", "", "Invented wall", "B2010", "",
     ("12' - 0\"", "12"), ("120 SF", "120"), ("60.50 CF", "60.5")),
    ("3", "Walls", "", "Invented curtain wall", "B2010", "",
     ("20' - 6 1/2\"", "20.541667"), ("205 SF", "205"), ("", "")),
    ("4", "Floors", "", "Invented slab", "A1030", "",
     ("", ""), ("1,000.00 SF", "1000"), ("500.00 CF", "500")),
    ("5", "Doors", "Invented door", "Single", "C1020", "",
     ("", ""), ("21 SF", "21"), ("1.75 CF", "1.75")),
    ("6", "Walls", "", "Invented wall DNC", "B2010", "",
     ("5' - 0\"", "5"), ("50 SF", "50"), ("25.00 CF", "25")),
    ("7", "Walls", "", "Invented wall", "", "",
     ("3' - 0\"", "3"), ("30 SF", "30"), ("15.00 CF", "15")),
    ("8", "Railings", "", "Invented handrail", "C2010", "",
     ("15' - 4 1/2\"", "15.375"), ("", ""), ("", "")),
]
STRUCT = [
    ("1", "Walls", "", "Invented wall", "B2010", "",
     ("9' - 7 3/4\"", "9.645833"), ("88 SF", "88"), ("44.00 CF", "44")),
    ("10", "Structural Framing", "Invented beam", "W8x10", "B1010", "",
     ("25' - 3 3/8\"", "25.28125"), ("", ""), ("2.50 CF", "2.5")),
    ("11", "Structural Columns", "Invented column", "C1", "A1010", "",
     ("", ""), ("", ""), ("16.00 CF", "16")),
]


def _write(path: Path, columns: list[str], rows, layout: int) -> Path:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for eid, cat, fam, typ, code, mark, length, area, volume in rows:
            values = {
                "ElementId": eid, "Category": cat, "Family": fam, "Type": typ,
                "Assembly Code": code, "Mark": mark, "Level": "L1", "Material": "Invented",
                "Length": length[layout], "Area": area[layout], "Volume": volume[layout],
            }
            writer.writerow({c: values.get(c, "") for c in columns})
    return path


@pytest.fixture
def layouts(tmp_path) -> dict[str, dict[str, Path]]:
    return {
        name: {
            "arch": _write(tmp_path / f"{name}_Architecture_TakeOff.csv", columns, ARCH, i),
            "struct": _write(tmp_path / f"{name}_Structural_Schedule.csv", columns, STRUCT, i),
        }
        for i, (name, columns) in enumerate((("old", OLD_COLUMNS), ("new", NEW_COLUMNS)))
    }


def test_layouts_have_the_documented_column_counts():
    assert (len(OLD_COLUMNS), len(NEW_COLUMNS)) == (44, 58)
    assert set(OLD_COLUMNS) < set(NEW_COLUMNS)  # nothing renamed or removed


def test_old_and_new_layout_give_identical_totals(layouts, island_config):
    runs = {
        name: run_files(str(paths["arch"]), str(paths["struct"]), str(COST_DB), island_config)
        for name, paths in layouts.items()
    }
    old, new = runs["old"], runs["new"]
    old_payload, new_payload = old.results_payload(), new.results_payload()
    assert old_payload["financials"] == new_payload["financials"]
    assert old_payload["cluster_summary"] == new_payload["cluster_summary"]
    # 6-decimal feet vs. exact fractions: line qty rounded to 4 decimals and cent totals agree.
    assert old_payload["line_items"] == new_payload["line_items"]
    assert (old.unmapped_count, old.dnc_count, old.total_elements, old.duplicates_removed) == (
        new.unmapped_count, new.dnc_count, new.total_elements, new.duplicates_removed) == (
        1, 1, 10, 1)
    assert old.quantity_parse_warnings == new.quantity_parse_warnings == {
        "parser": "tolerant", "total": 0, "columns": {}}
    # 15.375 LF x 40.00; the stored qty is rounded to 2 decimals.
    (handrail,) = [r for r in old_payload["line_items"]["Interiors"] if r["ac"] == "C2010"]
    assert (handrail["unit"], handrail["qty"], handrail["total"]) == ("LF", 15.38, 615.0)


def test_old_layout_with_legacy_parser_drops_the_fractions(layouts):
    """What P3.11 fixes: the same old-layout file, AutoTVD's parser vs. the tolerant one."""
    rows = load_csv_file(str(layouts["old"]["arch"]))
    legacy = aggregate_quantities(rows, legacy_length_parsing=True)[0]
    tolerant = aggregate_quantities(rows)[0]
    assert legacy["B2010"]["length_lf"] == 9 + 12 + 20
    assert tolerant["B2010"]["length_lf"] == pytest.approx(9 + 7.75 / 12 + 12 + 20 + 6.5 / 12)


def test_missing_columns_read_as_empty(tmp_path, island_config):
    """A layout without the optional TVD columns (Mark, Comments, Level, Material, Family) still
    prices by Assembly Code; a missing quantity column counts 0 without a parse warning."""
    minimal = ["ElementId", "Category", "Type", "Assembly Code", "Area", "Volume"]
    arch = _write(tmp_path / "min_Architecture_TakeOff.csv", minimal, ARCH, 1)
    struct = _write(tmp_path / "min_Structural_Schedule.csv", minimal, STRUCT[1:2], 1)
    full = _write(tmp_path / "full_Architecture_TakeOff.csv", NEW_COLUMNS, ARCH, 1)
    rows_min = load_csv_file(str(arch))
    rows_full = load_csv_file(str(full))
    q_min = aggregate_quantities(rows_min)[0]
    q_full = aggregate_quantities(rows_full)[0]
    for code, q in q_full.items():
        assert q_min[code]["area_sf"] == q["area_sf"]
        assert q_min[code]["volume_cf"] == q["volume_cf"]
        assert q_min[code]["length_lf"] == 0.0
    run = run_files(str(arch), str(struct), str(COST_DB), island_config)
    assert run.quantity_parse_warnings["total"] == 0
