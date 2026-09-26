from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
MICRO_SCHEDULE_PATH = ROOT / "src" / "Planning_engine" / "Micro_Schedule_Generator" / "outputs" / "Micro_Schedule.csv"
BIM_CONTEXT_PATH = ROOT / "outputs" / "takt_zones" / "central_bim_model_llm_context.csv"
PREFAB_OUTPUTS_DIR = ROOT / "src" / "Planning_engine" / "Prefab_BIM_Mapper" / "outputs"
PRODUCTION_ORDER_PATH = PREFAB_OUTPUTS_DIR / "Production_Order.xlsx"
PRODUCTION_ORDER_ITEMS_PATH = PREFAB_OUTPUTS_DIR / "Production_Order_Items.xlsx"
KIT_MAP_PATH = PREFAB_OUTPUTS_DIR / "Revit_Kit_Parameter_Map.csv"
ASSEMBLY_MAP_PATH = PREFAB_OUTPUTS_DIR / "Revit_Assembly_Id_Map.csv"
OUTPUT_DIR = ROOT / "outputs" / "delivery_window_analysis"

CONCRETE_TRUCK_ASSEMBLY_ID = "CONC_400CF_TRUCK_ASSEMBLY"
CONCRETE_TRUCK_VOLUME_CF = 400.0


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def parse_quantity(value: object) -> float:
    text = clean_text(value)
    if not text:
        return 0.0
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if match is None:
        return 0.0
    return max(float(match.group()), 0.0)


def join_unique(values: pd.Series) -> str:
    tokens = sorted({clean_text(value) for value in values if clean_text(value)})
    return "|".join(tokens)


def load_bim_context() -> pd.DataFrame:
    bim = pd.read_csv(BIM_CONTEXT_PATH, dtype=str).fillna("")
    bim["element_id_key"] = bim["element_id"].map(clean_text)
    bim["volume_cf"] = bim["volume"].map(parse_quantity)
    bim["storage_area_sf"] = bim["area"].map(parse_quantity)
    return bim


def assembly_id_from_kit_id(value: object) -> str:
    text = clean_text(value)
    return re.sub(r"_\d{8}$", "", text)


def week_start(date: pd.Timestamp, project_start: pd.Timestamp) -> pd.Timestamp:
    start = date - pd.Timedelta(days=int(date.weekday()))
    return max(start, project_start)


def window_start(date: pd.Timestamp, project_start: pd.Timestamp, window_days: int) -> pd.Timestamp:
    offset_days = max((pd.Timestamp(date) - project_start).days, 0)
    bucket_index = offset_days // window_days
    return project_start + pd.Timedelta(days=bucket_index * window_days)


