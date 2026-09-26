"""Smoke test: every schedule step runs via ``concho-schedule`` on an invented mini project.

The inputs come from ``mini_project.py`` (invented, not Island or course data). The Manufacton
templates are generated here with the column layout the adapters check; the real templates
are never committed. Runs in CI.
"""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from mini_project import write_mini_project
from openpyxl import Workbook

from engines.schedule.adapters.manufacton import assembly_import, kit_import, parts_import
from engines.schedule.cli import STEPS, main

EXAMPLES = Path(__file__).resolve().parents[2] / "engines" / "schedule" / "examples" / "island"


def _template(path: Path, columns: list[str], sheet: str = "Sheet1") -> Path:
    workbook = Workbook()
    workbook.active.title = sheet
    workbook.active.append(columns)
    workbook.save(path)
    return path


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _run(*args: object) -> None:
    assert main([str(arg) for arg in args]) == 0


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Run all 14 steps in pipeline order; return the output folders."""
    root = tmp_path_factory.mktemp("schedule_pipeline")
    inp = write_mini_project(root)
    tpl = root / "templates"
    tpl.mkdir()
    out = {name: root / "out" / name for name in
           ["model", "alice", "prefab", "micro", "fuzor", "manufacton", "delivery", "takt",
            "viewers"]}
    model, micro = out["model"], out["micro"]
    bim = model / "central_bim_model_with_takt.csv"
    context = model / "central_bim_model_llm_context.csv"
    micro_csv = micro / "Micro_Schedule.csv"
    build_codes = out["fuzor"] / "Revit_4D_Build_Code_Map.csv"
    mf = out["manufacton"]

    _run("takt-zones", "--schedules-dir", inp["schedules_dir"],
         "--takt-zones", inp["takt_zones"], "--out-dir", model)
    _run("llm-context", "--central-bim-with-takt", bim, "--out-dir", model)
    _run("prefab-walls", "--central-bim-with-takt", bim, "--out-dir", out["prefab"])
    _run("micro-schedule", "--macro-schedule", inp["macro"], "--tasks", inp["tasks"],
         "--crew", inp["crew"], "--equipment", inp["equipment"], "--bim-map", inp["bim_map"],
         "--central-bim-with-takt", bim, "--llm-context", context,
         "--prefab-wall-mapping", out["prefab"] / "Prefab_Wall_Mapping.csv",
         "--rules", EXAMPLES / "micro_schedule_rules.json", "--out-dir", micro)
    _run("alice-p6-xml", "--micro-schedule", micro_csv, "--out-dir", out["alice"])
    _run("fuzor-xml", "--micro-schedule", micro_csv, "--tasks", inp["tasks"],
         "--crew", inp["crew"], "--equipment", inp["equipment"], "--out-dir", out["fuzor"])
    _run("manufacton-parts",
         "--template", _template(tpl / "parts.xlsx", parts_import.OUTPUT_COLUMNS),
         "--central-bim-with-takt", bim, "--micro-schedule", micro_csv, "--out-dir", mf)
    _run("manufacton-assemblies",
         "--template", _template(tpl / "assembly.xlsx", assembly_import.OUTPUT_COLUMNS),
         "--parts-import", mf / "Parts_Import.xlsx", "--parts-summary", mf / "Parts_Summary.csv",
         "--micro-schedule", micro_csv, "--central-bim-with-takt", bim,
         "--build-code-map", build_codes, "--out-dir", mf)
    _run("manufacton-orders",
         "--order-template", _template(tpl / "order.xlsx", kit_import.OUTPUT_COLUMNS, "ORDERS"),
         "--item-template",
         _template(tpl / "item.xlsx", kit_import.ITEM_OUTPUT_COLUMNS, "ITEMS"),
         "--vendors", EXAMPLES / "vendors.csv", "--mapping", inp["build_code_mapping"],
         "--assembly-import", mf / "Assembly_Import.xlsx",
         "--parts-summary", mf / "Parts_Summary.csv", "--build-code-map", build_codes,
         "--micro-schedule", micro_csv, "--llm-context", context, "--out-dir", mf)
    _run("delivery-windows", "--micro-schedule", micro_csv, "--llm-context", context,
         "--production-order", mf / "Production_Order.xlsx",
         "--production-order-items", mf / "Production_Order_Items.xlsx",
         "--kit-map", mf / "Revit_Kit_Parameter_Map.csv",
         "--assembly-map", mf / "Revit_Assembly_Id_Map.csv", "--out-dir", out["delivery"])
    _run("takt-plan", "--central-bim", model / "central_bim_model.csv",
         "--room-takt-zones", inp["room_takt_zones"], "--crew", inp["crew"],
         "--equipment", inp["equipment"], "--out-dir", out["takt"])
    _run("takt-viewer", "--micro-schedule", micro_csv, "--out-dir", out["viewers"])
    _run("spatial-viewer", "--micro-schedule", micro_csv, "--out-dir", out["viewers"])
    return out


def test_cli_lists_every_step(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    listing = capsys.readouterr().out
    assert all(step in listing for step in STEPS)
    assert len(STEPS) == 14


def test_cli_rejects_unknown_step() -> None:
    assert main(["no-such-step"]) == 2


def test_takt_zones_assigns_elements_to_zones(pipeline: dict[str, Path]) -> None:
    rows = {row["ElementId"]: row for row in
            _rows(pipeline["model"] / "central_bim_model_with_takt.csv")}
    assert len(rows) == 12
    assert rows["2001"]["takt_id"] == "L 1 Zone 1"
    assert rows["1009"]["takt_id"] == "L 1 Zone 2"
    assert (pipeline["model"] / "central_bim_model.csv").exists()
    # Given --takt-zones, the zones are reused, not recalibrated.
    assert not (pipeline["model"] / "takt_zones.json").exists()


def test_takt_zone_polygon_drops_last_corner() -> None:
    """Characterizes a bug kept from the original calibrator (fix in Phase 3B).

    ``assign_takt_ids`` builds ``MplPath(corners, closed=True)``, which uses the last corner
    as the close code, so an open ring of N corners is treated as N-1 corners. The Island
    ``takt_zones.json`` stores open rings (see engines/schedule/README.md, "Findings").
    """
    import pandas as pd

    from engines.schedule.core.takt_zones import assign_takt_ids

    square = [[0, 0], [10, 0], [10, 10], [0, 10]]
    elements = pd.DataFrame(
        {"Level": ["L 1", "L 1"], "Bounding Box Center X (ft)": [8.0, 2.0],
         "Bounding Box Center Y (ft)": [2.0, 8.0]}
    )
    open_ring = assign_takt_ids(elements, {"L 1": [{"zone_name": "Z", "corners_model_xy": square}]})
    # (2, 8) lies in the square but outside the triangle (0,0)-(10,0)-(10,10).
    assert list(open_ring["takt_id"]) == ["Z", ""]
    closed = assign_takt_ids(
        elements, {"L 1": [{"zone_name": "Z", "corners_model_xy": [*square, square[0]]}]}
    )
    assert list(closed["takt_id"]) == ["Z", "Z"]


def test_llm_context_derives_disciplines(pipeline: dict[str, Path]) -> None:
    rows = {row["element_id"]: row for row in
            _rows(pipeline["model"] / "central_bim_model_llm_context.csv")}
    assert rows["2001"]["discipline"] == "Structural"
    assert rows["1009"]["discipline"] == "MEP"
    assert rows["1001"]["discipline"] == "Architecture"


def test_prefab_walls_group_panels_with_host(pipeline: dict[str, Path]) -> None:
    rows = _rows(pipeline["prefab"] / "Prefab_Wall_Mapping.csv")
    hosts = {row["element_id"]: row["host_wall_element_id"] for row in rows}
    assert hosts["1003"] == hosts["1004"] == "1001"
    assert len({row["prefab_group_id"] for row in rows}) == 2


def test_micro_schedule(pipeline: dict[str, Path]) -> None:
    rows = _rows(pipeline["micro"] / "Micro_Schedule.csv")
    assert min(row["element_start"] for row in rows) == "2029-10-01T09:00:00"
    tasks = {row["task_name"] for row in rows}
    assert tasks == {"Install Construction Fencing", "Frame: Columns", "Exterior Wall Install",
                     "Interior Walls", "MEP Rough-In", "Ceiling Installation"}
    # Curtain panel + mullion are installed with their prefab host wall, not by the glazing task.
    panel = [row for row in rows if row["element_id"] == "1003"]
    assert {row["task_name"] for row in panel} == {"Exterior Wall Install"}
    assert panel[0]["prefab_group_id"]
    log = (pipeline["micro"] / "Micro_Schedule_Log.md").read_text(encoding="utf-8")
    assert "A400 Glass Install + Glazing`: no BIM elements matched" in log


def test_alice_p6_xml(pipeline: dict[str, Path]) -> None:
    root = ET.parse(pipeline["alice"] / "ALICE_Task_Schedule.xml").getroot()
    activities = [el for el in root.iter() if el.tag.endswith("}Activity")]
    macro_view = _rows(pipeline["alice"] / "ALICE_Task_Schedule_Macro_View.csv")
    assert len(activities) == len(macro_view) == 6


def test_fuzor_xml_and_build_codes(pipeline: dict[str, Path]) -> None:
    ET.parse(pipeline["fuzor"] / "Fuzor_Micro_Schedule.xml")
    codes = {row["element_id"]: row["build_code"] for row in
             _rows(pipeline["fuzor"] / "Revit_4D_Build_Code_Map.csv")}
    assert codes["1001"] == "Exterior Wall Install | L 1 | PREFAB_WALL_L1_001"


def test_manufacton_outputs(pipeline: dict[str, Path]) -> None:
    mf = pipeline["manufacton"]
    for name in ["Parts_Import.xlsx", "Parts_Import.csv", "Parts_Summary.csv",
                 "Assembly_Import.xlsx", "Production_Order.xlsx", "Production_Order_Items.xlsx"]:
        assert (mf / name).exists(), name
    kits = {row["element_id"]: row["kit_id"] for row in
            _rows(mf / "Revit_Kit_Parameter_Map.csv")}
    assert kits["1001"] == kits["1003"]


def test_delivery_windows(pipeline: dict[str, Path]) -> None:
    metrics = {row["window"] for row in
               _rows(pipeline["delivery"] / "delivery_window_summary_metrics.csv")}
    assert {"1 day", "1 week"} <= metrics
    orders = _rows(pipeline["delivery"] / "production_order_count_by_delivery_window.csv")
    assert {row["window"] for row in orders} == {"1 day", "3 days", "1 week"}


def test_takt_plan(pipeline: dict[str, Path]) -> None:
    takt = pipeline["takt"]
    assert len(_rows(takt / "Takt_Zones.csv")) == 2
    schedule = _rows(takt / "Takt_Schedule.csv")
    assert len(schedule) == 2 * 5  # zones x (walls, MEP, ceiling, doors, finishes)
    assert schedule[0]["start"] == "2030-01-02T09:00"
    for name in ["Takt_Report.md", "Takt_Planner.html", "Takt_Zone_Map_L_1.png",
                 "Takt_Productivity_Rates.csv"]:
        assert (takt / name).exists(), name


def test_viewers(pipeline: dict[str, Path]) -> None:
    for name in ["Micro_Schedule_Takt_Viewer.html", "spatial_visualizer_micro.html"]:
        html = (pipeline["viewers"] / name).read_text(encoding="utf-8")
        assert "</html>" in html.lower(), name


def test_alice_inputs_from_workbook(tmp_path: Path) -> None:
    """Invented ALICE export workbook -> Macro_Schedule / Tasks / Crew / Equipment CSVs."""
    workbook = Workbook()
    sheets = {
        "Tasks": [["Id*", "Name*", "Planned Start Date - read only",
                   "Planned End Date - read only", "Alice WBS Id*"],
                  ["A200", "Frame: Columns", "2029-10-03", "2029-10-05", "W1"],
                  ["A100", "Install Construction Fencing", "2029-10-01", "2029-10-02", "W1"]],
        "Crews": [["Name*", "Available quantity", "Cost per crew per hr*", "Calendar*"],
                  ["Structural Crew", 2, 150, "Default calendar"]],
        "Equipment": [["Name*", "Available quantity", "Cost per hr*"], ["Mobile Crane", 1, 300]],
        "Task Crews": [["Task Id*", "Alice Crew Name*", "Required Amount"],
                       ["A200", "Structural Crew", 1]],
        "Task Equipment": [["Task Id*", "Alice Equipment Name*"], ["A200", "Mobile Crane"]],
    }
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    path = tmp_path / "alice_export.xlsx"
    workbook.save(path)

    _run("alice-inputs", "--workbook", path, "--out-dir", tmp_path / "out")
    macro = _rows(tmp_path / "out" / "Macro_Schedule.csv")
    assert [row["task_id"] for row in macro] == ["A100", "A200"]
    assert macro[1]["crew_type"] == "structural_crew"
    assert macro[1]["equipment_type"] == "mobile_crane"
    crew = _rows(tmp_path / "out" / "Crew.csv")
    assert crew == [{"crew_type": "structural_crew", "count": "2", "cost": "150",
                     "hours": "9,10,11,12,13,14,15,16,17"}]
    assert (tmp_path / "out" / "Missing_data.md").exists()
