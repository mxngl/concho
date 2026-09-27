"""P3.4: scripts/migrate_cost_data.py (old AutoTVD cost_data.csv → cost_db.csv).

Unit tests use invented rows in the old layout. The reference test converts the fetched
Island cost_data.csv (RSMeans-derived, ``.fixtures/`` only) into ``tmp_path``; nothing of it
is written into the repo. The TVD run on the converted file is compared with the original
AutoTVD output in ``test_tvd_equivalence.py``.
"""

import csv
from pathlib import Path

import pytest
from migrate_cost_data import convert_rows, main, migrate, parse_cost

ISLAND_CONFIG = (Path(__file__).resolve().parents[2] / "engines" / "common" / "examples"
                 / "island_2026.project_config.json")
OLD_HEADER = ["Cluster Name", "Assembly Code", "Assembly Group Name",
              "Description             ", "Unit             ", "Total O&P", "Fixed Quantity"]
OLD_ROWS = [
    ["Substructure", "A1030", "Slab on Grade", "Invented slab", "SF", "$25,00", ""],
    ["Substructure", "A1020", "Special Foundations", "", "", "", ""],
    ["Shell", "B1020", "Roof Construction", "Invented roof", "SF", "$9,61", "1200"],
    ["Shell", "B2010.PW", "Exterior Walls", "Invented plaster wall", "SF", "$13,33", ""],
    ["Shell", "B2010.CW", "Exterior Walls", "Invented curtain wall", "SF", "$175,00", ""],
    ["Shell", "B3010", "Roof Coverings", "Invented roofing", "SF", "30", ""],
    ["Interiors", "C1030", "Fittings", "Invented toilet partition", "EA", "$7.500,00", ""],
    ["Interiors", "C2010", "Stair Construction", "Invented stair", "Flight", "$1,000.50", "2"],
    ["Services", "D5030", "Communication & Security", "Invented Fire Protection Systems", "GSF",
     "$8,00", "1000"],
    ["Services", "D5090", "Other Electrical Systems", "Invented HVAC Systems", "GSF", "$6,00",
     "1000"],
    ["Services", "D2010", "Plumbing Fixtures", "Invented fixtures", "EA", "$500,00", ""],
    ["Special Contruction", "F2000", "Facade Extra", "Invented panels", "SF", "25", "10"],
    ["General Conditions", "H4000", "General Conditions", "Invented GC", "EA",
     "$1.234.567,89", "1"],
    ["", "", "", "", "", "", ""],
]


def _old(rows=OLD_ROWS) -> list[dict]:
    return [dict(zip(OLD_HEADER, r, strict=True)) for r in rows]


def _write_old(path, rows=OLD_ROWS):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(OLD_HEADER)
        w.writerows(rows)


@pytest.mark.parametrize("val, expected", [
    ("$6.184,22", (6184.22, "6184.22")),       # German: period thousands, comma decimal
    ("$25,00", (25.0, "25.00")),
    ("$1,000.00", (1000.0, "1000.00")),        # US
    ("$1.670.000,00", (1670000.0, "1670000.00")),
    ("750", (750.0, "750")),
    ("", (None, "")),
    ("n/a", (None, "")),
])
def test_parse_cost(val, expected):
    assert parse_cost(val) == expected


def test_convert_rows():
    m = convert_rows(_old())
    assert m.errors == []
    by = {r["assembly_code"]: r for r in m.rows}
    assert len(m.rows) == 13  # blank row skipped
    assert (by["A1030"]["unit_cost"], by["A1030"]["quantity_rule"]) == ("25.00", "takeoff")
    assert by["B1020"]["quantity_rule"] == "fixed" and by["B1020"]["quantity_value"] == "1200"
    assert by["B2010.CW"]["split_keywords"] == "storefront|curtain wall|curtain|glazing"
    assert by["B2010.PW"]["split_keywords"] == "*"
    assert by["B3010"]["quantity_rule"] == "mirror:B1020"
    assert by["C1030"]["quantity_rule"] == "count_codes:D2010"
    assert by["C1030"]["qty_label"] == "Toilet elements (D2010)"
    assert by["C2010"]["unit_cost"] == "1000.50"                  # fixed wins over takeoff
    assert (by["D2010"]["quantity_rule"], by["D2010"]["quantity_value"],
            by["D2010"]["qty_label"]) == ("fixed", "", "Fixed only (none set)")
    assert by["F2000"]["cluster"] == "Special Construction"
    # GC lump sum: fixed row with the exact old amount
    assert (by["H4000"]["unit_cost"], by["H4000"]["quantity_rule"],
            by["H4000"]["quantity_value"]) == ("1234567.89", "fixed", "1")
    assert m.warnings == ["row 13 (F2000): cluster 'Special Contruction' written as "
                          "'Special Construction'."]


def test_mirror_with_non_area_unit_warns():
    rows = [["Interiors", "C3010", "Wall Finishes", "Invented trim", "LF", "2", ""]]
    m = convert_rows(_old(rows))
    assert "mirror now uses the unit" in m.warnings[0]


def test_unparsable_numbers_are_errors(tmp_path):
    rows = [["Shell", "B1020", "Roof", "Invented", "SF", "abc", "1,2x"]]
    m = convert_rows(_old(rows))
    assert m.errors == ["row 2 (B1020): Total O&P 'abc' is not a number.",
                        "row 2 (B1020): Fixed Quantity '1,2x' is not a number."]
    _write_old(tmp_path / "old.csv", rows)
    migration, db = migrate(tmp_path / "old.csv", tmp_path / "new.csv")
    assert db is None and not (tmp_path / "new.csv").exists()


def test_migrate_validates_and_lists_mislabels(tmp_path, capsys):
    _write_old(tmp_path / "old.csv")
    assert main([str(tmp_path / "old.csv"), str(tmp_path / "new.csv")]) == 0
    out = capsys.readouterr().out
    assert "Converted 13 rows" in out
    assert "Mislabelled codes (kept as they are, 2):" in out
    assert "D5030 'Invented Fire Protection Systems': D5030 is Communications & Security " \
           "(D50); the description points to D40 Fire Protection" in out
    assert "D5090 'Invented HVAC Systems': D5090 is Other Electrical Systems (D50); the " \
           "description points to D30 HVAC" in out
    assert "0 errors," in out
    header = (tmp_path / "new.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.endswith("split_keywords,qty_label")


# ── reference mode: the fetched Island cost_data.csv ─────────────────────────────────────


def test_island_cost_data_converts_with_0_errors(tmp_path, autotvd_dir, capsys):
    new = tmp_path / "cost_db.csv"
    assert main([str(autotvd_dir / "cost_data.csv"), str(new), "--config",
                 str(ISLAND_CONFIG)]) == 0
    out = capsys.readouterr().out
    assert "0 errors," in out
    migration, db = migrate(autotvd_dir / "cost_data.csv", new,
                            custom_clusters=["Equipment Rental"])
    assert db.ok and len(db.lines) == 48
    assert [(m["assembly_code"], m["suggested_group"]) for m in db.mislabels] == [
        ("D5030", "D40"), ("D5090", "D30"),
    ]
    by = {(line.code, line.description): line for line in db.lines}
    # GC and contingency: fixed rows, quantity 1 (amounts compared via the TVD run)
    gc = [line for line in db.lines if line.code in ("H4000", "H5000")]
    assert [(line.quantity_rule, line.quantity_value) for line in gc] == [("fixed", 1.0)] * 2
    assert len(by) == 48  # no exact duplicates incl. description
