# Team pipeline, Tier 1 (P5.1, P5.2, P5.5)

Each team keeps its project data in its own **private** GitHub repository, made from
[`template/`](../template/). A GitHub Actions workflow in that repo
([`template/.github/workflows/pipeline.yml`](../template/.github/workflows/pipeline.yml))
computes TVD and STV on every push of new exports or tables, commits the results back to the
repo and publishes a dashboard. The logic lives in
[`scripts/run_pipeline.py`](../scripts/run_pipeline.py), so it also runs locally and in the
tests without GitHub Actions.

Scope is **Tier 1** (decision D13): TVD + STV. Not in it yet: the schedule (Tier 2), the SQLite
ingest (P5.3), the data API (P5.4), Concho chat, new dashboards (P7; TVD uses the existing
legacy renderer, STV is published as JSON only) and the Discord/budget alert (P5.2 step 9,
a TODO in the workflow).

## Private repository required

- STV needs the **course STV workbook** at runtime. It goes into `course/` of the team repo.
- `cost_db.csv` holds the team's **RSMeans-based** cost data.

Neither may be in a public repository (roadmap §0, hard rule 2). The team repo must therefore
be **private**. The pipeline checks this: in a public repo, validation fails when `cost_db.csv`
has rows or `course/` holds a workbook. **Pending the course lead's answer (D5)**: whether teams
may keep the course workbooks in their private repos; until then this is the working
assumption. In the public Concho template, `course/.gitignore` keeps `*.xlsx` out; teams
delete that file in their private repo.

**GitHub Pages** from a private repo needs GitHub Pro or Team (free for students with the
GitHub Student Developer Pack), and the published page is **public**, cost figures included.
Teams that can't or don't want that set the repository variable `CONCHO_PAGES=off`; every run
also uploads the site as the workflow artifact `dashboard`.

## Team repo layout

```
project_config.json      project values; files.cost_db / stv_mapping / custom_materials set
cost_db.csv              TVD cost DB (template: header only)
stv_mapping.csv          STV mapping table (template: the default table)
custom_materials.csv     STV custom materials (template: header only)
exports/                 Revit add-in exports (README: which file goes where)
course/                  course STV workbook (private repo only; README)
results/                 written by the pipeline (see Outputs)
.github/workflows/pipeline.yml
```

## Workflow (`pipeline.yml`)

**Triggers:** push to `main` that changes `exports/**`, `project_config.json`,
`cost_db.csv`, `stv_mapping.csv` or `custom_materials.csv`; `workflow_dispatch` with an
optional snapshot label. One run at a time (`concurrency`).

**Version:** `CONCHO_VERSION` at the top of the workflow is a git tag of `mxngl/concho`. The
workflow installs `pip install "concho[stv] @ git+https://github.com/mxngl/concho@$CONCHO_VERSION"`
and checks out `scripts/run_pipeline.py` from the same tag. A team upgrades by changing that
one line.

| # | Step (P5.2) | What happens |
|---|---|---|
| 1 | validate | `run_pipeline.py validate` (below). Any error stops the run with a GitHub error annotation per problem. |
| 2 | TVD | `concho-tvd --ci` once, with all architecture and structural exports |
| 3 | STV | `concho-stv` once, with **all** architecture, structural and MEP exports, so the engines' deduplication across exports (D15, P3.9) applies. Skipped with a warning when there is no course STV workbook. |
| 4 | results | `results/<UTC timestamp>/`, `results/latest/`, a new entry in `results/index.json` (P5.5); committed back to the repo |
| 6 | dashboards | `run_pipeline.py site`: `site/index.html` (all snapshots), `site/tvd/index.html` (latest TVD dashboard, legacy renderer), `site/results/` (the JSON files) |
| 7 | Pages | uploaded as artifact `dashboard` (always) and deployed to GitHub Pages (unless `CONCHO_PAGES=off`) |
| 9 | alert | TODO: Discord post + budget alert when the TVD estimate exceeds the target |

Steps 3b (schedule), 5 (SQLite) and 8 (data API) are not in Tier 1.

## `scripts/run_pipeline.py`

```
python run_pipeline.py validate [--repo DIR] [--repo-visibility public|private|unknown]
python run_pipeline.py run      [--repo DIR] [--label TEXT] [--commit SHA] [--commit-message TEXT]
python run_pipeline.py site     [--repo DIR] [--site DIR]
python run_pipeline.py all      (all options; validate, run and site in a row)
```

It calls the CLIs of the installed `concho` package (`python -m engines.cli`,
`engines.tvd`, `engines.stv.cli`) with the team repo as working directory, so every path in
the results is repo-relative. Exit code 1 on any error.

### Inputs

