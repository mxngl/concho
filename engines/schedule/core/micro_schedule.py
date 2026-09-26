from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, cast

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
PLANNING_ENGINE_DIR = BASE_DIR.parent
PROJECT_DIR = PLANNING_ENGINE_DIR.parent.parent
ALICE_BIM_MAPPER_DIR = PLANNING_ENGINE_DIR / "ALICE_BIM_mapper"
ALICE_BIM_INPUTS_DIR = ALICE_BIM_MAPPER_DIR / "inputs"
ALICE_BIM_OUTPUTS_DIR = ALICE_BIM_MAPPER_DIR / "outputs"

MACRO_SCHEDULE_PATH = ALICE_BIM_OUTPUTS_DIR / "Macro_Schedule.csv"
LOCAL_INPUTS_DIR = BASE_DIR / "inputs"
LOCAL_ALICE_BIM_MAP_PATH = LOCAL_INPUTS_DIR / "ALICE_BIM_Map.csv"
ALICE_BIM_MAP_PATH = (
    LOCAL_ALICE_BIM_MAP_PATH
    if LOCAL_ALICE_BIM_MAP_PATH.exists()
    else ALICE_BIM_INPUTS_DIR / "ALICE_BIM_Map.csv"
)
TASKS_PATH = ALICE_BIM_OUTPUTS_DIR / "Tasks.csv"
CREW_PATH = ALICE_BIM_OUTPUTS_DIR / "Crew.csv"
EQUIPMENT_PATH = ALICE_BIM_OUTPUTS_DIR / "Equipment.csv"

CENTRAL_BIM_PATH = PROJECT_DIR / "outputs" / "takt_zones" / "central_bim_model_with_takt.csv"
CENTRAL_BIM_CONTEXT_PATH = PROJECT_DIR / "outputs" / "takt_zones" / "central_bim_model_llm_context.csv"
REVIT_SCHEDULES_DIR = PROJECT_DIR / "revit_schedules"
PREFAB_MAPPING_PATH = PLANNING_ENGINE_DIR / "Prefab_BIM_Mapper" / "outputs" / "Prefab_Wall_Mapping.csv"
MICRO_SCHEDULE_PATH = OUTPUTS_DIR / "Micro_Schedule.csv"
MICRO_LOG_PATH = OUTPUTS_DIR / "Micro_Schedule_Log.md"
MICRO_RULES_PATH = BASE_DIR / "inputs" / "micro_schedule_rules.json"


@dataclass
class TaskContext:
    task_id: str
    task_name: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    crew_type: str
    equipment_type: str
    crew_num_req: int
    bim_map: str
    productivity: float
    unit: str
    productivity_dependency: str
    crew_hours: list[int]


@dataclass
class MicroTaskNode:
    node_id: str
    micro_task_name: str
    record: dict[str, object]
    task_elements: pd.DataFrame
    split_attrs: dict[str, str]
    sort_key: tuple[object, ...]


SUPERSTRUCTURE_TASKS = {
    "frame: beams",
    "floor",
    "frame: columns",
    "roof",
}

ENVELOPE_TASKS = {
    "exterior wall install",
    "glass install + glazing",
    "facade install + glazing",
    "mesh install",
}

INTERIOR_TASKS = {
    "interior walls",
    "ceiling installation",
}

MEP_ROUGH_IN_TASKS = {
    "mep rough-in",
}

INITIAL_SITE_TASK = "install construction fencing"

PARALLEL_SITE_TASKS_AFTER_FENCING = {
    "install site office & welfare units",
    "temporary water installation",
    "temporary power installation",
    "tree removal & clearing",
    "bleacher demolition",
    "crane pad construction",
}

EARLY_SITE_CHAIN_TASKS = {
    "laydown area preparation",
    "full basement excavation",
    "shoring / stabilization",
    "subgrade preparation",
}

FOUNDATION_PARALLEL_TASKS = {
    "basement retaining walls",
    "footings - form/rebar/pour",
}

FOUNDATION_CHAIN_TASKS = [
    "foundational columns",
    "grade beams",
    "basement slab on grade",
    "rocking walls",
]

BASEMENT_SUPPORT_TASKS = [
    "waterproofing & drainage",
    "underground utilities",
    "backfill & compaction",
]

BASEMENT_RETAINING_WALL_CURING_DAYS = 7

DEFAULT_MICRO_RULES: dict[str, Any] = {
    "split_rules": [
        {
            "tasks": [
                "Frame: Columns",
                "Frame: Beams",
                "Floor",
                "Roof",
                "Exterior Wall Install",
                "Glass Install + Glazing",
                "Facade Install + Glazing",
                "Mesh Install",
            ],
            "by": ["level"],
        },
        {
            "tasks": [
                "Interior Walls",
                "Ceiling Installation",
                "MEP Rough-In",
            ],
            "by": ["room"],
        }
    ],
    "constraints": [
        {
            "type": "same_start_after",
            "after": {"task": "Install Construction Fencing"},
            "tasks": [
                "Install Site Office & Welfare Units",
                "Temporary Water Installation",
                "Temporary Power Installation",
                "Tree Removal & Clearing",
                "Bleacher Demolition",
                "Crane Pad Construction",
            ],
        },
        {
            "type": "serial",
            "before": {
                "tasks": [
                    "Install Site Office & Welfare Units",
                    "Temporary Water Installation",
                    "Temporary Power Installation",
                    "Tree Removal & Clearing",
                    "Bleacher Demolition",
                    "Crane Pad Construction",
                ]
            },
            "after": {"task": "Laydown Area Preparation"},
        },
        {
            "type": "chain",
            "tasks": [
                "Laydown Area Preparation",
                "Full Basement Excavation",
                "Shoring / Stabilization",
                "Subgrade Preparation",
            ],
        },
        {
            "type": "same_start_after",
            "after": {"task": "Subgrade Preparation"},
            "tasks": ["Footings - Form/Rebar/Pour", "Basement Retaining Walls"],
        },
        {
            "type": "serial",
            "before": {"task": "Basement Retaining Walls"},
            "after": {"task": "Foundational Columns"},
            "lag_days": BASEMENT_RETAINING_WALL_CURING_DAYS,
        },
        {
            "type": "serial",
            "before": {"task": "Footings - Form/Rebar/Pour"},
            "after": {"task": "Foundational Columns"},
        },
        {
            "type": "chain",
            "tasks": [
                "Foundational Columns",
                "Grade Beams",
                "Basement Slab on Grade",
                "Rocking Walls",
            ],
        },
        {
            "type": "chain",
            "tasks": [
                "Basement Retaining Walls",
                "Waterproofing & Drainage",
                "Underground Utilities",
                "Backfill & Compaction",
            ],
            "lag_days": BASEMENT_RETAINING_WALL_CURING_DAYS,
        },
        {
            "type": "serial",
            "before": {"tasks": ["Rocking Walls", "Backfill & Compaction"]},
            "after": {"task": "Frame: Columns"},
        },
        {
            "type": "serial",
            "before": {"tasks": ["Rocking Walls", "Backfill & Compaction"]},
            "after": {"tasks": ["Mechanical Room Buildout", "Main Electrical & Riser Install"]},
        },
        {
            "type": "chain",
            "tasks": ["Frame: Columns", "Frame: Beams", "Floor"],
            "match_by": ["level"],
        },
        {
            "type": "serial",
            "before": {"task": "Frame: Beams"},
            "after": {"task": "Roof"},
            "match_by": ["level"],
        },
        {
            "type": "serial",
            "before": {"phase": "superstructure"},
            "after": {"task": "Exterior Wall Install"},
            "match_by": ["level"],
        },
        {
            "type": "serial",
            "before": {"task": "Exterior Wall Install"},
            "after": {"tasks": ["Glass Install + Glazing", "Mesh Install"]},
            "match_by": ["level"],
        },
        {
            "type": "same_start_after",
            "after": {"task": "Exterior Wall Install"},
            "tasks": ["Interior Walls", "MEP Rough-In"],
            "match_by": ["level"],
        },
        {
            "type": "serial",
            "before": {"tasks": ["Interior Walls", "MEP Rough-In"]},
            "after": {"task": "Ceiling Installation"},
            "match_by": ["room"],
        },
        {
            "type": "serial",
            "before": {
                "tasks": [
                    "Ceiling Installation",
                    "Glass Install + Glazing",
                    "Mesh Install",
                    "Mechanical Room Buildout",
                    "Main Electrical & Riser Install",
                ]
            },
            "after": {"task": "MEP Start-Up"},
        },
        {
            "type": "chain",
            "tasks": [
                "MEP Start-Up",
                "TAB",
                "Integrated Systems Testing",
                "Final Inspections",
                "Hurricane Contingency Buffer",
            ],
        },
    ],
}


