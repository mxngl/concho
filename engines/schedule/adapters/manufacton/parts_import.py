from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
INPUT_TEMPLATE_PATH = BASE_DIR / "inputs" / "Parts Import.xlsx"
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUT_XLSX_PATH = OUTPUTS_DIR / "Parts_Import.xlsx"
OUTPUT_CSV_PATH = OUTPUTS_DIR / "Parts_Import.csv"
OUTPUT_SUMMARY_CSV_PATH = OUTPUTS_DIR / "Parts_Summary.csv"
CENTRAL_BIM_PATH = BASE_DIR.parent.parent.parent / "outputs" / "takt_zones" / "central_bim_model_with_takt.csv"
MICRO_SCHEDULE_PATH = BASE_DIR.parent / "Micro_Schedule_Generator" / "outputs" / "Micro_Schedule.csv"
ASSEMBLY_PUSH_MAP_PATH = OUTPUTS_DIR / "Revit_Assembly_Id_Map.csv"

OUTPUT_COLUMNS = [
    "ID",
    "NAME",
    "CATALOG ID",
    "DESCRIPTION",
    "CATEGORY",
    "SUB CATEGORY",
    "MEASURE UNIT",
    "Vendor",
    "Default Vendor",
    "Pref Vendor",
    "Vendor SKU/Part #",
    "Vendor Description",
    "Vendor Item Cost",
    "Vendor Lead Time",
]

ASSEMBLIES = [
    {
        "assembly_code": "SL1-3R",
        "assembly_name": "South-L1-3 rooms part",
    },
    {
        "assembly_code": "SL1-2R",
        "assembly_name": "South-L1-2 rooms part",
    },
    {
        "assembly_code": "SL0W-LNEG1C",
        "assembly_name": "South-L0-Workshop part & South-L-1-Classrooms part",
    },
]

PART_DEFINITIONS = [
    {
        "part_code": "WALL",
        "name_suffix": "Generic 8 Exterior",
        "description": 'Generic - 8" - EXTERIOR wall part',
        "category": "Parts",
        "sub_category": "Prefab Envelope",
        "measure_unit": "EACH",
    },
    {
        "part_code": "MULLION-L",
        "name_suffix": "Rectangular Mullion Lengthwise",
        "description": 'Rectangular Mullion 2.5" x 5" rectangular - lengthwise part',
        "category": "Parts",
        "sub_category": "Prefab Envelope",
        "measure_unit": "EACH",
    },
    {
        "part_code": "MULLION-B",
        "name_suffix": "Rectangular Mullion Breadthwise",
        "description": 'Rectangular Mullion 2.5" x 5" rectangular - breadthwise part',
        "category": "Parts",
        "sub_category": "Prefab Envelope",
        "measure_unit": "EACH",
    },
    {
        "part_code": "GLAZED-PANEL",
        "name_suffix": "Curtain Panel Glazed",
        "description": "Curtain Panels / System Panel / Glazed part",
        "category": "Parts",
        "sub_category": "Prefab Envelope",
        "measure_unit": "EACH",
    },
]

CONCRETE_TRUCK_PART = {
    "part_code": "CONC_400CF_TRUCK",
    "name_suffix": "Concrete Truck Load - 400 CF",
    "description": "Concrete truck delivery load, 400 cubic feet",
    "category": "Parts",
    "sub_category": "Concrete",
    "measure_unit": "EACH",
}


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def slugify_token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.upper())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "UNKNOWN"


def level_token(value: object) -> str:
    text = clean_text(value) or "UNASSIGNED"
    text = text.replace("-", " NEG ")
    return slugify_token(text)


def catalog_id(prefix: str, value: str) -> str:
    raw = f"{prefix}-{slugify_token(value)}"
    if 4 <= len(raw) <= 32:
        return raw

    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8].upper()
    base = slugify_token(value)[: 32 - len(prefix) - len(digest) - 2].strip("_")
    return f"{prefix}-{base}-{digest}"