def load_micro_delivery_units(exclude_element_ids: set[str] | None = None) -> pd.DataFrame:
    exclude_element_ids = exclude_element_ids or set()
    micro = pd.read_csv(MICRO_SCHEDULE_PATH)
    bim = load_bim_context()

    micro["element_id_key"] = micro["element_id"].map(clean_text)
    micro = micro[
        (micro["source_model"].map(clean_text) != "Non-BIM")
        & (micro["element_id_key"] != "")
        & (~micro["element_id_key"].isin(exclude_element_ids))
    ].copy()
    micro["element_start_dt"] = pd.to_datetime(micro["element_start"], format="mixed")

    merged = micro.merge(
        bim[
            [
                "element_id_key",
                "volume_cf",
                "storage_area_sf",
                "discipline",
                "category",
                "family",
                "type",
                "takt_id",
            ]
        ],
        on="element_id_key",
        how="left",
        suffixes=("", "_bim"),
    )
    merged["volume_cf"] = pd.to_numeric(merged["volume_cf"], errors="coerce").fillna(0)
    merged["storage_area_sf"] = pd.to_numeric(merged["storage_area_sf"], errors="coerce").fillna(0)
    merged["takt_id_resolved"] = merged["takt_id"].map(clean_text)
    if "takt_id_bim" in merged.columns:
        merged["takt_id_resolved"] = merged["takt_id_resolved"].where(
            merged["takt_id_resolved"] != "",
            merged["takt_id_bim"].map(clean_text),
        )

    element_first_use = (
        merged.sort_values(["element_start_dt", "task_id", "slot_index"])
        .drop_duplicates(subset=["element_id_key"])
        .copy()
    )
    element_first_use = element_first_use[element_first_use["volume_cf"] > 0].copy()
    element_first_use["delivery_unit_id"] = element_first_use["prefab_group_id"].map(clean_text)
    element_first_use["delivery_unit_id"] = element_first_use["delivery_unit_id"].where(
        element_first_use["delivery_unit_id"] != "",
        element_first_use["element_id_key"],
    )

    units = (
        element_first_use.groupby("delivery_unit_id", as_index=False)
        .agg(
            need_ts=("element_start_dt", "min"),
            volume_cf=("volume_cf", "sum"),
            storage_area_sf=("storage_area_sf", "sum"),
            element_count=("element_id_key", "nunique"),
            takt_zones=("takt_id_resolved", join_unique),
            levels=("level", join_unique),
            disciplines=("discipline", join_unique),
            categories=("category", join_unique),
            first_task=("task_name", "first"),
        )
        .sort_values(["need_ts", "delivery_unit_id"])
        .reset_index(drop=True)
    )
    units["need_date"] = units["need_ts"].dt.normalize()
    return units


def load_production_delivery_units() -> pd.DataFrame:
    if not all(path.exists() for path in [PRODUCTION_ORDER_PATH, PRODUCTION_ORDER_ITEMS_PATH, KIT_MAP_PATH, ASSEMBLY_MAP_PATH]):
        return pd.DataFrame()

    orders = pd.read_excel(PRODUCTION_ORDER_PATH, dtype=str).fillna("")
    items = pd.read_excel(PRODUCTION_ORDER_ITEMS_PATH, dtype=str).fillna("")
    kit = pd.read_csv(KIT_MAP_PATH, dtype=str).fillna("")
    assembly_map = pd.read_csv(ASSEMBLY_MAP_PATH, dtype=str).fillna("")
    bim = load_bim_context()

    orders["Order ID"] = orders["Order ID"].map(clean_text)
    orders["Onsite_ts"] = pd.to_datetime(orders["Onsite"], format="mixed", errors="coerce")
    items["Order ID"] = items["Order ID"].map(clean_text)
    items["Item ID"] = items["Item ID"].map(clean_text)
    items["Quantity_num"] = pd.to_numeric(items["Quantity"], errors="coerce").fillna(0)

    kit["element_id_key"] = kit["element_id"].map(clean_text)
    kit["build_code"] = kit["build_code"].map(clean_text)
    kit["Order ID"] = kit["order_id"].map(clean_text)
    kit["assembly_id_from_kit"] = kit["kit_id"].map(assembly_id_from_kit_id)
    assembly_map["element_id_key"] = assembly_map["element_id"].map(clean_text)
    assembly_map["build_code"] = assembly_map["build_code"].map(clean_text)
    assembly_map["assembly_id"] = assembly_map["assembly_id"].map(clean_text)

    kit = kit.merge(
        assembly_map.loc[:, ["element_id_key", "build_code", "assembly_id"]],
        on=["element_id_key", "build_code"],
        how="left",
    )
    kit["Item ID"] = kit["assembly_id"].map(clean_text).where(
        kit["assembly_id"].map(clean_text) != "",
        kit["assembly_id_from_kit"],
    )
    kit = kit.merge(
        bim.loc[
            :,
            [
                "element_id_key",
                "volume_cf",
                "storage_area_sf",
                "discipline",
                "category",
                "family",
                "type",
                "takt_id",
                "level",
            ],
        ],
        on="element_id_key",
        how="left",
    )

    item_keys = items.merge(orders.loc[:, ["Order ID", "Onsite_ts"]], on="Order ID", how="left")
    rows: list[dict[str, object]] = []
    for _, item in item_keys.iterrows():
        order_id = clean_text(item["Order ID"])
        item_id = clean_text(item["Item ID"])
        quantity = float(item["Quantity_num"])
        need_ts = pd.Timestamp(item["Onsite_ts"])
        if pd.isna(need_ts):
            continue

        delivery_unit_id = f"{order_id}:{item_id}"
        if item_id == CONCRETE_TRUCK_ASSEMBLY_ID:
            rows.append(
                {
                    "delivery_unit_id": delivery_unit_id,
                    "need_ts": need_ts,
                    "volume_cf": quantity * CONCRETE_TRUCK_VOLUME_CF,
                    "storage_area_sf": 0.0,
                    "element_count": quantity,
                    "takt_zones": "",
                    "levels": clean_text(orders.loc[orders["Order ID"] == order_id, "Location"].iloc[0])
                    if (orders["Order ID"] == order_id).any()
                    else "",
                    "disciplines": "Concrete",
                    "categories": "Concrete Truck",
                    "first_task": "Concrete Truck Delivery",
                    "source": "Production Order",
                }
            )
            continue

        mapped = kit[(kit["Order ID"] == order_id) & (kit["Item ID"] == item_id)].copy()
        mapped = mapped.drop_duplicates(subset=["element_id_key"])
        rows.append(
            {
                "delivery_unit_id": delivery_unit_id,
                "need_ts": need_ts,
                "volume_cf": pd.to_numeric(mapped["volume_cf"], errors="coerce").fillna(0).sum(),
                "storage_area_sf": pd.to_numeric(mapped["storage_area_sf"], errors="coerce").fillna(0).sum(),
                "element_count": mapped["element_id_key"].nunique() if not mapped.empty else quantity,
                "takt_zones": join_unique(mapped["takt_id"]) if not mapped.empty and "takt_id" in mapped else "",
                "levels": join_unique(mapped["level"]) if not mapped.empty and "level" in mapped else "",
                "disciplines": join_unique(mapped["discipline"]) if not mapped.empty and "discipline" in mapped else "",
                "categories": join_unique(mapped["category"]) if not mapped.empty and "category" in mapped else "",
                "first_task": clean_text(item["Item Name"]) or item_id,
                "source": "Production Order",
            }
        )

    units = pd.DataFrame(rows)
    if units.empty:
        return units
    units["need_ts"] = pd.to_datetime(units["need_ts"])
    units["need_date"] = units["need_ts"].dt.normalize()
    return units.sort_values(["need_ts", "delivery_unit_id"]).reset_index(drop=True)


