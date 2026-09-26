"""Quantity rules: aggregate takeoff quantities per Assembly Code and price line items.

Rules (see :func:`pick_quantity`): fixed quantity, toilet count, quantity mirrors,
takeoff lookup by unit. Aggregation handles DNC elements, excluded categories and
keyword-based AC splitting.

The rule tables default to the engine defaults in :mod:`engines.tvd.rules` (moved to
the cost DB in P3.4). Clusters are compared by course cluster (A-H), see
:mod:`engines.tvd.clusters`.
"""

from collections import defaultdict

from engines.common.config import CourseCluster
from engines.tvd.clusters import course_cluster
from engines.tvd.loading import parse_qty_str
from engines.tvd.rules import (
    AC_KEYWORD_SPLIT,
    EXCLUDE_CATEGORIES,
    QUANTITY_MIRRORS,
    TAKEOFF_CLUSTERS,
    TOILET_ACS,
)

# Elements whose Family, Type, Mark, or Comments contain this marker (case-insensitive)
# are silently excluded from all quantity aggregation and cost calculations.
DNC_MARKER = "DNC"   # "Do Not Count"

# Uniformat code of the toilet partitions line item (quantity = toilet element count).
TOILET_PARTITION_AC = "C1030"

_UNMAPPED_EXPORT_COLS = [
    "ElementId", "Category", "Family", "Type", "Level", "Mark",
    "Area", "Length", "Volume", "Material", "Comments",
]


def aggregate_quantities(
    rows: list[dict],
    exclude_categories: set = EXCLUDE_CATEGORIES,
    *,
    ac_keyword_split: dict[str, list[tuple[list[str], str]]] = AC_KEYWORD_SPLIT,
    dnc_marker: str = DNC_MARKER,
) -> tuple[dict, int, dict, list[dict], int]:
    """
    Aggregate per Assembly Code for non-excluded categories:
      area_sf, length_lf, volume_cf, count

    Also builds all_ac_counts: element counts across ALL categories (including
    excluded ones like Furniture) — used for toilet stall mapping.

    Returns (code_qtys, unmapped_count, all_ac_counts, unmapped_rows, dnc_count).
    unmapped_rows = non-excluded rows with no Assembly Code, trimmed to export columns.
    dnc_count     = elements skipped because they carry the DNC marker.
    """
    code_qtys: dict[str, dict] = defaultdict(
        lambda: {"area_sf": 0.0, "length_lf": 0.0, "volume_cf": 0.0, "count": 0}
    )
    all_ac_counts: dict[str, int] = defaultdict(int)
    unmapped = 0
    unmapped_rows: list[dict] = []
    dnc_count = 0

    for row in rows:
        # Skip elements marked "Do Not Count" in any name field
        marker = dnc_marker.upper()
        if any(
            marker in row.get(f, "").upper()
            for f in ("Family", "Type", "Mark", "Comments")
        ):
            dnc_count += 1
            continue

        ac = row.get("Assembly Code", "").strip()
        cat = row.get("Category", "").strip()

        # Resolve keyword-based sub-codes before any counting
        if ac in ac_keyword_split:
            name = " ".join([
                row.get("Category", ""),
                row.get("Family",   ""),
                row.get("Type",     ""),
            ]).lower()
            for keywords, sub_ac in ac_keyword_split[ac]:
                if not keywords or any(kw in name for kw in keywords):
                    ac = sub_ac
                    break

        # Count every element by AC regardless of category (for toilet mapping)
        if ac:
            all_ac_counts[ac] += 1

        # Skip excluded categories from quantity aggregation
        if cat in exclude_categories:
            continue

        if not ac:
            unmapped += 1
            unmapped_rows.append({col: row.get(col, "") for col in _UNMAPPED_EXPORT_COLS})
            continue

        q = code_qtys[ac]
        q["area_sf"]   += parse_qty_str(row.get("Area", ""))
        q["length_lf"] += parse_qty_str(row.get("Length", ""))
        q["volume_cf"] += parse_qty_str(row.get("Volume", ""))
        q["count"]     += 1

    return dict(code_qtys), unmapped, dict(all_ac_counts), unmapped_rows, dnc_count


