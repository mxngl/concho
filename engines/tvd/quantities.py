"""Quantity rules: aggregate takeoff quantities per Assembly Code and price line items.

Since P3.4 every rule comes from the cost DB (``quantity_rule``, ``split_keywords``, see
:mod:`engines.tvd.cost_db` and ``docs/engines/tvd.md``); the engine has no rule tables of its
own apart from the DNC marker and the excluded categories (:mod:`engines.tvd.rules`).
Aggregation handles DNC elements, excluded categories and keyword-based AC splitting.

Several lines with the same code each get the full takeoff quantity of that code for their
own unit (e.g. two SF lines and one LF line under A2020: both SF lines get the whole A2020
area, the LF line the whole A2020 length), as in AutoTVD.
"""

from collections import defaultdict
from collections.abc import Iterable

from engines.common.uniformat import base_code
from engines.tvd.cost_db import FALLBACK_KEYWORD, TAKEOFF_UNITS, CostDbRow, Rule
from engines.tvd.loading import parse_qty_str
from engines.tvd.rules import EXCLUDE_CATEGORIES

# Elements whose Family, Type, Mark, or Comments contain this marker (case-insensitive)
# are silently excluded from all quantity aggregation and cost calculations.
DNC_MARKER = "DNC"   # "Do Not Count"

_UNMAPPED_EXPORT_COLS = [
    "ElementId", "Category", "Family", "Type", "Level", "Mark",
    "Area", "Length", "Volume", "Material", "Comments",
]

_FIELD_WORD = {"area_sf": "area", "length_lf": "length", "count": "count",
               "volume_cf": "volume"}


def split_rules(lines: Iterable[CostDbRow]) -> dict[str, list[tuple[list[str], str]]]:
    """Keyword split per base code from the cost DB's ``split_keywords``.

    ``{"B2010": [(["curtain wall", ...], "B2010.CW"), ([], "B2010.PW")]}``: sub-codes in
    file order, the ``*`` sub-code (empty keyword list = catch-all) last.
    """
    rules: dict[str, list[tuple[list[str], str]]] = defaultdict(list)
    fallback: dict[str, str] = {}
    seen: set[str] = set()
    for line in lines:
        if "." not in line.code or not line.split_keywords or line.code in seen:
            continue
        seen.add(line.code)
        if line.split_keywords.strip() == FALLBACK_KEYWORD:
            fallback[base_code(line.code)] = line.code
        else:
            rules[base_code(line.code)].append((line.keywords, line.code))
    for base, sub in fallback.items():
        rules[base].append(([], sub))
    return dict(rules)


def aggregate_quantities(
    rows: list[dict],
    exclude_categories: set = EXCLUDE_CATEGORIES,
    *,
    ac_keyword_split: dict[str, list[tuple[list[str], str]]] | None = None,
    dnc_marker: str = DNC_MARKER,
) -> tuple[dict, int, dict, list[dict], int]:
    """
    Aggregate per Assembly Code for non-excluded categories:
      area_sf, length_lf, volume_cf, count

    Also builds all_ac_counts: element counts across ALL categories (including
    excluded ones like Furniture), used by ``count_codes``.

    Returns (code_qtys, unmapped_count, all_ac_counts, unmapped_rows, dnc_count).
    unmapped_rows = non-excluded rows with no Assembly Code, trimmed to export columns.
    dnc_count     = elements skipped because they carry the DNC marker.
    """
    ac_keyword_split = ac_keyword_split or {}
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

        # Count every element by AC regardless of category (for count_codes)
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


def _by_unit(q: dict, unit: str) -> tuple[float, str] | None:
    """Takeoff quantity for a unit: (quantity, label), or None for a non-takeoff unit."""
    spec = TAKEOFF_UNITS.get(unit.upper())
    if spec is None:
        return None
    field, divisor, label = spec
    value = float(q[field])
    return (value / divisor if divisor != 1 else value), label