def load_delivery_units() -> pd.DataFrame:
    production_units = load_production_delivery_units()
    if production_units.empty:
        return load_micro_delivery_units()

    kit = pd.read_csv(KIT_MAP_PATH, dtype=str).fillna("")
    covered_element_ids = {clean_text(value) for value in kit["element_id"] if clean_text(value)}
    fallback_units = load_micro_delivery_units(covered_element_ids)
    if not fallback_units.empty:
        fallback_units["source"] = "Micro Schedule Fallback"
    return (
        pd.concat([production_units, fallback_units], ignore_index=True)
        .sort_values(["need_ts", "delivery_unit_id"])
        .reset_index(drop=True)
    )


def daily_series(delivery_units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    project_start = delivery_units["need_date"].min()
    project_finish = delivery_units["need_date"].max()
    dates = pd.date_range(project_start, project_finish, freq="D")

    consumption = (
        delivery_units.groupby("need_date")
        .agg(
            needed_volume_cf=("volume_cf", "sum"),
            needed_storage_area_sf=("storage_area_sf", "sum"),
            needed_element_count=("element_count", "sum"),
        )
        .reindex(dates, fill_value=0.0)
    )
    daily_delivery = consumption.copy()

    weekly_units = delivery_units.copy()
    weekly_units["delivery_date"] = weekly_units["need_date"].map(lambda value: week_start(value, project_start))
    weekly_delivery = (
        weekly_units.groupby("delivery_date")
        .agg(
            delivered_volume_cf=("volume_cf", "sum"),
            delivered_storage_area_sf=("storage_area_sf", "sum"),
            delivered_element_count=("element_count", "sum"),
        )
        .reindex(dates, fill_value=0.0)
    )

    daily = pd.DataFrame(
        {
            "date": dates,
            "needed_volume_cf": consumption["needed_volume_cf"].values,
            "needed_storage_area_sf": consumption["needed_storage_area_sf"].values,
            "needed_element_count": consumption["needed_element_count"].values,
            "delivered_volume_cf": daily_delivery["needed_volume_cf"].values,
            "delivered_storage_area_sf": daily_delivery["needed_storage_area_sf"].values,
            "delivered_element_count": daily_delivery["needed_element_count"].values,
            "window": "1 day",
        }
    )
    weekly = pd.DataFrame(
        {
            "date": dates,
            "needed_volume_cf": consumption["needed_volume_cf"].values,
            "needed_storage_area_sf": consumption["needed_storage_area_sf"].values,
            "needed_element_count": consumption["needed_element_count"].values,
            "delivered_volume_cf": weekly_delivery["delivered_volume_cf"].values,
            "delivered_storage_area_sf": weekly_delivery["delivered_storage_area_sf"].values,
            "delivered_element_count": weekly_delivery["delivered_element_count"].values,
            "window": "1 week",
        }
    )
    return daily, weekly


def add_inventory(df: pd.DataFrame) -> pd.DataFrame:
    current_volume = 0.0
    current_area = 0.0
    current_elements = 0.0
    peak_volume_values: list[float] = []
    end_volume_values: list[float] = []
    peak_area_values: list[float] = []
    end_area_values: list[float] = []
    peak_element_values: list[float] = []
    end_element_values: list[float] = []
    for row in df.itertuples(index=False):
        after_volume_delivery = current_volume + float(row.delivered_volume_cf)
        after_area_delivery = current_area + float(row.delivered_storage_area_sf)
        after_element_delivery = current_elements + float(row.delivered_element_count)

        end_volume_inventory = max(after_volume_delivery - float(row.needed_volume_cf), 0.0)
        end_area_inventory = max(after_area_delivery - float(row.needed_storage_area_sf), 0.0)
        end_element_inventory = max(after_element_delivery - float(row.needed_element_count), 0.0)

        peak_volume_values.append(after_volume_delivery)
        end_volume_values.append(end_volume_inventory)
        peak_area_values.append(after_area_delivery)
        end_area_values.append(end_area_inventory)
        peak_element_values.append(after_element_delivery)
        end_element_values.append(end_element_inventory)

        current_volume = end_volume_inventory
        current_area = end_area_inventory
        current_elements = end_element_inventory
    result = df.copy()
    result["peak_on_site_volume_cf"] = peak_volume_values
    result["end_of_day_inventory_cf"] = end_volume_values
    result["peak_on_site_storage_area_sf"] = peak_area_values
    result["end_of_day_storage_area_sf"] = end_area_values
    result["peak_on_site_element_count"] = peak_element_values
    result["end_of_day_element_count"] = end_element_values
    return result


def top_delivery_peaks(df: pd.DataFrame, count_field: str, limit: int = 3) -> pd.DataFrame:
    return (
        df[df[count_field] > 0]
        .nlargest(limit, count_field)
        .sort_values("date")
        .reset_index(drop=True)
    )


def dominant_task_by_delivery_date(delivery_units: pd.DataFrame, window: str) -> dict[pd.Timestamp, tuple[str, float]]:
    units = delivery_units.copy()
    project_start = units["need_date"].min()
    if window == "1 week":
        units["delivery_date"] = units["need_date"].map(lambda value: week_start(value, project_start))
    else:
        units["delivery_date"] = units["need_date"]

    task_counts = (
        units.groupby(["delivery_date", "first_task"], as_index=False)["element_count"]
        .sum()
        .sort_values(["delivery_date", "element_count", "first_task"], ascending=[True, False, True])
    )
    dominant = task_counts.drop_duplicates(subset=["delivery_date"])
    return {
        pd.Timestamp(row.delivery_date): (clean_text(row.first_task), float(row.element_count))
        for row in dominant.itertuples(index=False)
    }


def annotate_element_count_peaks(
    ax: plt.Axes,
    peaks: pd.DataFrame,
    dominant_tasks: dict[pd.Timestamp, tuple[str, float]],
    color: str,
    y_offset: int,
) -> None:
    for index, row in enumerate(peaks.itertuples(index=False)):
        date = pd.Timestamp(row.date)
        total_count = float(row.delivered_element_count)
        task_name, task_count = dominant_tasks.get(date, ("Unassigned", total_count))
        ax.annotate(
            f"{task_name}\n{task_count:.0f}/{total_count:.0f}",
            xy=(date, total_count),
            xytext=(8 if index % 2 == 0 else -46, y_offset),
            textcoords="offset points",
            ha="left" if index % 2 == 0 else "right",
            va="bottom",
            fontsize=8,
            color=color,
            arrowprops={"arrowstyle": "-", "color": color, "lw": 0.8, "alpha": 0.8},
        )


def plot_delivery(daily: pd.DataFrame, weekly: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.bar(
        weekly["date"],
        weekly["delivered_volume_cf"],
        width=0.9,
        alpha=0.45,
        label="1 week delivery window",
        color="#d95f02",
    )
    ax.plot(
        daily["date"],
        daily["delivered_volume_cf"],
        label="1 day delivery window",
        color="#1b9e77",
        linewidth=2,
    )
    ax.set_title("Material Delivered to Site by Date")
    ax.set_ylabel("Delivered volume (CF)")
    ax.set_xlabel("Delivery date")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "daily_vs_weekly_delivery_volume.png", dpi=180)
    plt.close(fig)


def plot_inventory(daily: pd.DataFrame, weekly: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(
        weekly["date"],
        weekly["peak_on_site_volume_cf"],
        label="1 week delivery window",
        color="#d95f02",
        linewidth=2,
    )
    ax.plot(
        daily["date"],
        daily["peak_on_site_volume_cf"],
        label="1 day delivery window",
        color="#1b9e77",
        linewidth=2,
    )
    ax.set_title("Temporary Material Volume on Site")
    ax.set_ylabel("Peak same-day on-site volume (CF)")
    ax.set_xlabel("Date")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "onsite_inventory_impact.png", dpi=180)
    plt.close(fig)


def plot_storage_area(daily: pd.DataFrame, weekly: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(
        weekly["date"],
        weekly["peak_on_site_storage_area_sf"],
        label="1 week delivery window",
        color="#d95f02",
        linewidth=2,
    )
    ax.plot(
        daily["date"],
        daily["peak_on_site_storage_area_sf"],
        label="1 day delivery window",
        color="#1b9e77",
        linewidth=2,
    )
    ax.set_title("Temporary Material Storage Area on Site")
    ax.set_ylabel("Peak same-day storage area (SF)")
    ax.set_xlabel("Date")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "onsite_storage_area_impact.png", dpi=180)
    plt.close(fig)


def plot_element_count(
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
    delivery_units: pd.DataFrame,
    output_path: Path | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.bar(
        weekly["date"],
        weekly["delivered_element_count"],
        width=0.9,
        alpha=0.45,
        label="7 days delivery window",
        color="#d95f02",
    )
    ax.plot(
        daily["date"],
        daily["delivered_element_count"],
        label="1 day delivery window",
        color="#1b9e77",
        linewidth=2,
    )
    daily_peaks = top_delivery_peaks(daily, "delivered_element_count")
    weekly_peaks = top_delivery_peaks(weekly, "delivered_element_count")
    annotate_element_count_peaks(
        ax,
        weekly_peaks,
        dominant_task_by_delivery_date(delivery_units, "1 week"),
        "#a84a00",
        28,
    )
    annotate_element_count_peaks(
        ax,
        daily_peaks,
        dominant_task_by_delivery_date(delivery_units, "1 day"),
        "#0b6b50",
        58,
    )
    peak_count = max(
        daily["delivered_element_count"].max(),
        weekly["delivered_element_count"].max(),
    )
    ax.set_ylim(top=peak_count * 1.28)
    ax.set_title("Material Elements Delivered to Site by Date")
    ax.set_ylabel("Delivered element count")
    ax.set_xlabel("Delivery date")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path or OUTPUT_DIR / "daily_vs_weekly_delivery_element_count.png", dpi=180)
    plt.close(fig)


def plot_metrics(combined: pd.DataFrame) -> pd.DataFrame:
    metrics = (
        combined.groupby("window")
        .agg(
            total_delivered_cf=("delivered_volume_cf", "sum"),
            total_delivered_storage_area_sf=("delivered_storage_area_sf", "sum"),
            total_delivered_elements=("delivered_element_count", "sum"),
            max_single_delivery_cf=("delivered_volume_cf", "max"),
            p95_delivery_day_cf=("delivered_volume_cf", lambda s: s.quantile(0.95)),
            max_peak_on_site_cf=("peak_on_site_volume_cf", "max"),
            average_peak_on_site_cf=("peak_on_site_volume_cf", "mean"),
            average_end_of_day_inventory_cf=("end_of_day_inventory_cf", "mean"),
            max_single_delivery_storage_area_sf=("delivered_storage_area_sf", "max"),
            max_peak_on_site_storage_area_sf=("peak_on_site_storage_area_sf", "max"),
            average_peak_on_site_storage_area_sf=("peak_on_site_storage_area_sf", "mean"),
            max_single_delivery_elements=("delivered_element_count", "max"),
            max_peak_on_site_elements=("peak_on_site_element_count", "max"),
            average_peak_on_site_elements=("peak_on_site_element_count", "mean"),
        )
        .reset_index()
    )
    metrics.to_csv(OUTPUT_DIR / "delivery_window_summary_metrics.csv", index=False)

    metric_labels = [
        ("max_single_delivery_cf", "Max Single Delivery"),
        ("max_peak_on_site_cf", "Max Peak On-Site Volume"),
        ("max_single_delivery_storage_area_sf", "Max Delivery Storage Area"),
        ("max_peak_on_site_storage_area_sf", "Max Peak On-Site Storage Area"),
        ("max_single_delivery_elements", "Max Delivery Elements"),
        ("max_peak_on_site_elements", "Max Peak On-Site Elements"),
    ]
    fig, axes = plt.subplots(3, 2, figsize=(12, 11))
    colors = {"1 day": "#1b9e77", "1 week": "#d95f02"}
    for ax, (field, title) in zip(axes.flatten(), metric_labels):
        plot_df = metrics.sort_values("window")
        ax.bar(plot_df["window"], plot_df[field], color=[colors[w] for w in plot_df["window"]])
        ax.set_title(title)
        if field.endswith("_cf"):
            ax.set_ylabel("Volume (CF)")
        elif "storage_area" in field:
            ax.set_ylabel("Area (SF)")
        else:
            ax.set_ylabel("Elements")
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "delivery_window_metric_comparison.png", dpi=180)
    plt.close(fig)
    return metrics