def parse_snapshot_field(value: object, field_name: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    for token in text.split("|"):
        token = token.strip()
        prefix = f"{field_name}="
        if token.startswith(prefix):
            return token[len(prefix):].strip()
    return ""


def load_template_columns() -> list[str]:
    template = pd.read_excel(INPUT_TEMPLATE_PATH)
    return [str(column).strip() for column in template.columns]


def load_unique_structural_column_parts() -> list[dict[str, str]]:
    if not CENTRAL_BIM_PATH.exists():
        return []

    bim_df = pd.read_csv(CENTRAL_BIM_PATH).fillna("")
    columns = bim_df[bim_df["Category"].astype(str).str.strip().eq("Structural Columns")].copy()
    if columns.empty:
        return []

    columns["resolved_height"] = columns.apply(
        lambda row: clean_text(row.get("Height")) or parse_snapshot_field(row.get("Parameter Snapshot", ""), "System Length"),
        axis=1,
    )
    columns["resolved_material"] = columns.apply(
        lambda row: clean_text(row.get("Material")) or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Structural Material"),
        axis=1,
    )

    unique_pairs = (
        columns.loc[:, ["resolved_height", "resolved_material"]]
        .drop_duplicates()
        .sort_values(["resolved_height", "resolved_material"])
    )

    parts: list[dict[str, str]] = []
    for _, row in unique_pairs.iterrows():
        height = clean_text(row["resolved_height"]) or "Unknown Height"
        material = clean_text(row["resolved_material"]) or "Unknown Material"
        token = f"{slugify_token(height)}_{slugify_token(material)}"
        parts.append(
            {
                "part_code": f"STRUCT_COL_{token}",
                "name_suffix": f"Structural Column {height} | {material}",
                "description": f"Structural column part based on height {height} and material {material}",
                "category": "Parts",
                "sub_category": "Structural Columns",
                "measure_unit": "EACH",
            }
        )

    return parts


def load_unique_structural_framing_parts() -> list[dict[str, str]]:
    if not CENTRAL_BIM_PATH.exists():
        return []

    bim_df = pd.read_csv(CENTRAL_BIM_PATH).fillna("")
    framing = bim_df[bim_df["Category"].astype(str).str.strip().eq("Structural Framing")].copy()
    if framing.empty:
        return []

    framing["resolved_length"] = framing.apply(
        lambda row: parse_snapshot_field(row.get("Parameter Snapshot", ""), "System Length")
        or clean_text(row.get("Length"))
        or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Cut Length"),
        axis=1,
    )
    framing["resolved_material"] = framing.apply(
        lambda row: clean_text(row.get("Material")) or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Structural Material"),
        axis=1,
    )

    unique_pairs = (
        framing.loc[:, ["resolved_length", "resolved_material"]]
        .drop_duplicates()
        .sort_values(["resolved_length", "resolved_material"])
    )

    parts: list[dict[str, str]] = []
    for _, row in unique_pairs.iterrows():
        length = clean_text(row["resolved_length"]) or "Unknown Length"
        material = clean_text(row["resolved_material"]) or "Unknown Material"
        token = f"{slugify_token(length)}_{slugify_token(material)}"
        parts.append(
            {
                "part_code": f"STRUCT_FRAME_{token}",
                "name_suffix": f"Structural Framing {length} | {material}",
                "description": f"Structural framing part based on length {length} and material {material}",
                "category": "Parts",
                "sub_category": "Structural Framing",
                "measure_unit": "EACH",
            }
        )

    return parts


def load_unique_structural_floor_parts() -> list[dict[str, str]]:
    if not CENTRAL_BIM_PATH.exists():
        return []

    bim_df = pd.read_csv(CENTRAL_BIM_PATH).fillna("")
    floors = get_structural_floor_rows(bim_df)
    if floors.empty:
        return []

    floors["resolved_level"] = floors["Level"].apply(lambda value: clean_text(value) or "Unassigned")
    floors["resolved_type"] = floors.apply(resolve_original_type, axis=1)
    floors["resolved_thickness"] = floors.apply(
        lambda row: clean_text(row.get("Depth"))
        or clean_text(row.get("Height"))
        or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Thickness")
        or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Default Thickness")
        or "Unknown Thickness",
        axis=1,
    )
    floors["resolved_material"] = floors.apply(
        lambda row: clean_text(row.get("Material")) or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Structural Material"),
        axis=1,
    )

    unique_groups = (
        floors.loc[:, ["resolved_level", "resolved_type", "resolved_thickness", "resolved_material"]]
        .drop_duplicates()
        .sort_values(["resolved_level", "resolved_type", "resolved_thickness", "resolved_material"])
    )

    parts: list[dict[str, str]] = []
    for _, row in unique_groups.iterrows():
        level = clean_text(row["resolved_level"]) or "Unassigned"
        type_name = clean_text(row["resolved_type"]) or "Unknown Type"
        thickness = clean_text(row["resolved_thickness"]) or "Unknown Thickness"
        material = clean_text(row["resolved_material"]) or "Unknown Material"
        token = "_".join(
            [
                slugify_token(level),
                slugify_token(type_name),
                slugify_token(thickness),
                slugify_token(material),
            ]
        )
        parts.append(
            {
                "part_code": f"STRUCT_FLOOR_{token}",
                "name_suffix": f"Structural Floor {level} | {type_name} | {thickness} | {material}",
                "description": (
                    f"Structural floor part for {level} based on type {type_name}, "
                    f"thickness {thickness}, and material {material}"
                ),
                "category": "Parts",
                "sub_category": "Structural Floors",
                "measure_unit": "SF",
            }
        )

    return parts


def load_unique_interior_wall_parts() -> list[dict[str, str]]:
    if not MICRO_SCHEDULE_PATH.exists():
        return []

    micro = pd.read_csv(MICRO_SCHEDULE_PATH, dtype=str).fillna("")
    interior = micro[micro["task_name"].astype(str).str.strip().eq("Interior Walls")].copy()
    if interior.empty:
        return []

    levels = sorted({clean_text(level) or "Unassigned" for level in interior["level"]})
    return [
        {
            "part_code": f"INTW_{level_token(level)}_WALL",
            "name_suffix": f"Interior Wall {level}",
            "description": f"Interior wall part for {level}",
            "category": "Parts",
            "sub_category": "Prefab Interior",
            "measure_unit": "EACH",
        }
        for level in levels
    ]


def load_unique_exterior_wall_parts() -> list[dict[str, str]]:
    if not MICRO_SCHEDULE_PATH.exists():
        return []

    micro = pd.read_csv(MICRO_SCHEDULE_PATH, dtype=str).fillna("")
    exterior = micro[micro["task_name"].astype(str).str.strip().eq("Exterior Wall Install")].copy()
    if exterior.empty:
        return []

    part_defs = [
        ("WALL", "Wall Panel", "Exterior wall panel part"),
        ("MULLION-L", "Mullion Lengthwise", "Exterior wall lengthwise mullion part"),
        ("MULLION-B", "Mullion Breadthwise", "Exterior wall breadthwise mullion part"),
        ("GLAZED-PANEL", "Glazed Panel", "Exterior wall glazed panel part"),
    ]
    parts: list[dict[str, str]] = []
    for level in sorted({clean_text(value) or "Unassigned" for value in exterior["level"]}):
        token = level_token(level)
        for part_code, name_suffix, description in part_defs:
            parts.append(
                {
                    "part_code": f"EXTW_{token}_{part_code}",
                    "name_suffix": f"Exterior Wall {level} - {name_suffix}",
                    "description": f"{description} for {level}",
                    "category": "Parts",
                    "sub_category": "Prefab Envelope",
                    "measure_unit": "EACH",
                }
            )
    return parts


def load_unique_mesh_parts() -> list[dict[str, str]]:
    if not MICRO_SCHEDULE_PATH.exists():
        return []

    micro = pd.read_csv(MICRO_SCHEDULE_PATH, dtype=str).fillna("")
    mesh = micro[micro["task_name"].astype(str).str.strip().eq("Mesh Install")].copy()
    if mesh.empty:
        return []

    return [
        {
            "part_code": f"MESH_{level_token(level)}_PANEL",
            "name_suffix": f"Mesh Panel {level}",
            "description": f"Mesh panel part for {level}",
            "category": "Parts",
            "sub_category": "Prefab Envelope",
            "measure_unit": "EACH",
        }
        for level in sorted({clean_text(value) or "Unassigned" for value in mesh["level"]})
    ]


def load_concrete_truck_parts() -> list[dict[str, str]]:
    return [CONCRETE_TRUCK_PART]


def load_unique_mep_parts() -> list[dict[str, str]]:
    if not MICRO_SCHEDULE_PATH.exists() or not CENTRAL_BIM_PATH.exists():
        return []

    micro = pd.read_csv(MICRO_SCHEDULE_PATH, dtype=str).fillna("")
    mep = micro[micro["task_name"].astype(str).str.strip().eq("MEP Rough-In")].copy()
    if mep.empty:
        return []

    bim_df = load_central_bim()
    if bim_df.empty:
        return []
    bim_lookup = bim_df.set_index(bim_df["ElementId"].apply(clean_text), drop=False)

    part_rows: dict[str, dict[str, str]] = {}
    for element_id in sorted({clean_text(value) for value in mep["element_id"] if clean_text(value)}):
        if element_id not in bim_lookup.index:
            continue
        row = bim_lookup.loc[element_id]
        category = clean_text(row.get("Category")) or "MEP"
        family = clean_text(row.get("Family")) or "Unspecified Family"
        type_name = clean_text(row.get("Type")) or clean_text(row.get("Size")) or "Unspecified Type"
        size = clean_text(row.get("Size"))
        token = "_".join([slugify_token(category), slugify_token(family), slugify_token(type_name), slugify_token(size)])
        part_code = f"MEP_{token}"
        if part_code in part_rows:
            continue
        descriptor = " | ".join(part for part in [category, family, type_name, size] if part)
        part_rows[part_code] = {
            "part_code": part_code,
            "name_suffix": f"MEP {descriptor}",
            "description": f"MEP rough-in part for {descriptor}",
            "category": "Parts",
            "sub_category": "MEP Rough-In",
            "measure_unit": "EACH",
        }

    return [part_rows[key] for key in sorted(part_rows)]


def load_central_bim() -> pd.DataFrame:
    if not CENTRAL_BIM_PATH.exists():
        return pd.DataFrame()
    bim_df = pd.read_csv(CENTRAL_BIM_PATH, dtype=str).fillna("")
    bim_df.columns = [str(column).strip() for column in bim_df.columns]
    return bim_df


def resolve_original_category(row: pd.Series) -> str:
    return clean_text(row.get("Original Category")) or clean_text(row.get("Category"))


def resolve_original_family(row: pd.Series) -> str:
    return clean_text(row.get("Original Family")) or clean_text(row.get("Family"))


def resolve_original_type(row: pd.Series) -> str:
    return clean_text(row.get("Original Type")) or clean_text(row.get("Type")) or "Unknown Type"


def get_structural_floor_rows(bim_df: pd.DataFrame) -> pd.DataFrame:
    if bim_df.empty:
        return pd.DataFrame()

    category = bim_df["Category"].astype(str).str.strip()
    original_category = (
        bim_df["Original Category"].astype(str).str.strip()
        if "Original Category" in bim_df.columns
        else pd.Series([""] * len(bim_df), index=bim_df.index)
    )

    floors = bim_df[
        (category.eq("Floors") | ((category.eq("Parts")) & original_category.eq("Floors")))
        & bim_df["Material"].astype(str).str.contains("Structural Bamboo", case=False, na=False)
    ].copy()
    floor_parts = floors[floors["Category"].astype(str).str.strip().eq("Parts")].copy()
    return floor_parts if not floor_parts.empty else floors


def structural_column_part_id(row: pd.Series) -> str:
    height = (
        clean_text(row.get("Height"))
        or parse_snapshot_field(row.get("Parameter Snapshot", ""), "System Length")
        or "Unknown Height"
    )
    material = (
        clean_text(row.get("Material"))
        or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Structural Material")
        or "Unknown Material"
    )
    return f"STRUCT_COL_{slugify_token(height)}_{slugify_token(material)}"


def structural_framing_part_id(row: pd.Series) -> str:
    length = (
        parse_snapshot_field(row.get("Parameter Snapshot", ""), "System Length")
        or clean_text(row.get("Length"))
        or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Cut Length")
        or "Unknown Length"
    )
    material = (
        clean_text(row.get("Material"))
        or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Structural Material")
        or "Unknown Material"
    )
    return f"STRUCT_FRAME_{slugify_token(length)}_{slugify_token(material)}"


def structural_floor_part_id(row: pd.Series) -> str:
    level = clean_text(row.get("Level")) or "Unassigned"
    type_name = resolve_original_type(row)
    thickness = (
        clean_text(row.get("Depth"))
        or clean_text(row.get("Height"))
        or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Thickness")
        or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Default Thickness")
        or "Unknown Thickness"
    )
    material = (
        clean_text(row.get("Material"))
        or parse_snapshot_field(row.get("Parameter Snapshot", ""), "Structural Material")
        or "Unknown Material"
    )
    token = "_".join(
        [
            slugify_token(level),
            slugify_token(type_name),
            slugify_token(thickness),
            slugify_token(material),
        ]
    )
    return f"STRUCT_FLOOR_{token}"


def interior_wall_part_id(row: pd.Series) -> str:
    return f"INTW_{level_token(row.get('level') or row.get('Level'))}_WALL"


def exterior_wall_part_id(row: pd.Series) -> str:
    level = level_token(row.get("level") or row.get("Level"))
    category = clean_text(row.get("category") or row.get("Category"))
    if category == "Walls":
        return f"EXTW_{level}_WALL"
    if category == "Curtain Panels":
        return f"EXTW_{level}_GLAZED-PANEL"
    if category == "Curtain Wall Mullions":
        return f"EXTW_{level}_{mullion_part_code(row)}"
    return ""


def mesh_part_id(row: pd.Series) -> str:
    return f"MESH_{level_token(row.get('level') or row.get('Level'))}_PANEL"


def mep_part_id(row: pd.Series) -> str:
    category = clean_text(row.get("Category")) or "MEP"
    family = clean_text(row.get("Family")) or "Unspecified Family"
    type_name = clean_text(row.get("Type")) or clean_text(row.get("Size")) or "Unspecified Type"
    size = clean_text(row.get("Size"))
    token = "_".join([slugify_token(category), slugify_token(family), slugify_token(type_name), slugify_token(size)])
    return f"MEP_{token}"


def parse_measure(value: object) -> float:
    text = clean_text(value).replace(",", "")
    number = ""
    decimal_seen = False
    for char in text:
        if char.isdigit():
            number += char
        elif char == "." and not decimal_seen:
            number += char
            decimal_seen = True
        elif number:
            break
    return float(number) if number else 0.0


def to_float(value: object) -> float:
    try:
        return float(clean_text(value))
    except ValueError:
        return 0.0


def mullion_part_code(row: pd.Series) -> str:
    x_span = abs(to_float(row.get("Bounding Box Max X (ft)")) - to_float(row.get("Bounding Box Min X (ft)")))
    y_span = abs(to_float(row.get("Bounding Box Max Y (ft)")) - to_float(row.get("Bounding Box Min Y (ft)")))
    z_span = abs(to_float(row.get("Bounding Box Max Z (ft)")) - to_float(row.get("Bounding Box Min Z (ft)")))
    horizontal_span = max(x_span, y_span)
    return "MULLION-L" if z_span >= horizontal_span else "MULLION-B"


def envelope_part_id(assembly_id: str, row: pd.Series) -> str:
    part_prefix = assembly_id.removesuffix("-WALL")
    category = clean_text(row.get("Category"))
    if category == "Walls":
        return f"{part_prefix}-WALL"
    if category == "Curtain Panels":
        return f"{part_prefix}-GLAZED-PANEL"
    if category == "Curtain Wall Mullions":
        return f"{part_prefix}-{mullion_part_code(row)}"
    return ""


def build_part_element_rows() -> pd.DataFrame:
    bim_df = load_central_bim()
    element_rows: list[dict[str, str]] = []

    if not bim_df.empty:
        bim_df["ElementId"] = bim_df["ElementId"].apply(clean_text)

        structural_columns = bim_df[bim_df["Category"].astype(str).str.strip().eq("Structural Columns")].copy()
        for _, row in structural_columns.iterrows():
            element_rows.append(
                {
                    "part_id": structural_column_part_id(row),
                    "element_id": clean_text(row["ElementId"]),
                    "quantity_area_sf": parse_measure(row.get("Area")),
                    "quantity_volume_cf": parse_measure(row.get("Volume")),
                }
            )

        structural_framing = bim_df[bim_df["Category"].astype(str).str.strip().eq("Structural Framing")].copy()
        for _, row in structural_framing.iterrows():
            element_rows.append(
                {
                    "part_id": structural_framing_part_id(row),
                    "element_id": clean_text(row["ElementId"]),
                    "quantity_area_sf": parse_measure(row.get("Area")),
                    "quantity_volume_cf": parse_measure(row.get("Volume")),
                }
            )

        structural_floors = get_structural_floor_rows(bim_df)
        for _, row in structural_floors.iterrows():
            element_rows.append(
                {
                    "part_id": structural_floor_part_id(row),
                    "element_id": clean_text(row["ElementId"]),
                    "quantity_area_sf": parse_measure(row.get("Area")),
                    "quantity_volume_cf": parse_measure(row.get("Volume")),
                }
            )

        if MICRO_SCHEDULE_PATH.exists():
            micro = pd.read_csv(MICRO_SCHEDULE_PATH, dtype=str).fillna("")
            element_lookup = bim_df.set_index("ElementId", drop=False)

            interior = micro[micro["task_name"].astype(str).str.strip().eq("Interior Walls")].copy()
            for _, micro_row in interior.drop_duplicates(subset=["element_id"]).iterrows():
                element_id = clean_text(micro_row["element_id"])
                if not element_id or element_id not in element_lookup.index:
                    continue
                element = element_lookup.loc[element_id]
                element_rows.append(
                    {
                        "part_id": interior_wall_part_id(micro_row),
                        "element_id": element_id,
                        "quantity_area_sf": parse_measure(element.get("Area")),
                        "quantity_volume_cf": parse_measure(element.get("Volume")),
                    }
                )

            exterior = micro[micro["task_name"].astype(str).str.strip().eq("Exterior Wall Install")].copy()
            for _, micro_row in exterior.drop_duplicates(subset=["element_id"]).iterrows():
                element_id = clean_text(micro_row["element_id"])
                if not element_id or element_id not in element_lookup.index:
                    continue
                element = element_lookup.loc[element_id]
                part_id = exterior_wall_part_id(element)
                if not part_id:
                    continue
                element_rows.append(
                    {
                        "part_id": part_id,
                        "element_id": element_id,
                        "quantity_area_sf": parse_measure(element.get("Area")),
                        "quantity_volume_cf": parse_measure(element.get("Volume")),
                    }
                )

            mesh = micro[micro["task_name"].astype(str).str.strip().eq("Mesh Install")].copy()
            for _, micro_row in mesh.drop_duplicates(subset=["element_id"]).iterrows():
                element_id = clean_text(micro_row["element_id"])
                if not element_id or element_id not in element_lookup.index:
                    continue
                element = element_lookup.loc[element_id]
                element_rows.append(
                    {
                        "part_id": mesh_part_id(micro_row),
                        "element_id": element_id,
                        "quantity_area_sf": parse_measure(element.get("Area")),
                        "quantity_volume_cf": parse_measure(element.get("Volume")),
                    }
                )

            mep = micro[micro["task_name"].astype(str).str.strip().eq("MEP Rough-In")].copy()
            for _, micro_row in mep.drop_duplicates(subset=["element_id"]).iterrows():
                element_id = clean_text(micro_row["element_id"])
                if not element_id or element_id not in element_lookup.index:
                    continue
                element = element_lookup.loc[element_id]
                element_rows.append(
                    {
                        "part_id": mep_part_id(element),
                        "element_id": element_id,
                        "quantity_area_sf": parse_measure(element.get("Area")),
                        "quantity_volume_cf": parse_measure(element.get("Volume")),
                    }
                )

        if ASSEMBLY_PUSH_MAP_PATH.exists():
            assembly_map = pd.read_csv(ASSEMBLY_PUSH_MAP_PATH, dtype=str).fillna("")
            if {"element_id", "assembly_id"}.issubset(assembly_map.columns):
                element_lookup = bim_df.set_index("ElementId", drop=False)
                for _, map_row in assembly_map.iterrows():
                    element_id = clean_text(map_row["element_id"])
                    assembly_id = clean_text(map_row["assembly_id"])
                    if not element_id or not assembly_id or element_id not in element_lookup.index:
                        continue
                    part_id = envelope_part_id(assembly_id, element_lookup.loc[element_id])
                    if part_id:
                        element = element_lookup.loc[element_id]
                        element_rows.append(
                            {
                                "part_id": part_id,
                                "element_id": element_id,
                                "quantity_area_sf": parse_measure(element.get("Area")),
                                "quantity_volume_cf": parse_measure(element.get("Volume")),
                            }
                        )

    if not element_rows:
        return pd.DataFrame(columns=["part_id", "element_id", "quantity_area_sf", "quantity_volume_cf"])

    return (
        pd.DataFrame(element_rows)
        .drop_duplicates(subset=["part_id", "element_id"])
        .sort_values(["part_id", "element_id"])
        .reset_index(drop=True)
    )


def build_part_element_summary(parts_import: pd.DataFrame) -> pd.DataFrame:
    summary_rows = parts_import.loc[
        :,
        ["ID", "NAME", "CATALOG ID", "CATEGORY", "SUB CATEGORY", "MEASURE UNIT"],
    ].rename(
        columns={
            "ID": "part_id",
            "NAME": "part_name",
            "CATALOG ID": "catalog_id",
            "CATEGORY": "category",
            "SUB CATEGORY": "sub_category",
            "MEASURE UNIT": "measure_unit",
        }
    )

    element_df = build_part_element_rows()
    element_summary = (
        element_df.groupby("part_id", as_index=False)
        .agg(
            element_count=("element_id", "nunique"),
            total_area_sf=("quantity_area_sf", "sum"),
            total_volume_cf=("quantity_volume_cf", "sum"),
            element_ids=("element_id", lambda values: "|".join(dict.fromkeys(values))),
        )
        if not element_df.empty
        else pd.DataFrame(columns=["part_id", "element_count", "total_area_sf", "total_volume_cf", "element_ids"])
    )

    output = summary_rows.merge(element_summary, on="part_id", how="left")
    output["element_count"] = output["element_count"].fillna(0).astype(int)
    output["total_area_sf"] = output["total_area_sf"].fillna(0.0).round(2)
    output["total_volume_cf"] = output["total_volume_cf"].fillna(0.0).round(2)
    output["takeoff_quantity"] = output.apply(
        lambda row: row["total_area_sf"] if clean_text(row["sub_category"]) == "Structural Floors" else row["element_count"],
        axis=1,
    )
    output["takeoff_unit"] = output.apply(
        lambda row: "SF" if clean_text(row["sub_category"]) == "Structural Floors" else clean_text(row["measure_unit"]),
        axis=1,
    )
    output["element_ids"] = output["element_ids"].fillna("")
    return output[
        [
            "part_id",
            "part_name",
            "catalog_id",
            "category",
            "sub_category",
            "measure_unit",
            "element_count",
            "takeoff_quantity",
            "takeoff_unit",
            "total_area_sf",
            "total_volume_cf",
            "element_ids",
        ]
    ]
def build_parts_import() -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for assembly in ASSEMBLIES:
        for part in PART_DEFINITIONS:
            item_id = f"{assembly['assembly_code']}-{part['part_code']}"
            rows.append(
                {
                    "ID": item_id,
                    "NAME": f"{assembly['assembly_name']} - {part['name_suffix']}",
                    "CATALOG ID": catalog_id("PART", item_id),
                    "DESCRIPTION": f"{assembly['assembly_name']} | {part['description']}",
                    "CATEGORY": part["category"],
                    "SUB CATEGORY": part["sub_category"],
                    "MEASURE UNIT": part["measure_unit"],
                    "Vendor": "",
                    "Default Vendor": "",
                    "Pref Vendor": "",
                    "Vendor SKU/Part #": "",
                    "Vendor Description": "",
                    "Vendor Item Cost": "",
                    "Vendor Lead Time": "",
                }
            )

    for part in load_unique_structural_column_parts():
        item_id = part["part_code"]
        rows.append(
            {
                "ID": item_id,
                "NAME": part["name_suffix"],
                "CATALOG ID": catalog_id("PART", item_id),
                "DESCRIPTION": part["description"],
                "CATEGORY": part["category"],
                "SUB CATEGORY": part["sub_category"],
                "MEASURE UNIT": part["measure_unit"],
                "Vendor": "",
                "Default Vendor": "",
                "Pref Vendor": "",
                "Vendor SKU/Part #": "",
                "Vendor Description": "",
                "Vendor Item Cost": "",
                "Vendor Lead Time": "",
            }
        )

    for part in load_unique_structural_framing_parts():
        item_id = part["part_code"]
        rows.append(
            {
                "ID": item_id,
                "NAME": part["name_suffix"],
                "CATALOG ID": catalog_id("PART", item_id),
                "DESCRIPTION": part["description"],
                "CATEGORY": part["category"],
                "SUB CATEGORY": part["sub_category"],
                "MEASURE UNIT": part["measure_unit"],
                "Vendor": "",
                "Default Vendor": "",
                "Pref Vendor": "",
                "Vendor SKU/Part #": "",
                "Vendor Description": "",
                "Vendor Item Cost": "",
                "Vendor Lead Time": "",
            }
        )

    for part in load_unique_structural_floor_parts():
        item_id = part["part_code"]
        rows.append(
            {
                "ID": item_id,
                "NAME": part["name_suffix"],
                "CATALOG ID": catalog_id("PART", item_id),
                "DESCRIPTION": part["description"],
                "CATEGORY": part["category"],
                "SUB CATEGORY": part["sub_category"],
                "MEASURE UNIT": part["measure_unit"],
                "Vendor": "",
                "Default Vendor": "",
                "Pref Vendor": "",
                "Vendor SKU/Part #": "",
                "Vendor Description": "",
                "Vendor Item Cost": "",
                "Vendor Lead Time": "",
            }
        )

    for part in [
        *load_unique_interior_wall_parts(),
        *load_unique_exterior_wall_parts(),
        *load_unique_mesh_parts(),
        *load_concrete_truck_parts(),
        *load_unique_mep_parts(),
    ]:
        item_id = part["part_code"]
        rows.append(
            {
                "ID": item_id,
                "NAME": part["name_suffix"],
                "CATALOG ID": catalog_id("PART", item_id),
                "DESCRIPTION": part["description"],
                "CATEGORY": part["category"],
                "SUB CATEGORY": part["sub_category"],
                "MEASURE UNIT": part["measure_unit"],
                "Vendor": "",
                "Default Vendor": "",
                "Pref Vendor": "",
                "Vendor SKU/Part #": "",
                "Vendor Description": "",
                "Vendor Item Cost": "",
                "Vendor Lead Time": "",
            }
        )

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def validate_template() -> None:
    template_columns = load_template_columns()
    if template_columns != OUTPUT_COLUMNS:
        raise ValueError(
            "Template columns do not match the expected Parts Import structure.\n"
            f"Expected: {OUTPUT_COLUMNS}\n"
            f"Found: {template_columns}"
        )


def write_parts_import() -> tuple[Path, Path, Path]:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    validate_template()
    output = build_parts_import()
    with pd.ExcelWriter(OUTPUT_XLSX_PATH, engine="openpyxl") as writer:
        output.to_excel(writer, sheet_name="Sheet1", index=False)
    output.to_csv(OUTPUT_CSV_PATH, index=False)
    summary = build_part_element_summary(output)
    summary.to_csv(OUTPUT_SUMMARY_CSV_PATH, index=False)
    return OUTPUT_XLSX_PATH, OUTPUT_CSV_PATH, OUTPUT_SUMMARY_CSV_PATH


if __name__ == "__main__":
    xlsx_path, csv_path, summary_path = write_parts_import()
    print(f"Wrote {xlsx_path.name}")
    print(f"Wrote {csv_path.name}")
    print(f"Wrote {summary_path.name}")
    print(f"Rows: {len(build_parts_import())}")
