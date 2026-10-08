"""P3.6: ``mapping_coverage`` block of the STV results JSON.

How much of the Revit exports the STV mapping table covers, per discipline:

- ``elements``: element (row) counts: ``mapped`` (a rule matched and the quantity is > 0),
  ``zero_quantity`` (a rule matched, quantity 0), ``unmapped`` (no rule), ``mapped_pct``;
- ``by_quantity``: the export's own area (SF), volume (CF) and length (FT), total and mapped;
- ``estimated``: elements whose quantity comes from a fallback estimate of a conversion,
  their quantity per STV item and the kgCO2e resting on them (needs the results);
- ``unmapped_types`` / ``zero_quantity_types``: (category, family, type) with counts;

plus, over all disciplines, the rule statistics (``rules``: elements each rule won, and how
many it lost to a rule of the same specificity with a lower priority or to a more specific
rule) and ``cross_discipline_elements``: ElementIds that appear in more than one discipline
export among the mapped rows, with how each one maps. Since P3.9 ``concho-stv`` maps only the
rows the duplicate / Parts rule keeps (``engines/common/dedup.py``, the ``deduplication``
block), so in a CLI run this list is empty unless the rule kept two rows of one ElementId.

:func:`dnc_rows` (P3.9) lists the counted rows that carry the DNC ("do not count") marker:
TVD skips them, STV counts them (a separate decision).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

from . import conversions
from .mapping import DISCIPLINES, MappedElement, ScheduleReport, StvMapping
from .models import STVResults

MEASURES = {
    "area_sf": conversions.area_sf,
    "volume_cf": conversions.volume_cf,
    "length_ft": conversions.length_ft,
}
MAX_MATERIALS = 5
CROSS_NOTE = ("not available for combined results; run all exports in one concho-stv call "
              "to list elements that appear in more than one discipline export")


def _pct(part: float, total: float) -> float | None:
    return None if total == 0 else 100.0 * part / total


def _carbon_per_unit(results: STVResults | None) -> dict[tuple[str, str], float] | None:
    if results is None:
        return None
    out = {}
    for item in results.construction_items:
        if item.amount > 0:
            out[(item.assembly, item.material_type)] = item.embodied_total.carbon / item.amount
    return out


def _types(elements: list[MappedElement], *, with_rule: bool) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[MappedElement]] = defaultdict(list)
    for e in elements:
        key = (e.element.category, e.element.get("Family"), e.element.get("Type"))
        groups[key].append(e)
    out = []
    for (category, family, type_name), members in groups.items():
        materials = Counter(m.element.get("Material") for m in members if m.element.get("Material"))
        entry: dict[str, Any] = {
            "category": category,
            "family": family,
            "type": type_name,
            "count": len(members),
            "materials": [name for name, _ in materials.most_common(MAX_MATERIALS)],
        }
        if with_rule:
            entry["rules"] = sorted({m.rule.row for m in members if m.rule is not None})
        for measure, reader in MEASURES.items():
            entry[measure] = sum(reader(m.element.row) for m in members)
        out.append(entry)
    return sorted(out, key=lambda t: (-t["count"], t["category"], t["family"], t["type"]))


def _discipline_block(
    elements: list[MappedElement], carbon: dict[tuple[str, str], float] | None
) -> dict[str, Any]:
    status = Counter(e.status for e in elements)
    total = len(elements)
    by_quantity = {}
    for measure, reader in MEASURES.items():
        values = [(reader(e.element.row), e.status == "mapped") for e in elements]
        all_q = sum(v for v, _ in values)
        mapped_q = sum(v for v, is_mapped in values if is_mapped)
        by_quantity[measure] = {"total": all_q, "mapped": mapped_q,
                                "mapped_pct": _pct(mapped_q, all_q)}

    items: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"amount": 0.0,
                                                                         "estimated": 0.0})
    units: dict[tuple[str, str], str] = {}
    n_estimated = 0
    for e in elements:
        if e.status != "mapped":
            continue
        key = (e.rule.stv_assembly, e.rule.stv_material_type)
        units[key] = e.rule.unit
        items[key]["amount"] += e.amount
        if e.estimated:
            items[key]["estimated"] += e.amount
            n_estimated += 1
    kgco2e = est_kgco2e = None
    if carbon is not None:
        kgco2e = sum(v["amount"] * carbon.get(k, 0.0) for k, v in items.items())
        est_kgco2e = sum(v["estimated"] * carbon.get(k, 0.0) for k, v in items.items())
    return {
        "sources": sorted({e.element.source for e in elements}),
        "elements": {
            "total": total,
            "mapped": status["mapped"],
            "zero_quantity": status["zero_quantity"],
            "unmapped": status["unmapped"],
            "mapped_pct": _pct(status["mapped"], total),
        },
        "by_quantity": by_quantity,
        "kgco2e": kgco2e,
        "estimated": {
            "elements": n_estimated,
            "items": [
                {"stv_assembly": a, "stv_material_type": m, "unit": units[(a, m)],
                 "amount": v["amount"], "estimated_amount": v["estimated"]}
                for (a, m), v in sorted(items.items()) if v["estimated"] > 0
            ],
            "kgco2e": est_kgco2e,
            "kgco2e_pct": None if kgco2e in (None, 0) else _pct(est_kgco2e, kgco2e),
        },
        "unmapped_types": _types([e for e in elements if e.status == "unmapped"],
                                 with_rule=False),
        "zero_quantity_types": _types([e for e in elements if e.status == "zero_quantity"],
                                      with_rule=True),
    }


def _outcome(e: MappedElement) -> dict[str, Any]:
    out: dict[str, Any] = {
        "discipline": e.element.discipline,
        "source": e.element.source,
        "category": e.element.category,
        "family": e.element.get("Family"),
        "type": e.element.get("Type"),
        "status": e.status,
    }
    if e.rule is not None:
        out.update(rule=e.rule.row, stv_assembly=e.rule.stv_assembly,
                   stv_material_type=e.rule.stv_material_type, amount=e.amount)
    return out


def _cross_discipline(elements: list[MappedElement]) -> list[dict[str, Any]]:
    by_id: dict[str, list[MappedElement]] = defaultdict(list)
    for e in elements:
        if e.element.element_id:
            by_id[e.element.element_id].append(e)
    out = []
    for element_id, members in by_id.items():
        disciplines = sorted({m.element.discipline for m in members})
        if len(disciplines) > 1:
            out.append({"element_id": element_id, "disciplines": disciplines,
                        "occurrences": [_outcome(m) for m in members]})
    return sorted(out, key=lambda x: (len(x["element_id"]), x["element_id"]))


# Same marker and fields as TVD (engines/tvd/quantities.py), matched case-insensitively.
DNC_MARKER = "DNC"
DNC_FIELDS = ("Family", "Type", "Mark", "Comments")


def dnc_rows(reports: Iterable[ScheduleReport]) -> list[dict[str, Any]]:
    """Rows of ``reports`` with the DNC marker in Family, Type, Mark or Comments. STV counts
    them (TVD skips them); listed as a warning, no quantities."""
    out = []
    for report in reports:
        for e in report.elements:
            if any(DNC_MARKER in e.element.get(name).upper() for name in DNC_FIELDS):
                out.append({"element_id": e.element.element_id,
                            "category": e.element.category,
                            "type": e.element.get("Type"),
                            "discipline": e.element.discipline,
                            "status": e.status})
    return out


def build_mapping_coverage(
    reports: Iterable[ScheduleReport],
    mapping: StvMapping,
    results: STVResults | None = None,
) -> dict[str, Any]:
    """The ``mapping_coverage`` block for the elements of ``reports`` (one run)."""
    elements = [e for r in reports for e in r.elements]
    carbon = _carbon_per_unit(results)
    by_discipline: dict[str, list[MappedElement]] = defaultdict(list)
    for e in elements:
        by_discipline[e.element.discipline].append(e)
    order = [d for d in DISCIPLINES if d in by_discipline] + sorted(
        d for d in by_discipline if d not in DISCIPLINES
    )

    won: Counter[int] = Counter()
    won_zero: Counter[int] = Counter()
    lost_priority: Counter[int] = Counter()
    lost_specificity: Counter[int] = Counter()
    for e in elements:
        if e.rule is not None:
            won[e.rule.row] += 1
            if e.status == "zero_quantity":
                won_zero[e.rule.row] += 1
        for r in e.lost_to_priority:
            lost_priority[r.row] += 1
        for r in e.lost_to_specificity:
            lost_specificity[r.row] += 1

    disciplines = {d: _discipline_block(by_discipline[d], carbon) for d in order}
    return {
        "mapping_file": mapping.source,
        "total": _total(disciplines),
        "disciplines": disciplines,
        "rules": [
            {**rule.summary(), "won": won[rule.row], "won_zero_quantity": won_zero[rule.row],
             "lost_to_priority": lost_priority[rule.row],
             "lost_to_specificity": lost_specificity[rule.row]}
            for rule in mapping.rules
        ],
        "cross_discipline_elements": _cross_discipline(elements),
    }


def _merge_types(lists: list[list[dict[str, Any]]], with_rule: bool) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entries in lists:
        for t in entries:
            key = (t["category"], t["family"], t["type"])
            if key not in merged:
                merged[key] = {**t, "materials": list(t["materials"])}
                if with_rule:
                    merged[key]["rules"] = list(t.get("rules", []))
                continue
            m = merged[key]
            m["count"] += t["count"]
            m["materials"] = list(dict.fromkeys(m["materials"] + t["materials"]))[:MAX_MATERIALS]
            if with_rule:
                m["rules"] = sorted(set(m["rules"]) | set(t.get("rules", [])))
            for measure in MEASURES:
                m[measure] += t[measure]
    return sorted(merged.values(),
                  key=lambda t: (-t["count"], t["category"], t["family"], t["type"]))


def _total(disciplines: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """All disciplines together: element counts and kgCO2e (mapped / on estimates)."""
    blocks = list(disciplines.values())
    counts = {k: sum(b["elements"][k] for b in blocks)
              for k in ("total", "mapped", "zero_quantity", "unmapped")}
    counts["mapped_pct"] = _pct(counts["mapped"], counts["total"])
    kgco2e = est = 0.0
    for b in blocks:
        kgco2e = _add(kgco2e, b["kgco2e"])
        est = _add(est, b["estimated"]["kgco2e"])
    return {
        "elements": counts,
        "kgco2e": kgco2e,
        "estimated_kgco2e": est,
        "estimated_kgco2e_pct": None if kgco2e in (None, 0) else _pct(est, kgco2e),
    }


def _add(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def _merge_discipline(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    if len(blocks) == 1:
        return blocks[0]
    first = blocks[0]
    counts = {k: sum(b["elements"][k] for b in blocks)
              for k in ("total", "mapped", "zero_quantity", "unmapped")}
    counts["mapped_pct"] = _pct(counts["mapped"], counts["total"])
    by_quantity = {}
    for measure in first["by_quantity"]:
        total = sum(b["by_quantity"][measure]["total"] for b in blocks)
        mapped = sum(b["by_quantity"][measure]["mapped"] for b in blocks)
        by_quantity[measure] = {"total": total, "mapped": mapped,
                                "mapped_pct": _pct(mapped, total)}
    kgco2e, est = first["kgco2e"], first["estimated"]["kgco2e"]
    items: dict[tuple[str, str], dict[str, Any]] = {}
    for b in blocks[1:]:
        kgco2e = _add(kgco2e, b["kgco2e"])
        est = _add(est, b["estimated"]["kgco2e"])
    for b in blocks:
        for item in b["estimated"]["items"]:
            key = (item["stv_assembly"], item["stv_material_type"])
            if key in items:
                items[key]["amount"] += item["amount"]
                items[key]["estimated_amount"] += item["estimated_amount"]
            else:
                items[key] = dict(item)
    return {
        "sources": sorted({s for b in blocks for s in b["sources"]}),
        "elements": counts,
        "by_quantity": by_quantity,
        "kgco2e": kgco2e,
        "estimated": {
            "elements": sum(b["estimated"]["elements"] for b in blocks),
            "items": [items[k] for k in sorted(items)],
            "kgco2e": est,
            "kgco2e_pct": None if kgco2e in (None, 0) else _pct(est, kgco2e),
        },
        "unmapped_types": _merge_types([b["unmapped_types"] for b in blocks], False),
        "zero_quantity_types": _merge_types([b["zero_quantity_types"] for b in blocks], True),
    }


def merge_coverage(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge the coverage blocks of results that are combined (``--combine-results``).
    Disciplines and rule counts are summed; cross-discipline elements cannot be recovered."""
    if len(blocks) == 1:
        return blocks[0]
    per_discipline: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        for name, d in block["disciplines"].items():
            per_discipline[name].append(d)
    files = list(dict.fromkeys(b["mapping_file"] for b in blocks))
    rules: dict[tuple[str, int], dict[str, Any]] = {}
    for block in blocks:
        for rule in block["rules"]:
            key = (block["mapping_file"], rule["row"])
            if key not in rules:
                rules[key] = {**rule, **({"mapping_file": key[0]} if len(files) > 1 else {})}
                continue
            for count in ("won", "won_zero_quantity", "lost_to_priority",
                          "lost_to_specificity"):
                rules[key][count] += rule[count]
    order = [d for d in DISCIPLINES if d in per_discipline] + sorted(
        d for d in per_discipline if d not in DISCIPLINES
    )
    disciplines = {d: _merge_discipline(per_discipline[d]) for d in order}
    return {
        "mapping_file": files[0] if len(files) == 1 else files,
        "total": _total(disciplines),
        "disciplines": disciplines,
        "rules": list(rules.values()),
        "cross_discipline_elements": None,
        "cross_discipline_note": CROSS_NOTE,
    }
