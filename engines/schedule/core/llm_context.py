from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent.parent

INPUT_PATH = PROJECT_DIR / "outputs" / "takt_zones" / "central_bim_model_with_takt.csv"
OUTPUT_PATH = PROJECT_DIR / "outputs" / "takt_zones" / "central_bim_model_llm_context.csv"


KEEP_COLUMNS = [
    "element_id",
    "discipline",
    "category",
    "family",
    "type",
    "level",
    "base_level",
    "top_level",
    "mark",
    "system_name",
    "system_type",
    "service_type",
    "classification",
    "assembly_code",
    "assembly_description",
    "material",
    "size",
    "width",
    "height",
    "length",
    "depth",
    "area",
    "volume",
    "room_id",
    "room_number",
    "room_name",
    "room_level",
    "room_area_sf",
    "room_volume_cf",
    "room_location_x_ft",
    "room_location_y_ft",
    "room_location_z_ft",
    "takt_id",
]


RENAME_COLUMNS = {
    "ElementId": "element_id",
    "Category": "category",
    "Family": "family",
    "Type": "type",
    "Level": "level",
    "Mark": "mark",
    "System Name": "system_name",
    "System Type": "system_type",
    "Service Type": "service_type",
    "Classification": "classification",
    "Assembly Code": "assembly_code",
    "Assembly Description": "assembly_description",
    "Material": "material",
    "Size": "size",
    "Width": "width",
    "Height": "height",
    "Length": "length",
    "Depth": "depth",
    "Area": "area",
    "Volume": "volume",
    "Room Id": "room_id",
    "Room Number": "room_number",
    "Room Name": "room_name",
    "Room Level": "room_level",
    "Room Area (SF)": "room_area_sf",
    "Room Volume (CF)": "room_volume_cf",
    "Room Location X (ft)": "room_location_x_ft",
    "Room Location Y (ft)": "room_location_y_ft",
    "Room Location Z (ft)": "room_location_z_ft",
    "Location Type": "location_type",
    "Bounding Box Center X (ft)": "center_x_ft",
    "Bounding Box Center Y (ft)": "center_y_ft",
    "Bounding Box Center Z (ft)": "center_z_ft",
    "Position X (ft)": "position_x_ft",
    "Position Y (ft)": "position_y_ft",
    "Position Z (ft)": "position_z_ft",
    "Start X (ft)": "start_x_ft",
    "Start Y (ft)": "start_y_ft",
    "Start Z (ft)": "start_z_ft",
    "End X (ft)": "end_x_ft",
    "End Y (ft)": "end_y_ft",
    "End Z (ft)": "end_z_ft",
    "Rotation (deg)": "rotation_deg",
    "Base Level": "base_level",
    "Top Level": "top_level",
    "source_schedule": "source_schedule",
    "takt_id": "takt_id",
}


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def source_model_name(value: object) -> str:
    text = clean_text(value)
    return Path(text).name if text else ""


def discipline_from_source(source_model: str, category: str) -> str:
    source = source_model.casefold()
    category_text = category.casefold()
    if "structural" in source or category_text.startswith("structural"):
        return "Structural"
    if "mep" in source or category_text in {
        "air terminals",
        "ducts",
        "duct fittings",
        "duct accessories",
        "mechanical equipment",
        "pipes",
        "pipe fittings",
        "plumbing fixtures",
        "sprinklers",
        "electrical equipment",
        "electrical fixtures",
        "lighting fixtures",
        "cable trays",
    }:
        return "MEP"
    if "architecture" in source:
        return "Architecture"
    return "General"


def first_nonempty(*values: object) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def semantic_name(row: pd.Series) -> str:
    pieces = [
        clean_text(row.get("category")),
        clean_text(row.get("family")),
        clean_text(row.get("type")),
    ]
    return " | ".join(dict.fromkeys(piece for piece in pieces if piece))


def build_llm_context() -> pd.DataFrame:
    frame = pd.read_csv(INPUT_PATH, dtype=str).fillna("")
    frame = frame.rename(columns=RENAME_COLUMNS)

    for column in RENAME_COLUMNS.values():
        if column not in frame.columns:
            frame[column] = ""

    frame["source_model"] = frame["source_schedule"].apply(source_model_name)
    frame["discipline"] = frame.apply(
        lambda row: discipline_from_source(row["source_model"], row["category"]),
        axis=1,
    )
    frame["semantic_name"] = frame.apply(semantic_name, axis=1)
    frame["level"] = frame.apply(
        lambda row: first_nonempty(row.get("level"), row.get("base_level"), row.get("top_level")),
        axis=1,
    )
    frame["center_x_ft"] = frame.apply(
        lambda row: first_nonempty(row.get("center_x_ft"), row.get("position_x_ft")),
        axis=1,
    )
    frame["center_y_ft"] = frame.apply(
        lambda row: first_nonempty(row.get("center_y_ft"), row.get("position_y_ft")),
        axis=1,
    )
    frame["center_z_ft"] = frame.apply(
        lambda row: first_nonempty(row.get("center_z_ft"), row.get("position_z_ft")),
        axis=1,
    )

    compact = frame.loc[:, KEEP_COLUMNS].copy()
    compact = compact.apply(lambda column: column.map(clean_text))
    compact = compact.sort_values(
        ["discipline", "level", "category", "family", "type", "element_id"],
        kind="stable",
    ).reset_index(drop=True)
    return compact


if __name__ == "__main__":
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    llm_context = build_llm_context()
    llm_context.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Rows: {len(llm_context)}")
    print(f"Columns: {len(llm_context.columns)}")