def plot_takt_zone_weekly_peak(delivery_units: pd.DataFrame) -> None:
    exploded = delivery_units.copy()
    exploded["primary_takt_zone"] = exploded["takt_zones"].map(lambda value: clean_text(value).split("|")[0])
    exploded["primary_takt_zone"] = exploded["primary_takt_zone"].where(
        exploded["primary_takt_zone"] != "",
        "Unassigned",
    )
    top = (
        exploded.groupby("primary_takt_zone", as_index=False)["volume_cf"]
        .sum()
        .sort_values("volume_cf", ascending=False)
        .head(15)
        .sort_values("volume_cf")
    )
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.barh(top["primary_takt_zone"], top["volume_cf"], color="#7570b3")
    ax.set_title("Total Delivered Volume by Takt Zone")
    ax.set_xlabel("Volume (CF)")
    ax.set_ylabel("Takt zone")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "delivered_volume_by_takt_zone.png", dpi=180)
    plt.close(fig)


def production_order_window_series(delivery_units: pd.DataFrame) -> pd.DataFrame:
    units = delivery_units[delivery_units["source"].map(clean_text).eq("Production Order")].copy()
    if units.empty:
        return pd.DataFrame(columns=["date", "window", "production_order_count"])

    units["order_id"] = units["delivery_unit_id"].map(lambda value: clean_text(value).split(":", 1)[0])
    units["need_date"] = pd.to_datetime(units["need_date"])
    project_start = units["need_date"].min()
    project_finish = units["need_date"].max()
    dates = pd.date_range(project_start, project_finish, freq="D")

    rows: list[pd.DataFrame] = []
    for label, days in [("1 day", 1), ("3 days", 3), ("1 week", 7)]:
        bucketed = units.copy()
        if days == 7:
            bucketed["delivery_date"] = bucketed["need_date"].map(lambda value: week_start(value, project_start))
        else:
            bucketed["delivery_date"] = bucketed["need_date"].map(lambda value: window_start(value, project_start, days))
        series = (
            bucketed.groupby("delivery_date")["order_id"]
            .nunique()
            .reindex(dates, fill_value=0)
            .rename("production_order_count")
            .reset_index()
            .rename(columns={"index": "date"})
        )
        series["window"] = label
        rows.append(series)

    return pd.concat(rows, ignore_index=True)


