"""P3.5: reliability summary per cluster (course sheet ``TVD Reliability`` and the cluster
sheets' reliability rows, e.g. ``'A Substructure'!K26:P28``).

Each cost DB line has a quantity and a cost reliability rating on the course scale
1 = High, 2 = Medium, 3 = Low (:data:`engines.tvd.cost_db.RELIABILITY_LEVELS`). The course
sums the line estimates per rating (``SUMIF`` over columns N, O, P); "overall" is the worse
of the two ratings (course column P = ``MAX`` of N and O, so a line with only one rating
takes that one). Lines without a rating are summed as ``not_rated``.

Differences from the course's ``TVD Reliability`` sheet, which has two reference errors: its
quantity HIGH row for H (E14) points to ``'H Gen. Cond.'!W30`` (the target column) instead of
N30, and its LOW totals (C6, C18) sum rows A-G only, leaving out H. The engine sums all
clusters A-H of the line items.
"""

from __future__ import annotations

from engines.common.config import CLUSTER_NAMES
from engines.tvd.cost_db import RELIABILITY_LEVELS, CostDbRow

CATEGORIES = ("quantity", "cost", "overall")
LEVELS = (*RELIABILITY_LEVELS.values(), "not_rated")
COURSE_CLUSTERS = set(CLUSTER_NAMES.values())


def overall_rating(qty: int | None, cost: int | None) -> int | None:
    """The worse of the two ratings (higher number = lower reliability); ``None`` if
    neither is rated."""
    rated = [r for r in (qty, cost) if r is not None]
    return max(rated) if rated else None


def _empty() -> dict[str, dict[str, float]]:
    return {cat: dict.fromkeys(LEVELS, 0.0) for cat in CATEGORIES}


def _level(rating: int | None) -> str:
    return "not_rated" if rating is None else RELIABILITY_LEVELS[rating]


def _rounded(block: dict[str, dict[str, float]]) -> dict:
    out: dict = {cat: {lv: round(v, 2) for lv, v in block[cat].items()} for cat in CATEGORIES}
    out["estimate"] = round(sum(block["quantity"].values()), 2)
    return out


def reliability_summary(lines: list[CostDbRow], results: list[dict]) -> dict:
    """The ``reliability`` block of the results JSON.

    ``results`` are the priced line items of :func:`engines.tvd.quantities.calculate_costs`
    (same order as ``lines``). Per cluster and category (quantity, cost, overall): the
    estimate $ by level (high, medium, low, not_rated). ``totals`` sums all clusters of the
    run (= the grand total); ``totals_a_to_h`` only the course clusters A-H.
    """
    if len(lines) != len(results):
        raise ValueError("reliability_summary: lines and results differ in length")
    clusters: dict[str, dict[str, dict[str, float]]] = {}
    for line, res in zip(lines, results, strict=True):
        block = clusters.setdefault(res["cluster"], _empty())
        total = res["total"]
        q, c = line.qty_reliability, line.cost_reliability
        block["quantity"][_level(q)] += total
        block["cost"][_level(c)] += total
        block["overall"][_level(overall_rating(q, c))] += total

    totals, course = _empty(), _empty()
    for name, block in clusters.items():
        for cat in CATEGORIES:
            for lv in LEVELS:
                totals[cat][lv] += block[cat][lv]
                if name in COURSE_CLUSTERS:
                    course[cat][lv] += block[cat][lv]
    return {
        "scale": {str(k): v for k, v in RELIABILITY_LEVELS.items()},
        "clusters": {name: _rounded(block) for name, block in clusters.items()},
        "totals": _rounded(totals),
        "totals_a_to_h": _rounded(course),
    }
