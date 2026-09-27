"""TVD computation pipeline: QTO + cost DB → line items, cluster summary, results dict.

Project values (targets, GSF, names) come from ``project_config`` via
:class:`engines.tvd.targets.ProjectTargets`. The cost DB (``cost_db.csv``, P3.4) is validated
before anything is computed: errors stop the run (:class:`engines.tvd.cost_db.CostDbError`),
warnings go into the ``cost_db_validation`` block of the results JSON. No HTML here; the
legacy dashboard lives in :mod:`dashboards.tvd.legacy_render`.
"""

from dataclasses import dataclass, field

from engines.common.config import ProjectConfig
from engines.tvd.cost_db import CostDb, Rule, load_cost_db
from engines.tvd.loading import load_csv_file, merge_takeoffs, source_label
from engines.tvd.quantities import aggregate_quantities, calculate_costs, split_rules
from engines.tvd.reliability import reliability_summary
from engines.tvd.results_writer import build_results_payload
from engines.tvd.rules import EXCLUDE_CATEGORIES
from engines.tvd.summary import build_cluster_summary
from engines.tvd.targets import ProjectTargets


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
    project: ProjectTargets
    notes: list[str] = field(default_factory=list)
    cost_db_validation: dict | None = None
    reliability: dict | None = None

    @property
    def targets(self) -> dict[str, float]:
        return self.project.cluster_targets

    @property
    def total_target(self) -> float:
        return self.project.total_target

    @property
    def gross_sf(self) -> float:
        return self.project.gross_sf

    def results_payload(self, ts=None, tracking: dict | None = None) -> dict:
        """The results dict in the ``results/SCHEMA.md`` format; ``tracking`` is the block
        from :func:`engines.tvd.history.tracking_table` (P3.5, optional)."""
        return build_results_payload(
            self.results, self.summary, self.unmapped_count,
            self.source, self.targets, self.total_target, self.gross_sf,
            self.total_elements, self.duplicates_removed, self.dnc_count,
            ts=ts,
            project_name=self.project.project_name,
            team_name=self.project.team_name,
            target_derivation=(
                self.project.derivation.block() if self.project.derivation else None
            ),
            target_consistency=self.project.target_consistency(),
            cost_db_validation=self.cost_db_validation,
            reliability=self.reliability,
            tracking=tracking,
        )


def _project(config: ProjectConfig | ProjectTargets) -> ProjectTargets:
    if isinstance(config, ProjectTargets):
        return config
    return ProjectTargets.from_config(config)


def custom_cluster_names(config: ProjectConfig | ProjectTargets) -> list[str]:
    """Custom cluster names of the config (valid non-course clusters in the cost DB)."""
    return list(_project(config).custom_modes)


def compute(
    arch_rows: list[dict],
    struct_rows: list[dict],
    cost_db: CostDb,
    config: ProjectConfig | ProjectTargets,
    source: str = "",
) -> TvdRun:
    """Run the TVD computation on parsed QTO rows and a validated cost DB."""
    if not cost_db.ok:
        raise ValueError("compute() needs a cost DB without validation errors")
    project = _project(config)
    notes = project.check()
    lines = cost_db.lines

    # Merge takeoffs (dedup by ElementId)
    all_elements = merge_takeoffs(arch_rows, struct_rows)
    dupes = len(arch_rows) + len(struct_rows) - len(all_elements)
    print(f"   Elements: arch={len(arch_rows)}, struct={len(struct_rows)}, "
          f"combined={len(all_elements)}, duplicates removed={dupes}")

    # Aggregate takeoff quantities (excluding furnishings and DNC elements)
    code_qtys, unmapped_count, all_ac_counts, unmapped_rows, dnc_count = aggregate_quantities(
        all_elements, EXCLUDE_CATEGORIES, ac_keyword_split=split_rules(lines)
    )
    print(f"   Assembly codes in takeoff: {len(code_qtys)}")
    print(f"   Unmapped elements (no AC): {unmapped_count}")
    print(f"   Skipped (DNC marker):      {dnc_count}")
    for line in lines:
        if line.rule is Rule.COUNT_CODES:
            count = sum(all_ac_counts.get(c, 0) for c in dict.fromkeys(line.rule_targets))
            print(f"   Elements counted for {line.code} ({line.quantity_rule}): {count}")

    print(f"   Cost line items: {len(lines)} ({len(cost_db.warnings)} validation warnings)")

    # Calculate line item costs and the cluster summary
    results = calculate_costs(lines, code_qtys, all_ac_counts, gross_sf=project.gross_sf)
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
        project=project,
        notes=notes,
        cost_db_validation=cost_db.validation_block(),
        reliability=reliability_summary(lines, results),
    )


def run_files(
    arch_path: str, struct_path: str, cost_path: str, config: ProjectConfig | ProjectTargets
) -> TvdRun:
    """Load the QTO exports and the cost DB from explicit local paths and run :func:`compute`.

    Raises :class:`engines.tvd.cost_db.CostDbError` if the cost DB has validation errors.
    """
    cost_db = load_cost_db(cost_path, custom_clusters=custom_cluster_names(config))
    parts = [
        f"arch={source_label(arch_path)}",
        f"struct={source_label(struct_path)}",
        f"cost={source_label(cost_path)}",
    ]
    source = "Custom files — " + ", ".join(parts)
    print(f"Loaded data from custom paths: {', '.join(parts)}")
    return compute(load_csv_file(arch_path), load_csv_file(struct_path), cost_db, config, source)
