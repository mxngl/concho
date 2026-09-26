# project_config

One JSON file per team describes the project: TVD targets, STV inputs, schedule, agent
settings and input files. Defined in `engines/common/config.py` (pydantic v2), exported as
JSON Schema to [`schema/project_config.schema.json`](schema/project_config.schema.json)
(task P3.1).

> **Status:** read by the TVD engine and dashboard (`concho-tvd --config`) and the STV engine
> (`concho-stv --config`) since P3.2; the schedule engines follow in P3B.2. See "Used by the
> engines" below.

Examples:
- [`template/project_config.example.json`](../template/project_config.example.json): neutral
  example with invented values; field-by-field notes in [`template/README.md`](../template/README.md).
- [`engines/common/examples/island_2026.project_config.json`](../engines/common/examples/island_2026.project_config.json):
  the Island 2026 values from the current engine defaults.

## Commands

```bash
concho config validate path/to/project_config.json   # exit 0 = valid (warnings allowed), 1 = errors
concho config schema                                  # print the JSON Schema
python scripts/export_config_schema.py [--check]      # regenerate schema + field reference (CI: --check)
```

From Python: `engines.common.config.load_config(path)` (raises `ConfigError` with all errors)
or `validate_config_file(path)` (returns errors and warnings).

## Validation rules (beyond types)

| Rule | Result |
|---|---|
| Unknown or missing required field | error |
| `tvd`: exactly one of `total_target` or `budget` + `target` | error |
| `tvd.cluster_split` (`basis: amount`): course clusters A–H + `carved_out` custom clusters sum to the total target within `target_sum_tolerance` (fraction of the total) | error outside (warning if `target_sum_override` is set), warning inside the tolerance if not exact |
| `tvd.custom_clusters` with `mode: on_top`: listed with the gap above the total | warning |
| `tvd.target` above the course budget formula result | warning |
| Shares sum to 1.0: `cluster_split` with `basis: pct`, every `reference_columns[].shares`, `cogeneration.splits` | error |
| `stv.use_phase`: every value stated (0 allowed; `cogeneration: null` = none; `water.urinal_gpf: null` = no urinals) unless `not_modeled: true` | error |
| `stv.use_phase.not_modeled: true`, or all use-phase values 0 | warning |
| Dates in order: `budget.grant_year ≤ construction_year`, `schedule.start_date < target_completion ≤ project.completion_date`, each blocked window `start ≤ end` | error |
| Blocked window or holiday outside the schedule | warning |
| `files.cost_db`, `files.macro_schedule`: set but not found | error (unset: warning) |
| `files.stv_mapping`, `custom_materials`, `schedule_rules`, `stv.custom_materials_file`: set but not found | warning |
| `stv.custom_materials_file` and `files.custom_materials` both set but different | error |
| Secrets: tokens (GitHub, `sk-…`, Slack, AWS, Google, JWT, Discord bot, bearer), URLs with credentials or token parameters, webhook URLs, private keys, 17–20 digit Discord IDs, long opaque strings | error (value not echoed) |
| Env var names (`agent.discord.*`, `stv.course_workbook_env`) must be `UPPER_SNAKE_CASE` | error |

All paths in the file are relative to the config file.

## Used by the engines (P3.2)

| Engine | Fields read | Notes |
|---|---|---|
| TVD (`concho-tvd --config`) | `project.name`, `project.team_name`, `project.gross_sf`, `tvd.total_target` / `tvd.target`, `tvd.cluster_split` (`explicit`), `tvd.custom_clusters`, `tvd.target_sum_tolerance`, `tvd.target_sum_override`, `files.cost_db` (default for `--cost`) | Cluster targets: course clusters A–H under their canonical names (`Special Construction`), then the custom clusters. `derive_from_references` is not implemented yet (P3.5). The total target excludes `on_top` custom clusters. Target check and `target_consistency` block: see below. Results JSON: `meta.project_name`, `meta.team_name`. |
| TVD dashboard | team name, GSF, targets (from the run) | No project strings in the renderer. |
| STV (`concho-stv --config`) | `stv.course_team` (`--team` overrides), `stv.lifetime_years`, `stv.use_phase`, `stv.custom_materials_file` / `files.custom_materials` | `lifetime_years` ≠ 50 is used but reported as a warning (the course formula uses 50). `not_modeled: true` → use phase 0 (warning). `cogeneration: null` and `urinal_gpf: null` → 0 (the explicit-0 urinal case is P3.10). Custom materials are loaded and validated only; the calculation uses them from P3.7. `--no-use-phase` skips the use phase (for per-trade runs combined later). |

