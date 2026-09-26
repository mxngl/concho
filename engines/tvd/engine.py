"""TVD computation pipeline: QTO + cost DB → line items, cluster summary, results dict.

No HTML here; the legacy dashboard lives in :mod:`dashboards.tvd.legacy_render`.
"""

from dataclasses import dataclass, field

from engines.tvd.cost_db import load_cost_data
from engines.tvd.island_defaults import (
    CLUSTER_TARGETS,
    EXCLUDE_CATEGORIES,
    GROSS_SF,
    TOILET_ACS,
    TOTAL_TARGET,
)
from engines.tvd.loading import load_inputs, merge_takeoffs
from engines.tvd.quantities import aggregate_quantities, calculate_costs
from engines.tvd.results_writer import build_results_payload
from engines.tvd.summary import build_cluster_summary


@dataclass
class TvdRun:
    """Everything one engine run produces (input for the writers and the dashboard)."""

    results: list[dict]
    summary: list[dict]
    unmapped_count: int
    unmapped_rows: list[dict]
    dnc_count: int
    source: str
    total_elements: int
    duplicates_removed: int
    targets: dict[str, float] = field(default_factory=lambda: dict(CLUSTER_TARGETS))
    total_target: float = TOTAL_TARGET
    gross_sf: int = GROSS_SF

    def results_payload(self, ts=None) -> dict:
        """The results dict in the ``results/SCHEMA.md`` format."""
        return build_results_payload(
            self.results, self.summary, self.unmapped_count,
            self.source, self.targets, self.total_target, self.gross_sf,
            self.total_elements, self.duplicates_removed, self.dnc_count,
            ts=ts,
        )


def compute(
    arch_rows: list[dict],
    struct_rows: list[dict],
    cost_rows: list[dict],
    source: str = "",
) -> TvdRun:
    """Run the TVD computation on already-parsed CSV rows."""
    # Merge takeoffs (dedup by ElementId)
    all_elements = merge_takeoffs(arch_rows, struct_rows)
    dupes = len(arch_rows) + len(struct_rows) - len(all_elements)
    print(f"   Elements: arch={len(arch_rows)}, struct={len(struct_rows)}, "
          f"combined={len(all_elements)}, duplicates removed={dupes}")

    # Aggregate takeoff quantities (excluding furnishings and DNC elements)
    code_qtys, unmapped_count, all_ac_counts, unmapped_rows, dnc_count = aggregate_quantities(
        all_elements, EXCLUDE_CATEGORIES
    )
    toilet_count = sum(all_ac_counts.get(t, 0) for t in TOILET_ACS)
    print(f"   Assembly codes in takeoff: {len(code_qtys)}")
    print(f"   Unmapped elements (no AC): {unmapped_count}")
    print(f"   Skipped (DNC marker):      {dnc_count}")
    print(f"   Toilet elements found (C1030): {toilet_count}")

    # Load cost data
    cost_data = load_cost_data(cost_rows)
    print(f"   Cost line items: {len(cost_data)}")

    # Calculate line item costs and the cluster summary
    results = calculate_costs(cost_data, code_qtys, all_ac_counts)
    summary = build_cluster_summary(results)

    return TvdRun(
        results=results,
        summary=summary,
        unmapped_count=unmapped_count,
        unmapped_rows=unmapped_rows,
        dnc_count=dnc_count,
        source=source,
        total_elements=len(all_elements),
        duplicates_removed=dupes,
    )


def run_files(arch_path: str, struct_path: str, cost_path: str) -> TvdRun:
    """Load the three input files from explicit local paths and run :func:`compute`."""
    arch_rows, struct_rows, cost_rows, source = load_inputs(arch_path, struct_path, cost_path)
    return compute(arch_rows, struct_rows, cost_rows, source)
