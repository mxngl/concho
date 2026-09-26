from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
INPUT_TEMPLATE_PATH = BASE_DIR / "inputs" / "Assembly.Import.xlsx"
OUTPUTS_DIR = BASE_DIR / "outputs"
PARTS_IMPORT_PATH = OUTPUTS_DIR / "Parts_Import.xlsx"
PARTS_SUMMARY_PATH = OUTPUTS_DIR / "Parts_Summary.csv"
OUTPUT_XLSX_PATH = OUTPUTS_DIR / "Assembly_Import.xlsx"
MICRO_SCHEDULE_PATH = BASE_DIR.parent / "Micro_Schedule_Generator" / "outputs" / "Micro_Schedule.csv"
CENTRAL_BIM_PATH = BASE_DIR.parent.parent.parent / "outputs" / "takt_zones" / "central_bim_model_with_takt.csv"
BUILD_CODE_MAP_PATH = BASE_DIR.parent / "Fuzor_Mapper" / "outputs" / "Revit_4D_Build_Code_Map.csv"

OUTPUT_COLUMNS = [
    "ID",
    "Name",
    "Catalog Id",
    "Description",
    "Category",
    "Sub Category",
    "Part CatId",
    "Part Quantity",
    "Part Notes",
    "Assembly CatId",
    "Assembly Quantity",
    "Assembly Notes",
    "Attribute Name",
    "Attribute Value",
]

ASSEMBLIES = [
    {
        "assembly_code": "SL1-3R-WALL",
        "assembly_name": "South-L1-3 rooms wall",
        "description": "South-L1-3 rooms wall prefab assembly",
        "part_prefix": "SL1-3R",
    },
    {
        "assembly_code": "SL1-2R-WALL",
        "assembly_name": "South-L1-2 rooms wall",
        "description": "South-L1-2 rooms wall prefab assembly",
        "part_prefix": "SL1-2R",
    },
    {
        "assembly_code": "SL0W-LNEG1C-WALL",
        "assembly_name": "South-L0-Workshop wall part & South-L-1-Classrooms wall",
        "description": "South-L0-Workshop wall part & South-L-1-Classrooms wall prefab assembly",
        "part_prefix": "SL0W-LNEG1C",
    },
]

PART_CODES = [
    "WALL",
    "MULLION-L",
    "MULLION-B",
    "GLAZED-PANEL",
]

CONCRETE_TRUCK_ASSEMBLY_ID = "CONC_400CF_TRUCK_ASSEMBLY"


def slugify_token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.upper())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "UNKNOWN"


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


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


def load_template_columns() -> list[str]:
    template = pd.read_excel(INPUT_TEMPLATE_PATH)
    return [str(column).strip() for column in template.columns]


def load_part_catalog_ids() -> dict[str, str]:
    parts = pd.read_excel(PARTS_IMPORT_PATH).fillna("")
    required_columns = {"ID", "CATALOG ID"}
    if not required_columns.issubset(parts.columns):
        raise ValueError(
            f"Parts import is missing required columns: {sorted(required_columns - set(parts.columns))}"
        )
    return {
        str(row["ID"]).strip(): str(row["CATALOG ID"]).strip()
        for _, row in parts.iterrows()
        if str(row["ID"]).strip()
    }


def load_central_bim() -> pd.DataFrame:
    if not CENTRAL_BIM_PATH.exists():
        return pd.DataFrame()
    frame = pd.read_csv(CENTRAL_BIM_PATH, dtype=str).fillna("")
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


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


def exterior_wall_part_id(row: pd.Series) -> str:
    level = level_token(row.get("Level"))
    category = clean_text(row.get("Category"))
    if category == "Walls":
        return f"EXTW_{level}_WALL"
    if category == "Curtain Panels":
        return f"EXTW_{level}_GLAZED-PANEL"
    if category == "Curtain Wall Mullions":
        return f"EXTW_{level}_{mullion_part_code(row)}"
    return ""


def mesh_part_id(level: object) -> str:
    return f"MESH_{level_token(level)}_PANEL"


