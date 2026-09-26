from __future__ import annotations

import argparse
import html
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[2]
CENTRAL_BIM_PATH = PROJECT_DIR / "outputs" / "takt_zones" / "central_bim_model.csv"
ROOM_TAKT_ZONES_PATH = PROJECT_DIR / "outputs" / "room_boundaries" / "room_takt_zones.csv"
ROOM_BOUNDARIES_GLOB = "*_Room_Boundaries.csv"
FBX_GLOB = "*.fbx"
CREW_PATH = PROJECT_DIR / "src" / "Planning_engine" / "ALICE_BIM_mapper" / "outputs" / "Crew.csv"
EQUIPMENT_PATH = PROJECT_DIR / "src" / "Planning_engine" / "ALICE_BIM_mapper" / "outputs" / "Equipment.csv"
OUTPUT_DIR = PROJECT_DIR / "src" / "Takt_engine" / "outputs"
PRODUCTIVITY_RATES_PATH = OUTPUT_DIR / "Takt_Productivity_Rates.csv"

DEFAULT_PRODUCTIVITY_ROWS = [
    {"task": "Interior Walls", "planning_crew": "interior_walls_crew", "rate": 1.0, "unit": "EA/crew-hour"},
    {"task": "MEP", "planning_crew": "mep_rough_in_crew", "rate": 45.0, "unit": "EA/crew-hour"},
    {"task": "Ceiling", "planning_crew": "ceiling_crew", "rate": 750.0, "unit": "SF/crew-hour"},
    {"task": "Doors", "planning_crew": "doors_crew", "rate": 20.0, "unit": "EA/crew-hour"},
    {"task": "Interior Finishes", "planning_crew": "interior_finishes_crew", "rate": 300.0, "unit": "SF/crew-hour"},
]
TASK_COLORS = {
    "Interior Walls": "#2563eb",
    "MEP": "#d97706",
    "Ceiling": "#059669",
    "Doors": "#7c3aed",
    "Interior Finishes": "#db2777",
}
ZONE_COLORS = [
    "#2563eb",
    "#16a34a",
    "#dc2626",
    "#9333ea",
    "#ea580c",
    "#0891b2",
    "#be123c",
    "#4f46e5",
    "#65a30d",
    "#ca8a04",
]
LAST_ZONE_IDS = {"L 1 Takt Zone 8"}


@dataclass(slots=True)
class RoomZone:
    room_takt_id: str
    room_id: str
    room_number: str
    room_name: str
    level: str
    area_sf: float
    volume_cf: float
    x: float
    y: float
    z: float
    points: list[tuple[float, float]]

    @property
    def min_x(self) -> float:
        return min(point[0] for point in self.points) if self.points else self.x

    @property
    def max_x(self) -> float:
        return max(point[0] for point in self.points) if self.points else self.x

    @property
    def min_y(self) -> float:
        return min(point[1] for point in self.points) if self.points else self.y

    @property
    def max_y(self) -> float:
        return max(point[1] for point in self.points) if self.points else self.y


@dataclass(slots=True)
class GroupedZone:
    takt_zone_id: str
    level: str
    sequence: int
    rooms: list[RoomZone]

    @property
    def label(self) -> str:
        room_numbers = ", ".join(room.room_number or room.room_takt_id for room in self.rooms)
        return f"{self.takt_zone_id} ({room_numbers})"

    @property
    def room_ids(self) -> set[str]:
        return {room.room_id for room in self.rooms if room.room_id}

    @property
    def min_x(self) -> float:
        return min(room.min_x for room in self.rooms)

    @property
    def max_x(self) -> float:
        return max(room.max_x for room in self.rooms)

    @property
    def min_y(self) -> float:
        return min(room.min_y for room in self.rooms)

    @property
    def max_y(self) -> float:
        return max(room.max_y for room in self.rooms)


def clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def parse_measure(value: object) -> float:
    text = clean_text(value).replace(",", "")
    token = ""
    decimal_seen = False
    sign_seen = False
    for char in text:
        if char.isdigit():
            token += char
        elif char == "." and not decimal_seen:
            token += char
            decimal_seen = True
        elif char == "-" and not token and not sign_seen:
            token += char
            sign_seen = True
        elif token:
            break
    try:
        return float(token) if token not in {"", "-", "."} else 0.0
    except ValueError:
        return 0.0