def parse_datetime(value: object) -> pd.Timestamp:
    stamp = pd.to_datetime(value)
    return stamp.normalize() + pd.Timedelta(hours=9)


def to_float(value: object, default: float = 0.0) -> float:
    if pd.isna(value) or str(value).strip() == "":
        return default
    return float(value)


def to_int(value: object, default: int = 1) -> int:
    return max(int(round(to_float(value, default))), 1)


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def normalize_task_name(value: object) -> str:
    text = clean_text(value)
    for dash in ("\u2013", "\u2014", "\u2212"):
        text = text.replace(dash, "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_measure(value: object) -> float:
    if pd.isna(value):
        return 0.0
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else 0.0


def parse_snapshot_field(value: object, field_name: str) -> str:
    if pd.isna(value):
        return ""
    pattern = rf"{re.escape(field_name)}=([^|]+)"
    match = re.search(pattern, str(value))
    return match.group(1).strip() if match else ""


def level_sort_key(level: object) -> tuple[float, str]:
    text = str(level).strip()
    if not text:
        return (9999.0, text)
    roof_match = re.fullmatch(r"roof", text, flags=re.IGNORECASE)
    if roof_match:
        return (9000.0, text)
    level_match = re.search(r"(-?\d+)", text)
    if level_match:
        return (float(level_match.group(1)), text)
    return (9500.0, text)


def parse_hours_list(value: object) -> list[int]:
    if pd.isna(value) or str(value).strip() == "":
        return []
    hours = []
    for token in str(value).split(","):
        token = token.strip()
        if token:
            hours.append(int(token))
    return sorted(dict.fromkeys(hours))


def resource_tokens(value: object) -> list[str]:
    return [token.strip() for token in clean_text(value).split("|") if token.strip()]


def resolve_crew_hours(crew_type: object, crew_hours_by_type: dict[str, list[int]]) -> list[int]:
    for token in resource_tokens(crew_type):
        hours = crew_hours_by_type.get(token, [])
        if hours:
            return hours
    return []


def combined_resource_count(resource_value: object, counts: dict[str, int], default: int = 1) -> int:
    tokens = resource_tokens(resource_value)
    if not tokens:
        return default
    return max(sum(counts.get(token, default) for token in tokens), default)


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def choose_coord(row: pd.Series, primary: str, fallback: str) -> float:
    primary_value = row.get(primary)
    if pd.notna(primary_value):
        return float(primary_value)
    fallback_value = row.get(fallback)
    return float(fallback_value) if pd.notna(fallback_value) else 0.0


def latest_room_boundaries_path() -> Path | None:
    candidates = sorted(
        REVIT_SCHEDULES_DIR.glob("*_Room_Boundaries.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def polygon_contains_point(points: list[tuple[float, float]], x: float, y: float) -> bool:
    if len(points) < 3:
        return False

    inside = False
    j = len(points) - 1
    for i, point in enumerate(points):
        xi, yi = point
        xj, yj = points[j]
        crosses = (yi > y) != (yj > y)
        if crosses:
            x_intersection = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < x_intersection:
                inside = not inside
        j = i
    return inside


def load_room_takt_zones() -> list[dict[str, object]]:
    boundary_path = latest_room_boundaries_path()
    if boundary_path is None:
        return []

    rooms = pd.read_csv(boundary_path, dtype=str).fillna("")
    numeric_columns = [
        "Start X (ft)",
        "Start Y (ft)",
        "End X (ft)",
        "End Y (ft)",
        "Room Location X (ft)",
        "Room Location Y (ft)",
    ]
    for column in numeric_columns:
        rooms[column] = pd.to_numeric(rooms[column], errors="coerce")

    zones: list[dict[str, object]] = []
    for (room_id, loop_id), loop_df in rooms.groupby(["RoomId", "Boundary Loop"], sort=False):
        loop_df = loop_df.sort_values("Segment Index")
        points = [
            (float(row["Start X (ft)"]), float(row["Start Y (ft)"]))
            for _, row in loop_df.iterrows()
            if pd.notna(row["Start X (ft)"]) and pd.notna(row["Start Y (ft)"])
        ]
        if len(points) < 3:
            continue

        first_row = loop_df.iloc[0]
        level = clean_text(first_row.get("Level"))
        room_number = clean_text(first_row.get("RoomNumber"))
        room_name = clean_text(first_row.get("RoomName"))
        room_label = room_number or clean_text(room_id)
        zones.append(
            {
                "room_id": clean_text(room_id),
                "room_number": room_number,
                "room_name": room_name,
                "room_level": level,
                "room_takt_id": f"{level} Room {room_label}".strip(),
                "points": points,
                "min_x": min(point[0] for point in points),
                "max_x": max(point[0] for point in points),
                "min_y": min(point[1] for point in points),
                "max_y": max(point[1] for point in points),
            }
        )
    return zones


def normalize_room_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    room_column_map = {
        "Room Id": "room_id",
        "Room Number": "room_number",
        "Room Name": "room_name",
        "Room Level": "room_level",
        "Room Area (SF)": "room_area_sf",
        "Room Volume (CF)": "room_volume_cf",
        "Room Location X (ft)": "room_location_x_ft",
        "Room Location Y (ft)": "room_location_y_ft",
        "Room Location Z (ft)": "room_location_z_ft",
    }
    for source, target in room_column_map.items():
        if source in frame.columns and target not in frame.columns:
            frame[target] = frame[source]

    for column in [
        "room_id",
        "room_number",
        "room_name",
        "room_level",
        "room_area_sf",
        "room_volume_cf",
        "room_location_x_ft",
        "room_location_y_ft",
        "room_location_z_ft",
        "room_takt_id",
    ]:
        if column not in frame.columns:
            frame[column] = ""
    return frame


def assign_room_takt_ids(frame: pd.DataFrame) -> pd.DataFrame:
    frame = normalize_room_columns(frame)
    zones = load_room_takt_zones()
    if not zones:
        frame["room_takt_id"] = frame["room_takt_id"].where(
            frame["room_takt_id"].astype(str).str.strip() != "",
            frame.apply(
                lambda row: (
                    f"{clean_text(row.get('room_level'))} Room {clean_text(row.get('room_number'))}".strip()
                    if clean_text(row.get("room_id")) and clean_text(row.get("room_number"))
                    else ""
                ),
                axis=1,
            ),
        )
        return frame

    for row_index, row in frame.iterrows():
        if clean_text(row.get("room_takt_id")):
            continue

        existing_room_id = clean_text(row.get("room_id"))
        if existing_room_id:
            matching_zone = next((zone for zone in zones if zone["room_id"] == existing_room_id), None)
            if matching_zone:
                for key in ["room_number", "room_name", "room_level", "room_takt_id"]:
                    frame.at[row_index, key] = matching_zone[key]
                continue

        level = clean_text(row.get("Level"))
        x = row.get("coord_x")
        y = row.get("coord_y")
        if pd.isna(x) or pd.isna(y):
            continue

        for zone in zones:
            if level and clean_text(zone["room_level"]) != level:
                continue
            x_float = float(x)
            y_float = float(y)
            if not (zone["min_x"] <= x_float <= zone["max_x"] and zone["min_y"] <= y_float <= zone["max_y"]):
                continue
            if polygon_contains_point(cast(list[tuple[float, float]], zone["points"]), x_float, y_float):
                for key in ["room_id", "room_number", "room_name", "room_level", "room_takt_id"]:
                    frame.at[row_index, key] = zone[key]
                break

    return frame


def normalize_source_model(row: pd.Series) -> str:
    existing = clean_text(row.get("source_model"))
    if existing:
        return existing

    source_schedule = clean_text(row.get("source_schedule")).lower()
    if "structural_schedule" in source_schedule:
        return "Structural_Schedule.csv"
    if "architecture_takeoff" in source_schedule:
        return "Architecture_TakeOff.csv"
    if "mep_takeoff" in source_schedule:
        return "MEP_TakeOff.csv"
    if source_schedule:
        return Path(source_schedule).name
    return "Central_BIM_Model.csv"


def infer_discipline(row: pd.Series) -> str:
    discipline = clean_text(row.get("discipline"))
    if discipline:
        return discipline

    source_schedule = clean_text(row.get("source_schedule")).lower()
    if "mep_takeoff" in source_schedule:
        return "MEP"
    if "structural_schedule" in source_schedule:
        return "Structural"
    if "architecture_takeoff" in source_schedule:
        return "Architecture"
    return ""


def load_element_discipline_lookup() -> dict[str, str]:
    if not CENTRAL_BIM_CONTEXT_PATH.exists():
        return {}

    context = pd.read_csv(CENTRAL_BIM_CONTEXT_PATH, dtype=str).fillna("")
    context = normalize_columns(context)
    required = {"element_id", "discipline"}
    if not required.issubset(context.columns):
        return {}

    return {
        clean_text(row["element_id"]): clean_text(row["discipline"])
        for _, row in context.iterrows()
        if clean_text(row["element_id"]) and clean_text(row["discipline"])
    }


def load_model_elements() -> pd.DataFrame:
    if not CENTRAL_BIM_PATH.exists():
        return pd.DataFrame()

    frame = pd.read_csv(CENTRAL_BIM_PATH)
    if "discipline" not in frame.columns:
        discipline_lookup = load_element_discipline_lookup()
        frame["discipline"] = frame["ElementId"].astype(str).map(discipline_lookup).fillna("")
    frame["discipline"] = frame.apply(infer_discipline, axis=1)

    for column in ["Original Category", "Original Family", "Original Type"]:
        if column not in frame.columns:
            frame[column] = ""

    frame["source_model"] = frame.apply(normalize_source_model, axis=1)
    if "Parameter Snapshot" in frame.columns:
        reference_levels = frame["Parameter Snapshot"].apply(
            lambda value: parse_snapshot_field(value, "Reference Level")
        )
        frame["Level"] = frame["Level"].where(
            frame["Level"].notna() & (frame["Level"].astype(str).str.strip() != ""),
            reference_levels,
        )

    frame["coord_x"] = frame.apply(
        lambda row: choose_coord(row, "Bounding Box Center X (ft)", "Position X (ft)"), axis=1
    )
    frame["coord_y"] = frame.apply(
        lambda row: choose_coord(row, "Bounding Box Center Y (ft)", "Position Y (ft)"), axis=1
    )
    frame["coord_z"] = frame.apply(
        lambda row: choose_coord(row, "Bounding Box Center Z (ft)", "Position Z (ft)"), axis=1
    )
    frame = assign_room_takt_ids(frame)
    frame["element_key"] = frame["source_model"].astype(str) + ":" + frame["ElementId"].astype(str)
    frame["quantity_count"] = 1.0
    frame["quantity_sf"] = frame["Area"].apply(parse_measure) if "Area" in frame.columns else 0.0
    frame["quantity_cf"] = frame["Volume"].apply(parse_measure) if "Volume" in frame.columns else 0.0
    frame["quantity_hr"] = 0.0
    if "takt_id" not in frame.columns:
        frame["takt_id"] = ""
    return frame


def effective_category(row: pd.Series) -> str:
    category = clean_text(row.get("Category"))
    if category == "Parts":
        return clean_text(row.get("Original Category")) or category
    return category


def effective_family(row: pd.Series) -> str:
    category = clean_text(row.get("Category"))
    if category == "Parts":
        return clean_text(row.get("Original Family")) or clean_text(row.get("Family"))
    return clean_text(row.get("Family"))


def effective_type(row: pd.Series) -> str:
    category = clean_text(row.get("Category"))
    if category == "Parts":
        return clean_text(row.get("Original Type")) or clean_text(row.get("Type"))
    return clean_text(row.get("Type"))


def is_floor_part(row: pd.Series) -> bool:
    return clean_text(row.get("Category")) == "Parts" and clean_text(row.get("Original Category")) == "Floors"


def parse_bim_map_selectors(bim_map: object) -> list[tuple[str, str]]:
    def clean_selector_token(token: str) -> str:
        token = token.strip()
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
            token = token[1:-1]
        return token.strip()

    selectors: list[tuple[str, str]] = []
    for raw_selector in [part.strip() for part in clean_text(bim_map).split("|") if part.strip()]:
        pieces = [piece.strip() for piece in raw_selector.split(",") if piece.strip()]
        attributes: dict[str, str] = {}
        for piece in pieces:
            if ":" not in piece:
                continue
            key, value = piece.split(":", 1)
            attributes[clean_selector_token(key).casefold()] = clean_selector_token(value)

        category = attributes.get("category", "")
        family = attributes.get("family", "")
        type_name = attributes.get("type", "")
        level = attributes.get("level", "")
        discipline = attributes.get("discipline", "")
        if discipline:
            selectors.append(("Discipline", discipline))
        if category and family:
            selectors.append(("Category:Family", f"{category}:{family}"))
        elif category and type_name:
            selectors.append(("Category:Type", f"{category}:{type_name}"))
        elif category and level:
            selectors.append(("Category:Level", f"{category}:{level}"))
        elif category:
            selectors.append(("Category", category))
        elif family:
            selectors.append(("Family", family))
        elif type_name:
            selectors.append(("Type", type_name))
    return selectors


def match_elements(elements: pd.DataFrame, bim_map: str) -> pd.DataFrame:
    matches: list[pd.DataFrame] = []
    if not elements.empty:
        elements = elements.copy()
        elements["effective_category"] = elements.apply(effective_category, axis=1)
        elements["effective_family"] = elements.apply(effective_family, axis=1)
        elements["effective_type"] = elements.apply(effective_type, axis=1)

    for bim_rule, token in parse_bim_map_selectors(bim_map):
        if bim_rule == "Discipline":
            if "discipline" not in elements.columns:
                continue
            matches.append(elements[elements["discipline"].fillna("").astype(str).str.casefold() == token.casefold()])
        elif bim_rule == "Category":
            matches.append(elements[elements["effective_category"].astype(str) == token])
        elif bim_rule == "Category:Family":
            category, family = token.split(":", 1)
            matches.append(
                elements[
                    (elements["effective_category"].astype(str) == category)
                    & (elements["effective_family"].fillna("").astype(str) == family)
                ]
            )
        elif bim_rule == "Category:Type":
            category, type_name = token.split(":", 1)
            matches.append(
                elements[
                    (elements["effective_category"].astype(str) == category)
                    & (elements["effective_type"].astype(str) == type_name)
                ]
            )
        elif bim_rule == "Category:Level":
            category, level = token.split(":", 1)
            matches.append(
                elements[
                    (elements["effective_category"].astype(str) == category)
                    & (elements["Level"].fillna("").astype(str).str.strip() == level)
                ]
            )
        elif bim_rule == "Family":
            matches.append(elements[elements["effective_family"].fillna("").astype(str) == token])
        elif bim_rule == "Type":
            matches.append(elements[elements["effective_type"].fillna("").astype(str) == token])

    if not matches:
        return elements.iloc[0:0].copy()

    return pd.concat(matches, ignore_index=True).drop_duplicates(subset=["element_key"]).copy()


def filter_task_specific_elements(task: TaskContext, matched: pd.DataFrame) -> pd.DataFrame:
    if matched.empty:
        return matched

    task_name = str(task.task_name).strip().lower()
    level_text = matched["Level"].astype(str).str.strip().str.lower()
    effective_type_text = matched.apply(effective_type, axis=1).astype(str).str.strip().str.lower()
    effective_family_text = matched.apply(effective_family, axis=1).astype(str).str.strip().str.lower()
    source_text = matched["source_model"].fillna("").astype(str).str.strip().str.lower()

    basement_structural_tasks = {
        "footings - form/rebar/pour",
        "grade beams",
        "basement slab on grade",
    }
    basement_non_bim_tasks = {
        "full basement excavation",
        "subgrade preparation",
        "shoring / stabilization",
        "waterproofing & drainage",
        "backfill & compaction",
    }

    if task_name == "roof":
        roof_matches = matched[level_text == "roof"].copy()
        floor_part_mask = roof_matches.apply(is_floor_part, axis=1)
        if floor_part_mask.any():
            return roof_matches[floor_part_mask].copy()
        return roof_matches
    if task_name == "floor":
        floor_matches = matched[level_text != "roof"].copy()
        floor_part_mask = floor_matches.apply(is_floor_part, axis=1)
        if floor_part_mask.any():
            return floor_matches[floor_part_mask].copy()
        return floor_matches
    if task_name in basement_structural_tasks:
        matched = matched[source_text == "structural_schedule.csv"].copy()
    if task_name in basement_non_bim_tasks:
        matched = matched[source_text == "non-bim"].copy()
    if task_name == "footings - form/rebar/pour":
        footing_mask = (
            effective_family_text.str.contains("footing", regex=False)
            | effective_type_text.str.contains("footing", regex=False)
        ) & (~effective_type_text.str.contains("slab", regex=False))
        return matched[footing_mask].copy()
    if task_name == "basement slab on grade":
        slab_mask = effective_type_text.str.contains('foundation slab', regex=False) | effective_type_text.str.contains('slab', regex=False)
        return matched[slab_mask].copy()
    return matched


def snake_order(elements: pd.DataFrame) -> pd.DataFrame:
    ordered_groups: list[pd.DataFrame] = []
    row_groups = list(elements.groupby("row_y", sort=True))
    for row_index, (_, row_df) in enumerate(row_groups):
        ascending = row_index % 2 == 0
        ordered_groups.append(
            row_df.sort_values(["coord_x", "coord_z", "ElementId"], ascending=[ascending, True, True]).copy()
        )
    if not ordered_groups:
        return elements.iloc[0:0].copy()
    return pd.concat(ordered_groups, ignore_index=True)


def frame_phase_priority(row: pd.Series) -> int:
    category = clean_text(row.get("Category")).casefold()
    if category == "structural columns":
        return 0
    if category == "structural framing":
        return 1
    return 2


def prepare_task_elements(task: TaskContext, elements: pd.DataFrame) -> pd.DataFrame:
    matched = match_elements(elements, task.bim_map)
    matched = filter_task_specific_elements(task, matched)
    if matched.empty:
        return matched

    matched = matched.copy()
    matched["level_key"] = matched["Level"].apply(level_sort_key)
    matched["row_y"] = matched["coord_y"].round(3)

    ordered_levels: list[pd.DataFrame] = []
    if task.task_name.casefold() == "frame: columns + beams":
        matched["frame_phase_priority"] = matched.apply(frame_phase_priority, axis=1)
        for phase_priority in sorted(matched["frame_phase_priority"].unique()):
            phase_df = matched[matched["frame_phase_priority"] == phase_priority].copy()
            for _, level_df in sorted(phase_df.groupby("Level", sort=False), key=lambda pair: level_sort_key(pair[0])):
                level_snake = snake_order(
                    level_df.sort_values(["row_y", "coord_x", "coord_z", "ElementId"]).copy()
                )
                ordered_levels.append(level_snake)
    else:
        for _, level_df in sorted(matched.groupby("Level", sort=False), key=lambda pair: level_sort_key(pair[0])):
            level_snake = snake_order(level_df.sort_values(["row_y", "coord_x", "coord_z", "ElementId"]).copy())
            ordered_levels.append(level_snake)

    result = pd.concat(ordered_levels, ignore_index=True)
    result["order_in_task"] = range(1, len(result) + 1)
    return result


def task_phase(task_name: str) -> str | None:
    normalized = normalize_task_name(task_name).casefold()
    if normalized in SUPERSTRUCTURE_TASKS:
        return "superstructure"
    if normalized in ENVELOPE_TASKS:
        return "envelope"
    if normalized in INTERIOR_TASKS:
        return "interior"
    if normalized in MEP_ROUGH_IN_TASKS:
        return "mep"
    return None


def envelope_support_ready_time(
    level_text: str, level_task_finishes: dict[str, dict[str, pd.Timestamp]]
) -> pd.Timestamp | None:
    current_sort_key = level_sort_key(level_text)
    candidate_levels = sorted(level_task_finishes.keys(), key=level_sort_key)

    for candidate_level in candidate_levels:
        if level_sort_key(candidate_level) <= current_sort_key:
            continue
        task_finishes = level_task_finishes[candidate_level]
        if "Floor" in task_finishes:
            return task_finishes["Floor"]
        if "Roof" in task_finishes:
            return task_finishes["Roof"]
    return None


def max_defined_timestamps(*timestamps: pd.Timestamp | None) -> pd.Timestamp | None:
    defined = [timestamp for timestamp in timestamps if timestamp is not None]
    if not defined:
        return None
    return max(defined)


def previous_level(level_text: str, level_task_finishes: dict[str, dict[str, pd.Timestamp]]) -> str | None:
    ordered_levels = sorted(level_task_finishes.keys(), key=level_sort_key)
    try:
        index = ordered_levels.index(level_text)
    except ValueError:
        return None
    if index <= 0:
        return None
    return ordered_levels[index - 1]


def cycle_sort_key(
    job: dict[str, object],
    level_indices: dict[str, int],
) -> tuple[object, ...]:
    task = cast(TaskContext, job["task"])
    phase = str(job["phase"])
    level_text = str(job["level"])
    level_index = level_indices[level_text]
    normalized_task_name = normalize_task_name(task.task_name).casefold()

    if normalized_task_name == "frame: columns":
        return (level_index, 0, task.start_date, task.task_id)
    if normalized_task_name == "frame: beams":
        if level_text.casefold() == "roof":
            return (level_indices.get("__roof_cycle_index", max(level_index - 1, 0)), 1, task.start_date, task.task_id)
        return (max(level_index - 1, 0), 1, task.start_date, task.task_id)
    if normalized_task_name == "floor":
        return (max(level_index - 1, 0), 2, task.start_date, task.task_id)
    if normalized_task_name == "roof":
        return (level_indices.get("__roof_cycle_index", max(level_index - 1, 0)), 3, task.start_date, task.task_id)
    if phase == "envelope":
        return (level_index, 4, task.start_date, task.task_id)
    if phase == "interior":
        return (level_index, 5, task.start_date, task.task_id)
    if phase == "mep":
        return (level_index, 5, task.start_date, task.task_id)
    return (level_index, 9, task.start_date, task.task_id)


def element_units(row: pd.Series, unit: str) -> float:
    normalized = str(unit).strip().lower()
    if normalized == "hr":
        return max(float(row.get("quantity_hr", 0.0)), 0.0)
    if normalized == "sf":
        return max(float(row.get("quantity_sf", 0.0)), 0.0)
    if normalized == "cf":
        return max(float(row.get("quantity_cf", 0.0)), 0.0)
    return max(float(row.get("quantity_count", 1.0)), 1.0)


def duration_from_productivity(units: float, productivity: float) -> float:
    if productivity <= 0:
        return 0.0
    return max(units / productivity, 0.0)


def is_working_day(timestamp: pd.Timestamp) -> bool:
    return timestamp.weekday() < 5


def align_to_work_time(timestamp: pd.Timestamp, allowed_hours: list[int]) -> pd.Timestamp:
    if not allowed_hours:
        return timestamp

    current = pd.Timestamp(timestamp)
    day_start_hour = min(allowed_hours)
    day_end_hour = max(allowed_hours)

    while True:
        if not is_working_day(current):
            current = (current + pd.Timedelta(days=1)).normalize() + pd.Timedelta(hours=day_start_hour)
            continue

        day_start = current.normalize() + pd.Timedelta(hours=day_start_hour)
        day_end = current.normalize() + pd.Timedelta(hours=day_end_hour)

        if current < day_start:
            current = day_start
            continue
        if current >= day_end:
            current = (current + pd.Timedelta(days=1)).normalize() + pd.Timedelta(hours=day_start_hour)
            continue
        return current


def allocate_work_segments(
    start_time: pd.Timestamp, duration_hours: float, allowed_hours: list[int]
) -> tuple[pd.Timestamp, pd.Timestamp, list[tuple[pd.Timestamp, pd.Timestamp]]]:
    if duration_hours <= 0:
        aligned = align_to_work_time(start_time, allowed_hours)
        return aligned, aligned, []

    if not allowed_hours:
        actual_start = start_time
        actual_end = start_time + pd.Timedelta(hours=duration_hours)
        return actual_start, actual_end, [(actual_start, actual_end)]

    day_start_hour = min(allowed_hours)
    day_end_hour = max(allowed_hours)
    daily_capacity_hours = max(float(day_end_hour - day_start_hour), 0.0)
    current = align_to_work_time(start_time, allowed_hours)

    # Keep each element within a single working day when it can fit in one full day.
    if 0 < duration_hours <= daily_capacity_hours:
        while True:
            current = align_to_work_time(current, allowed_hours)
            day_end = current.normalize() + pd.Timedelta(hours=day_end_hour)
            remaining_today = max((day_end - current).total_seconds() / 3600.0, 0.0)
            if remaining_today + 1e-9 >= duration_hours:
                break
            current = (current + pd.Timedelta(days=1)).normalize() + pd.Timedelta(hours=day_start_hour)

    actual_start = current
    remaining_hours = duration_hours
    segments: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    while remaining_hours > 1e-9:
        current = align_to_work_time(current, allowed_hours)
        day_end = current.normalize() + pd.Timedelta(hours=day_end_hour)
        available_hours = max((day_end - current).total_seconds() / 3600.0, 0.0)
        if available_hours <= 1e-9:
            current = (current + pd.Timedelta(days=1)).normalize() + pd.Timedelta(hours=day_start_hour)
            continue

        worked_hours = min(remaining_hours, available_hours)
        segment_end = current + pd.Timedelta(hours=worked_hours)
        segments.append((current, segment_end))
        current = segment_end
        remaining_hours -= worked_hours

    return actual_start, segments[-1][1], segments


def push_count_work_to_next_day_if_needed(
    start_time: pd.Timestamp, duration_hours: float, allowed_hours: list[int], unit: str
) -> pd.Timestamp:
    if str(unit).strip().lower() != "count" or not allowed_hours:
        return start_time

    current = align_to_work_time(start_time, allowed_hours)
    day_start_hour = min(allowed_hours)
    day_end_hour = max(allowed_hours)
    daily_capacity_hours = max(float(day_end_hour - day_start_hour), 0.0)

    if duration_hours > daily_capacity_hours:
        return current

    day_end = current.normalize() + pd.Timedelta(hours=day_end_hour)
    remaining_today = max((day_end - current).total_seconds() / 3600.0, 0.0)
    if remaining_today + 1e-9 >= duration_hours:
        return current

    return (current + pd.Timedelta(days=1)).normalize() + pd.Timedelta(hours=day_start_hour)


def segment_slots(
    segments: list[tuple[pd.Timestamp, pd.Timestamp]]
) -> list[tuple[pd.Timestamp, pd.Timestamp, float]]:
    slots: list[tuple[pd.Timestamp, pd.Timestamp, float]] = []
    for segment_start, segment_end in segments:
        slot_start = segment_start.floor("30min")
        while slot_start < segment_end:
            slot_end = slot_start + pd.Timedelta(minutes=30)
            overlap_start = max(segment_start, slot_start)
            overlap_end = min(segment_end, slot_end)
            overlap_hours = max((overlap_end - overlap_start).total_seconds() / 3600.0, 0.0)
            if overlap_hours > 1e-9:
                slots.append((slot_start, slot_end, overlap_hours))
            slot_start = slot_end
    return slots


def append_contingency_rows(
    schedule_rows: list[dict[str, object]],
    start_time: pd.Timestamp,
    contingency_hours: float,
    allowed_hours: list[int],
    macro_start: pd.Timestamp,
    macro_end: pd.Timestamp,
) -> pd.Timestamp:
    if contingency_hours <= 1e-9:
        return start_time

    contingency_start, contingency_end, segments = allocate_work_segments(
        start_time, contingency_hours, allowed_hours
    )
    slots = segment_slots(segments)

    for slot_index, (slot_start, slot_end, slot_active_duration_hr) in enumerate(slots, start=1):
        schedule_rows.append(
            {
                "task_id": "CONTINGENCY",
                "task_name": "Contingency",
                "element_id": None,
                "element_key": None,
                "source_model": None,
                "level": None,
                "category": None,
                "family": None,
                "type": None,
                "coord_x_ft": None,
                "coord_y_ft": None,
                "coord_z_ft": None,
                "order_in_task": slot_index,
                "batch_index": 1,
                "slot_index": slot_index,
                "slot_start": slot_start.isoformat(),
                "slot_end": slot_end.isoformat(),
                "element_start": contingency_start.isoformat(),
                "element_end": contingency_end.isoformat(),
                "scheduled_duration_hr": round(contingency_hours, 4),
                "raw_duration_hr": round(contingency_hours, 4),
                "slot_active_duration_hr": round(slot_active_duration_hr, 4),
                "units_per_element": round(contingency_hours, 4),
                "unit": "hr",
                "productivity": 1.0,
                "productivity_dependency": "time",
                "parallel_count": 1,
                "crew_hours": ",".join(str(hour) for hour in allowed_hours),
                "macro_start": macro_start.isoformat(),
                "macro_end": macro_end.isoformat(),
            }
        )

    return contingency_end


def working_hours_between(start_time: pd.Timestamp, end_time: pd.Timestamp, allowed_hours: list[int]) -> float:
    if end_time <= start_time:
        return 0.0
    if not allowed_hours:
        return (end_time - start_time).total_seconds() / 3600.0

    current = start_time.floor("30min")
    total_hours = 0.0

    while current < end_time:
        slot_end = current + pd.Timedelta(minutes=30)
        if (
            is_working_day(current)
            and current.hour in allowed_hours
            and slot_end <= end_time
        ):
            total_hours += 0.5
        current = slot_end

    return total_hours


def build_non_bim_task_elements(task: TaskContext) -> pd.DataFrame:
    total_hours = max(working_hours_between(task.start_date, task.end_date, task.crew_hours), 0.5)
    return pd.DataFrame(
        [
            {
                "ElementId": task.task_id,
                "Level": "Basement / Site",
                "Category": "Non-BIM",
                "Family": "",
                "Type": task.task_name,
                "source_model": "Non-BIM",
                "coord_x": 0.0,
                "coord_y": 0.0,
                "coord_z": 0.0,
                "element_key": f"Non-BIM:{task.task_id}",
                "quantity_count": 1.0,
                "quantity_sf": 0.0,
                "quantity_cf": 0.0,
                "quantity_hr": total_hours,
                "order_in_task": 1,
            }
        ]
    )


def load_macro_schedule() -> pd.DataFrame:
    macro = pd.read_csv(MACRO_SCHEDULE_PATH, dtype=str).fillna("")

    if {"Task ID", "Task Name", "Start Date", "End Date"}.issubset(macro.columns):
        if "WBS Outline" in macro.columns:
            macro = macro[macro["WBS Outline"].astype(str).str.strip().le("1.3.3")].copy()
        return pd.DataFrame(
            {
                "task_id": macro["Task ID"].apply(clean_text),
                "task_name": macro["Task Name"].apply(normalize_task_name),
                "start_date": macro["Start Date"].apply(clean_text),
                "end_date": macro["End Date"].apply(clean_text),
            }
        )

    if {"task_id", "task_name", "start_date", "end_date"}.issubset(macro.columns):
        normalized = macro.loc[:, ["task_id", "task_name", "start_date", "end_date"]].copy()
        normalized["task_name"] = normalized["task_name"].apply(normalize_task_name)
        return normalized

    raise ValueError(
        f"Unsupported macro schedule format in {MACRO_SCHEDULE_PATH.name}. "
        "Expected either ALICE export columns or simplified task columns."
    )


def build_task_contexts() -> list[TaskContext]:
    macro = load_macro_schedule()
    tasks = normalize_columns(pd.read_csv(TASKS_PATH, dtype=str).fillna(""))
    bim_map = normalize_columns(pd.read_csv(ALICE_BIM_MAP_PATH, dtype=str).fillna(""))
    crews = pd.read_csv(CREW_PATH)
    crew_hours_by_type = {
        clean_text(row["crew_type"]): parse_hours_list(row.get("hours", ""))
        for _, row in crews.iterrows()
    }

    bim_map = bim_map.rename(
        columns={
            "ALICE_task": "task_name",
            "BIM_map": "bim_map",
        }
    )

    macro["task_name_key"] = macro["task_name"].apply(normalize_task_name).str.casefold()
    tasks["task_name"] = tasks["task_name"].apply(normalize_task_name)
    tasks["task_name_key"] = tasks["task_name"].str.casefold()
    bim_map["task_name"] = bim_map["task_name"].apply(normalize_task_name)
    bim_map["task_name_key"] = bim_map["task_name"].str.casefold()

    merged = macro.merge(tasks.drop(columns=["task_name"]), on="task_name_key", how="left")
    merged = merged.merge(
        bim_map[
            [
                "task_name_key",
                "bim_map",
                "productivity",
                "unit",
                "productivity_dependency",
            ]
        ],
        on="task_name_key",
        how="left",
    )
    merged["task_name"] = merged["task_name"].apply(normalize_task_name)

    contexts: list[TaskContext] = []
    for _, row in merged.iterrows():
        has_bim_map = bool(clean_text(row.get("bim_map", "")))
        productivity = to_float(row["productivity"])
        unit = clean_text(row["unit"])
        productivity_dependency = clean_text(row["productivity_dependency"]).lower()
        if not has_bim_map:
            productivity = 1.0
            unit = "hr"
            productivity_dependency = "crew"

        contexts.append(
            TaskContext(
                task_id=clean_text(row["task_id"]),
                task_name=clean_text(row["task_name"]),
                start_date=parse_datetime(row["start_date"]),
                end_date=pd.to_datetime(row["end_date"]),
                crew_type=clean_text(row["crew_type"]),
                equipment_type=clean_text(row["equipment_type"]),
                crew_num_req=to_int(row.get("crew_num_req"), 1),
                bim_map=clean_text(row.get("bim_map", "")),
                productivity=productivity,
                unit=unit,
                productivity_dependency=productivity_dependency,
                crew_hours=resolve_crew_hours(row.get("crew_type", ""), crew_hours_by_type),
            )
        )
    return contexts


def load_resource_counts() -> tuple[dict[str, int], dict[str, int]]:
    crew_df = pd.read_csv(CREW_PATH)
    equipment_df = pd.read_csv(EQUIPMENT_PATH)
    crew_counts = {str(row["crew_type"]): to_int(row["count"], 1) for _, row in crew_df.iterrows()}
    equipment_counts = {
        str(row["equipment_type"]): to_int(row["count"], 1) for _, row in equipment_df.iterrows()
    }
    return crew_counts, equipment_counts


def load_prefab_mapping() -> tuple[dict[str, list[str]], set[str], dict[str, str], set[str]]:
    if not PREFAB_MAPPING_PATH.exists():
        return {}, set(), {}, set()

    mapping = pd.read_csv(PREFAB_MAPPING_PATH, dtype=str).fillna("")
    if not {"prefab_group_id", "host_wall_element_id", "element_id", "category"}.issubset(mapping.columns):
        return {}, set(), {}, set()

    host_to_members: dict[str, list[str]] = {}
    prefab_attached_ids: set[str] = set()
    element_to_prefab_group: dict[str, str] = {}
    prefab_non_host_ids: set[str] = set()

    for _, row in mapping.iterrows():
        prefab_group_id = clean_text(row["prefab_group_id"])
        host_id = clean_text(row["host_wall_element_id"])
        element_id = clean_text(row["element_id"])
        category = clean_text(row["category"])
        if prefab_group_id and element_id:
            element_to_prefab_group[element_id] = prefab_group_id
        if not host_id or not element_id or element_id == host_id:
            continue
        host_to_members.setdefault(host_id, [])
        if element_id not in host_to_members[host_id]:
            host_to_members[host_id].append(element_id)
        prefab_non_host_ids.add(element_id)
        if category in {"Curtain Panels", "Curtain Wall Mullions"}:
            prefab_attached_ids.add(element_id)

    return host_to_members, prefab_attached_ids, element_to_prefab_group, prefab_non_host_ids


def load_micro_rules() -> dict[str, Any]:
    if not MICRO_RULES_PATH.exists():
        return DEFAULT_MICRO_RULES

    with MICRO_RULES_PATH.open(encoding="utf-8") as file:
        loaded = json.load(file)
    if not isinstance(loaded, dict):
        raise ValueError(f"{MICRO_RULES_PATH.name} must contain a JSON object.")
    return loaded


def normalized_task_selector(value: object) -> str:
    return normalize_task_name(value).casefold()


def split_rule_matches(record: dict[str, object], rule: dict[str, Any]) -> bool:
    task = cast(TaskContext, record["task"])
    task_name = normalized_task_selector(task.task_name)
    phase = cast(str | None, record.get("phase"))

    rule_tasks = {normalized_task_selector(name) for name in rule.get("tasks", [])}
    if rule_tasks and task_name in rule_tasks:
        return True

    rule_phase = clean_text(rule.get("phase", "")).casefold()
    return bool(rule_phase and phase == rule_phase)


def node_task_name(node: MicroTaskNode) -> str:
    task = cast(TaskContext, node.record["task"])
    return normalized_task_selector(task.task_name)


def selector_matches_node(node: MicroTaskNode, selector: object) -> bool:
    if isinstance(selector, str):
        return node_task_name(node) == normalized_task_selector(selector)
    if not isinstance(selector, dict):
        return False

    if "task" in selector:
        return node_task_name(node) == normalized_task_selector(selector["task"])

    if "tasks" in selector:
        task_names = {normalized_task_selector(name) for name in selector.get("tasks", [])}
        return node_task_name(node) in task_names

    if "phase" in selector:
        return cast(str | None, node.record.get("phase")) == clean_text(selector["phase"]).casefold()

    return False


def selector_nodes(nodes: list[MicroTaskNode], selector: object) -> list[MicroTaskNode]:
    return [node for node in nodes if selector_matches_node(node, selector)]


def split_attr_matches(before: MicroTaskNode, after: MicroTaskNode, match_by: list[str]) -> bool:
    for key in match_by:
        if before.split_attrs.get(key, "") != after.split_attrs.get(key, ""):
            return False
    return True


def add_dependency_edges(
    edges: dict[str, set[str]],
    lags: dict[tuple[str, str], pd.Timedelta],
    before_nodes: list[MicroTaskNode],
    after_nodes: list[MicroTaskNode],
    match_by: list[str],
    lag: pd.Timedelta,
) -> None:
    for after in after_nodes:
        matched_before_nodes = [
            before
            for before in before_nodes
            if before.node_id != after.node_id and (not match_by or split_attr_matches(before, after, match_by))
        ]
        if match_by and before_nodes and not matched_before_nodes:
            matched_before_nodes = [before for before in before_nodes if before.node_id != after.node_id]

        for before in matched_before_nodes:
            if before.node_id == after.node_id:
                continue
            edges.setdefault(after.node_id, set()).add(before.node_id)
            edge_key = (before.node_id, after.node_id)
            lags[edge_key] = max(lags.get(edge_key, pd.Timedelta(0)), lag)


def constraint_lag(rule: dict[str, Any]) -> pd.Timedelta:
    days = to_float(rule.get("lag_days", 0), 0.0)
    hours = to_float(rule.get("lag_hours", 0), 0.0)
    return pd.Timedelta(days=days, hours=hours)


def make_node_id(task_name: str, split_attrs: dict[str, str]) -> str:
    parts = [re.sub(r"[^a-z0-9]+", "_", task_name.casefold()).strip("_")]
    for key, value in sorted(split_attrs.items()):
        if value:
            token = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
            parts.append(f"{key}_{token}")
    return "__".join(parts)


def make_micro_task_name(task_name: str, split_attrs: dict[str, str]) -> str:
    suffixes = [
        split_attrs[key]
        for key in ["room", "takt_id", "level"]
        if split_attrs.get(key)
    ]
    if not suffixes:
        return task_name
    return f"{task_name} - {' - '.join(suffixes)}"


def split_groups(
    task_elements: pd.DataFrame,
    split_by: list[str],
) -> list[tuple[dict[str, str], pd.DataFrame, tuple[object, ...]]]:
    if "room" in split_by and "room_takt_id" in task_elements.columns:
        room_elements = task_elements[task_elements["room_takt_id"].astype(str).str.strip() != ""].copy()
        if not room_elements.empty:
            groups: list[tuple[dict[str, str], pd.DataFrame, tuple[object, ...]]] = []
            for room_takt_id, group in room_elements.groupby("room_takt_id", sort=False):
                level_text = clean_text(group["Level"].iloc[0]) if "Level" in group.columns else ""
                room_number = clean_text(group["room_number"].iloc[0]) if "room_number" in group.columns else ""
                room_id = clean_text(group["room_id"].iloc[0]) if "room_id" in group.columns else ""
                attrs = {
                    "level": level_text,
                    "room": clean_text(room_takt_id),
                    "room_id": room_id,
                    "room_number": room_number,
                }
                groups.append((attrs, group.copy(), (level_sort_key(level_text), clean_text(room_takt_id))))
            return sorted(groups, key=lambda item: item[2])

    if "takt_id" in split_by and "takt_id" in task_elements.columns:
        takt_elements = task_elements[task_elements["takt_id"].astype(str).str.strip() != ""].copy()
        if not takt_elements.empty:
            groups = []
            for takt_id, group in takt_elements.groupby("takt_id", sort=False):
                level_text = clean_text(group["Level"].iloc[0]) if "Level" in group.columns else ""
                attrs = {"level": level_text, "takt_id": clean_text(takt_id)}
                groups.append((attrs, group.copy(), (level_sort_key(level_text), clean_text(takt_id))))
            return sorted(groups, key=lambda item: item[2])

    if "level" in split_by and "Level" in task_elements.columns:
        groups = [
            ({"level": clean_text(level)}, group.copy(), (level_sort_key(level), ""))
            for level, group in task_elements.groupby("Level", sort=False)
            if clean_text(level)
        ]
        return sorted(groups, key=lambda item: item[2])

    return [({}, task_elements.copy(), ((9999.0, ""), ""))]


def create_micro_task_nodes(
    task_records: list[dict[str, object]],
    rules: dict[str, Any],
) -> list[MicroTaskNode]:
    nodes: list[MicroTaskNode] = []
    split_rules = [rule for rule in rules.get("split_rules", []) if isinstance(rule, dict)]

    for record_index, record in enumerate(task_records):
        task = cast(TaskContext, record["task"])
        task_elements = cast(pd.DataFrame, record["task_elements"])
        split_by: list[str] = []
        for rule in split_rules:
            if split_rule_matches(record, rule):
                split_by = [clean_text(value).casefold() for value in rule.get("by", [])]
                break

        groups = split_groups(task_elements, split_by)

        for group_index, (split_attrs, node_elements, group_sort_key) in enumerate(groups):
            micro_task_name = make_micro_task_name(task.task_name, split_attrs)
            node_elements = node_elements.copy()
            node_elements["order_in_task"] = range(1, len(node_elements) + 1)
            node = MicroTaskNode(
                node_id=make_node_id(task.task_name, split_attrs),
                micro_task_name=micro_task_name,
                record=record,
                task_elements=node_elements,
                split_attrs=split_attrs,
                sort_key=(task.start_date, record_index, group_sort_key, group_index, task.task_id),
            )
            nodes.append(node)

    return nodes


def compile_dependency_graph(
    nodes: list[MicroTaskNode],
    rules: dict[str, Any],
) -> tuple[dict[str, set[str]], dict[tuple[str, str], pd.Timedelta], list[str]]:
    edges: dict[str, set[str]] = {node.node_id: set() for node in nodes}
    lags: dict[tuple[str, str], pd.Timedelta] = {}
    log_lines: list[str] = []

    for rule in [item for item in rules.get("constraints", []) if isinstance(item, dict)]:
        rule_type = clean_text(rule.get("type", "")).casefold()
        match_by = [clean_text(value).casefold() for value in rule.get("match_by", [])]
        lag = constraint_lag(rule)

        if rule_type == "chain":
            chain_tasks = rule.get("tasks", [])
            selectors = [{"task": task_name} for task_name in chain_tasks]
            for before_selector, after_selector in zip(selectors, selectors[1:]):
                add_dependency_edges(
                    edges,
                    lags,
                    selector_nodes(nodes, before_selector),
                    selector_nodes(nodes, after_selector),
                    match_by,
                    lag,
                )
            continue

        if rule_type == "serial":
            add_dependency_edges(
                edges,
                lags,
                selector_nodes(nodes, rule.get("before", {})),
                selector_nodes(nodes, rule.get("after", {})),
                match_by,
                lag,
            )
            continue

        if rule_type == "same_start_after":
            after_selector = rule.get("after", {})
            for task_name in rule.get("tasks", []):
                add_dependency_edges(
                    edges,
                    lags,
                    selector_nodes(nodes, after_selector),
                    selector_nodes(nodes, {"task": task_name}),
                    match_by,
                    lag,
                )
            continue

        if rule_type == "parallel":
            log_lines.append(f"- Parallel rule documented for `{', '.join(rule.get('tasks', []))}`.")
            continue

        log_lines.append(f"- Ignored unknown micro constraint type `{rule_type}`.")

    return edges, lags, log_lines


def apply_split_parallel_limits(
    nodes: list[MicroTaskNode],
    edges: dict[str, set[str]],
    lags: dict[tuple[str, str], pd.Timedelta],
) -> list[str]:
    log_lines: list[str] = []
    nodes_by_task: dict[str, list[MicroTaskNode]] = {}
    for node in nodes:
        if not any(node.split_attrs.get(key) for key in ["room", "takt_id"]):
            continue
        nodes_by_task.setdefault(node_task_name(node), []).append(node)

    for task_name, task_nodes in nodes_by_task.items():
        ordered_nodes = sorted(task_nodes, key=lambda node: node.sort_key)
        if len(ordered_nodes) <= 1:
            continue

        parallel_limit = max(cast(int, ordered_nodes[0].record["parallel_count"]), 1)
        if len(ordered_nodes) <= parallel_limit:
            continue

        for index in range(parallel_limit, len(ordered_nodes)):
            predecessor = ordered_nodes[index - parallel_limit]
            successor = ordered_nodes[index]
            edges.setdefault(successor.node_id, set()).add(predecessor.node_id)
            lags.setdefault((predecessor.node_id, successor.node_id), pd.Timedelta(0))

        display_name = cast(TaskContext, ordered_nodes[0].record["task"]).task_name
        log_lines.append(
            f"- Limited `{display_name}` room/zone flow to `{parallel_limit}` concurrent takt zones."
        )

    return log_lines


def schedule_micro_task_graph(
    nodes: list[MicroTaskNode],
    edges: dict[str, set[str]],
    lags: dict[tuple[str, str], pd.Timedelta],
    project_anchor: pd.Timestamp,
    schedule_rows: list[dict[str, object]],
    prefab_members_by_host: dict[str, list[pd.Series]],
    element_to_prefab_group: dict[str, str],
) -> list[str]:
    node_lookup = {node.node_id: node for node in nodes}
    unscheduled = {node.node_id for node in nodes}
    finishes: dict[str, pd.Timestamp] = {}
    log_lines: list[str] = []

    while unscheduled:
        ready = [
            node_lookup[node_id]
            for node_id in unscheduled
            if edges.get(node_id, set()).issubset(finishes.keys())
        ]
        if not ready:
            cycle_nodes = ", ".join(sorted(unscheduled))
            raise ValueError(f"Micro schedule constraints contain a cycle or unresolved dependency: {cycle_nodes}")

        for node in sorted(ready, key=lambda item: item.sort_key):
            predecessors = edges.get(node.node_id, set())
            dependency_start = max(
                [
                    finishes[pred_id] + lags.get((pred_id, node.node_id), pd.Timedelta(0))
                    for pred_id in predecessors
                ],
                default=project_anchor,
            )
            start_time = max(project_anchor, dependency_start)
            task = cast(TaskContext, node.record["task"])
            normalized_task_name = cast(str, node.record["normalized_task_name"])
            parallel_count = cast(int, node.record["parallel_count"])
            finish_time = schedule_element_batches(
                task,
                node.task_elements,
                start_time,
                parallel_count,
                schedule_rows,
                prefab_members_by_host if normalized_task_name == "exterior wall install" else None,
                element_to_prefab_group,
                micro_task_id=node.node_id,
                micro_task_name=node.micro_task_name,
            )
            finishes[node.node_id] = finish_time
            unscheduled.remove(node.node_id)

    log_lines.append(f"- Scheduled `{len(nodes)}` micro task nodes using `{len(lags)}` configured dependency edges.")
    return log_lines


def schedule_element_batches(
    task: TaskContext,
    task_elements: pd.DataFrame,
    start_time: pd.Timestamp,
    parallel_count: int,
    schedule_rows: list[dict[str, object]],
    prefab_members_by_host: dict[str, list[pd.Series]] | None = None,
    element_to_prefab_group: dict[str, str] | None = None,
    micro_task_id: str = "",
    micro_task_name: str = "",
) -> pd.Timestamp:
    t = align_to_work_time(start_time, task.crew_hours)

    for batch_start in range(0, len(task_elements), parallel_count):
        batch = task_elements.iloc[batch_start : batch_start + parallel_count].copy()
        batch_end = t

        for _, element in batch.iterrows():
            units_per_element = element_units(element, task.unit)
            raw_hours = duration_from_productivity(units_per_element, task.productivity)
            scheduled_hours = max(raw_hours, 1 / 60)

            element_ready_time = push_count_work_to_next_day_if_needed(
                t, scheduled_hours, task.crew_hours, task.unit
            )
            element_start, element_end, segments = allocate_work_segments(
                element_ready_time, scheduled_hours, task.crew_hours
            )
            if element_end > batch_end:
                batch_end = element_end
            slots = segment_slots(segments)

            for slot_index, (slot_start, slot_end, slot_active_duration_hr) in enumerate(slots, start=1):
                base_row = {
                    "task_id": task.task_id,
                    "task_name": task.task_name,
                    "micro_task_id": micro_task_id,
                    "micro_task_name": micro_task_name or task.task_name,
                    "order_in_task": int(element["order_in_task"]),
                    "batch_index": batch_start // parallel_count + 1,
                    "slot_index": slot_index,
                    "slot_start": slot_start.isoformat(),
                    "slot_end": slot_end.isoformat(),
                    "element_start": element_start.isoformat(),
                    "element_end": element_end.isoformat(),
                    "scheduled_duration_hr": round(scheduled_hours, 4),
                    "raw_duration_hr": round(raw_hours, 4),
                    "slot_active_duration_hr": round(slot_active_duration_hr, 4),
                    "units_per_element": round(units_per_element, 4),
                    "unit": task.unit,
                    "productivity": task.productivity,
                    "productivity_dependency": task.productivity_dependency,
                    "parallel_count": parallel_count,
                    "crew_hours": ",".join(str(hour) for hour in task.crew_hours),
                    "macro_start": task.start_date.isoformat(),
                    "macro_end": task.end_date.isoformat(),
                }

                def append_element_row(target: pd.Series) -> None:
                    schedule_rows.append(
                        {
                            **base_row,
                            "element_id": str(target["ElementId"]),
                            "element_key": str(target["element_key"]),
                            "source_model": target["source_model"],
                            "level": target.get("Level", ""),
                            "category": target.get("Category", ""),
                            "family": target.get("Family", ""),
                            "type": target.get("Type", ""),
                            "coord_x_ft": round(float(target["coord_x"]), 3),
                            "coord_y_ft": round(float(target["coord_y"]), 3),
                            "coord_z_ft": round(float(target["coord_z"]), 3),
                            "takt_id": clean_text(target.get("takt_id", "")),
                            "room_takt_id": clean_text(target.get("room_takt_id", "")),
                            "room_id": clean_text(target.get("room_id", "")),
                            "room_number": clean_text(target.get("room_number", "")),
                            "room_name": clean_text(target.get("room_name", "")),
                            "prefab_group_id": (
                                element_to_prefab_group.get(str(target["ElementId"]), "")
                                if element_to_prefab_group
                                else ""
                            ),
                        }
                    )

                append_element_row(element)

                host_id = str(element["ElementId"])
                if prefab_members_by_host and host_id in prefab_members_by_host:
                    for companion in prefab_members_by_host[host_id]:
                        append_element_row(companion)

        t = batch_end

    return t


def build_micro_schedule() -> tuple[pd.DataFrame, list[str]]:
    elements = load_model_elements()
    task_contexts = build_task_contexts()
    crew_counts, equipment_counts = load_resource_counts()
    (
        prefab_member_ids_by_host,
        prefab_attached_ids,
        element_to_prefab_group,
        prefab_non_host_ids,
    ) = load_prefab_mapping()
    element_lookup = {
        str(row["ElementId"]): row
        for _, row in elements.drop_duplicates(subset=["ElementId"]).iterrows()
    }
    prefab_members_by_host = {
        host_id: [element_lookup[member_id] for member_id in member_ids if member_id in element_lookup]
        for host_id, member_ids in prefab_member_ids_by_host.items()
    }

    schedule_rows: list[dict[str, object]] = []
    log_lines: list[str] = []
    project_anchor = min((task.start_date for task in task_contexts), default=pd.Timestamp("2029-01-01 09:00"))
    task_records: list[dict[str, object]] = []

    for task in task_contexts:
        if not task.bim_map.strip():
            task_elements = build_non_bim_task_elements(task)
        else:
            task_elements = prepare_task_elements(task, elements)
        normalized_task_name = normalize_task_name(task.task_name).casefold()
        if normalized_task_name == "glass install + glazing" and prefab_attached_ids:
            task_elements = task_elements[
                ~task_elements["ElementId"].astype(str).isin(prefab_attached_ids)
            ].copy()
        if normalized_task_name == "exterior wall install" and prefab_non_host_ids:
            task_elements = task_elements[
                ~task_elements["ElementId"].astype(str).isin(prefab_non_host_ids)
            ].copy()
        b = len(task_elements)
        total_hours = max(working_hours_between(task.start_date, task.end_date, task.crew_hours), 0.5)
        phase = task_phase(task.task_name)

        if task.productivity_dependency == "equipment":
            n = combined_resource_count(task.equipment_type, equipment_counts)
        else:
            n = combined_resource_count(task.crew_type, crew_counts)
        n = max(n, 1)

        if b == 0:
            log_lines.append(f"- `{task.task_id} {task.task_name}`: no BIM elements matched `{task.bim_map}`.")
            continue

        required_hours = (
            sum(duration_from_productivity(element_units(element, task.unit), task.productivity) for _, element in task_elements.iterrows())
            / n
        )
        e_value = ((total_hours - required_hours) / b) if b else 0.0
        comparison = "more time available than needed" if e_value >= 0 else "less time available than needed"
        log_lines.append(
            f"- `{task.task_id} {task.task_name}`: `T={total_hours:.2f} hr`, `n={n}`, `b={b}`, "
            f"`p={task.productivity}`, `e={e_value:.4f} hr/element` -> {comparison}."
        )

        parallel_count = max(n, 1)
        task_records.append(
            {
                "task": task,
                "task_elements": task_elements,
                "normalized_task_name": normalized_task_name,
                "phase": phase,
                "parallel_count": parallel_count,
            }
        )

    rules = load_micro_rules()
    micro_nodes = create_micro_task_nodes(task_records, rules)
    dependency_edges, dependency_lags, rule_logs = compile_dependency_graph(micro_nodes, rules)
    log_lines.extend(rule_logs)
    log_lines.extend(apply_split_parallel_limits(micro_nodes, dependency_edges, dependency_lags))
    log_lines.extend(
        schedule_micro_task_graph(
            micro_nodes,
            dependency_edges,
            dependency_lags,
            project_anchor,
            schedule_rows,
            prefab_members_by_host,
            element_to_prefab_group,
        )
    )

    micro_df = pd.DataFrame(
        schedule_rows,
        columns=[
            "task_id",
            "task_name",
            "micro_task_id",
            "micro_task_name",
            "element_id",
            "element_key",
            "source_model",
            "level",
            "category",
            "family",
            "type",
            "coord_x_ft",
            "coord_y_ft",
            "coord_z_ft",
            "takt_id",
            "room_takt_id",
            "room_id",
            "room_number",
            "room_name",
            "prefab_group_id",
            "order_in_task",
            "batch_index",
            "slot_index",
            "slot_start",
            "slot_end",
            "element_start",
            "element_end",
            "scheduled_duration_hr",
            "raw_duration_hr",
            "slot_active_duration_hr",
            "units_per_element",
            "unit",
            "productivity",
            "productivity_dependency",
            "parallel_count",
            "crew_hours",
            "macro_start",
            "macro_end",
        ],
    )
    return micro_df, log_lines


def write_log(log_lines: list[str]) -> None:
    content = [
        "# Micro Schedule Log",
        "",
        "Rule-driven micro schedule generated from `ALICE_BIM_mapper/outputs`, `Micro_Schedule_Generator/inputs`, and the central BIM model.",
        "",
        "## Time-fit check",
        "",
    ]
    content.extend(log_lines if log_lines else ["- None."])
    MICRO_LOG_PATH.write_text("\n".join(content) + "\n", encoding="utf-8")


if __name__ == "__main__":
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    micro_df, logs = build_micro_schedule()
    micro_df.to_csv(MICRO_SCHEDULE_PATH, index=False)
    write_log(logs)
    print(f"Wrote {MICRO_SCHEDULE_PATH.name}")
    print(f"Wrote {MICRO_LOG_PATH.name}")
