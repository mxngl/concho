# Concho team repo (Tier 1)

Your team's data repo for Concho: the Revit exports, your project config and cost data, and
a GitHub Actions pipeline that computes **TVD** (cost) and **STV** (carbon) on every push and
publishes a dashboard. Tier 1 = TVD + STV (decision D13); schedule tools come later (Tier 2).

This folder is the template. It ships **without any course or RSMeans data**.

> ## ⚠️ Your team repo must be PRIVATE
>
> - STV needs the **course STV workbook** at runtime; it goes into `course/` of your repo.
> - `cost_db.csv` holds your **RSMeans-based cost data**.
>
> Neither may be in a public repository. Create your team repo as **private**. The pipeline
> refuses to run in a public repo once `cost_db.csv` has rows or `course/` holds a workbook.
>
> **Pending the course lead's answer (decision D5):** whether teams may keep the course
> workbooks in their private team repos. Until then this is the working assumption.

## Quickstart

1. **Create a private repo** for your team on GitHub (empty, no README). Copy this template
   into it (replace `v0.1.0` with the current Concho version):

   ```sh
   git clone --depth 1 --branch v0.1.0 https://github.com/mxngl/concho concho-src
   git clone https://github.com/<your-org>/<your-team-repo> team
   cp -r concho-src/template/. team/
   cd team
   ```

