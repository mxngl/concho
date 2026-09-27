"""P3.6: a synthetic project mapped only by Uniformat codes with the default table
(``template/stv_mapping.csv``), end to end: mapping → engine → ``mapping_coverage``; CLI with
the default table, ``--combine-results``; catalog check of the shipped tables.

The exports and all LCA numbers here are invented (no course data); the reference data only
uses the catalog *names* that the default table refers to.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import pytest

from engines.stv import STVEngine, STVInputs, cli
from engines.stv.coverage import build_mapping_coverage
from engines.stv.mapping import DEFAULT_MAPPING_PATH, load_stv_mapping
from engines.stv.models import ImpactVector
from engines.stv.reference import (
    TEMPLATE_ENV_VAR,
    FuelRecord,
    MaterialRecord,
    STVReferenceData,
    TeamFactors,
)
from engines.stv.revit_architecture import load_architecture_schedule
from engines.stv.revit_structural import load_structural_schedule

REPO_ROOT = Path(__file__).resolve().parents[2]
ISLAND_MAPPING = REPO_ROOT / "engines" / "stv" / "examples" / "island" / "stv_mapping.csv"
TEAM = "Testteam"
LIST_NAMES = {"Column": "Columns", "Beam": "Beams"}

STRUCTURAL = [
    # ElementId, Category, Family, Type, Material, Assembly Code, Area, Volume
    ("101", "Structural Foundations", "Footing-Rectangular", "6' x 6' x 18\"", "Concrete",
     "A1010", "", "54 CF"),
    ("102", "Structural Foundations", "", "Slab 8\"", "Concrete", "A1030", "", "270 CF"),
    ("103", "Structural Columns", "Concrete-Square-Column", "18x18", "Concrete", "B1010", "",
     "27 CF"),
    ("104", "Structural Framing", "Concrete-Rectangular Beam", "12x24", "Concrete", "B1010",
     "", "13.5 CF"),
    ("105", "Structural Framing", "W-Wide Flange", "W12x26", "Steel", "B1010", "", "2 CF"),
    ("106", "Parts", "", "", "Concrete", "", "", "5 CF"),
    ("201", "Floors", "", "Concrete 8\"", "Concrete", "B1010", "1000 SF", "666 CF"),
]
ARCHITECTURE = [
    ("201", "Floors", "", "Concrete 8\"", "Concrete", "B1010", "1000 SF", "666 CF"),
    ("202", "Floors", "", "CLT 5-ply", "Cross laminated timber", "B1010", "500 SF", "250 CF"),
    ("203", "Walls", "", "EIFS on metal studs", "EIFS; Metal Stud Layer", "B2010", "800 SF",
     "400 CF"),
    ("204", "Walls", "", "Brick veneer", "Brick; Steel Stud Layer", "B2010", "300 SF",
     "200 CF"),
    ("205", "Roofs", "", "EPDM on deck", "EPDM membrane", "B3010", "1000 SF", "300 CF"),
    ("206", "Walls", "", "Partition", "Metal Stud Layer; Gypsum", "C1010", "1200 SF",
     "500 CF"),
    ("207", "Floors", "", "Carpet tile", "Carpet", "C3020", "400 SF", "5 CF"),
    ("208", "Walls", "", "Generic 6\"", "Default Wall", "", "150 SF", "75 CF"),
    ("209", "Windows", "Fixed", "36x48", "Glass", "B2020", "", ""),
    ("210", "Furniture", "Desk", "60x30", "Wood", "E2010", "", ""),
]
HEADER = ["ElementId", "Category", "Family", "Type", "Material", "Assembly Code", "Area",
          "Volume"]


def _write(path: Path, rows) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    return path


def _material(assembly: str, material_type: str) -> MaterialRecord:
    v = ImpactVector(carbon=1.0, energy=10.0, water=100.0, ozone=0.001)
    return MaterialRecord(assembly, material_type, v.scale(3), v, v, v, 1.0)


@pytest.fixture
def default_reference() -> STVReferenceData:
    names = set()
    with DEFAULT_MAPPING_PATH.open(encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    for row in csv.DictReader(lines):
        assembly = {"Columns": "Column", "Beams": "Beam"}.get(row["stv_assembly"],
                                                               row["stv_assembly"])
        names.add((assembly, row["stv_material_type"]))
    records = [_material(a, m) for a, m in sorted(names)]
    materials = {(r.assembly, r.material_type): r for r in records}
    by_name: dict[str, list[MaterialRecord]] = {}
    valid: dict[str, set[str]] = {}
    for r in records:
        by_name.setdefault(r.material_type, []).append(r)
        valid.setdefault(LIST_NAMES.get(r.assembly, r.assembly), set()).add(r.material_type)
    team = TeamFactors(TEAM, ImpactVector(0.5, 5.0, 1.0, 0.0), 0.1, 1000.0, 0.1)
    fuel = FuelRecord("Test Gas", 1.0, 0.0, 40.0, 0.05)
    return STVReferenceData(materials, by_name, valid, {TEAM: team}, {"Test Gas": fuel})


@pytest.fixture
def exports(tmp_path) -> dict[str, Path]:
    return {
        "structural": _write(tmp_path / "struct.csv", STRUCTURAL),
        "architecture": _write(tmp_path / "arch.csv", ARCHITECTURE),
    }


def test_synthetic_project_with_default_table(default_reference, exports):
    mapping = load_stv_mapping(DEFAULT_MAPPING_PATH, catalog=default_reference)
    assert mapping.warnings == []
    reports = [load_structural_schedule(exports["structural"], mapping),
               load_architecture_schedule(exports["architecture"], mapping)]
    items: dict[tuple[str, str], float] = {}
    for i in (i for r in reports for i in r.construction_items):
        key = (i.assembly, i.material_type)
        items[key] = items.get(key, 0) + i.amount
    assert items == {
        ("Foundation", "Strip Foundation (cy)"): pytest.approx(2.0),
        ("Foundation", "Concrete Slab (cy)"): pytest.approx(10.0),
        ("Columns", "Reinforced Concrete Column (cy)"): pytest.approx(1.0),
        ("Beams", "Reinforced Concrete Beam (cy)"): pytest.approx(0.5),
        ("Floor", "Concrete (sf)"): 2000.0,  # element 201 is in both exports
        ("Floor", "Wood System (sf)"): 500.0,
        ("Exterior Wall", "EIFS on Metal Stud (sf)"): 800.0,
        ("Exterior Wall", "Brick on Metal Stud (sf)"): 300.0,
        ("Roof", "EPDM Membrane (sf)"): 1000.0,
        ("Interior Wall", "Steel Studs and Painted Gypsum (sf)"): 1200.0,
        ("Floor", "Carpet (sf)"): 400.0,
    }

    payload = {"team": TEAM, "construction_items": [
        {"assembly": i.assembly, "material_type": i.material_type, "amount": i.amount}
        for r in reports for i in r.construction_items]}
    results = STVEngine(default_reference).calculate(STVInputs.from_dict(payload))
    coverage = build_mapping_coverage(reports, mapping, results)

    struct = coverage["disciplines"]["structural"]
    assert struct["elements"] == {"total": 7, "mapped": 5, "zero_quantity": 0, "unmapped": 2,
                                  "mapped_pct": pytest.approx(500 / 7)}
    assert struct["by_quantity"]["volume_cf"]["total"] == pytest.approx(1037.5)
    assert struct["by_quantity"]["volume_cf"]["mapped"] == pytest.approx(1030.5)
    assert [(t["category"], t["family"], t["count"]) for t in struct["unmapped_types"]] == [
        ("Parts", "", 1), ("Structural Framing", "W-Wide Flange", 1)]
    arch = coverage["disciplines"]["architecture"]
    assert arch["elements"]["mapped"] == 7 and arch["elements"]["unmapped"] == 3
    assert {t["category"] for t in arch["unmapped_types"]} == {"Walls", "Windows", "Furniture"}
    assert arch["estimated"]["elements"] == 0 and arch["estimated"]["kgco2e"] == 0
    # 3 kgCO2e per unit (invented), mapped amounts only.
    assert struct["kgco2e"] == pytest.approx(3 * (2 + 10 + 1 + 0.5 + 1000))
    assert coverage["total"]["elements"]["total"] == 17
    assert coverage["total"]["kgco2e"] == pytest.approx(results.breakdown.embodied.carbon)
    (cross,) = coverage["cross_discipline_elements"]
    assert cross["element_id"] == "201"
    assert [o["status"] for o in cross["occurrences"]] == ["mapped", "mapped"]
    wood, concrete = (r for r in coverage["rules"] if r["category"] == "Floors"
                      and r["assembly_code"] == "B1010")
    assert (wood["won"], concrete["won"], concrete["lost_to_priority"]) == (1, 2, 0)


def _run_cli(monkeypatch, reference, *args: str) -> None:
    monkeypatch.setattr(STVReferenceData, "from_workbook",
                        staticmethod(lambda path=None: reference))
    monkeypatch.setattr(sys, "argv", ["concho-stv", *args])
    cli.main()


def test_cli_uses_default_table_and_writes_coverage(monkeypatch, tmp_path, default_reference,
                                                    exports, capsys):
    template = tmp_path / "course.xlsx"
    template.write_bytes(b"")
    monkeypatch.setenv(TEMPLATE_ENV_VAR, str(template))
    out = {}
    for trade in ("structural", "architecture"):
        out[trade] = tmp_path / trade
        _run_cli(monkeypatch, default_reference, "--team", TEAM, "--output-dir",
                 str(out[trade]), f"--{trade}-schedule", str(exports[trade]))
        assert "using the default table" in capsys.readouterr().err
        result = json.loads((out[trade] / "stv_results.json").read_text(encoding="utf-8"))
        assert list(result["mapping_coverage"]["disciplines"]) == [trade]
        assert all("estimated" in i for i in result["construction_items"])

    combined = tmp_path / "project"
    _run_cli(monkeypatch, default_reference, "--output-dir", str(combined),
             "--combine-results", *(str(out[t] / "stv_results.json") for t in out))
    result = json.loads((combined / "stv_results.json").read_text(encoding="utf-8"))
    coverage = result["mapping_coverage"]
    assert list(coverage["disciplines"]) == ["architecture", "structural"]
    assert coverage["total"]["elements"]["total"] == 17
    assert coverage["cross_discipline_elements"] is None
    assert "one concho-stv call" in coverage["cross_discipline_note"]
    rule_won = {r["row"]: r["won"] for r in coverage["rules"]}
    assert sum(rule_won.values()) == 12


def test_cli_tie_and_bad_mapping_stop(monkeypatch, tmp_path, default_reference, exports,
                                      capsys):
    template = tmp_path / "course.xlsx"
    template.write_bytes(b"")
    monkeypatch.setenv(TEMPLATE_ENV_VAR, str(template))
    tie = tmp_path / "tie.csv"
    tie.write_text(
        "assembly_code,category,keyword,stv_assembly,stv_material_type,quantity_field,"
        "conversion,note\n"
        "B1010,Floors,concrete,Floor,Concrete (sf),area,,\n"
        "B1010,Floors,8,Floor,Wood System (sf),area,,\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        _run_cli(monkeypatch, default_reference, "--team", TEAM, "--output-dir",
                 str(tmp_path / "o"), "--architecture-schedule", str(exports["architecture"]),
                 "--stv-mapping", str(tie))
    err = capsys.readouterr().err
    assert "tie: element 201" in err and "row 2" in err and "row 3" in err

    bad = tmp_path / "bad.csv"
    bad.write_text(tie.read_text(encoding="utf-8").replace("Wood System", "Wood Sytem"),
                   encoding="utf-8")
    with pytest.raises(SystemExit):
        _run_cli(monkeypatch, default_reference, "--team", TEAM, "--output-dir",
                 str(tmp_path / "o"), "--architecture-schedule", str(exports["architecture"]),
                 "--stv-mapping", str(bad))
    assert "not in the course LCA catalog for 'Floor'" in capsys.readouterr().err


@pytest.mark.skipif(not os.environ.get(TEMPLATE_ENV_VAR),
                    reason=f"{TEMPLATE_ENV_VAR} not set (course workbook must be supplied "
                           "locally)")
@pytest.mark.parametrize("path", [DEFAULT_MAPPING_PATH, ISLAND_MAPPING], ids=["default", "island"])
def test_shipped_tables_match_the_course_catalog(path):
    catalog = STVReferenceData.from_workbook(os.environ[TEMPLATE_ENV_VAR])
    mapping = load_stv_mapping(path, catalog=catalog)
    assert mapping.warnings == []