def mep_part_id(row: pd.Series) -> str:
    category = clean_text(row.get("Category")) or "MEP"
    family = clean_text(row.get("Family")) or "Unspecified Family"
    type_name = clean_text(row.get("Type")) or clean_text(row.get("Size")) or "Unspecified Type"
    size = clean_text(row.get("Size"))
    token = "_".join([slugify_token(category), slugify_token(family), slugify_token(type_name), slugify_token(size)])
    return f"MEP_{token}"


def load_interior_wall_assemblies() -> list[dict[str, object]]:
    if not MICRO_SCHEDULE_PATH.exists():
        return []
    micro = pd.read_csv(MICRO_SCHEDULE_PATH, dtype=str).fillna("")
    interior = micro[micro["task_name"].astype(str).str.strip().eq("Interior Walls")].copy()
    if interior.empty:
        return []

    assemblies: list[dict[str, object]] = []
    for level in sorted({clean_text(value) or "Unassigned" for value in interior["level"]}):
        token = level_token(level)
        assemblies.append(
            {
                "assembly_id": f"INTW_{token}_ASSEMBLY",
                "name": f"Interior Walls {level}",
                "description": f"Interior wall assembly for {level}",
                "sub_category": "Prefab Interior",
                "parts": [(f"INTW_{token}_WALL", 1)],
            }
        )
    return assemblies


def load_exterior_wall_group_assemblies() -> list[dict[str, object]]:
    if not BUILD_CODE_MAP_PATH.exists() or not CENTRAL_BIM_PATH.exists():
        return []

    build_df = pd.read_csv(BUILD_CODE_MAP_PATH, dtype=str).fillna("")
    exterior = build_df[build_df["task_name"].astype(str).str.strip().eq("Exterior Wall Install")].copy()
    if exterior.empty:
        return []

    bim = load_central_bim()
    if bim.empty:
        return []
    element_lookup = bim.set_index(bim["ElementId"].apply(clean_text), drop=False)

    assemblies: list[dict[str, object]] = []
    for build_code, group in exterior.groupby("build_code", sort=False):
        part_counts: dict[str, int] = {}
        for element_id in group["element_id"].map(clean_text):
            if not element_id or element_id not in element_lookup.index:
                continue
            part_id = exterior_wall_part_id(element_lookup.loc[element_id])
            if part_id:
                part_counts[part_id] = part_counts.get(part_id, 0) + 1
        if not part_counts:
            continue
        build_token = slugify_token(str(build_code).split("|")[-1])
        level = clean_text(group["level"].iloc[0]) or "Unassigned"
        assembly_id = f"EXTW_{build_token}"
        assemblies.append(
            {
                "assembly_id": assembly_id,
                "name": f"Exterior Wall {level} {str(build_code).split('|')[-1].strip()}",
                "description": f"Exterior wall assembly for {build_code}",
                "sub_category": "Prefab Envelope",
                "parts": sorted(part_counts.items()),
            }
        )
    return assemblies


def load_mesh_assemblies() -> list[dict[str, object]]:
    if not MICRO_SCHEDULE_PATH.exists():
        return []

    micro = pd.read_csv(MICRO_SCHEDULE_PATH, dtype=str).fillna("")
    mesh = micro[micro["task_name"].astype(str).str.strip().eq("Mesh Install")].copy()
    if mesh.empty:
        return []

    assemblies: list[dict[str, object]] = []
    for level in sorted({clean_text(value) or "Unassigned" for value in mesh["level"]}):
        token = level_token(level)
        assemblies.append(
            {
                "assembly_id": f"MESH_{token}_ASSEMBLY",
                "name": f"Mesh Install {level}",
                "description": f"Mesh install assembly for {level}",
                "sub_category": "Prefab Envelope",
                "parts": [(mesh_part_id(level), 1)],
            }
        )
    return assemblies


