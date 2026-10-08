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
    *,
    project_name: str = "",
    team_name: str = "",
    target_derivation: dict | None = None,
    target_consistency: dict | None = None,
    cost_db_validation: dict | None = None,
    reliability: dict | None = None,
    tracking: dict | None = None,
    quantity_parse_warnings: dict | None = None,
    deduplication: dict | None = None,
) -> dict:
    """
    Build the structured results dict of a run.

    Schema
    ------
    meta              – run provenance (timestamp, project/team name, source files,
                        element counts)
    financials        – grand total, TVD target, delta, $/SF, status
    cluster_targets   – dict of cluster → target value
    cluster_summary   – list of {cluster, estimate, target, delta, delta_pct, per_sf}
    target_derivation – how the cluster targets A-H were derived (P3.5; only if given):
                        method, budget (course formula inputs + amount, or null),
                        total_target, target_above_budget, course_cluster_base,
                        clusters {A..H: name, final_share, target, ...}, warnings;
                        see docs/engines/tvd.md
    target_consistency – cluster targets vs. total target (P3.3; only if given):
                        total_target, sum_a_to_h, sum_carved_out, sum_on_top, gap,
                        gap_pct, gap_incl_on_top, tolerance, tolerance_amount, status
                        (ok | within_tolerance | override | failed), override_reason,
                        carved_out_clusters, on_top_clusters
    cost_db_validation – cost DB validation result (P3.4; only if given): status
                        (ok | warnings), rows, error_count, warning_count, warnings,
                        unpriced [{row, cluster, assembly_code}], not_rated {column: count}
    reliability       – estimate $ per cluster by reliability level (P3.5; only if given):
                        scale, clusters {name: {quantity, cost, overall: {high, medium,
                        low, not_rated}, estimate}}, totals, totals_a_to_h
    tracking          – course "TVD Tracking" table (P3.5; only if given): target, rows
                        [{date, label, event, note, estimate, delta = target − estimate,
                        current}]
    quantity_parse_warnings – quantity cells the parser could not read cleanly (P3.11; only if
                        given): parser (tolerant | legacy), total, columns {column: {count,
                        by_issue {issue: count}, examples [{value, issue}] (max. 20, raw
                        cell text only)}}; see docs/engines/tvd.md
    deduplication     – rows dropped by the P3.9 rule (D15; only if given): rule, exports
                        [{export, discipline, rows}], rows_in, rows_kept, dropped, by_reason
                        {host_of_parts, duplicate_without_code, duplicate_other_discipline,
                        duplicate_same_discipline}, parts {rows, with_part_source_id, hosts},
                        dropped_rows [{element_id, category, kept_export, kept_discipline,
                        dropped_export, dropped_discipline, reason}] (no quantities);
                        meta.duplicates_removed = dropped; see docs/model-requirements.md
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

    payload = {
        "meta": {
            "generated_at":      ts.isoformat(),
            "date":              date_str,
            "label":             f"Run {date_str}",
            "project_name":      project_name,
            "team_name":         team_name,
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
    }
    if target_derivation is not None:
        payload["target_derivation"] = target_derivation
    if target_consistency is not None:
        payload["target_consistency"] = target_consistency
    if cost_db_validation is not None:
        payload["cost_db_validation"] = cost_db_validation
    if reliability is not None:
        payload["reliability"] = reliability
    if tracking is not None:
        payload["tracking"] = tracking
    if quantity_parse_warnings is not None:
        payload["quantity_parse_warnings"] = quantity_parse_warnings
    if deduplication is not None:
        payload["deduplication"] = deduplication
    payload["line_items"] = grouped
    return payload


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
