"""Cluster summary and console formatting."""

from collections import defaultdict


def fmt_usd(n) -> str:
    if n is None or n == 0:
        return "—"
    return f"${n:,.0f}"


def build_cluster_summary(results: list[dict]) -> list[dict]:
    totals: dict[str, float] = defaultdict(float)
    for r in results:
        totals[r["cluster"]] += r["total"]

    # Preserve order from results
    seen = []
    for r in results:
        if r["cluster"] not in seen:
            seen.append(r["cluster"])

    rows = [{"cluster": c, "total": totals[c]} for c in seen]
    rows.append({"cluster": "GRAND TOTAL", "total": sum(totals.values())})
    return rows


def grand_total_of(summary: list[dict]) -> float:
    """Return the GRAND TOTAL row's total (0.0 if missing)."""
    return next((r["total"] for r in summary if r["cluster"] == "GRAND TOTAL"), 0.0)
