"""Results JSON writer (schema: AutoTVD ``results/SCHEMA.md``)."""

import json
import os
from datetime import datetime


def build_results_payload(
    results: list[dict],
    summary: list[dict],
    unmapped_count: int,
    source: str,
    targets: dict[str, float],
    total_target: float,
    gross_sf: int,
    all_elements_count: int,
    dupes_removed: int,
    dnc_count: int,
    ts: datetime | None = None,
) -> dict:
    """
    Build the structured results dict of a run.

    Schema
    ------
    meta              – run provenance (timestamp, source files, element counts)
    financials        – grand total, TVD target, delta, $/SF, status
    cluster_targets   – dict of cluster → target value
    cluster_summary   – list of {cluster, estimate, target, delta, delta_pct, per_sf}
    line_items        – dict of cluster → list of full line-item rows
    """
    ts       = ts or datetime.now()
    date_str = ts.strftime("%Y-%m-%d")

    grand_total = next((r["total"] for r in summary if r["cluster"] == "GRAND TOTAL"), 0.0)
    grand_delta = grand_total - total_target
    grand_pct   = (grand_delta / total_target * 100) if total_target else 0.0

    cluster_summary_out = []
    for r in summary:
        if r["cluster"] == "GRAND TOTAL":
            continue
        tgt   = targets.get(r["cluster"], 0.0)
        delta = r["total"] - tgt
        pct   = (delta / tgt * 100) if tgt else 0.0
        cluster_summary_out.append({
            "cluster":   r["cluster"],
            "estimate":  round(r["total"], 2),
            "target":    round(tgt, 2),
            "delta":     round(delta, 2),
            "delta_pct": round(pct, 2),
            "per_sf":    round(r["total"] / gross_sf, 2) if gross_sf else None,
        })

    grouped: dict[str, list] = {}
    for r in results:
        grouped.setdefault(r["cluster"], []).append({
            "ac":        r["ac"],
            "group":     r["group"],
            "desc":      r["desc"],
            "unit":      r["unit"],
            "unit_cost": r["unit_cost"],
            "qty":       round(r["qty"], 4) if r["qty"] is not None else None,
            "qty_src":   r["qty_src"],
            "total":     round(r["total"], 2),
            "notes":     r["notes"],
        })

    return {
        "meta": {
            "generated_at":      ts.isoformat(),
            "date":              date_str,
            "label":             f"Run {date_str}",
            "data_source":       source,
            "gross_sf":          gross_sf,
            "total_elements":    all_elements_count,
            "duplicates_removed": dupes_removed,
            "unmapped_count":    unmapped_count,
            "dnc_count":         dnc_count,
        },
        "financials": {
            "grand_total":  round(grand_total, 2),
            "tvd_target":   round(total_target, 2),
            "delta":        round(grand_delta, 2),
            "delta_pct":    round(grand_pct, 2),
            "cost_per_sf":  round(grand_total / gross_sf, 2) if gross_sf else None,
            "status":       "under_target" if grand_delta < 0 else (
                            "over_target"  if grand_delta > 0 else "on_target"),
        },
        "cluster_targets":  {k: round(v, 2) for k, v in targets.items()},
        "cluster_summary":  cluster_summary_out,
        "line_items":       grouped,
    }


def save_results_json(results_dir: str, payload: dict) -> str:
    """
    Write ``payload`` to ``results_dir/<YYYYMMDD_HHMMSS>.json`` (timestamp taken from
    ``meta.generated_at``) and to ``results_dir/latest.json``. Returns the first path.
    """
    os.makedirs(results_dir, exist_ok=True)
    ts_str = datetime.fromisoformat(payload["meta"]["generated_at"]).strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(results_dir, f"{ts_str}.json")
    latest   = os.path.join(results_dir, "latest.json")
    for path in (out_path, latest):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    return out_path