def pick_quantity(
    line: CostDbRow,
    code_qtys: dict,
    all_ac_counts: dict,
    fixed_qty_by_ac: dict | None = None,
    *,
    gross_sf: float = 0.0,
) -> tuple[float, str]:
    """
    Quantity and generic quantity-source label of a cost line (``pct_of_subtotal`` lines
    are priced in :func:`calculate_costs`):

      fixed       → quantity_value (blank = 0)
      per_gsf     → gross_sf × quantity_value (blank = 1)
      count_codes → takeoff elements with these codes, all categories
      mirror:<AC> → <AC>'s takeoff quantity for this unit, or <AC>'s fixed quantity
      takeoff     → the code's takeoff quantity for this unit
    """
    rule = line.rule
    ac = line.code

    if rule is Rule.FIXED:
        if line.quantity_value is None:
            return 0.0, "Fixed (no quantity set)"
        return line.quantity_value, "Fixed"

    if rule is Rule.PER_GSF:
        factor = 1.0 if line.quantity_value is None else line.quantity_value
        return gross_sf * factor, f"GSF × {factor:g}"

    if rule is Rule.COUNT_CODES:
        codes = list(dict.fromkeys(line.rule_targets))
        count = sum(all_ac_counts.get(c, 0) for c in codes)
        return float(count), f"Count of codes ({', '.join(codes)})"

    if rule is Rule.MIRROR:
        (src_ac,) = line.rule_targets
        q = code_qtys.get(src_ac)
        if q:
            picked = _by_unit(q, line.unit)
            if picked is None:
                return 0.0, f"Unknown unit: {line.unit}"
            field = TAKEOFF_UNITS[line.unit.upper()][0]
            return picked[0], f"Mirror: {src_ac} {_FIELD_WORD[field]}"
        # Source AC may have a fixed qty instead of takeoff data
        if fixed_qty_by_ac and src_ac in fixed_qty_by_ac:
            return fixed_qty_by_ac[src_ac], f"Mirror: {src_ac} (Fixed)"
        return 0.0, f"Mirror source {src_ac} not in takeoff"

    if rule is Rule.TAKEOFF:
        q = code_qtys.get(ac)
        if q is None:
            return 0.0, "No takeoff match"
        picked = _by_unit(q, line.unit)
        if picked is None:
            return 0.0, f"Unknown unit: {line.unit}"
        return picked

    raise ValueError(f"pick_quantity: rule {rule} is priced in calculate_costs")


def _line(line: CostDbRow, qty: float, qty_src: str, cost, total: float, notes) -> dict:
    return {
        "cluster":    line.display_cluster,
        "ac":         line.code,
        "group":      line.group,
        "desc":       line.description,
        "unit":       line.unit,
        "unit_cost":  cost,
        "qty":        round(qty, 2),
        "qty_src":    line.qty_label or qty_src,
        "total":      round(total, 2),
        "notes":      " | ".join(notes),
    }


def calculate_costs(
    lines: list[CostDbRow],
    code_qtys: dict,
    all_ac_counts: dict,
    *,
    gross_sf: float = 0.0,
) -> list[dict]:
    """Apply unit costs to quantities and return enriched line items (cost DB order).

    ``pct_of_subtotal`` lines are priced last: quantity_value % of the sum of all other
    (cent-rounded) line totals; their ``qty`` is the percent and ``unit_cost`` 1 % of that
    subtotal.
    """
    fixed_qty_by_ac = {
        line.code: line.quantity_value
        for line in lines
        if line.rule is Rule.FIXED and line.quantity_value is not None
    }

    results: list[dict | None] = []
    pct_lines: list[tuple[int, CostDbRow]] = []
    for line in lines:
        if line.rule is Rule.PCT_OF_SUBTOTAL:
            pct_lines.append((len(results), line))
            results.append(None)
            continue
        qty, qty_src = pick_quantity(line, code_qtys, all_ac_counts, fixed_qty_by_ac,
                                     gross_sf=gross_sf)
        cost = line.unit_cost
        line_total = qty * cost if (cost is not None and qty) else 0.0

        notes = []
        if cost is None:
            notes.append("No unit cost")
        if line.rule is Rule.TAKEOFF:
            if qty == 0:
                notes.append("Zero qty from takeoff")
            if line.code not in code_qtys:
                notes.append("AC not in takeoff")
        results.append(_line(line, qty, qty_src, cost, line_total, notes))

    subtotal = sum(r["total"] for r in results if r is not None)
    for i, line in pct_lines:
        pct = line.quantity_value or 0.0
        results[i] = _line(line, pct, f"{pct:g} % of subtotal", subtotal / 100,
                           subtotal * pct / 100, [])
    return [r for r in results if r is not None]