def load_concrete_truck_assemblies() -> list[dict[str, object]]:
    return [
        {
            "assembly_id": CONCRETE_TRUCK_ASSEMBLY_ID,
            "name": "Concrete Truck Load - 400 CF",
            "description": "Concrete delivery assembly for one 400 cubic foot truck load",
            "sub_category": "Concrete",
            "parts": [("CONC_400CF_TRUCK", 1)],
        }
    ]


def load_mep_group_assemblies() -> list[dict[str, object]]:
    if not MICRO_SCHEDULE_PATH.exists() or not CENTRAL_BIM_PATH.exists():
        return []

    micro = pd.read_csv(MICRO_SCHEDULE_PATH, dtype=str).fillna("")
    mep = micro[micro["task_name"].astype(str).str.strip().eq("MEP Rough-In")].copy()
    if mep.empty:
        return []

    mep["element_start_ts"] = pd.to_datetime(mep["element_start"], format="mixed", errors="coerce")
    mep_unique = (
        mep.sort_values(["level", "element_start_ts", "order_in_task", "element_id"])
        .drop_duplicates(subset=["element_id"])
        .reset_index(drop=True)
    )

    bim = load_central_bim()
    if bim.empty:
        return []
    element_lookup = bim.set_index(bim["ElementId"].apply(clean_text), drop=False)

    assemblies: list[dict[str, object]] = []
    for level, level_df in mep_unique.groupby("level", sort=False):
        level_text = clean_text(level) or "Unassigned"
        token = level_token(level_text)
        level_df = level_df.reset_index(drop=True)
        for group_index, start in enumerate(range(0, len(level_df), 3), start=1):
            group = level_df.iloc[start : start + 3]
            part_counts: dict[str, int] = {}
            for element_id in group["element_id"].map(clean_text):
                if not element_id or element_id not in element_lookup.index:
                    continue
                part_id = mep_part_id(element_lookup.loc[element_id])
                part_counts[part_id] = part_counts.get(part_id, 0) + 1
            if not part_counts:
                continue
            assembly_id = f"MEP_{token}_G{group_index:03d}"
            assemblies.append(
                {
                    "assembly_id": assembly_id,
                    "name": f"MEP Rough-In {level_text} Group {group_index:03d}",
                    "description": f"MEP rough-in assembly for {level_text}, micro-schedule group {group_index:03d}",
                    "sub_category": "MEP Rough-In",
                    "parts": sorted(part_counts.items()),
                }
            )
    return assemblies


def load_structural_parts() -> pd.DataFrame:
    parts = pd.read_excel(PARTS_IMPORT_PATH, dtype=str).fillna("")
    required_columns = {"ID", "NAME", "CATALOG ID", "DESCRIPTION", "SUB CATEGORY"}
    if not required_columns.issubset(parts.columns):
        raise ValueError(
            f"Parts import is missing required columns: {sorted(required_columns - set(parts.columns))}"
        )

    structural_parts = parts[parts["ID"].astype(str).str.startswith("STRUCT_")].copy()
    if structural_parts.empty:
        return structural_parts

    if PARTS_SUMMARY_PATH.exists():
        summary = pd.read_csv(PARTS_SUMMARY_PATH, dtype=str).fillna("")
        structural_parts = structural_parts.merge(
            summary.loc[:, ["part_id", "takeoff_quantity", "takeoff_unit"]],
            left_on="ID",
            right_on="part_id",
            how="left",
        )
    else:
        structural_parts["takeoff_quantity"] = ""
        structural_parts["takeoff_unit"] = ""

    return structural_parts.sort_values("ID").reset_index(drop=True)