def plot_production_order_windows(delivery_units: pd.DataFrame) -> pd.DataFrame:
    series = production_order_window_series(delivery_units)
    series.to_csv(OUTPUT_DIR / "production_order_count_by_delivery_window.csv", index=False)
    if series.empty:
        return series

    fig, ax = plt.subplots(figsize=(13, 6))
    styles = {
        "1 day": {"color": "#1b9e77", "linewidth": 2.0},
        "3 days": {"color": "#7570b3", "linewidth": 2.0},
        "1 week": {"color": "#d95f02", "linewidth": 2.4},
    }
    for label in ["1 day", "3 days", "1 week"]:
        subset = series[series["window"] == label]
        ax.plot(
            subset["date"],
            subset["production_order_count"],
            label=label,
            **styles[label],
        )
    ax.set_title("Production Orders by Delivery Window")
    ax.set_ylabel("Production order count")
    ax.set_xlabel("Delivery date")
    ax.legend(title="Delivery window")
    ax.grid(axis="y", alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "production_order_count_by_delivery_window.png", dpi=180)
    plt.close(fig)
    return series


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    delivery_units = load_delivery_units()
    delivery_units.to_csv(OUTPUT_DIR / "delivery_units_by_micro_schedule.csv", index=False)

    daily, weekly = daily_series(delivery_units)
    daily = add_inventory(daily)
    weekly = add_inventory(weekly)
    combined = pd.concat([daily, weekly], ignore_index=True)
    combined.to_csv(OUTPUT_DIR / "delivery_window_daily_timeseries.csv", index=False)

    plot_delivery(daily, weekly)
    plot_inventory(daily, weekly)
    plot_storage_area(daily, weekly)
    plot_element_count(daily, weekly, delivery_units)
    metrics = plot_metrics(combined)
    plot_takt_zone_weekly_peak(delivery_units)
    order_window_series = plot_production_order_windows(delivery_units)

    print(f"Delivery units: {len(delivery_units):,}")
    print(f"Total volume: {delivery_units['volume_cf'].sum():,.2f} CF")
    if not order_window_series.empty:
        order_peaks = (
            order_window_series.groupby("window", as_index=False)["production_order_count"]
            .max()
            .rename(columns={"production_order_count": "max_production_orders"})
        )
        print(order_peaks.to_string(index=False))
    print(metrics.to_string(index=False))
    print(f"Wrote plots and CSVs to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
