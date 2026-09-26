"""Invented mini project for the schedule smoke tests (not Island data, not course data).

One level ("L 1"), two takt zones / rooms, 12 elements: exterior walls with a curtain panel
and mullion (one prefab group), interior walls, a door, a ceiling, a duct and three timber
columns. Written to ``tmp_path`` at test time; nothing here is committed as data files.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REVIT_COLUMNS = [
    "ElementId", "Category", "Family", "Type", "Level", "Assembly Code",
    "Assembly Description", "Area", "Volume",
    "Position X (ft)", "Position Y (ft)", "Position Z (ft)",
    "Bounding Box Min X (ft)", "Bounding Box Min Y (ft)", "Bounding Box Min Z (ft)",
    "Bounding Box Max X (ft)", "Bounding Box Max Y (ft)", "Bounding Box Max Z (ft)",
    "Bounding Box Center X (ft)", "Bounding Box Center Y (ft)", "Bounding Box Center Z (ft)",
    "Room Id", "Room Number", "Room Name", "Room Level", "Material",
]


def _element(element_id, category, family, type_name, box, area="", volume="", room=None):
    """box = (min_x, min_y, min_z, max_x, max_y, max_z)."""
    min_x, min_y, min_z, max_x, max_y, max_z = box
    center = ((min_x + max_x) / 2, (min_y + max_y) / 2, (min_z + max_z) / 2)
    room_id, room_number, room_name = room or ("", "", "")
    return [
        element_id, category, family, type_name, "L 1", "", "", area, volume,
        *center, min_x, min_y, min_z, max_x, max_y, max_z, *center,
        room_id, room_number, room_name, "L 1" if room_id else "", "",
    ]


ROOM_1 = ("R1", "101", "Office")
ROOM_2 = ("R2", "102", "Lab")
EXT = 'Generic - 8" - EXTERIOR'
INT = 'Generic - 8" - INTERIOR'

ARCHITECTURE = [
    _element(1001, "Walls", "Basic Wall", EXT, (0, -0.5, 0, 20, 0.5, 12), "240 SF", "160 CF"),
    _element(1002, "Walls", "Basic Wall", EXT, (20, -0.5, 0, 40, 0.5, 12), "240 SF", "160 CF"),
    _element(1003, "Curtain Panels", "System Panel", "Glazed", (4, -0.1, 0, 6, 0.1, 12), "24 SF"),
    _element(1004, "Curtain Wall Mullions", "Rectangular Mullion", '2.5" x 5"',
             (9.9, -0.1, 0, 10.1, 0.1, 12)),
    _element(1005, "Walls", "Basic Wall", INT, (19.75, 0, 0, 20.25, 20, 12), "240 SF", "160 CF",
             ROOM_1),
    _element(1006, "Walls", "Basic Wall", INT, (0, 9.75, 0, 20, 10.25, 12), "240 SF", "160 CF",
             ROOM_1),
    _element(1007, "Doors", "Single-Flush", '36" x 84"', (9.5, 9.9, 0, 10.5, 10.1, 7), "",
             "", ROOM_1),
    _element(1008, "Ceilings", "Compound Ceiling", "2x2 ACT", (0, 0, 10.9, 20, 20, 11.1),
             "400 SF", "80 CF", ROOM_1),
    _element(1009, "Ducts", "Rectangular Duct", "Supply", (25, 9, 10, 35, 11, 11), "", "",
             ROOM_2),
]
STRUCTURAL = [
    _element(2001, "Structural Columns", "Timber-Column", "12x12", (-0.5, -0.5, 0, 0.5, 0.5, 12),
             "", "12 CF"),
    _element(2002, "Structural Columns", "Timber-Column", "12x12", (19.5, -0.5, 0, 20.5, 0.5, 12),
             "", "12 CF"),
    _element(2003, "Structural Columns", "Timber-Column", "12x12", (39.5, -0.5, 0, 40.5, 0.5, 12),
             "", "12 CF"),
]

# Rings repeat their first corner: the calibrator treats the last corner as the "close"
# code and drops it (see test_takt_zone_polygon_drops_last_corner).
ZONE_1 = [[-1, -1], [20, -1], [20, 21], [-1, 21], [-1, -1]]
ZONE_2 = [[20, -1], [41, -1], [41, 21], [20, 21], [20, -1]]
TAKT_ZONES = {
    "levels": {
        "L 1": [
            {"zone_name": "L 1 Zone 1", "corners_model_xy": ZONE_1},
            {"zone_name": "L 1 Zone 2", "corners_model_xy": ZONE_2},
        ]
    }
}

HOURS = "9,10,11,12,13,14,15,16,17"

# Hand-written macro schedule in the simplified format (no ALICE needed).
MACRO = [
    ["task_id", "task_name", "start_date", "end_date", "crew_type", "equipment_type"],
    ["A100", "Install Construction Fencing", "2029-10-01", "2029-10-02", "site_setup_crew", ""],
    ["A200", "Frame: Columns", "2029-10-03", "2029-10-05", "structural_crew", "mobile_crane"],
    ["A300", "Exterior Wall Install", "2029-10-08", "2029-10-10", "facade_install_crew",
     "mobile_crane"],
    ["A400", "Glass Install + Glazing", "2029-10-11", "2029-10-12", "facade_install_crew", ""],
    ["A500", "Interior Walls", "2029-10-11", "2029-10-15", "interiors_crew", ""],
    ["A600", "MEP Rough-In", "2029-10-11", "2029-10-15", "mep_rough_in_crew", ""],
    ["A700", "Ceiling Installation", "2029-10-16", "2029-10-17", "interiors_crew", ""],
]
TASKS = [["task_name", "crew_type", "crew_num_req", "equipment_type"]] + [
    [row[1], row[4], "1", row[5]] for row in MACRO[1:]
]
CREWS = [
    ["crew_type", "count", "cost", "hours"],
    *[[crew, "1", "100", HOURS] for crew in
      ["site_setup_crew", "structural_crew", "facade_install_crew", "interiors_crew",
       "mep_rough_in_crew"]],
]
EQUIPMENT = [["equipment_type", "count", "cost"], ["mobile_crane", "1", "200"]]
BIM_MAP = [
    ["ALICE_task", "BIM_map", " productivity", " unit", " productivity_dependency"],
    ["Install Construction Fencing", "", "", "", ""],
    ["Frame: Columns", "Category:Structural Columns, Family:Timber-Column", "3", "count",
     "equipment"],
    ["Exterior Wall Install", f"Category:Walls, Type:{EXT}", "2", "count", "equipment"],
    ["Glass Install + Glazing", "Category:Curtain Panels | Category:Curtain Wall Mullions", "4",
     "count", "equipment"],
    ["Interior Walls", f"Category:Walls, Type:{INT}", "2", "count", "crew"],
    ["MEP Rough-In", "discipline:MEP", "3", "count", "crew"],
    ["Ceiling Installation", "Category:Ceilings", "2", "count", "crew"],
]
ROOM_TAKT_ZONES = [
    ["room_takt_id", "room_id", "room_number", "room_name", "level", "area_sf", "volume_cf",
     "location_x_ft", "location_y_ft", "location_z_ft"],
    ["L 1 Room 101", "R1", "101", "Office", "L 1", "400", "4800", "10", "10", "0"],
    ["L 1 Room 102", "R2", "102", "Lab", "L 1", "400", "4800", "30", "10", "0"],
]


def _write_csv(path: Path, rows: list[list[object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    return path


def write_mini_project(root: Path) -> dict[str, Path]:
    """Write the invented project inputs under ``root/inputs``; return their paths."""
    inputs = root / "inputs"
    schedules = inputs / "schedules"
    _write_csv(schedules / "Mini_Architecture_TakeOff.csv", [REVIT_COLUMNS, *ARCHITECTURE])
    _write_csv(schedules / "Mini_Structural_Schedule.csv", [REVIT_COLUMNS, *STRUCTURAL])
    takt_zones = inputs / "takt_zones.json"
    takt_zones.write_text(json.dumps(TAKT_ZONES), encoding="utf-8")
    return {
        "schedules_dir": schedules,
        "takt_zones": takt_zones,
        "macro": _write_csv(inputs / "Macro_Schedule.csv", MACRO),
        "tasks": _write_csv(inputs / "Tasks.csv", TASKS),
        "crew": _write_csv(inputs / "Crew.csv", CREWS),
        "equipment": _write_csv(inputs / "Equipment.csv", EQUIPMENT),
        "bim_map": _write_csv(inputs / "ALICE_BIM_Map.csv", BIM_MAP),
        "room_takt_zones": _write_csv(inputs / "room_takt_zones.csv", ROOM_TAKT_ZONES),
        # Header only: the kit import then derives the prefab-wall mapping itself.
        "build_code_mapping": _write_csv(inputs / "build_code_mapping.csv",
                                         [["build_code", "assembly_id"]]),
    }