| Input | From | Checked by |
|---|---|---|
| project config | `project_config.json` in the repo root | `concho config validate` |
| cost DB | `files.cost_db` (required) | `concho costdb validate --config`; empty → warning (TVD is $0) |
| STV mapping | `files.stv_mapping`, else `stv_mapping.csv` (required: the engine's built-in default table is not part of an installed package) | `concho stvmap validate` with all exports (ties are errors) and the workbook (catalog check) |
| custom materials | `files.custom_materials` / `stv.custom_materials_file` (optional) | `concho custmat validate` |
| exports | `files.exports` (default `exports/`), recursively, except `raw/` folders; kind by file-name ending: `_Architecture_TakeOff.csv`, `_Structural_Schedule.csv`, `_MEP_TakeOff.csv` (`_Room_Boundaries.csv` is recognised and not used) | UTF-8, columns `ElementId`, `Category` (+ `Assembly Code` for architecture/structural); no architecture and no structural export → error; other CSV files → warning |
| course STV workbook | `$COURSE_STV_XLSX`, else the one `course/*.xlsx` whose name contains `STV` | missing → STV skipped (warning); several → error |

TVD takes one `--arch` and one `--struct` file. With several exports of one discipline the
pipeline joins them by column name into one temporary file; with none, it passes a header-only
file. STV reads every file itself.

### Outputs

```
results/
  index.json                      every snapshot (below)
  <YYYYMMDDTHHMMSSZ>/             one folder per run (UTC)
    run.json                      this run's index entry
    tvd/tvd_results.json          TVD results JSON (docs/engines/tvd.md)
    tvd/dashboard.html            TVD dashboard (legacy renderer)
    stv/stv_results.json          STV results JSON, charts, *_schedule_items.json (if STV ran)
  latest/                         copy of the newest run folder
  tvd_history/                    TVD snapshots (history and compare tabs of the TVD dashboard)
site/                             not committed; built by `site`, published / uploaded
```

`results/index.json` (P5.5), schema 1:

```json
{
  "schema": 1,
  "latest": "20270117T093000Z",
  "snapshots": [
    {
      "id": "20270117T093000Z",
      "timestamp": "2027-01-17T09:30:00Z",
      "commit": "<full commit SHA>",
      "label": "Week 3",
      "label_source": "snapshot_tag",
      "exports": ["exports/Team_ARCH_Architecture_TakeOff.csv", "…"],
      "paths": {
        "tvd_results": "results/20270117T093000Z/tvd/tvd_results.json",
        "tvd_dashboard": "results/20270117T093000Z/tvd/dashboard.html",
        "stv_results": "results/20270117T093000Z/stv/stv_results.json"
      },
      "tvd": {"grand_total": 52880.0, "tvd_target": 18500000, "status": "under_target",
              "unmapped_count": 0},
      "stv": {"life_cycle_kgco2e": 0.0, "target_kgco2e": 0.0, "embodied_kgco2e": 0.0},
      "stv_note": null
    }
  ]
}
```

- `label`: `--label` (workflow_dispatch input) → `manual`; else `[snapshot: …]` anywhere in
  the commit message → `snapshot_tag`; else the message's first line → `commit_message`;
  else `Run <id>` → `default`.
- `stv` is `null` and `stv_note` says why when STV was skipped; `paths.stv_results` is then
  `null`.
- Snapshots are only appended; the index page lists all of them, newest first, with no code
  change per snapshot.

## Run it locally

```sh
pip install "concho[stv] @ git+https://github.com/mxngl/concho@<tag>"
curl -O https://raw.githubusercontent.com/mxngl/concho/<tag>/scripts/run_pipeline.py
python run_pipeline.py all --repo path/to/team-repo
```

## Tests

`tests/pipeline/test_pipeline.py` copies `template/` into a temporary team repo, adds the
invented exports and 5-row cost DB of
[`tests/fixtures/pipeline_team/`](../tests/fixtures/pipeline_team/) and runs the script:
full run (TVD total pinned), appended snapshots, labels, several exports per discipline,
validation errors (missing column, not UTF-8, no exports, invalid config / cost DB, public
repo with cost data or a workbook), and the workflow file. The STV step runs only with
`$COURSE_STV_XLSX`; without it the tests check the "STV skipped" note. The CI job `pipeline`
runs them with concho installed non-editable, as in a team repo.

## Known gaps (follow-ups)

- `concho-tvd` takes one `--arch` and one `--struct` file; the pipeline joins several exports
  per discipline, so TVD sees one file per discipline and not the individual exports.
- The STV default mapping table (`template/stv_mapping.csv`) is found by a path relative to
  the source tree, so an installed package has no default table; the pipeline therefore
  requires `files.stv_mapping` or `stv_mapping.csv` in the repo.
- Budget alert / Discord post (P5.2 step 9), SQLite ingest (P5.3), data API (P5.4), static
  TVD/STV dashboards (P7.1/P7.2) are later tasks.
