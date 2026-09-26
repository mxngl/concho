# template

The per-team data repo template (project config, cost DB, STV mapping, custom materials, macro schedule, exports, pipeline workflow). Ships without any course or RSMeans data.

Filled by: Phase 5 (P5.1, P5.2). Already here: `project_config.example.json` (P3.1).

## `project_config.example.json`

A neutral example: every value is invented (no course data, no RSMeans data, no IDs).
JSON has no comments, so the notes are here, section by section. Full field reference and
validation rules: [`docs/config.md`](../docs/config.md). Check your copy with
`concho config validate project_config.json`.

- `$schema`: relative path to the JSON Schema; lets editors autocomplete and check fields.
  Adjust the path when you move the file.
- **`project`**: display data. `gross_sf` feeds the $/SF index; `currency` applies to every
  amount in the file; `units` is `imperial` (the course workbooks are imperial).
- **`tvd`**: uses the course budget formula here:
  `budget = grant × (1 − inflation + roi)^(construction_year − grant_year)`
  = 20,000,000 × 0.99³ ≈ 19,405,980; the team target `target` (18,500,000) sits below it.
  A team with a fixed total writes `"total_target": …` instead of `budget` + `target`.
  - `cluster_split` with `method: derive_from_references` mirrors the course "TVD Targets" /
    "TVD Owners" sheets: four reference columns (shares per cluster A–H, each column sums
    to 1.0), owner ratings per cluster and the 10 % reallocation. The alternative is
    `method: explicit` with `basis: amount` (currency per cluster) or `basis: pct`
    (fractions summing to 1.0).
  - `custom_clusters`: "Owner Allowance" is team data (`is_course_data: false`) and
    `carved_out`: its 250,000 comes out of the total, clusters A–H share the rest. With
    `on_top` it would be added to the total instead (reported as a warning).
  - `target_sum_tolerance`: 0.001 = cluster targets may differ from the total by 0.1 %.
  - `target_sum_override` (not set here): a reason string that accepts cluster targets
    outside the tolerance; the TVD engine then reports status `override` instead of
    failing.
- **`stv`**: `course_team` picks the team row of the course STV workbook (Pacific, Atlantic,
  Ridge, Island, River, Central, Express). The workbook path comes from the env var named in
  `course_workbook_env`, never from this file.
  - `use_phase`: every value is stated. `natural_gas_m3: 0` and `lab_sink_gpm: 0` are
    explicit zeros; `cogeneration: null` means no cogeneration. `urinal_gpf: 0.125` means
    urinals exist; `null` would mean no urinals (toilet factor 1.0), `0` the course
    behaviour (factor 0.75), see decision D11. A team that has not modeled the use phase yet
    writes `"use_phase": {"not_modeled": true}` instead.
  - `custom_materials_file: null`: no custom materials (P3.7).
- **`schedule`**: construction from 2029-03-01 to 2030-06-30, Monday–Friday, 8 h/day, four
  holidays and a winter shutdown as a blocked window. `rooms_per_zone` and `trade_sequence`
  drive the takt planner (the sequence shown is the engine default). All licensed-tool
  adapters are off, so the tool-agnostic core is used.
- **`agent`**: answer language and model names (D6 is open; these are placeholders).
  `discord` holds env var **names**; the IDs go into `.env`.
- **`files`**: all `null` until the team has its files (formats: cost DB P3.4, STV mapping
  P3.6, custom materials P3.7, macro schedule P3B.1, schedule rules P3B.2). Validation warns
  that `cost_db` and `macro_schedule` are unset. Paths are relative to the config file.
