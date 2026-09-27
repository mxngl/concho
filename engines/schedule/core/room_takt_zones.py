"""Room takt zones (step ``room-takt-zones``): one row per Revit room, input of the takt planner.

Reads the room boundary export of the Revit add-in (``*_Room_Boundaries.csv``: one row per
boundary segment) and writes ``OUT_DIR/room_takt_zones.csv`` with one row per room:

``room_takt_id, room_id, room_number, room_name, level, area_sf, volume_cf, location_x_ft,
location_y_ft, location_z_ft, boundary_segments``

``room_takt_id`` is ``"<level> Room <room number>"`` (room id if there is no number), the same
id the micro schedule derives from the same file (``micro_schedule.load_room_takt_zones``).
Values are copied as exported (no reformatting); ``boundary_segments`` counts the segment
rows of all boundary loops of the room. Rooms keep the order of the export.

Added in P3B.8 (fix 2): IPD_Challenge@989a6b7 has no generator for this file, only the
committed output ``outputs/room_boundaries/room_takt_zones.csv``. That output was made from an
earlier export of the same rooms; see engines/schedule/README.md ("Fixed in P3B.8").
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

OUTPUT_NAME = "room_takt_zones.csv"
OUTPUT_COLUMNS = [
    "room_takt_id", "room_id", "room_number", "room_name", "level", "area_sf", "volume_cf",
    "location_x_ft", "location_y_ft", "location_z_ft", "boundary_segments",
]
# output column -> column of the Revit room boundary export
SOURCE_COLUMNS = {
    "room_id": "RoomId",
    "room_number": "RoomNumber",
    "room_name": "RoomName",
    "level": "Level",
    "area_sf": "Area (SF)",
    "volume_cf": "Volume (CF)",
    "location_x_ft": "Room Location X (ft)",
    "location_y_ft": "Room Location Y (ft)",
    "location_z_ft": "Room Location Z (ft)",
}


def build_room_takt_zones(boundaries: pd.DataFrame) -> pd.DataFrame:
    """One row per room of a room boundary export (all values as strings)."""
    missing = sorted(set(SOURCE_COLUMNS.values()) - set(boundaries.columns))
    if missing:
        raise ValueError(f"Room boundary export is missing columns: {missing}")
    boundaries = boundaries.astype(str).apply(lambda column: column.str.strip())
    boundaries = boundaries[boundaries["RoomId"] != ""]
    rooms = boundaries.groupby("RoomId", sort=False)
    output = rooms[list(SOURCE_COLUMNS.values())].first().reset_index(drop=True)
    output.columns = list(SOURCE_COLUMNS)
    output["boundary_segments"] = rooms.size().to_numpy()
    label = output["room_number"].where(output["room_number"] != "", output["room_id"])
    output["room_takt_id"] = (output["level"] + " Room " + label).str.strip()
    return output[OUTPUT_COLUMNS]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="concho-schedule room-takt-zones",
        description="Revit room boundary export -> room_takt_zones.csv (input of takt-plan).",
    )
    parser.add_argument("--room-boundaries", type=Path, required=True, metavar="CSV",
                        help="*_Room_Boundaries.csv exported by the Revit add-in")
    parser.add_argument("--out-dir", type=Path, required=True, metavar="DIR",
                        help="output folder")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    # utf-8-sig: the add-in writes a byte order mark.
    boundaries = pd.read_csv(
        args.room_boundaries, dtype=str, keep_default_na=False, encoding="utf-8-sig"
    )
    output = build_room_takt_zones(boundaries)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / OUTPUT_NAME
    output.to_csv(path, index=False)
    print(f"Wrote {path} ({len(output)} rooms)")


if __name__ == "__main__":
    main()