def build_assembly_import(part_catalog_ids: dict[str, str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for assembly in ASSEMBLIES:
        for part_index, part_code in enumerate(PART_CODES):
            part_id = f"{assembly['part_prefix']}-{part_code}"
            part_catalog_id = part_catalog_ids.get(part_id, "")
            if not part_catalog_id:
                raise ValueError(f"Missing part catalog id for `{part_id}` in Parts_Import.xlsx")

            rows.append(
                {
                    "ID": assembly["assembly_code"] if part_index == 0 else "",
                    "Name": assembly["assembly_name"] if part_index == 0 else "",
                    "Catalog Id": catalog_id("ASM", assembly["assembly_code"]) if part_index == 0 else "",
                    "Description": assembly["description"] if part_index == 0 else "",
                    "Category": "Assemblies" if part_index == 0 else "",
                    "Sub Category": "Prefab Envelope" if part_index == 0 else "",
                    "Part CatId": part_catalog_id,
                    "Part Quantity": 1,
                    "Part Notes": "",
                    "Assembly CatId": "",
                    "Assembly Quantity": 1,
                    "Assembly Notes": "",
                    "Attribute Name": "",
                    "Attribute Value": "",
                }
            )

    for _, structural_part in load_structural_parts().iterrows():
        part_id = str(structural_part["ID"]).strip()
        part_catalog_id = str(structural_part["CATALOG ID"]).strip()
        part_name = str(structural_part["NAME"]).strip()
        sub_category = str(structural_part["SUB CATEGORY"]).strip()
        takeoff_quantity = str(structural_part.get("takeoff_quantity", "")).strip()
        takeoff_unit = str(structural_part.get("takeoff_unit", "")).strip()
        notes = ""
        if takeoff_quantity and takeoff_unit:
            notes = f"Building takeoff: {takeoff_quantity} {takeoff_unit}"

        rows.append(
            {
                "ID": part_id,
                "Name": f"{part_name} assembly",
                "Catalog Id": catalog_id("ASM", part_id),
                "Description": f"Single-part structural assembly for {part_name}",
                "Category": "Assemblies",
                "Sub Category": sub_category or "Structural",
                "Part CatId": part_catalog_id,
                "Part Quantity": 1,
                "Part Notes": notes,
                "Assembly CatId": "",
                "Assembly Quantity": 1,
                "Assembly Notes": "Single part assembly",
                "Attribute Name": "",
                "Attribute Value": "",
            }
        )

    for dynamic_assembly in [
        *load_interior_wall_assemblies(),
        *load_exterior_wall_group_assemblies(),
        *load_mesh_assemblies(),
        *load_concrete_truck_assemblies(),
        *load_mep_group_assemblies(),
    ]:
        assembly_id = clean_text(dynamic_assembly["assembly_id"])
        parts = list(dynamic_assembly["parts"])
        for part_index, (part_id, quantity) in enumerate(parts):
            part_catalog_id = part_catalog_ids.get(part_id, "")
            if not part_catalog_id:
                raise ValueError(f"Missing part catalog id for `{part_id}` in Parts_Import.xlsx")
            rows.append(
                {
                    "ID": assembly_id if part_index == 0 else "",
                    "Name": clean_text(dynamic_assembly["name"]) if part_index == 0 else "",
                    "Catalog Id": catalog_id("ASM", assembly_id) if part_index == 0 else "",
                    "Description": clean_text(dynamic_assembly["description"]) if part_index == 0 else "",
                    "Category": "Assemblies" if part_index == 0 else "",
                    "Sub Category": clean_text(dynamic_assembly["sub_category"]) if part_index == 0 else "",
                    "Part CatId": part_catalog_id,
                    "Part Quantity": int(quantity),
                    "Part Notes": "",
                    "Assembly CatId": "",
                    "Assembly Quantity": 1,
                    "Assembly Notes": "",
                    "Attribute Name": "",
                    "Attribute Value": "",
                }
            )

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


if __name__ == "__main__":
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    template_columns = load_template_columns()
    if template_columns != OUTPUT_COLUMNS:
        raise ValueError(
            "Template columns do not match the expected Assembly Import structure.\n"
            f"Expected: {OUTPUT_COLUMNS}\n"
            f"Found: {template_columns}"
        )

    part_catalog_ids = load_part_catalog_ids()
    output = build_assembly_import(part_catalog_ids)
    with pd.ExcelWriter(OUTPUT_XLSX_PATH, engine="openpyxl") as writer:
        output.to_excel(writer, sheet_name="Sheet1", index=False)

    print(f"Wrote {OUTPUT_XLSX_PATH.name}")
    print(f"Rows: {len(output)}")