### Cluster target consistency (P3.3)

The TVD engine (not only `concho config validate`) checks the targets before it computes
anything:

- **gap** = (course clusters A–H + `carved_out` custom clusters) − total target.
  `on_top` custom clusters are outside the total target: they are not in the gap and are
  reported separately (`sum_on_top`, `gap_incl_on_top`).
- `|gap| ≤ target_sum_tolerance × total target` → the run continues.
- Outside the tolerance the run **fails** with the gap in currency and % of the total,
  unless `tvd.target_sum_override` is set. The override is a **reason string** (why the
  mismatch is accepted, e.g. `"targets from the week-4 worksheet, reconciled later"`); the
  run then continues with status `override`, and `concho config validate` reports a warning
  instead of an error. Leave it unset (`null`) otherwise.

The results JSON gets a `target_consistency` block (amounts in project currency):

| Key | Meaning |
|---|---|
| `total_target` | `tvd.total_target` or `tvd.target` |
| `sum_a_to_h` | course clusters A–H |
| `sum_carved_out`, `carved_out_clusters` | custom clusters inside the total |
| `sum_on_top`, `on_top_clusters` | custom clusters on top of the total |
| `gap`, `gap_pct` | A–H + carved_out − total (currency, % of the total) |
| `gap_incl_on_top` | all cluster targets − total |
| `tolerance`, `tolerance_amount` | `target_sum_tolerance` as fraction and amount |
| `status` | `ok` (gap < 0.005), `within_tolerance`, `override` (outside, override set), `failed` (outside, no override; the engine stops, so only `ProjectTargets.target_consistency()` returns it) |
| `override_reason` | `tvd.target_sum_override` or `null` |

Island 2026 example: A–H 16,705,852 vs. total 16,700,000 → gap +5,852 (+0.035 %, within the
0.1 % tolerance of 16,700), Equipment Rental 400,000 on top → `gap_incl_on_top` 405,852,
status `within_tolerance`; no override needed.

The TVD quantity rule tables (takeoff clusters A–C, quantity mirrors, keyword split, toilet
codes, excluded categories) are engine defaults in `engines/tvd/rules.py` until they move to
the cost DB (P3.4).

## How to fill it in (new team)

1. Copy `template/project_config.example.json` next to your team data and rename it
   `project_config.json`. Keep the `$schema` line (fix the relative path) so editors such as
   VS Code autocomplete and check the fields.
2. **project:** name, team name, location, gross floor area (SF), completion date.
3. **tvd:** take the numbers from the course TVD workbook (`PBL_Lab_TVD-collaboration_tool.xlsx`):

   | Field | Course workbook source |
   |---|---|
   | `tvd.budget.grant`, `grant_year`, `construction_year`, `inflation`, `roi` | budget inputs on **TVD Targets** (formula: grant × (1 − inflation + ROI)^(construction_year − grant_year)) |
   | `tvd.target` | the target the team sets below that budget, **TVD Targets** |
   | `tvd.total_target` | instead of `budget` + `target`: a fixed total (e.g. from an older team worksheet) |
   | `tvd.cluster_split` `derive_from_references` → `reference_columns` | the RSMeans reference column and the three previous-project columns on **TVD Targets** (enter shares as fractions per cluster A–H) |
   | `…owner_ratings`, `…reallocation_pct` | owner value ratings on **TVD Owners** and the reallocated share (course: 10 %) |
   | `tvd.cluster_split` `explicit` → `values` | the resulting cluster targets (amount) or shares (pct), **TVD Targets** column N |
   | clusters `A`–`H` | cluster sheets **A Substructure**, **B Shell**, **C Interiors**, **D Services**, **E Equip. and Furn.**, **F Special Const.**, **G Bldg. Sitework**, **H Gen. Cond.** (roll-up on **TVD Summary**) |
   | `tvd.custom_clusters` | not in the course workbook: team data (`is_course_data: false`); choose `carved_out` (part of the total) or `on_top` (added to it) |

   The exact cells are pinned when the engine implements the derivation (P3.5).
