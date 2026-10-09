// The JSON paths the dashboards read (P7.1, P7.2, P7.4). One list, so a test can check them
// against the results the engines write (tests/site/test_site.py). The file must stay
// strict JSON after "export const PATHS =".
//
// Syntax: "a.b.c" = keys; a trailing "[]" on a key = every item of that list; "*" = every
// value of that object. "required": the page cannot render without it. "optional": the page
// shows the block only when it is there (older results, or a run that did not produce it).
// Page code reads top-level paths with get(res, "...") or get(idx, "..."); a test checks that
// every such literal is listed here.
export const PATHS = {
  "index": {
    "required": [
      "schema", "latest",
      "snapshots[].id", "snapshots[].timestamp", "snapshots[].label",
      "snapshots[].paths.tvd_results", "snapshots[].paths.stv_results",
      "snapshots[].tvd.grand_total", "snapshots[].tvd.tvd_target", "snapshots[].tvd.status",
      "snapshots[].stv", "snapshots[].stv_note"
    ],
    "optional": [
      "snapshots[].commit", "snapshots[].paths.tvd_dashboard",
      "snapshots[].stv.life_cycle_kgco2e", "snapshots[].stv.target_kgco2e",
      "snapshots[].stv.embodied_kgco2e"
    ]
  },
  "tvd": {
    "required": [
      "meta.project_name", "meta.team_name", "meta.gross_sf", "meta.total_elements", "meta.unmapped_count",
      "meta.duplicates_removed", "meta.dnc_count",
      "financials.grand_total", "financials.tvd_target", "financials.delta",
      "financials.delta_pct", "financials.cost_per_sf", "financials.status",
      "cluster_summary[].cluster", "cluster_summary[].estimate", "cluster_summary[].target",
      "cluster_summary[].delta", "cluster_summary[].delta_pct", "cluster_summary[].per_sf",
      "line_items.*[].ac", "line_items.*[].group", "line_items.*[].desc",
      "line_items.*[].unit", "line_items.*[].unit_cost", "line_items.*[].qty",
      "line_items.*[].qty_src", "line_items.*[].total", "line_items.*[].notes"
    ],
    "optional": [
      "target_derivation.method", "target_derivation.budget.amount",
      "target_derivation.budget.grant", "target_derivation.budget.grant_year",
      "target_derivation.budget.construction_year", "target_derivation.budget.inflation",
      "target_derivation.budget.roi", "target_derivation.total_target",
      "target_derivation.target_above_budget", "target_derivation.course_cluster_base",
      "target_derivation.clusters.*.name", "target_derivation.clusters.*.final_share",
      "target_derivation.clusters.*.target", "target_derivation.sums.final_share",
      "target_derivation.sums.target", "target_derivation.warnings[]",
      "target_derivation.sums.reference_average", "target_derivation.sums.owner_share",
      "target_derivation.sums.owner_adjusted", "target_derivation.sums.team_adjustment",
      "target_derivation.clusters.*.reference_average",
      "target_derivation.clusters.*.owner_share",
      "target_derivation.clusters.*.owner_adjusted",
      "target_derivation.clusters.*.team_adjustment",
      "target_consistency.status", "target_consistency.total_target",
      "target_consistency.sum_a_to_h", "target_consistency.sum_carved_out",
      "target_consistency.sum_on_top", "target_consistency.gap",
      "target_consistency.gap_pct", "target_consistency.tolerance_amount",
      "target_consistency.override_reason", "target_consistency.carved_out_clusters",
      "target_consistency.on_top_clusters",
      "reliability.totals.quantity.high", "reliability.totals.quantity.medium",
      "reliability.totals.quantity.low", "reliability.totals.quantity.not_rated",
      "reliability.totals.cost.high", "reliability.totals.cost.medium",
      "reliability.totals.cost.low", "reliability.totals.cost.not_rated",
      "reliability.totals.overall.high", "reliability.totals.overall.medium",
      "reliability.totals.overall.low", "reliability.totals.overall.not_rated",
      "reliability.totals.estimate",
      "reliability.clusters.*.overall.high", "reliability.clusters.*.overall.medium",
      "reliability.clusters.*.overall.low", "reliability.clusters.*.overall.not_rated",
      "reliability.clusters.*.estimate",
      "tracking.target", "tracking.rows[].date", "tracking.rows[].label",
      "tracking.rows[].event", "tracking.rows[].note", "tracking.rows[].estimate",
      "tracking.rows[].delta", "tracking.rows[].current",
      "cost_db_validation.status", "cost_db_validation.rows",
      "cost_db_validation.warning_count", "cost_db_validation.warnings[]",
      "cost_db_validation.unpriced[].row", "cost_db_validation.unpriced[].cluster",
      "cost_db_validation.unpriced[].assembly_code", "cost_db_validation.not_rated",
      "quantity_parse_warnings.parser", "quantity_parse_warnings.total",
      "quantity_parse_warnings.columns.*.count", "quantity_parse_warnings.columns.*.by_issue",
      "quantity_parse_warnings.columns.*.examples[].value", "quantity_parse_warnings.columns.*.examples[].issue",
      "deduplication.rows_in", "deduplication.rows_kept", "deduplication.dropped",
      "deduplication.by_reason", "deduplication.dropped_rows[].element_id",
      "deduplication.dropped_rows[].category", "deduplication.dropped_rows[].reason",
      "deduplication.dropped_rows[].kept_export", "deduplication.dropped_rows[].dropped_export",
      "unmapped_rows.total", "unmapped_rows.listed", "unmapped_rows.cap", "unmapped_rows.ranked_by",
      "unmapped_rows.rows[].element_id", "unmapped_rows.rows[].category", "unmapped_rows.rows[].family",
      "unmapped_rows.rows[].type", "unmapped_rows.rows[].level", "unmapped_rows.rows[].area_sf",
      "unmapped_rows.rows[].length_lf", "unmapped_rows.rows[].volume_cf", "unmapped_rows.rows[].reason"
    ]
  },
  "stv": {
    "required": [
      "team", "lifetime_years", "targets",
      "metric_summary.carbon.target", "metric_summary.carbon.project", "metric_summary.carbon.percent_of_target",
      "metric_summary.energy.target", "metric_summary.energy.project", "metric_summary.energy.percent_of_target",
      "metric_summary.water.target", "metric_summary.water.project", "metric_summary.water.percent_of_target",
      "metric_summary.ozone.target", "metric_summary.ozone.project", "metric_summary.ozone.percent_of_target",
      "breakdown.embodied_materials.carbon", "breakdown.embodied_materials.energy", "breakdown.embodied_materials.water", "breakdown.embodied_materials.ozone",
      "breakdown.embodied_transport.carbon", "breakdown.embodied_transport.energy", "breakdown.embodied_transport.water", "breakdown.embodied_transport.ozone",
      "breakdown.embodied_construction.carbon", "breakdown.embodied_construction.energy", "breakdown.embodied_construction.water", "breakdown.embodied_construction.ozone",
      "breakdown.use_electricity.carbon", "breakdown.use_electricity.energy", "breakdown.use_electricity.water", "breakdown.use_electricity.ozone",
      "breakdown.use_heating.carbon", "breakdown.use_heating.energy", "breakdown.use_heating.water", "breakdown.use_heating.ozone",
      "breakdown.use_water.carbon", "breakdown.use_water.energy", "breakdown.use_water.water", "breakdown.use_water.ozone",
      "breakdown.embodied.carbon", "breakdown.embodied.energy", "breakdown.embodied.water", "breakdown.embodied.ozone",
      "breakdown.use_phase.carbon", "breakdown.use_phase.energy", "breakdown.use_phase.water", "breakdown.use_phase.ozone",
      "breakdown.life_cycle.carbon", "breakdown.life_cycle.energy", "breakdown.life_cycle.water", "breakdown.life_cycle.ozone",
      "construction_items[].assembly", "construction_items[].material_type",
      "construction_items[].amount", "construction_items[].embodied_total.carbon",
      "construction_items[].embodied_total.energy", "construction_items[].embodied_total.water",
      "construction_items[].proxy", "construction_items[].proxy_amount",
      "construction_items[].custom_material", "construction_items[].custom_material_source",
      "construction_items[].estimated"
    ],
    "optional": [
      "project_name", "mapping_coverage.rules[].proxy_note",
      "use_phase_status.modeled", "use_phase_status.not_modeled_reason",
      "use_phase_status.all_zero", "use_phase_status.source",
      "data_flags.proxy", "data_flags.custom_material",
      "data_flags.proxies.embodied.carbon", "data_flags.proxies.share_of_embodied.carbon",
      "data_flags.proxies.share_of_life_cycle.carbon", "data_flags.proxies.items[].assembly",
      "data_flags.proxies.items[].material_type", "data_flags.proxies.items[].amount",
      "data_flags.proxies.items[].proxy_amount", "data_flags.proxies.items[].embodied.carbon",
      "data_flags.custom_materials.embodied.carbon",
      "data_flags.custom_materials.share_of_embodied.carbon",
      "data_flags.custom_materials.materials[].assembly",
      "data_flags.custom_materials.materials[].material_type",
      "data_flags.custom_materials.materials[].source",
      "data_flags.custom_materials.materials[].embodied.carbon",
      "mapping_coverage.mapping_file", "mapping_coverage.total.kgco2e",
      "mapping_coverage.rules[].proxy", "mapping_coverage.rules[].discipline",
      "mapping_coverage.rules[].category", "mapping_coverage.rules[].keyword",
      "mapping_coverage.rules[].stv_assembly", "mapping_coverage.rules[].stv_material_type",
      "mapping_coverage.rules[].won",
      "mapping_coverage.disciplines.*.elements.total",
      "mapping_coverage.disciplines.*.elements.mapped",
      "mapping_coverage.disciplines.*.elements.zero_quantity",
      "mapping_coverage.disciplines.*.elements.unmapped",
      "mapping_coverage.disciplines.*.elements.mapped_pct",
      "mapping_coverage.disciplines.*.by_quantity.area_sf.mapped_pct",
      "mapping_coverage.disciplines.*.by_quantity.volume_cf.mapped_pct",
      "mapping_coverage.disciplines.*.by_quantity.length_ft.mapped_pct",
      "mapping_coverage.disciplines.*.kgco2e",
      "mapping_coverage.disciplines.*.estimated.kgco2e_pct",
      "mapping_coverage.disciplines.*.unmapped_types[].category",
      "mapping_coverage.disciplines.*.unmapped_types[].family",
      "mapping_coverage.disciplines.*.unmapped_types[].type",
      "mapping_coverage.disciplines.*.unmapped_types[].count",
      "deduplication.rows_in", "deduplication.rows_kept", "deduplication.dropped",
      "deduplication.by_reason", "deduplication.dropped_rows[].element_id",
      "deduplication.dropped_rows[].category", "deduplication.dropped_rows[].reason",
      "deduplication.dropped_rows[].kept_export", "deduplication.dropped_rows[].dropped_export",
      "dnc_rows[].element_id", "dnc_rows[].category", "dnc_rows[].type",
      "dnc_rows[].discipline", "dnc_rows[].status"
    ]
  }
};