2. **Fill in your project:** `project_config.json` (targets, GSF, course team, use phase;
   field reference: [`docs/config.md`](https://github.com/mxngl/concho/blob/main/docs/config.md))
   and `cost_db.csv` (your cost lines; see below). Check them locally with
   `pip install "concho[stv] @ git+https://github.com/mxngl/concho@v0.1.0"`, then
   `concho config validate project_config.json` and
   `concho costdb validate cost_db.csv --config project_config.json`.
3. **Course workbook:** delete `course/.gitignore`, put the course STV workbook into
   `course/` (see [`course/README.md`](course/README.md)). Without it only TVD runs.
4. **Install the Revit add-in** (Concho release on GitHub, `INSTALL.md` in the zip) and run
   the Architecture, Structural and MEP TakeOffs of your models.
5. **Export → push:** copy the CSV files into `exports/` (naming:
   [`exports/README.md`](exports/README.md)), commit and push to `main`.
6. **Dashboard:** the pipeline (Actions tab → *Concho pipeline*) validates your files, runs
   TVD and STV, commits the results to `results/` and publishes the dashboard (next section).
   Validation errors appear at the top of the run with what to fix.

Name a snapshot by putting `[snapshot: Design review 1]` into the commit message; otherwise
the first line of the commit message is the label. You can also run the pipeline by hand
(Actions → Concho pipeline → Run workflow) with a label.

## Dashboard: GitHub Pages or artifact

The pipeline builds a small site: an index page listing every snapshot (TVD estimate vs.
target, STV kgCO₂e, links to the JSON files) and the TVD dashboard of the latest run.

- **GitHub Pages:** in the repo settings, *Pages → Build and deployment → Source: GitHub
  Actions*. Pages from a **private** repo needs **GitHub Pro or Team**; students get Pro free
  with the [GitHub Student Developer Pack](https://education.github.com/pack).
  **The published page is public** (anyone with the link can open it, including cost figures
  of the TVD dashboard), even though the repo is private.
- **Without Pages** (not available, or you don't want a public page): set the repository
  variable `CONCHO_PAGES` to `off` (*Settings → Secrets and variables → Actions →
  Variables*). Every run still uploads the site as the workflow artifact **`dashboard`**:
  download it from the run page, unzip, open `index.html`.

## What's in here

| Path | What | Who edits it |
|---|---|---|
| `project_config.json` | project values (targets, GSF, course team, use phase, file paths) | team |
| `cost_db.csv` | TVD cost DB, **empty** (header only) | team |
| `stv_mapping.csv` | STV mapping table (default table, not course data) | team, optional |
| `custom_materials.csv` | STV custom materials from EPDs, **empty** | team, optional |
| `exports/` | Revit add-in exports ([`README`](exports/README.md)) | team |
| `course/` | course workbooks, private repo only ([`README`](course/README.md)) | team |
| `results/` | one folder per run + `latest/` + `index.json` | pipeline |
| `.github/workflows/pipeline.yml` | the pipeline; `CONCHO_VERSION` pins the engines | Concho |
| `project_config.example.json`, `examples/` | annotated examples (below) | – |

Details of the pipeline (steps, inputs, outputs, `results/index.json`):
[`docs/pipeline.md`](https://github.com/mxngl/concho/blob/main/docs/pipeline.md).

## `cost_db.csv`

The TVD cost DB, shipped **empty** (header only): no RSMeans or course data. Fill in one row
per cost line item (format and rules: [`docs/engines/tvd.md`](../docs/engines/tvd.md)), set
`files.cost_db` in the config and check it with `concho costdb validate cost_db.csv --config
project_config.json`. `examples/cost_db.example.csv` shows five invented rows with comments
(takeoff, mirror, counted codes, lump sum, percent of subtotal). A team with an old AutoTVD
`cost_data.csv` converts it with `python scripts/migrate_cost_data.py`.

## `stv_mapping.csv`

The default STV mapping table (P3.6): Revit export rows → course LCA catalog entries for
common Uniformat codes, a small reviewed set (names only, no LCA values; not course data).
`concho-stv` uses it when the project sets no `files.stv_mapping`. Copy it, extend it with
your categories and keywords (format: [`docs/engines/stv.md`](../docs/engines/stv.md)) and
check it with `concho stvmap validate stv_mapping.csv` (with `$COURSE_STV_XLSX` set for the
catalog check). The `mapping_coverage` block of the results lists what is still unmapped.

## `custom_materials.csv`

STV custom materials (P3.7), shipped **empty** (header only). One row per material that is not
in the course LCA catalog, with its values from an EPD per unit of the material (columns of a
course `LCA Data` row plus `source` and `is_course_data: false`; format:
[`docs/engines/stv.md`](../docs/engines/stv.md#custom-materials-custom_materialscsv-p37)).
Set `files.custom_materials` in the config and check it with `concho custmat validate
custom_materials.csv` (with `$COURSE_STV_XLSX` set, so names are checked against the catalog).

## `project_config.example.json`

`project_config.json` is this example with two changes for a team repo: `$schema` is the
URL of the schema on GitHub, and `files` points to `cost_db.csv`, `stv_mapping.csv` and
`custom_materials.csv` next to it (the pipeline needs `cost_db` and `stv_mapping` set).

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
    to 1.0), owner value items per cluster rated 0–10 by two owners (`null` = blank), the
    10 % reallocation and a team adjustment (+1 % Shell, −1 % Building Sitework; sums to 0).
    `target_shares: null` means the targets are L + M; typed-in shares (course column N)
    would replace them. The alternative is
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
    behaviour (factor 0.75), see decision D11. `onsite_renewable_kwh` is the PV output: the
    course books it at zero impact and does not subtract it from `grid_kwh`, so `grid_kwh` is
    the grid draw that remains. A team that has not modeled the use phase yet writes
    `"use_phase": {"not_modeled": true, "not_modeled_reason": "…why…"}` instead (P3.8).
  - `construction_items`: items that are not in the Revit exports, typed in as in the course
    sheet "Construction and Materials"; here 3,000 sf of PV panels as Energy /
    `Photovoltaics (sf)` (P3.8). `note` (required) says where the amount comes from.
  - `custom_materials_file: null`: no custom materials (P3.7; format in
    `custom_materials.csv`).
- **`schedule`**: construction from 2029-03-01 to 2030-06-30, Monday–Friday, 8 h/day, four
  holidays and a winter shutdown as a blocked window. `rooms_per_zone` and `trade_sequence`
  drive the takt planner (the sequence shown is the engine default). All licensed-tool
  adapters are off, so the tool-agnostic core is used.
- **`agent`**: answer language and model names (D6 is open; these are placeholders).
  `discord` holds env var **names**; the IDs go into `.env`.
- **`files`**: all `null` until the team has its files (formats: cost DB P3.4, STV mapping
  P3.6, custom materials P3.7, macro schedule P3B.1, schedule rules P3B.2). Validation warns
  that `cost_db` and `macro_schedule` are unset. Paths are relative to the config file.
  With `stv_mapping: null`, `concho-stv` uses the default table `template/stv_mapping.csv`.