4. **stv:** `course_team` is your team row in the course STV workbook (`CEE_222_STV_V12.xlsx`,
   `Construction and Materials` C5). The use-phase values come from its **Use Phase** sheet:
   `grid_kwh` ← "Electricity Drawn from Grid:", `onsite_renewable_kwh` ← "On-site Renewable
   Electricity:", `natural_gas_m3` ← "Natural Gas Use:", `cogeneration.*` ← "Fuel Type",
   "Electricity", "Heating", "Cooling" and the three "… Split" cells, `water.*` ← the "… Flow
   Rate:", "Landscaping Water Use:" and "Rainwater Collection:" rows. If the team has not
   modeled the use phase yet, set `not_modeled: true` (the result then covers construction
   only, reported as a warning). The workbook itself is never committed; set the env var named
   in `course_workbook_env` to its local path.
5. **schedule:** start date, work calendar, blocked periods (e.g. hurricane season), target
   completion, takt rooms per zone, trade order, and which licensed-tool adapters the team
   uses (ALICE, Fuzor, Manufacton; all off = tool-agnostic core).
6. **agent:** answer language and model names. Discord server/channel IDs go into `.env`;
   the config only names the env vars (e.g. `"ask": "DISCORD_CHANNEL_ID_ASK"`).
7. **files:** paths to the cost DB, STV mapping, custom materials, macro schedule and
   schedule rules, and the exports directory.
8. Run `concho config validate project_config.json` and fix every error; read the warnings.

## Field reference

<!-- BEGIN GENERATED: field reference (python scripts/export_config_schema.py) -->

