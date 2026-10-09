"""Precomputed per-snapshot summary (P5.3): one small JSON, stored in ``snapshots.summary_json``
and printed by ``concho-api summary``. Always below :data:`MAX_BYTES` (10 KB, P5.3 AC): the
lists are cut down (largest entries kept) until it fits."""

from __future__ import annotations

import json
from collections import defaultdict

MAX_BYTES = 10_000
_LISTS = ("clusters", "top_assemblies", "levels", "top_categories")


def _round(value, digits=2):
    return None if value is None else round(value, digits)


def build(sid: str, entry: dict, tvd: dict, stv: dict | None, clusters: list[tuple],
          items: list[tuple], qsum: list[tuple], quality: list[tuple], elements_status: str,
          ) -> dict:
    """Summary of one snapshot. Row tuples are the table rows of :mod:`engines.api.ingest`."""
    fin, meta = tvd.get("financials", {}), tvd.get("meta", {})
    q = {(r[1], r[2]): r for r in quality}  # (scope, metric) -> row
    unmapped = q.get(("tvd", "unmapped_elements"))
    out: dict = {
        "snapshot": {"id": sid, "timestamp": entry.get("timestamp"), "label": entry.get("label"),
                     "commit": (entry.get("commit") or "")[:10] or None,
                     "project": meta.get("project_name") or None},
        "cost": {
            "grand_total": fin.get("grand_total"), "target": fin.get("tvd_target"),
            "delta": fin.get("delta"), "delta_pct": fin.get("delta_pct"),
            "status": fin.get("status"), "cost_per_sf": fin.get("cost_per_sf"),
            "clusters": [[c[1], _round(c[2]), _round(c[3]), c[5]] for c in
                         sorted(clusters, key=lambda c: -c[2])],
            "columns": ["cluster", "estimate", "target", "delta_pct"],
            "unmapped_elements": unmapped[3] if unmapped else None,
            "unmapped_pct": unmapped[5] if unmapped else None,
        },
        "carbon": None,
        "quantities": None,
        "elements_status": elements_status,
    }
    if stv is not None:
        carbon = (stv.get("metric_summary") or {}).get("carbon") or {}
        bd = stv.get("breakdown") or {}
        by_assembly: dict[str, float] = defaultdict(float)
        for it in items:
            by_assembly[it[2]] += it[6]
        flags = stv.get("data_flags") or {}
        out["carbon"] = {
            "unit": "kgCO2e", "life_cycle": _round(carbon.get("project")),
            "target": _round(carbon.get("target")),
            "percent_of_target": _round(carbon.get("percent_of_target"), 4),
            "embodied": _round((bd.get("embodied") or {}).get("carbon")),
            "use_phase": _round((bd.get("use_phase") or {}).get("carbon")),
            "use_phase_modeled": bool((stv.get("use_phase_status") or {}).get("modeled")),
            "custom_material": bool(flags.get("custom_material")),
            "proxy": bool(flags.get("proxy")),
            "top_assemblies": [[a, _round(v)] for a, v in
                               sorted(by_assembly.items(), key=lambda kv: -abs(kv[1]))],
        }
    else:
        out["carbon"] = {"available": False, "note": entry.get("stv_note")}
    if elements_status == "loaded":
        by_level: dict[str, int] = defaultdict(int)
        by_cat: dict[str, int] = defaultdict(int)
        for r in qsum:
            by_level[r[2] or "(no level)"] += r[4]
            by_cat[r[1]] += r[4]
        out["quantities"] = {
            "elements": sum(by_level.values()),
            "levels": [[k, v] for k, v in sorted(by_level.items(), key=lambda kv: -kv[1])],
            "top_categories": [[k, v] for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])],
        }
    out["quality"] = {
        f"{scope}.{metric}": row[5] if row[5] is not None else row[3]
        for (scope, metric), row in q.items()
        if scope in ("tvd", "stv", "elements")
        and metric in ("unmapped_elements", "missing_level", "missing_assembly_code",
                       "no_quantity", "unpriced_line_items", "zero_quantity_elements")
    }
    return _fit(out)


def _fit(summary: dict) -> dict:
    """Cut the long lists (clusters, assemblies, levels, categories) until the JSON fits."""
    limits = {"clusters": 30, "top_assemblies": 15, "levels": 20, "top_categories": 15}
    while True:
        view = json.loads(json.dumps(summary))
        for section, key in (("cost", "clusters"), ("carbon", "top_assemblies"),
                             ("quantities", "levels"), ("quantities", "top_categories")):
            block = view.get(section)
            if block and key in block:
                block[key] = block[key][:limits[key]]
        if len(json.dumps(view, separators=(",", ":"), ensure_ascii=False).encode()) < MAX_BYTES:
            return view
        if max(limits.values()) <= 1:
            return view
        limits = {k: max(1, v // 2) for k, v in limits.items()}