def pick_quantity(
    cr: dict,
    code_qtys: dict,
    all_ac_counts: dict,
    fixed_qty_by_ac: dict | None = None,
    *,
    toilet_acs: set[str] = TOILET_ACS,
    takeoff_clusters: frozenset[CourseCluster] = TAKEOFF_CLUSTERS,
    quantity_mirrors: dict[str, tuple[str, str]] = QUANTITY_MIRRORS,
) -> tuple[float, str]:
    """
    Determine the quantity to use for a cost line item.

    Rules (in priority order):
      1. Fixed Quantity in cost_data → always wins.
      2. C1030 Toilet Partitions → count elements with toilet_acs (all categories).
      3. quantity_mirrors entry → use a different AC's takeoff quantity, or its
         fixed_qty if the source AC has no takeoff data (e.g. B1020 is Fixed).
      4. Normal takeoff lookup by unit type (clusters A–C only).
      5. Non-A/B/C cluster with no Fixed Quantity → 0.
    """
    fq = cr["fixed_qty"]
    ac = cr["ac"]

    # Rule 1 — fixed quantity overrides everything
    if fq is not None:
        return fq, "Fixed"

    # Rule 2 — toilet stall count (C1030 only, uses toilet_acs across all categories)
    if ac == TOILET_PARTITION_AC:
        count = sum(all_ac_counts.get(t, 0) for t in toilet_acs)
        label = f"Toilet elements ({', '.join(sorted(toilet_acs))})"
        return float(count), label

    # Only clusters A–C use takeoff data from here on
    if course_cluster(cr["cluster"]) not in takeoff_clusters:
        return 0.0, "Fixed only (none set)"

    # Rule 3 — finish mirrors: track another AC's quantity
    if ac in quantity_mirrors:
        src_ac, field = quantity_mirrors[ac]
        q = code_qtys.get(src_ac)
        if q:
            return q[field], f"Mirror: {src_ac} area"
        # Source AC may have a fixed qty instead of takeoff data
        if fixed_qty_by_ac and src_ac in fixed_qty_by_ac:
            return fixed_qty_by_ac[src_ac], f"Mirror: {src_ac} (Fixed)"
        return 0.0, f"Mirror source {src_ac} not in takeoff"

    # Rule 4 — normal unit-based lookup
    q = code_qtys.get(ac)
    if q is None:
        return 0.0, "No takeoff match"

    u = cr["unit"].upper()
    if u in ("SF", "GSF"):
        return q["area_sf"],            "Area (SF)"
    if u == "MSF":
        return q["area_sf"] / 1000,     "Area/1000 (MSF)"
    if u == "LF":
        return q["length_lf"],          "Length (LF)"
    if u in ("EA", "FLIGHT"):
        return float(q["count"]),       "Count (EA)"
    if u == "CY":
        return q["volume_cf"] / 27,     "Volume (CY)"
    if u == "CF":
        return q["volume_cf"],          "Volume (CF)"
    return 0.0, f"Unknown unit: {cr['unit']}"


def calculate_costs(
    cost_data: list[dict],
    code_qtys: dict,
    all_ac_counts: dict,
    *,
    toilet_acs: set[str] = TOILET_ACS,
    takeoff_clusters: frozenset[CourseCluster] = TAKEOFF_CLUSTERS,
    quantity_mirrors: dict[str, tuple[str, str]] = QUANTITY_MIRRORS,
) -> list[dict]:
    """Apply unit costs to quantities and return enriched line items."""
    # ACs that have special quantity rules (no "AC not in takeoff" warning)
    special_acs = set(quantity_mirrors.keys()) | {TOILET_PARTITION_AC}

    fixed_qty_by_ac = {
        cr["ac"]: cr["fixed_qty"]
        for cr in cost_data
        if cr["fixed_qty"] is not None
    }

    results = []
    for cr in cost_data:
        is_takeoff = course_cluster(cr["cluster"]) in takeoff_clusters
        qty, qty_src = pick_quantity(
            cr, code_qtys, all_ac_counts, fixed_qty_by_ac,
            toilet_acs=toilet_acs,
            takeoff_clusters=takeoff_clusters,
            quantity_mirrors=quantity_mirrors,
        )
        cost = cr["cost"]
        line_total = qty * cost if (cost is not None and qty) else 0.0

        notes = []
        if cost is None:
            notes.append("No unit cost")
        if (qty == 0
                and cr["fixed_qty"] is None
                and is_takeoff
                and cr["ac"] not in special_acs):
            notes.append("Zero qty from takeoff")
        if (cr["ac"] not in code_qtys
                and cr["fixed_qty"] is None
                and is_takeoff
                and cr["ac"] not in special_acs):
            notes.append("AC not in takeoff")

        results.append({
            "cluster":    cr["cluster"],
            "ac":         cr["ac"],
            "group":      cr["group"],
            "desc":       cr["desc"],
            "unit":       cr["unit"],
            "unit_cost":  cost,
            "qty":        round(qty, 2),
            "qty_src":    qty_src,
            "total":      round(line_total, 2),
            "notes":      " | ".join(notes),
        })
    return results