Generated from `docs/schema/project_config.schema.json`; do not edit by hand.
`required` = the key must be present. `{method}` marks the variants of
`tvd.cluster_split`; `[]` marks list items.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `$schema` | string \| null |  | `null` | Optional path/URL of the JSON Schema (for editor support). |
| `project` | object | yes |  | General project data. |
| `project.name` | string | yes |  | Project name, e.g. the building name. |
| `project.team_name` | string | yes |  | Team name as shown in dashboards and answers. |
| `project.location` | string | yes |  | City, region/country of the site. |
| `project.currency` | string |  | `"USD"` | ISO 4217 currency code of all amounts in this file. (pattern `^[A-Z]{3}$`) |
| `project.units` | `"imperial"` |  | `"imperial"` | Unit system of quantities (only imperial, as in the course workbooks). |
| `project.gross_sf` | number | yes |  | Gross floor area in square feet ($/SF index). (> 0) |
| `project.completion_date` | string (date) | yes |  | Planned project completion (YYYY-MM-DD). |
| `tvd` | object | yes |  | Target Value Design: total target, cluster split, custom clusters. |
| `tvd.total_target` | number \| null |  | `null` | Total target amount. Give this OR `budget` + `target`, not both. (> 0) |
| `tvd.budget` | object \| null |  | `null` | Course budget formula inputs (requires `target`). |
| `tvd.budget.grant` | number | yes |  | Grant amount in the grant year. (> 0) |
| `tvd.budget.grant_year` | integer | yes |  | Year the grant is given. (≥ 1900, ≤ 2200) |
| `tvd.budget.construction_year` | integer | yes |  | Year of construction. (≥ 1900, ≤ 2200) |
| `tvd.budget.inflation` | number | yes |  | Annual inflation as a fraction (0.03 = 3 %). (≥ 0, ≤ 1) |
| `tvd.budget.roi` | number | yes |  | Annual return on investment as a fraction. (≥ 0, ≤ 1) |
| `tvd.target` | number \| null |  | `null` | Target set by the team, used together with `budget`. (> 0) |
| `tvd.cluster_split` | object \| object | yes |  | How the total is split into clusters A-H. |
| `tvd.cluster_split{explicit}.method` | `"explicit"` | yes |  |  |
| `tvd.cluster_split{explicit}.basis` | `"pct"` \| `"amount"` | yes |  | `pct`: values are fractions of the course-cluster total (total target minus carved-out custom clusters) and must sum to 1.0. `amount`: values are currency amounts that, with the carved-out custom clusters, must sum to the total target. |
| `tvd.cluster_split{explicit}.values` | map `"A"` \| `"B"` \| `"C"` \| `"D"` \| `"E"` \| `"F"` \| `"G"` \| `"H"` → number | yes |  | One value per course cluster A-H (all eight required; 0 is allowed). |
| `tvd.cluster_split{derive_from_references}.method` | `"derive_from_references"` | yes |  |  |
| `tvd.cluster_split{derive_from_references}.reference_columns` | list of object | yes |  | RSMeans reference and previous projects (course: 1 + 3 columns). (≥ 1 item(s)) |
| `tvd.cluster_split{derive_from_references}.reference_columns[].name` | string | yes |  | Column label, e.g. 'RSMeans' or 'Project 1'. |
| `tvd.cluster_split{derive_from_references}.reference_columns[].shares` | map `"A"` \| `"B"` \| `"C"` \| `"D"` \| `"E"` \| `"F"` \| `"G"` \| `"H"` → number | yes |  | Share per course cluster A-H; the eight shares must sum to 1.0. |
| `tvd.cluster_split{derive_from_references}.owner_ratings` | map `"A"` \| `"B"` \| `"C"` \| `"D"` \| `"E"` \| `"F"` \| `"G"` \| `"H"` → number | yes |  | Owner value rating per course cluster A-H (course sheet 'TVD Owners'). |
| `tvd.cluster_split{derive_from_references}.reallocation_pct` | number |  | `0.1` | Share of the total reallocated by owner ratings (0.10 = 10 %). (≥ 0, ≤ 1) |
| `tvd.custom_clusters` | list of object |  |  | Optional non-course clusters. |
| `tvd.custom_clusters[].name` | string | yes |  | Display name, e.g. 'Equipment Rental'. |
| `tvd.custom_clusters[].target` | number | yes |  | Target amount in project currency. (≥ 0) |
| `tvd.custom_clusters[].mode` | `"carved_out"` \| `"on_top"` | yes |  | `carved_out`: part of the total target (course clusters get the rest). `on_top`: added on top of the total target (reported as a warning). |
| `tvd.custom_clusters[].is_course_data` | `false` |  | `false` | Always false: custom clusters are team data. |
| `tvd.target_sum_tolerance` | number |  | `0.001` | Allowed difference between the sum of the cluster targets and the total target, as a fraction of the total target (0.001 = 0.1 %). (≥ 0, < 1) |
| `tvd.target_sum_override` | string \| null |  | `null` | Accept cluster targets outside `target_sum_tolerance`: the reason why the mismatch is intended (e.g. 'targets from an older worksheet, reconciled in week 6'). null (default) = a mismatch outside the tolerance is an error. The TVD engine reports the gap with status `override`. |
| `stv` | object | yes |  | Sustainable Target Value (life-cycle carbon, energy, water). |
| `stv.course_team` | `"Pacific"` \| `"Atlantic"` \| `"Ridge"` \| `"Island"` \| `"River"` \| `"Central"` \| `"Express"` | yes |  | Team row of the course STV workbook used for the targets. |
| `stv.lifetime_years` | integer |  | `50` | Building lifetime. (> 0, ≤ 200) |
| `stv.course_workbook_env` | string |  | `"COURSE_STV_XLSX"` | Env var that holds the local path to the course STV workbook. (pattern `^[A-Z_][A-Z0-9_]*$`) |
| `stv.use_phase` | object | yes |  | Operational energy and water per year. Every value is required (0 is allowed but must be stated) unless `not_modeled` is true. |
| `stv.use_phase.not_modeled` | boolean |  | `false` | true = the use phase is not modeled; the STV result then covers construction only (reported as a warning). |
| `stv.use_phase.grid_kwh` | number \| null |  | `null` | Grid electricity (kWh/yr). (≥ 0) |
| `stv.use_phase.onsite_renewable_kwh` | number \| null |  | `null` | On-site renewable electricity, e.g. PV (kWh/yr). (≥ 0) |
| `stv.use_phase.natural_gas_m3` | number \| null |  | `null` | Natural gas (m3/yr). (≥ 0) |
| `stv.use_phase.cogeneration` | object \| null |  | `null` | Cogeneration inputs; the key must be present (`null` = no cogeneration). |
| `stv.use_phase.cogeneration.fuel_type` | string | yes |  | Fuel name as in the course 'Cogen Data' sheet. |
| `stv.use_phase.cogeneration.electricity_kwh` | number | yes |  | Electricity per year (kWh). (≥ 0) |
| `stv.use_phase.cogeneration.heating_mj` | number | yes |  | Heating per year (MJ). (≥ 0) |
| `stv.use_phase.cogeneration.cooling_kwh` | number | yes |  | Cooling per year (kWh). (≥ 0) |
| `stv.use_phase.cogeneration.splits` | object | yes |  | Shares of the cogeneration fuel per output; must sum to 1.0. |
| `stv.use_phase.cogeneration.splits.electricity` | number | yes |  | Share of the fuel used for electricity. (≥ 0, ≤ 1) |
| `stv.use_phase.cogeneration.splits.heating` | number | yes |  | Share of the fuel used for heating. (≥ 0, ≤ 1) |
| `stv.use_phase.cogeneration.splits.cooling` | number | yes |  | Share of the fuel used for cooling. (≥ 0, ≤ 1) |
| `stv.use_phase.water` | object \| null |  | `null` | Water fixtures and volumes. |
| `stv.use_phase.water.toilet_gpf` | number \| null |  | `null` | Toilet flush (gal/flush). (≥ 0) |
| `stv.use_phase.water.urinal_gpf` | number \| null |  | `null` | Urinal flush (gal/flush). `null` = no urinals (toilet factor 1.0); an explicit `0` = course behaviour (the course applies the 0.75 toilet factor whenever the urinal cell is non-blank). The key must be present unless not_modeled is true. See docs/decisions.md. (≥ 0) |
| `stv.use_phase.water.wc_sink_gpm` | number \| null |  | `null` | WC sink (gal/min). (≥ 0) |
| `stv.use_phase.water.lab_sink_gpm` | number \| null |  | `null` | Lab sink (gal/min). (≥ 0) |
| `stv.use_phase.water.kitchen_sink_gpm` | number \| null |  | `null` | Kitchen sink (gal/min). (≥ 0) |
| `stv.use_phase.water.shower_gpm` | number \| null |  | `null` | Shower (gal/min). (≥ 0) |
| `stv.use_phase.water.landscaping_gal` | number \| null |  | `null` | Landscaping water per year (gal). (≥ 0) |
| `stv.use_phase.water.rainwater_gal` | number \| null |  | `null` | Rainwater collected per year (gal). (≥ 0) |
| `stv.custom_materials_file` | string \| null |  | `null` | Optional custom materials CSV (P3.7). Same as files.custom_materials; if both are set they must be the same path. |
| `schedule` | object | yes |  | Schedule inputs (P3B.7). |
| `schedule.start_date` | string (date) | yes |  | Construction start. |
| `schedule.calendar` | object |  |  | Work calendar. |
| `schedule.calendar.hours_per_day` | number |  | `8` | Working hours per day. (> 0, ≤ 24) |
| `schedule.calendar.workdays` | list of `"Mon"` \| `"Tue"` \| `"Wed"` \| `"Thu"` \| `"Fri"` \| `"Sat"` \| `"Sun"` |  |  | Working weekdays. (≥ 1 item(s)) |
| `schedule.calendar.holidays` | list of string (date) |  |  | Non-working dates. |
| `schedule.blocked_windows` | list of object |  |  | Periods without site work (weather, shutdowns). |
| `schedule.blocked_windows[].name` | string | yes |  | Label, e.g. 'Hurricane season 2030'. |
| `schedule.blocked_windows[].start` | string (date) | yes |  | First blocked day. |
| `schedule.blocked_windows[].end` | string (date) | yes |  | Last blocked day. |
| `schedule.target_completion` | string (date) | yes |  | Target completion of construction. |
| `schedule.rooms_per_zone` | integer |  | `1` | Takt planner: rooms per zone. (≥ 1) |
| `schedule.trade_sequence` | list of string |  |  | Takt trade order (default = the engine's current fixed sequence). (≥ 1 item(s)) |
| `schedule.adapters` | object |  |  | Optional licensed-tool adapters (D8). The core runs with all of them off. |
| `schedule.adapters.alice` | boolean |  | `false` | ALICE macro schedule import/export. |
| `schedule.adapters.fuzor` | boolean |  | `false` | Fuzor 4D export. |
| `schedule.adapters.manufacton` | boolean |  | `false` | Manufacton parts/assemblies/orders. |
| `agent` | object | yes |  | Concho agent settings. |
| `agent.default_language` | string |  | `"en"` | Answer language (ISO 639-1, e.g. 'en', 'de'). (pattern `^[a-z]{2}(-[A-Z]{2})?$`) |
| `agent.models` | object | yes |  | Model names per agent role (D6: provider still open). |
| `agent.models.router` | string | yes |  | Model for the router agent. |
| `agent.models.subagent` | string | yes |  | Model for the subagents. |
| `agent.models.tts` | string \| null |  | `null` | Text-to-speech model (optional). |
| `agent.discord` | object |  |  | Discord IDs are given as env var NAMES only, never as IDs. |
| `agent.discord.guild` | string \| null |  | `null` | Env var with the server ID. (pattern `^[A-Z_][A-Z0-9_]*$`) |
| `agent.discord.channels` | map `^[a-z][a-z0-9_-]*$` → string |  |  | Logical channel name (e.g. 'ask', 'debug') -> env var with the channel ID. |
| `agent.extensions` | object |  |  | Optional agent extensions (Phase 10). |
| `agent.extensions.transcripts` | boolean |  | `false` | Meeting transcript agent. |
| `agent.extensions.clashbot` | boolean |  | `false` | ClashBot (needs ACC/APS access). |
| `files` | object |  |  | Input files and the exports directory, relative to this config file. `cost_db` and `macro_schedule` are needed by the engines (error if set but missing, warning if unset); the others are optional (warning if set but missing). |
| `files.cost_db` | string \| null |  | `null` | TVD cost DB CSV (P3.4). |
| `files.stv_mapping` | string \| null |  | `null` | STV mapping CSV (P3.6). |
| `files.custom_materials` | string \| null |  | `null` | Custom materials CSV (P3.7). |
| `files.macro_schedule` | string \| null |  | `null` | Macro schedule CSV (P3B.1). |
| `files.schedule_rules` | string \| null |  | `null` | Schedule rules JSON (P3B.2). |
| `files.exports` | string |  | `"exports"` | Directory for Revit exports. |

<!-- END GENERATED -->