def latest_room_boundaries_path() -> Path | None:
    candidates = sorted(
        (PROJECT_DIR / "revit_schedules").glob(ROOM_BOUNDARIES_GLOB),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def latest_fbx_path() -> Path | None:
    candidates = sorted(
        (PROJECT_DIR / "revit_schedules").glob(FBX_GLOB),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def load_room_polygons() -> dict[str, list[tuple[float, float]]]:
    boundary_path = latest_room_boundaries_path()
    if boundary_path is None:
        return {}

    rows = pd.read_csv(boundary_path, dtype=str).fillna("")
    for column in ["Start X (ft)", "Start Y (ft)", "Segment Index"]:
        rows[column] = pd.to_numeric(rows[column], errors="coerce")

    polygons: dict[str, list[tuple[float, float]]] = {}
    for (room_id, loop_id), loop_df in rows.groupby(["RoomId", "Boundary Loop"], sort=False):
        loop_df = loop_df.sort_values("Segment Index")
        points = [
            (float(row["Start X (ft)"]), float(row["Start Y (ft)"]))
            for _, row in loop_df.iterrows()
            if pd.notna(row["Start X (ft)"]) and pd.notna(row["Start Y (ft)"])
        ]
        if len(points) >= 3 and clean_text(loop_id) == "1":
            polygons[clean_text(room_id)] = points
    return polygons


def load_rooms() -> list[RoomZone]:
    if not ROOM_TAKT_ZONES_PATH.exists():
        raise FileNotFoundError(f"Missing room takt zones: {ROOM_TAKT_ZONES_PATH}")

    polygons = load_room_polygons()
    rooms_df = pd.read_csv(ROOM_TAKT_ZONES_PATH, dtype=str).fillna("")
    rooms: list[RoomZone] = []
    for _, row in rooms_df.iterrows():
        room_id = clean_text(row.get("room_id"))
        x = parse_measure(row.get("location_x_ft"))
        y = parse_measure(row.get("location_y_ft"))
        fallback_points = [(x - 1.0, y - 1.0), (x + 1.0, y - 1.0), (x + 1.0, y + 1.0), (x - 1.0, y + 1.0)]
        rooms.append(
            RoomZone(
                room_takt_id=clean_text(row.get("room_takt_id")),
                room_id=room_id,
                room_number=clean_text(row.get("room_number")),
                room_name=clean_text(row.get("room_name")),
                level=clean_text(row.get("level")),
                area_sf=parse_measure(row.get("area_sf")),
                volume_cf=parse_measure(row.get("volume_cf")),
                x=x,
                y=y,
                z=parse_measure(row.get("location_z_ft")),
                points=polygons.get(room_id, fallback_points),
            )
        )
    return rooms


def centroid_distance(a: RoomZone, b: RoomZone) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def rooms_touch_or_overlap(a: RoomZone, b: RoomZone, tolerance: float = 1.0) -> bool:
    x_overlap = min(a.max_x, b.max_x) + tolerance >= max(a.min_x, b.min_x)
    y_overlap = min(a.max_y, b.max_y) + tolerance >= max(a.min_y, b.min_y)
    x_touch = abs(a.max_x - b.min_x) <= tolerance or abs(b.max_x - a.min_x) <= tolerance
    y_touch = abs(a.max_y - b.min_y) <= tolerance or abs(b.max_y - a.min_y) <= tolerance
    return (x_overlap and y_touch) or (y_overlap and x_touch) or (x_overlap and y_overlap)


def group_rooms(rooms: list[RoomZone], rooms_per_zone: int, level_filter: str = "L 1") -> list[GroupedZone]:
    if rooms_per_zone < 1:
        raise ValueError("rooms_per_zone must be at least 1")

    if level_filter:
        rooms = [room for room in rooms if room.level == level_filter]

    grouped: list[GroupedZone] = []
    sequence = 1
    for level in sorted({room.level for room in rooms}):
        unassigned = sorted(
            [room for room in rooms if room.level == level],
            key=lambda room: (room.y, room.x, room.room_number),
        )
        level_zone_index = 1
        while unassigned:
            current = [unassigned.pop(0)]
            while unassigned and len(current) < rooms_per_zone:
                neighbors = [room for room in unassigned if any(rooms_touch_or_overlap(room, chosen) for chosen in current)]
                candidates = neighbors or unassigned
                next_room = min(candidates, key=lambda room: min(centroid_distance(room, chosen) for chosen in current))
                unassigned.remove(next_room)
                current.append(next_room)

            grouped.append(
                GroupedZone(
                    takt_zone_id=f"{level} Takt Zone {level_zone_index}",
                    level=level,
                    sequence=sequence,
                    rooms=current,
                )
            )
            sequence += 1
            level_zone_index += 1
    return apply_zone_sequence_overrides(grouped)


def apply_zone_sequence_overrides(zones: list[GroupedZone]) -> list[GroupedZone]:
    normal_zones = [zone for zone in zones if zone.takt_zone_id not in LAST_ZONE_IDS]
    last_zones = [zone for zone in zones if zone.takt_zone_id in LAST_ZONE_IDS]
    reordered = normal_zones + last_zones
    for index, zone in enumerate(reordered, start=1):
        zone.sequence = index
    return reordered


def classify_tasks(row: pd.Series) -> list[str]:
    category = clean_text(row.get("Category"))
    original_category = clean_text(row.get("Original Category"))
    type_name = clean_text(row.get("Type")).lower()

    if category == "Walls" and "interior" in type_name:
        return ["Interior Walls", "Interior Finishes"]
    if category == "Doors":
        return ["Doors"]
    if category == "Ceilings" or (category == "Parts" and original_category == "Ceilings"):
        return ["Ceiling"]
    if category in {
        "Air Terminals",
        "Duct Fittings",
        "Ducts",
        "Electrical Fixtures",
        "Flex Ducts",
        "Mechanical Equipment",
        "Plumbing Fixtures",
        "Runs",
    }:
        return ["MEP"]
    return []


def element_bbox(row: pd.Series) -> tuple[float, float, float, float]:
    cx = parse_measure(row.get("Bounding Box Center X (ft)")) or parse_measure(row.get("Position X (ft)"))
    cy = parse_measure(row.get("Bounding Box Center Y (ft)")) or parse_measure(row.get("Position Y (ft)"))
    min_x = parse_measure(row.get("Bounding Box Min X (ft)"))
    max_x = parse_measure(row.get("Bounding Box Max X (ft)"))
    min_y = parse_measure(row.get("Bounding Box Min Y (ft)"))
    max_y = parse_measure(row.get("Bounding Box Max Y (ft)"))
    if min_x == 0.0 and max_x == 0.0:
        min_x, max_x = cx - 0.5, cx + 0.5
    if min_y == 0.0 and max_y == 0.0:
        min_y, max_y = cy - 0.5, cy + 0.5
    return min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y)


def bbox_overlap_area(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    min_x = max(a[0], b[0])
    min_y = max(a[1], b[1])
    max_x = min(a[2], b[2])
    max_y = min(a[3], b[3])
    if max_x <= min_x or max_y <= min_y:
        return 0.0
    return (max_x - min_x) * (max_y - min_y)


def zone_bbox(zone: GroupedZone) -> tuple[float, float, float, float]:
    return zone.min_x, zone.min_y, zone.max_x, zone.max_y


def build_boundary_zone_overlaps(zones: list[GroupedZone]) -> dict[str, list[tuple[GroupedZone, float]]]:
    boundary_path = latest_room_boundaries_path()
    if boundary_path is None:
        return {}

    room_to_zone: dict[str, GroupedZone] = {}
    for zone in zones:
        for room in zone.rooms:
            if room.room_id:
                room_to_zone[room.room_id] = zone

    rows = pd.read_csv(boundary_path, dtype=str).fillna("")
    for column in ["Start X (ft)", "Start Y (ft)", "End X (ft)", "End Y (ft)"]:
        rows[column] = pd.to_numeric(rows[column], errors="coerce")

    zone_lengths_by_element: dict[str, dict[str, float]] = {}
    zone_by_id = {zone.takt_zone_id: zone for zone in zones}
    for _, row in rows.iterrows():
        element_id = clean_text(row.get("Boundary Element Id"))
        room_id = clean_text(row.get("RoomId"))
        if not element_id or room_id not in room_to_zone:
            continue

        start_x = row.get("Start X (ft)")
        start_y = row.get("Start Y (ft)")
        end_x = row.get("End X (ft)")
        end_y = row.get("End Y (ft)")
        if pd.isna(start_x) or pd.isna(start_y) or pd.isna(end_x) or pd.isna(end_y):
            continue

        length = math.hypot(float(end_x) - float(start_x), float(end_y) - float(start_y))
        if length <= 0:
            continue

        zone = room_to_zone[room_id]
        zone_lengths_by_element.setdefault(element_id, {})
        zone_lengths_by_element[element_id][zone.takt_zone_id] = (
            zone_lengths_by_element[element_id].get(zone.takt_zone_id, 0.0) + length
        )

    overlaps: dict[str, list[tuple[GroupedZone, float]]] = {}
    for element_id, zone_lengths in zone_lengths_by_element.items():
        overlaps[element_id] = [
            (zone_by_id[zone_id], length)
            for zone_id, length in sorted(zone_lengths.items(), key=lambda item: zone_by_id[item[0]].sequence)
            if zone_id in zone_by_id and length > 0
        ]
    return overlaps


def build_room_zone_lookup(zones: list[GroupedZone]) -> dict[str, tuple[GroupedZone, RoomZone]]:
    lookup: dict[str, tuple[GroupedZone, RoomZone]] = {}
    for zone in zones:
        for room in zone.rooms:
            tokens = {
                room.room_id,
                room.room_number,
                room.room_name,
                room.room_takt_id,
                f"{room.level} Room {room.room_number}".strip(),
            }
            for token in tokens:
                cleaned = normalize_room_token(token)
                if cleaned:
                    lookup[cleaned] = (zone, room)
    return lookup


def normalize_room_token(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text.casefold()


def zone_from_room_parameters(row: pd.Series, room_zone_lookup: dict[str, tuple[GroupedZone, RoomZone]]) -> tuple[GroupedZone, RoomZone] | None:
    for column in ["Room Id", "Room Number", "Room Name", "room_id", "room_number", "room_name", "room_takt_id"]:
        match = room_zone_lookup.get(normalize_room_token(row.get(column)))
        if match is not None:
            return match
    return None


def element_centroid(row: pd.Series) -> tuple[float, float]:
    x = parse_measure(row.get("Bounding Box Center X (ft)")) or parse_measure(row.get("Position X (ft)"))
    y = parse_measure(row.get("Bounding Box Center Y (ft)")) or parse_measure(row.get("Position Y (ft)"))
    return x, y


def polygon_contains_point(points: list[tuple[float, float]], x: float, y: float) -> bool:
    inside = False
    if len(points) < 3:
        return inside

    previous_x, previous_y = points[-1]
    for current_x, current_y in points:
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            x_at_y = (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x
            if x <= x_at_y:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def zone_from_centroid(row: pd.Series, zones: list[GroupedZone]) -> tuple[GroupedZone | None, RoomZone | None, str]:
    level = clean_text(row.get("Level"))
    level_zones = [zone for zone in zones if zone.level == level]
    if not level_zones:
        return None, None, ""

    x, y = element_centroid(row)
    for zone in sorted(level_zones, key=lambda item: item.sequence):
        for room in zone.rooms:
            if polygon_contains_point(room.points, x, y):
                return zone, room, "centroid in room polygon"

    nearest_room_zone = min(
        ((zone, room) for zone in level_zones for room in zone.rooms),
        key=lambda item: math.hypot(x - item[1].x, y - item[1].y),
    )
    return nearest_room_zone[0], nearest_room_zone[1], "nearest centroid fallback"


def room_group_key(room: RoomZone | None, zone: GroupedZone) -> str:
    if room is None:
        return normalize_room_token(zone.takt_zone_id)
    return (
        normalize_room_token(room.room_id)
        or normalize_room_token(room.room_number)
        or normalize_room_token(room.room_name)
        or normalize_room_token(room.room_takt_id)
        or normalize_room_token(zone.takt_zone_id)
    )


def room_group_label(room: RoomZone | None, zone: GroupedZone) -> str:
    if room is None:
        return zone.takt_zone_id
    return room.room_takt_id or room.room_number or room.room_name or room.room_id or zone.takt_zone_id


def nearest_zone(row: pd.Series, zones: list[GroupedZone]) -> GroupedZone | None:
    level = clean_text(row.get("Level"))
    level_zones = [zone for zone in zones if zone.level == level]
    if not level_zones:
        return None
    x = parse_measure(row.get("Bounding Box Center X (ft)")) or parse_measure(row.get("Position X (ft)"))
    y = parse_measure(row.get("Bounding Box Center Y (ft)")) or parse_measure(row.get("Position Y (ft)"))
    return min(
        level_zones,
        key=lambda zone: math.hypot(x - ((zone.min_x + zone.max_x) / 2), y - ((zone.min_y + zone.max_y) / 2)),
    )


def quantity_unit_from_rate_unit(unit: object) -> str:
    text = clean_text(unit).upper()
    if "/" in text:
        text = text.split("/", 1)[0]
    text = text.strip()
    if text in {"SF", "SQFT", "SQ FT", "SQUARE FEET", "SQUARE FOOT"}:
        return "SF"
    if text in {"CF", "CUFT", "CU FT", "CUBIC FEET", "CUBIC FOOT"}:
        return "CF"
    return "EA"


def productivity_task_order(productivity_rates: pd.DataFrame) -> list[str]:
    return [clean_text(task) for task in productivity_rates["task"].tolist() if clean_text(task)]


def productivity_units(productivity_rates: pd.DataFrame) -> dict[str, str]:
    return {
        clean_text(row["task"]): quantity_unit_from_rate_unit(row["unit"])
        for _, row in productivity_rates.iterrows()
    }


def element_quantity(row: pd.Series, task: str, task_units: dict[str, str]) -> float:
    unit = task_units.get(task, "EA")
    if unit == "SF":
        return parse_measure(row.get("Area")) or 1.0
    if unit == "CF":
        return parse_measure(row.get("Volume")) or 1.0
    return 1.0


def element_long_axis(row: pd.Series) -> str:
    min_x, min_y, max_x, max_y = element_bbox(row)
    width = abs(max_x - min_x)
    depth = abs(max_y - min_y)
    if width > depth:
        return "x-long"
    if depth > width:
        return "y-long"
    return "balanced"


def grouped_element_key(row: pd.Series, task: str, zone: GroupedZone, room_key: str) -> str:
    category = clean_text(row.get("Category"))
    original_category = clean_text(row.get("Original Category"))
    if task == "MEP":
        return f"mep-assembly:{room_key or normalize_room_token(zone.takt_zone_id)}:{element_long_axis(row)}"
    if task == "Ceiling" and category == "Parts" and original_category == "Ceilings":
        room_token = (
            normalize_room_token(row.get("Room Id"))
            or normalize_room_token(row.get("Room Number"))
            or normalize_room_token(row.get("Room Name"))
            or room_key
            or normalize_room_token(zone.takt_zone_id)
        )
        center_x = round(parse_measure(row.get("Bounding Box Center X (ft)")) or parse_measure(row.get("Position X (ft)")), 3)
        center_y = round(parse_measure(row.get("Bounding Box Center Y (ft)")) or parse_measure(row.get("Position Y (ft)")), 3)
        min_x = round(parse_measure(row.get("Bounding Box Min X (ft)")), 3)
        max_x = round(parse_measure(row.get("Bounding Box Max X (ft)")), 3)
        min_y = round(parse_measure(row.get("Bounding Box Min Y (ft)")), 3)
        max_y = round(parse_measure(row.get("Bounding Box Max Y (ft)")), 3)
        return f"ceiling-footprint:{room_token}:{center_x}:{center_y}:{min_x}:{max_x}:{min_y}:{max_y}"
    return clean_text(row.get("ElementId"))


def allocate_elements(
    zones: list[GroupedZone],
    productivity_rates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not CENTRAL_BIM_PATH.exists():
        raise FileNotFoundError(f"Missing central BIM model: {CENTRAL_BIM_PATH}")

    bim = pd.read_csv(CENTRAL_BIM_PATH, dtype=str).fillna("")
    records: list[dict[str, object]] = []
    task_units = productivity_units(productivity_rates)
    configured_tasks = set(task_units)
    room_zone_lookup = build_room_zone_lookup(zones)

    for _, row in bim.iterrows():
        tasks = [task for task in classify_tasks(row) if task in configured_tasks]
        if not tasks:
            continue

        level_zones = [zone for zone in zones if zone.level == clean_text(row.get("Level"))]
        if not level_zones:
            continue

        element_id = clean_text(row.get("ElementId"))
        room_match = zone_from_room_parameters(row, room_zone_lookup)
        if room_match is not None and room_match[0].level == clean_text(row.get("Level")):
            assigned_zone, assigned_room = room_match
            allocation_method = "room parameter"
        else:
            assigned_zone, assigned_room, allocation_method = zone_from_centroid(row, zones)
        if assigned_zone is None:
            continue
        allocation_room_key = room_group_key(assigned_room, assigned_zone)

        for task in tasks:
            quantity = element_quantity(row, task, task_units)
            records.append(
                {
                    "element_id": element_id,
                    "grouped_element_key": grouped_element_key(row, task, assigned_zone, allocation_room_key),
                    "task": task,
                    "level": clean_text(row.get("Level")),
                    "takt_zone_id": assigned_zone.takt_zone_id,
                    "allocation_room": room_group_label(assigned_room, assigned_zone),
                    "source_category": clean_text(row.get("Category")),
                    "source_original_category": clean_text(row.get("Original Category")),
                    "quantity": round(quantity, 4),
                    "quantity_unit": task_units.get(task, "EA"),
                    "allocation_method": allocation_method,
                    "split_from_element_id": "",
                    "split_share": 1.0,
                }
            )

    allocation_columns = [
        "element_id",
        "grouped_element_key",
        "task",
        "level",
        "takt_zone_id",
        "allocation_room",
        "source_category",
        "source_original_category",
        "quantity",
        "quantity_unit",
        "allocation_method",
        "split_from_element_id",
        "split_share",
    ]
    split_columns = ["element_id", "task", "level", "zone_count", "outside_share", "threshold", "method"]
    return pd.DataFrame(records, columns=allocation_columns), pd.DataFrame(columns=split_columns)


def load_crews() -> pd.DataFrame:
    if not CREW_PATH.exists():
        raise FileNotFoundError(f"Missing crew file: {CREW_PATH}")
    crews = pd.read_csv(CREW_PATH, dtype=str).fillna("")
    crews["count_numeric"] = crews["count"].apply(parse_measure).replace(0, 1)
    return crews


def load_equipment() -> pd.DataFrame:
    if not EQUIPMENT_PATH.exists():
        return pd.DataFrame(columns=["equipment_type", "count", "cost"])
    return pd.read_csv(EQUIPMENT_PATH, dtype=str).fillna("")


def productivity_rates_frame() -> pd.DataFrame:
    default_rates = pd.DataFrame(DEFAULT_PRODUCTIVITY_ROWS)
    if not PRODUCTIVITY_RATES_PATH.exists():
        return default_rates

    rates = pd.read_csv(PRODUCTIVITY_RATES_PATH, dtype=str).fillna("")
    required_columns = {"task", "planning_crew", "rate", "unit"}
    if not required_columns.issubset(rates.columns):
        missing = sorted(required_columns - set(rates.columns))
        raise ValueError(f"Productivity rates file is missing columns: {missing}")

    rates = rates[rates["task"].apply(clean_text) != ""].copy()

    rates["planning_crew"] = rates.apply(
        lambda row: clean_text(row.get("planning_crew")) or f"{clean_text(row.get('task')).lower().replace(' ', '_')}_crew",
        axis=1,
    )
    rates["rate"] = rates["rate"].apply(parse_measure)
    rates["unit"] = rates.apply(
        lambda row: clean_text(row.get("unit")) or "EA/crew-hour",
        axis=1,
    )
    if (rates["rate"] <= 0).any():
        bad_tasks = rates.loc[rates["rate"] <= 0, "task"].tolist()
        raise ValueError(f"Productivity rates must be greater than zero for: {bad_tasks}")

    return rates.reset_index(drop=True)


def productivity_lookup(productivity_rates: pd.DataFrame) -> dict[str, dict[str, object]]:
    return {
        clean_text(row["task"]): {
            "planning_crew": clean_text(row["planning_crew"]),
            "rate": float(row["rate"]),
            "unit": clean_text(row["unit"]),
        }
        for _, row in productivity_rates.iterrows()
    }


def crew_for_task(task: str, crews: pd.DataFrame, productivity_rates: pd.DataFrame) -> tuple[str, float]:
    crew_label = clean_text(productivity_lookup(productivity_rates).get(task, {}).get("planning_crew"))
    matches = crews[crews["crew_type"].astype(str).str.strip().eq(crew_label)]
    if matches.empty:
        return crew_label, 1.0
    row = matches.iloc[0]
    return crew_label, float(row["count_numeric"])


def working_hours_per_day(crews: pd.DataFrame) -> int:
    hour_lists = []
    for value in crews.get("hours", []):
        hours = [hour.strip() for hour in clean_text(value).split(",") if hour.strip()]
        if hours:
            hour_lists.append(hours)
    return max((len(hours) for hours in hour_lists), default=8)


def build_schedule(
    element_allocations: pd.DataFrame,
    zones: list[GroupedZone],
    crews: pd.DataFrame,
    productivity_rates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    hours_per_day = working_hours_per_day(crews)
    start_anchor = datetime(2030, 1, 2, 9, 0, 0)
    crew_available: dict[str, float] = {}
    task_zone_finish: dict[tuple[str, str], float] = {}
    rows: list[dict[str, object]] = []
    rates_by_task = productivity_lookup(productivity_rates)
    task_sequence = productivity_task_order(productivity_rates)
    task_units = productivity_units(productivity_rates)

    quantities = (
        element_allocations.groupby(["takt_zone_id", "task", "quantity_unit"], as_index=False)["quantity"].sum()
        if not element_allocations.empty
        else pd.DataFrame(columns=["takt_zone_id", "task", "quantity_unit", "quantity"])
    )
    grouped_ea_quantities = (
        element_allocations[
            element_allocations["quantity_unit"].astype(str).eq("EA")
        ]
        .groupby(["takt_zone_id", "task", "quantity_unit"], as_index=False)
        .agg(quantity=("grouped_element_key", "nunique"))
        if not element_allocations.empty and "grouped_element_key" in element_allocations.columns
        else pd.DataFrame(columns=["takt_zone_id", "task", "quantity_unit", "quantity"])
    )
    if not grouped_ea_quantities.empty:
        non_ea_quantities = quantities[~quantities["quantity_unit"].astype(str).eq("EA")]
        quantities = pd.concat([non_ea_quantities, grouped_ea_quantities], ignore_index=True)

    zone_by_id = {zone.takt_zone_id: zone for zone in zones}
    for zone in zones:
        for task_index, task in enumerate(task_sequence):
            crew_name, crew_count = crew_for_task(task, crews, productivity_rates)
            unit = task_units.get(task, "EA")
            production_rate = float(rates_by_task.get(task, {}).get("rate", 1.0))
            match = quantities[
                (quantities["takt_zone_id"] == zone.takt_zone_id)
                & (quantities["task"] == task)
                & (quantities["quantity_unit"] == unit)
            ]
            quantity = float(match["quantity"].sum()) if not match.empty else 0.0
            duration_hours = max(quantity / (production_rate * max(crew_count, 1.0)), 0.25)

            predecessor_finish = 0.0
            if task_index > 0:
                predecessor_finish = task_zone_finish.get((zone.takt_zone_id, task_sequence[task_index - 1]), 0.0)
            crew_ready = crew_available.get(crew_name, 0.0)
            start_hour = max(predecessor_finish, crew_ready)
            finish_hour = start_hour + duration_hours
            idle_hours = max(0.0, start_hour - crew_ready)
            crew_available[crew_name] = finish_hour
            task_zone_finish[(zone.takt_zone_id, task)] = finish_hour

            start_dt = start_anchor + timedelta(days=int(start_hour // hours_per_day), hours=start_hour % hours_per_day)
            finish_dt = start_anchor + timedelta(days=int(finish_hour // hours_per_day), hours=finish_hour % hours_per_day)
            rows.append(
                {
                    "sequence": zone.sequence,
                    "takt_zone_id": zone.takt_zone_id,
                    "level": zone.level,
                    "rooms": "; ".join(room.room_takt_id for room in zone.rooms),
                    "task": task,
                    "crew": crew_name,
                    "quantity": round(quantity, 4),
                    "quantity_unit": unit,
                    "productivity_rate": round(production_rate, 4),
                    "productivity_unit": clean_text(rates_by_task.get(task, {}).get("unit")) or f"{unit}/crew-hour",
                    "duration_hours": round(duration_hours, 4),
                    "start_hour": round(start_hour, 4),
                    "finish_hour": round(finish_hour, 4),
                    "idle_before_hours": round(idle_hours, 4),
                    "start": start_dt.isoformat(timespec="minutes"),
                    "finish": finish_dt.isoformat(timespec="minutes"),
                }
            )

    schedule = pd.DataFrame(rows)
    idle = (
        schedule.groupby("crew", as_index=False)
        .agg(idle_hours=("idle_before_hours", "sum"), work_hours=("duration_hours", "sum"), finish_hour=("finish_hour", "max"))
        .sort_values("crew")
    )
    idle["idle_hours"] = idle["idle_hours"].round(4)
    idle["work_hours"] = idle["work_hours"].round(4)
    idle["finish_hour"] = idle["finish_hour"].round(4)
    idle["utilization"] = (idle["work_hours"] / idle["finish_hour"].where(idle["finish_hour"] > 0, 1)).round(4)
    return schedule, idle


def write_zone_summary(zones: list[GroupedZone], path: Path) -> None:
    rows = []
    for zone in zones:
        rows.append(
            {
                "takt_zone_id": zone.takt_zone_id,
                "sequence": zone.sequence,
                "level": zone.level,
                "room_count": len(zone.rooms),
                "rooms": "; ".join(room.room_takt_id for room in zone.rooms),
                "area_sf": round(sum(room.area_sf for room in zone.rooms), 3),
                "volume_cf": round(sum(room.volume_cf for room in zone.rooms), 3),
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def write_report(
    schedule: pd.DataFrame,
    idle: pd.DataFrame,
    split_records: pd.DataFrame,
    equipment: pd.DataFrame,
    productivity_rates: pd.DataFrame,
    rooms_per_zone: int,
    level: str,
    path: Path,
) -> None:
    final_duration = float(schedule["finish_hour"].max()) if not schedule.empty else 0.0
    task_sequence = productivity_task_order(productivity_rates)
    lines = [
        "# Takt Planner Report",
        "",
        f"- Level: {level}",
        f"- Rooms per grouped zone: {rooms_per_zone}",
        f"- Task dependency: {' -> '.join(task_sequence)}",
        f"- Final duration: {final_duration:.2f} working hours",
        f"- Split planning records: {len(split_records)} source elements",
        "",
        "## Crew Idle Time",
        "",
        "| Crew | Idle Hours | Work Hours | Utilization |",
        "|---|---:|---:|---:|",
    ]
    for _, row in idle.iterrows():
        lines.append(
            f"| {row['crew']} | {float(row['idle_hours']):.2f} | {float(row['work_hours']):.2f} | {float(row['utilization']) * 100:.1f}% |"
        )
    lines.extend(["", "## Productivity Rates", "", "| Task | Planning Crew | Rate | Unit |", "|---|---|---:|---|"])
    for _, row in productivity_rates.iterrows():
        lines.append(
            f"| {row['task']} | {row['planning_crew']} | {float(row['rate']):.2f} | {row['unit']} |"
        )
    lines.extend(["", "## Equipment Inputs", "", "| Equipment | Count | Cost |", "|---|---:|---:|"])
    if equipment.empty:
        lines.append("| No equipment rows found | 0 | 0 |")
    else:
        for _, row in equipment.iterrows():
            lines.append(
                f"| {clean_text(row.get('equipment_type'))} | {clean_text(row.get('count')) or '0'} | {clean_text(row.get('cost')) or '0'} |"
            )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Neighboring room grouping uses shared/touching room bounding boxes when possible, then nearest centroid as a fallback.",
            "- Elements are assigned to one takt zone using room parameters first, centroid-in-room second, and nearest room centroid as the final fallback.",
            "- MEP quantities are counted as one assembly per assigned room and dominant direction when the MEP task uses an EA productivity unit.",
            "- Split threshold logic is disabled; no planning cuts are created by the takt planner.",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_zone_map_png(zones: list[GroupedZone], level: str, path: Path) -> Path | None:
    level_zones = [zone for zone in zones if zone.level == level]
    all_points = [point for zone in level_zones for room in zone.rooms for point in room.points]
    if not all_points:
        return None

    min_x = min(point[0] for point in all_points)
    max_x = max(point[0] for point in all_points)
    min_y = min(point[1] for point in all_points)
    max_y = max(point[1] for point in all_points)

    fig, ax = plt.subplots(figsize=(12, 10), dpi=180)
    ax.set_title(f"Takt Zones - {level}")
    ax.set_xlabel("X (ft)")
    ax.set_ylabel("Y (ft)")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.28, linewidth=0.5)

    for index, zone in enumerate(sorted(level_zones, key=lambda item: item.sequence)):
        color = ZONE_COLORS[index % len(ZONE_COLORS)]
        zone_points: list[tuple[float, float]] = []
        for room in zone.rooms:
            if len(room.points) < 3:
                continue
            patch = Polygon(
                room.points,
                closed=True,
                facecolor=color,
                edgecolor=color,
                alpha=0.25,
                linewidth=2.2,
            )
            ax.add_patch(patch)
            ax.plot(
                [point[0] for point in room.points] + [room.points[0][0]],
                [point[1] for point in room.points] + [room.points[0][1]],
                color="#1f2937",
                linewidth=1.2,
                alpha=0.9,
            )
            ax.text(
                room.x,
                room.y,
                room.room_number or room.room_takt_id,
                color="#111827",
                fontsize=8,
                ha="center",
                va="center",
            )
            zone_points.extend(room.points)
        if zone_points:
            label_x = sum(point[0] for point in zone_points) / len(zone_points)
            label_y = sum(point[1] for point in zone_points) / len(zone_points)
            ax.text(
                label_x,
                label_y,
                str(zone.sequence),
                color="#111827",
                fontsize=9,
                ha="center",
                va="center",
                bbox={"boxstyle": "round,pad=0.22", "facecolor": "white", "edgecolor": color, "linewidth": 1.4},
            )

    padding = 4.0
    ax.set_xlim(min_x - padding, max_x + padding)
    ax.set_ylim(min_y - padding, max_y + padding)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def build_trade_hover_summaries(element_allocations: pd.DataFrame) -> dict[tuple[str, str], str]:
    if element_allocations.empty:
        return {}

    summaries: dict[tuple[str, str], str] = {}
    for (zone_id, task), task_df in element_allocations.groupby(["takt_zone_id", "task"], sort=False):
        if "grouped_element_key" in task_df.columns:
            element_count = task_df["grouped_element_key"].astype(str).nunique()
        else:
            element_count = task_df["element_id"].astype(str).nunique()
        label = "element" if element_count == 1 else "elements"
        summaries[(clean_text(zone_id), clean_text(task))] = (
            f"<strong>{html.escape(clean_text(task))}</strong>"
            f"<span>{element_count} unique {label}</span>"
        )
    return summaries


def build_model_metadata(
    zones: list[GroupedZone],
    schedule: pd.DataFrame,
    element_allocations: pd.DataFrame,
) -> dict[str, object]:
    zone_color_by_id = {
        zone.takt_zone_id: ZONE_COLORS[(zone.sequence - 1) % len(ZONE_COLORS)]
        for zone in zones
    }
    zone_options = [
        {
            "id": zone.takt_zone_id,
            "label": zone.label,
            "sequence": zone.sequence,
            "color": zone_color_by_id[zone.takt_zone_id],
        }
        for zone in sorted(zones, key=lambda item: item.sequence)
    ]

    element_by_id: dict[str, dict[str, object]] = {}
    zone_elements: dict[str, set[str]] = {zone.takt_zone_id: set() for zone in zones}
    task_counts: dict[str, dict[str, set[str]]] = {zone.takt_zone_id: {} for zone in zones}

    if not element_allocations.empty:
        for _, row in element_allocations.iterrows():
            element_id = clean_text(row.get("element_id"))
            zone_id = clean_text(row.get("takt_zone_id"))
            task = clean_text(row.get("task"))
            if not element_id or not zone_id:
                continue

            record = element_by_id.setdefault(
                element_id,
                {
                    "element_id": element_id,
                    "zones": set(),
                    "tasks": set(),
                    "rooms": set(),
                    "categories": set(),
                    "original_categories": set(),
                },
            )
            record["zones"].add(zone_id)
            if task:
                record["tasks"].add(task)
            allocation_room = clean_text(row.get("allocation_room"))
            if allocation_room:
                record["rooms"].add(allocation_room)
            category = clean_text(row.get("source_category"))
            if category:
                record["categories"].add(category)
            original_category = clean_text(row.get("source_original_category"))
            if original_category:
                record["original_categories"].add(original_category)

            zone_elements.setdefault(zone_id, set()).add(element_id)
            task_counts.setdefault(zone_id, {}).setdefault(task, set()).add(clean_text(row.get("grouped_element_key")) or element_id)

    schedule_by_zone: dict[str, list[dict[str, object]]] = {zone.takt_zone_id: [] for zone in zones}
    for _, row in schedule.iterrows():
        zone_id = clean_text(row.get("takt_zone_id"))
        schedule_by_zone.setdefault(zone_id, []).append(
            {
                "task": clean_text(row.get("task")),
                "crew": clean_text(row.get("crew")),
                "start_hour": round(float(row.get("start_hour", 0.0)), 2),
                "finish_hour": round(float(row.get("finish_hour", 0.0)), 2),
                "duration_hours": round(float(row.get("duration_hours", 0.0)), 2),
                "quantity": round(float(row.get("quantity", 0.0)), 2),
                "quantity_unit": clean_text(row.get("quantity_unit")),
            }
        )

    serializable_elements = {
        element_id: {
            key: sorted(value) if isinstance(value, set) else value
            for key, value in record.items()
        }
        for element_id, record in element_by_id.items()
    }
    zone_summaries = {
        zone_id: {
            "element_count": len(zone_elements.get(zone_id, set())),
            "task_counts": {
                task: len(keys)
                for task, keys in sorted(task_counts.get(zone_id, {}).items())
                if task
            },
            "schedule": schedule_by_zone.get(zone_id, []),
        }
        for zone_id in zone_elements
    }

    return {
        "zones": zone_options,
        "zone_colors": zone_color_by_id,
        "element_by_id": serializable_elements,
        "zone_elements": {zone_id: sorted(elements) for zone_id, elements in zone_elements.items()},
        "zone_summaries": zone_summaries,
    }


def write_model_viewer_html(
    zones: list[GroupedZone],
    schedule: pd.DataFrame,
    element_allocations: pd.DataFrame,
    fbx_path: Path | None,
    path: Path,
) -> Path | None:
    if fbx_path is None:
        return None

    metadata = build_model_metadata(zones, schedule, element_allocations)
    metadata_json = json.dumps(metadata)
    model_src = html.escape(Path(os.path.relpath(fbx_path, path.parent)).as_posix())
    zone_options = "\n".join(
        f"<option value=\"{html.escape(zone['id'])}\">{html.escape(zone['label'])}</option>"
        for zone in metadata["zones"]
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Takt BIM Model Viewer</title>
<style>
:root {{ color-scheme: light; font-family: Inter, Segoe UI, Arial, sans-serif; }}
body {{ margin: 0; background: #eef2f7; color: #111827; overflow: hidden; }}
.app {{ display: grid; grid-template-columns: 320px 1fr; height: 100vh; }}
aside {{ background: #ffffff; border-right: 1px solid #dbe3ee; padding: 16px; overflow: auto; }}
main {{ position: relative; min-width: 0; }}
h1 {{ margin: 0 0 12px; font-size: 20px; letter-spacing: 0; }}
h2 {{ margin: 18px 0 8px; font-size: 13px; color: #334155; text-transform: uppercase; letter-spacing: 0; }}
label {{ display: block; font-size: 12px; color: #475569; margin-bottom: 6px; }}
select, button {{ width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 4px; background: white; color: #111827; padding: 8px 10px; font-size: 13px; }}
button {{ cursor: pointer; margin-top: 8px; }}
button:hover {{ background: #f8fafc; }}
.row {{ display: flex; gap: 8px; align-items: center; margin-top: 10px; font-size: 13px; color: #334155; }}
.row input {{ width: 16px; height: 16px; }}
#viewer {{ width: 100%; height: 100%; display: block; background: #dbe5ef; }}
.status {{ position: absolute; left: 16px; top: 16px; background: rgba(15, 23, 42, 0.88); color: white; padding: 8px 10px; border-radius: 4px; font-size: 12px; max-width: 520px; }}
.swatch-list {{ display: grid; gap: 6px; margin-top: 8px; }}
.swatch {{ display: grid; grid-template-columns: 14px 1fr auto; gap: 8px; align-items: center; font-size: 12px; color: #334155; }}
.swatch i {{ width: 14px; height: 14px; border-radius: 2px; display: block; }}
.info {{ font-size: 13px; line-height: 1.45; color: #334155; }}
.info strong {{ display: block; color: #0f172a; margin: 8px 0 2px; }}
.schedule-row {{ border-bottom: 1px solid #e5e7eb; padding: 6px 0; font-size: 12px; }}
.schedule-row span {{ display: block; color: #64748b; }}
.empty {{ color: #64748b; font-size: 13px; }}
canvas {{ outline: none; }}
</style>
</head>
<body>
<div class="app">
  <aside>
    <h1>Takt BIM Viewer</h1>
    <label for="zoneFilter">Takt Zone</label>
    <select id="zoneFilter">
      <option value="all">All zones</option>
      {zone_options}
    </select>
    <button id="resetView" type="button">Reset View</button>
    <label class="row"><input id="isolateZone" type="checkbox" checked> Isolate selected zone</label>

    <h2>Zones</h2>
    <div id="zoneLegend" class="swatch-list"></div>

    <h2>Selected</h2>
    <div id="selectedInfo" class="info empty">Click an element in the model.</div>

    <h2>Zone Schedule</h2>
    <div id="zoneSchedule" class="info empty">Select a takt zone.</div>
  </aside>
  <main>
    <canvas id="viewer"></canvas>
    <div id="status" class="status">Loading model...</div>
  </main>
</div>
<script type="importmap">
{{
  "imports": {{
    "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
  }}
}}
</script>
<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
import {{ FBXLoader }} from 'three/addons/loaders/FBXLoader.js';

const MODEL_SRC = "{model_src}";
const DATA = {metadata_json};
const canvas = document.getElementById('viewer');
const statusEl = document.getElementById('status');
const zoneFilter = document.getElementById('zoneFilter');
const isolateZone = document.getElementById('isolateZone');
const selectedInfo = document.getElementById('selectedInfo');
const zoneSchedule = document.getElementById('zoneSchedule');
const zoneLegend = document.getElementById('zoneLegend');

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xdbe5ef);
const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 100000);
const renderer = new THREE.WebGLRenderer({{ canvas, antialias: true }});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

scene.add(new THREE.HemisphereLight(0xffffff, 0x64748b, 2.2));
const sun = new THREE.DirectionalLight(0xffffff, 2.4);
sun.position.set(80, 120, 80);
scene.add(sun);

let model = null;
let selectable = [];
let selectedObject = null;
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const VALID_ELEMENT_IDS = new Set(Object.keys(DATA.element_by_id));
const VALID_ELEMENT_IDS_BY_LENGTH = [...VALID_ELEMENT_IDS].sort((a, b) => b.length - a.length);

function extractElementId(object) {{
  const candidates = [];
  let current = object;
  while (current) {{
    candidates.push(current.name);
    candidates.push(current.geometry && current.geometry.name);
    candidates.push(current.material && current.material.name);
    if (current.userData) {{
      for (const value of Object.values(current.userData)) candidates.push(value);
    }}
    current = current.parent;
  }}
  for (const candidate of candidates) {{
    const text = String(candidate || '');
    const directMatch = text.match(/\\[(\\d{{4,}})\\]/);
    if (directMatch && VALID_ELEMENT_IDS.has(directMatch[1])) return directMatch[1];

    const encodedMatch = text.match(/(?:_u005[Bb]|%5[Bb]|\\()\\s*(\\d{{4,}})\\s*(?:_u005[Dd]|%5[Dd]|\\))/);
    if (encodedMatch && VALID_ELEMENT_IDS.has(encodedMatch[1])) return encodedMatch[1];

    const tailMatch = text.match(/(?:^|[^0-9])(\\d{{6,}})(?:[^0-9]|$)/g);
    if (tailMatch) {{
      for (const token of tailMatch) {{
        const id = token.replace(/\\D/g, '');
        if (VALID_ELEMENT_IDS.has(id)) return id;
      }}
    }}
  }}
  const joined = candidates.map(value => String(value || '')).join(' ');
  for (const id of VALID_ELEMENT_IDS_BY_LENGTH) {{
    if (joined.includes(id)) return id;
  }}
  return '';
}}

function colorForZone(zoneId) {{
  return DATA.zone_colors[zoneId] || '#94a3b8';
}}

function materialFor(color, opacity = 1) {{
  return new THREE.MeshStandardMaterial({{
    color: new THREE.Color(color),
    roughness: 0.72,
    metalness: 0.05,
    transparent: opacity < 1,
    opacity,
    depthWrite: opacity >= 1,
  }});
}}

function firstZoneForElement(elementId) {{
  const record = DATA.element_by_id[elementId];
  return record && record.zones && record.zones.length ? record.zones[0] : '';
}}

function selectedZoneId() {{
  return zoneFilter.value === 'all' ? '' : zoneFilter.value;
}}

function applyZoneFilter() {{
  const zoneId = selectedZoneId();
  for (const mesh of selectable) {{
    const elementId = mesh.userData.elementId;
    const record = DATA.element_by_id[elementId];
    const zones = record ? record.zones || [] : [];
    const inZone = !zoneId || zones.includes(zoneId);
    mesh.visible = !zoneId || inZone || !isolateZone.checked;
    const color = inZone ? colorForZone(zones[0]) : '#cbd5e1';
    const opacity = inZone ? 0.92 : 0.16;
    mesh.material = materialFor(color, opacity);
  }}
  renderZoneSchedule(zoneId);
}}

function renderZoneSchedule(zoneId) {{
  if (!zoneId) {{
    zoneSchedule.className = 'info empty';
    zoneSchedule.textContent = 'Select a takt zone.';
    return;
  }}
  const summary = DATA.zone_summaries[zoneId] || {{}};
  const rows = summary.schedule || [];
  const counts = summary.task_counts || {{}};
  zoneSchedule.className = 'info';
  zoneSchedule.innerHTML = `
    <strong>${{zoneId}}</strong>
    <div>${{summary.element_count || 0}} linked FBX/BIM elements</div>
    <div>${{Object.entries(counts).map(([task, count]) => `${{task}}: ${{count}}`).join('<br>')}}</div>
    <strong>Tasks</strong>
    ${{rows.map(row => `<div class="schedule-row">${{row.task}}<span>${{row.start_hour}}h to ${{row.finish_hour}}h · ${{row.quantity}} ${{row.quantity_unit}}</span></div>`).join('') || '<div class="empty">No schedule rows.</div>'}}
  `;
}}

function renderLegend() {{
  zoneLegend.innerHTML = DATA.zones.map(zone => {{
    const summary = DATA.zone_summaries[zone.id] || {{}};
    return `<button class="swatch" type="button" data-zone="${{zone.id}}">
      <i style="background:${{zone.color}}"></i>
      <span>${{zone.label}}</span>
      <em>${{summary.element_count || 0}}</em>
    </button>`;
  }}).join('');
  zoneLegend.querySelectorAll('button[data-zone]').forEach(button => {{
    button.addEventListener('click', () => {{
      zoneFilter.value = button.dataset.zone;
      applyZoneFilter();
    }});
  }});
}}

function showElementInfo(mesh) {{
  const elementId = mesh.userData.elementId || extractElementId(mesh);
  const record = DATA.element_by_id[elementId];
  selectedObject = mesh;
  if (!record) {{
    selectedInfo.className = 'info';
    selectedInfo.innerHTML = `<strong>${{mesh.name || 'FBX object'}}</strong><div>ElementId: ${{elementId || 'not found'}}</div><div>No takt allocation match.</div>`;
    return;
  }}
  selectedInfo.className = 'info';
  selectedInfo.innerHTML = `
    <strong>${{mesh.name || 'FBX object'}}</strong>
    <div>ElementId: ${{elementId}}</div>
    <div>Zone: ${{record.zones.join(', ')}}</div>
    <div>Task: ${{record.tasks.join(', ')}}</div>
    <div>Room: ${{record.rooms.join(', ') || 'n/a'}}</div>
    <div>Category: ${{record.categories.join(', ') || 'n/a'}}</div>
  `;
}}

function fitCameraToObject(object) {{
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z);
  const distance = maxDim / (2 * Math.tan((Math.PI * camera.fov) / 360));
  camera.position.set(center.x + distance * 0.72, center.y + distance * 0.64, center.z + distance * 0.72);
  camera.near = Math.max(distance / 1000, 0.1);
  camera.far = distance * 12;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}}

function resize() {{
  const rect = canvas.parentElement.getBoundingClientRect();
  renderer.setSize(rect.width, rect.height, false);
  camera.aspect = rect.width / Math.max(rect.height, 1);
  camera.updateProjectionMatrix();
}}

function animate() {{
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}}

canvas.addEventListener('pointerdown', event => {{
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(selectable.filter(mesh => mesh.visible), false)[0];
  if (hit) showElementInfo(hit.object);
}});

zoneFilter.addEventListener('change', applyZoneFilter);
isolateZone.addEventListener('change', applyZoneFilter);
document.getElementById('resetView').addEventListener('click', () => {{
  if (model) fitCameraToObject(model);
}});
window.addEventListener('resize', resize);

renderLegend();
resize();
animate();

new FBXLoader().load(
  MODEL_SRC,
  object => {{
    model = object;
    scene.add(model);
    let matched = 0;
    let total = 0;
    const unmatchedNames = [];
    object.traverse(child => {{
      if (!child.isMesh) return;
      total += 1;
      const elementId = extractElementId(child);
      child.userData.elementId = elementId;
      child.castShadow = true;
      child.receiveShadow = true;
      if (elementId && DATA.element_by_id[elementId]) matched += 1;
      else if (unmatchedNames.length < 4) unmatchedNames.push(child.name || (child.parent && child.parent.name) || 'unnamed mesh');
      const zoneId = firstZoneForElement(elementId);
      child.material = materialFor(zoneId ? colorForZone(zoneId) : '#cbd5e1', zoneId ? 0.9 : 0.22);
      selectable.push(child);
    }});
    fitCameraToObject(model);
    statusEl.textContent = `Loaded ${{total}} meshes · ${{matched}} matched to takt BIM data` + (unmatchedNames.length ? ` · sample unmatched: ${{unmatchedNames.join(' | ')}}` : '');
    applyZoneFilter();
  }},
  event => {{
    if (event.total) statusEl.textContent = `Loading model... ${{Math.round((event.loaded / event.total) * 100)}}%`;
  }},
  error => {{
    console.error(error);
    statusEl.textContent = 'Could not load FBX. Open this page through a local web server, not directly as a file.';
  }}
);
</script>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")
    return path


def write_html(
    schedule: pd.DataFrame,
    idle: pd.DataFrame,
    zones: list[GroupedZone],
    productivity_rates: pd.DataFrame,
    element_allocations: pd.DataFrame,
    zone_map_path: Path | None,
    model_viewer_path: Path | None,
    path: Path,
) -> None:
    if schedule.empty:
        path.write_text("<!doctype html><title>Takt Planner</title><p>No schedule rows generated.</p>", encoding="utf-8")
        return

    final_hour = float(schedule["finish_hour"].max())
    scale = 28
    task_sequence = productivity_task_order(productivity_rates)
    zone_labels = {zone.takt_zone_id: zone.label for zone in zones}
    trade_summaries = build_trade_hover_summaries(element_allocations)
    bars = []
    for _, row in schedule.iterrows():
        start = float(row["start_hour"]) * scale
        width = max((float(row["finish_hour"]) - float(row["start_hour"])) * scale, 4)
        color = TASK_COLORS.get(row["task"], "#334155")
        bars.append(
            f"""
            <div class="bar" style="left:{start:.1f}px;width:{width:.1f}px;background:{color};">
              <span>{html.escape(row['task'])}</span>
              <small>{html.escape(row['crew'])} · {float(row['duration_hours']):.1f}h</small>
            </div>
            """
        )

    rows_html = []
    for zone_id, zone_df in schedule.groupby("takt_zone_id", sort=False):
        zone_bars = "\n".join(
            (
            f"""
            <div class="bar trade-bar" style="left:{float(row['start_hour']) * scale:.1f}px;width:{max((float(row['finish_hour']) - float(row['start_hour'])) * scale, 4):.1f}px;background:{TASK_COLORS.get(row['task'], '#334155')};">
              <span>{html.escape(row['task'])}</span>
              <div class="trade-tooltip">{trade_summaries.get((clean_text(row['takt_zone_id']), clean_text(row['task'])), '<strong>No elements</strong><span>0 unique elements</span>')}</div>
            </div>
            """
            )
            for _, row in zone_df.iterrows()
        )
        rows_html.append(
            f"""
            <section class="lane" data-zone="{html.escape(zone_id)}">
              <div class="lane-label">{html.escape(zone_labels.get(zone_id, zone_id))}</div>
              <div class="lane-track" style="width:{max(final_hour * scale + 240, 760):.1f}px">{zone_bars}</div>
            </section>
            """
        )

    idle_rows = "\n".join(
        f"<tr><td>{html.escape(row['crew'])}</td><td>{float(row['idle_hours']):.2f}</td><td>{float(row['work_hours']):.2f}</td><td>{float(row['utilization']) * 100:.1f}%</td></tr>"
        for _, row in idle.iterrows()
    )

    legend = "\n".join(
        f"<span><i style=\"background:{TASK_COLORS.get(task, '#334155')}\"></i>{html.escape(task)}</span>"
        for task in task_sequence
    )
    zone_map_panel = ""
    zone_map_button = ""
    model_viewer_button = ""
    if zone_map_path is not None:
        zone_map_src = html.escape(zone_map_path.name)
        zone_map_button = '<button id="zoneMapToggle" class="tool-button" type="button">Show Zone Map</button>'
        zone_map_panel = f"""
  <section id="zoneMapPanel" class="zone-map-panel" hidden>
    <div class="panel-heading">
      <h2>Zone Map</h2>
      <span>{html.escape(zone_map_path.name)}</span>
    </div>
    <img src="{zone_map_src}" alt="Colored takt zones over room boundaries">
  </section>
"""
    if model_viewer_path is not None:
        model_viewer_button = f'<a class="tool-button" href="{html.escape(model_viewer_path.name)}" target="_blank" rel="noopener">View 3D Model</a>'
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Takt Zone Planner</title>
<style>
:root {{ color-scheme: light; font-family: Inter, Segoe UI, Arial, sans-serif; }}
body {{ margin: 0; background: #f8fafc; color: #111827; }}
header {{ padding: 22px 28px 14px; background: white; border-bottom: 1px solid #e5e7eb; }}
h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
.summary {{ display: flex; gap: 18px; flex-wrap: wrap; color: #475569; font-size: 14px; }}
.legend {{ display: flex; gap: 14px; flex-wrap: wrap; margin-top: 14px; }}
.legend span {{ display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }}
.legend i {{ width: 12px; height: 12px; border-radius: 2px; display: inline-block; }}
.toolbar {{ display: flex; gap: 10px; margin-top: 14px; }}
.tool-button {{ border: 1px solid #cbd5e1; background: #fff; color: #0f172a; border-radius: 4px; padding: 8px 12px; font-size: 13px; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; }}
.tool-button:hover {{ background: #f1f5f9; }}
main {{ padding: 20px 28px 32px; }}
.timeline {{ overflow-x: auto; border: 1px solid #dbe3ee; background: white; }}
.lane {{ display: grid; grid-template-columns: 230px 1fr; border-bottom: 1px solid #edf2f7; min-height: 54px; position: relative; }}
.lane:hover {{ background: #f8fafc; }}
.lane-label {{ padding: 12px; font-size: 12px; color: #334155; border-right: 1px solid #e5e7eb; background: #fbfdff; }}
.lane-track {{ position: relative; min-height: 54px; background-image: linear-gradient(to right, #e5e7eb 1px, transparent 1px); background-size: {scale * 8}px 100%; }}
.bar {{ position: absolute; top: 9px; height: 36px; border-radius: 4px; color: white; display: flex; align-items: center; justify-content: center; padding: 0 8px; box-sizing: border-box; font-size: 12px; overflow: hidden; white-space: nowrap; }}
.trade-bar {{ overflow: visible; }}
.trade-tooltip {{ display: none; position: absolute; left: 50%; bottom: 44px; transform: translateX(-50%); z-index: 40; min-width: 150px; padding: 8px 10px; background: #0f172a; color: white; border-radius: 4px; box-shadow: 0 12px 28px rgba(15, 23, 42, 0.24); font-size: 12px; line-height: 1.35; pointer-events: none; text-align: left; }}
.trade-tooltip::after {{ content: ""; position: absolute; left: 50%; top: 100%; transform: translateX(-50%); border: 6px solid transparent; border-top-color: #0f172a; }}
.trade-tooltip strong {{ display: block; margin-bottom: 4px; font-size: 12px; }}
.trade-tooltip span {{ display: block; color: #e2e8f0; }}
.trade-bar:hover .trade-tooltip {{ display: block; }}
.panel {{ margin-top: 20px; background: white; border: 1px solid #dbe3ee; padding: 16px; }}
.zone-map-panel {{ margin-bottom: 20px; background: white; border: 1px solid #dbe3ee; padding: 16px; }}
.zone-map-panel img {{ display: block; max-width: 100%; height: auto; border: 1px solid #e5e7eb; }}
.panel-heading {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }}
.panel-heading span {{ color: #64748b; font-size: 12px; }}
h2 {{ margin: 0 0 12px; font-size: 16px; }}
.panel-heading h2 {{ margin: 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; }}
th {{ color: #475569; }}
</style>
</head>
<body>
<header>
  <h1>Takt Zone Planner</h1>
  <div class="summary">
    <span>Dependency: {html.escape(' -> '.join(task_sequence))}</span>
    <span>Final duration: {final_hour:.2f} working hours</span>
    <span>Zones: {len(zones)}</span>
  </div>
  <div class="legend">{legend}</div>
  <div class="toolbar">{zone_map_button}{model_viewer_button}</div>
</header>
<main>
{zone_map_panel}
  <div class="timeline">
    {''.join(rows_html)}
  </div>
  <section class="panel">
    <h2>Crew Idle Time</h2>
    <table><thead><tr><th>Crew</th><th>Idle Hours</th><th>Work Hours</th><th>Utilization</th></tr></thead><tbody>{idle_rows}</tbody></table>
  </section>
</main>
<script>
const zoneMapToggle = document.getElementById('zoneMapToggle');
const zoneMapPanel = document.getElementById('zoneMapPanel');
if (zoneMapToggle && zoneMapPanel) {{
  zoneMapToggle.addEventListener('click', () => {{
    const isHidden = zoneMapPanel.hasAttribute('hidden');
    if (isHidden) {{
      zoneMapPanel.removeAttribute('hidden');
      zoneMapToggle.textContent = 'Hide Zone Map';
    }} else {{
      zoneMapPanel.setAttribute('hidden', '');
      zoneMapToggle.textContent = 'Show Zone Map';
    }}
  }});
}}
</script>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def run(rooms_per_zone: int, level: str = "L 1") -> dict[str, Path | float | int | str]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rooms = load_rooms()
    zones = group_rooms(rooms, rooms_per_zone, level)
    crews = load_crews()
    equipment = load_equipment()
    productivity_rates = productivity_rates_frame()
    element_allocations, split_records = allocate_elements(zones, productivity_rates)
    schedule, idle = build_schedule(element_allocations, zones, crews, productivity_rates)

    zone_summary_path = OUTPUT_DIR / "Takt_Zones.csv"
    element_allocations_path = OUTPUT_DIR / "Takt_Element_Allocations.csv"
    split_path = OUTPUT_DIR / "Takt_Element_Splits.csv"
    schedule_path = OUTPUT_DIR / "Takt_Schedule.csv"
    idle_path = OUTPUT_DIR / "Takt_Crew_Idle_Report.csv"
    equipment_path = OUTPUT_DIR / "Takt_Equipment_Inputs.csv"
    productivity_path = PRODUCTIVITY_RATES_PATH
    report_path = OUTPUT_DIR / "Takt_Report.md"
    html_path = OUTPUT_DIR / "Takt_Planner.html"
    model_viewer_path = OUTPUT_DIR / "Takt_Model_Viewer.html"
    zone_map_path = OUTPUT_DIR / f"Takt_Zone_Map_{level.replace(' ', '_').replace('-', 'minus')}.png"
    fbx_path = latest_fbx_path()

    write_zone_summary(zones, zone_summary_path)
    element_allocations.to_csv(element_allocations_path, index=False)
    split_records.to_csv(split_path, index=False)
    schedule.to_csv(schedule_path, index=False)
    idle.to_csv(idle_path, index=False)
    equipment.to_csv(equipment_path, index=False)
    productivity_rates.to_csv(productivity_path, index=False)
    write_report(schedule, idle, split_records, equipment, productivity_rates, rooms_per_zone, level, report_path)
    written_zone_map_path = write_zone_map_png(zones, level, zone_map_path)
    written_model_viewer_path = write_model_viewer_html(zones, schedule, element_allocations, fbx_path, model_viewer_path)
    write_html(schedule, idle, zones, productivity_rates, element_allocations, written_zone_map_path, written_model_viewer_path, html_path)

    return {
        "level": level,
        "zone_count": len(zones),
        "schedule_rows": len(schedule),
        "split_elements": len(split_records),
        "final_duration_hours": float(schedule["finish_hour"].max()) if not schedule.empty else 0.0,
        "html_path": html_path,
        "model_viewer_path": written_model_viewer_path or "",
        "zone_map_path": written_zone_map_path or "",
        "report_path": report_path,
        "schedule_path": schedule_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a room-zone takt planner.")
    parser.add_argument("--level", default="L 1", help="Level to plan. Default: L 1.")
    parser.add_argument("--rooms-per-zone", type=int, default=1, help="Number of neighboring rooms to group into each takt zone.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run(args.rooms_per_zone, args.level)
    print(json.dumps({key: str(value) for key, value in result.items()}, indent=2))


if __name__ == "__main__":
    main()
