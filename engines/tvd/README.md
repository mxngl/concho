# engines/tvd

Target Value Design (cost) engine, migrated from [AutoTVD](https://github.com/mxngl/AutoTVD)
(tag `island-2026-final`, `tvd_analysis.py`) in P1.3. It reads Revit quantity take-off (QTO)
CSV exports and a cost database, prices every cost line item and compares the estimate with the
TVD targets per cluster. Results are identical to AutoTVD (see "Tests" below).
Line totals are rounded to cents when computed; see
[docs/engines/tvd.md](../../docs/engines/tvd.md) for where and why.

> ⚠️ **Never commit cost data.** The Island `cost_data.csv` is RSMeans-derived (licensed).
> Cost DBs, QTO exports, `results/`, `history/` and generated dashboards stay outside this repo.

## Modules

| Module | Content |
|---|---|
| `loading.py` | CSV reading (BOM cleanup), quantity string parsing, `merge_takeoffs` (dedup by `ElementId`, structural wins) |
| `cost_db.py` | `cost_db.csv` format (P3.4): pydantic row model, loader, validator (`concho costdb validate`) |
| `quantities.py` | aggregation (DNC marker, excluded categories, keyword AC split) and quantity rules |
| `summary.py` | cluster summary, console formatting |
| `engine.py` | `compute()` / `run_files()`: inputs + project config → `TvdRun` (line items, summary, counts, results dict) |
| `targets.py` | `ProjectTargets`: project values from `project_config` (names, GSF, total and cluster targets, custom clusters, tolerance) |
| `derivation.py` | course target derivation (P3.5): budget, reference average, owner reallocation, team adjustment → `target_derivation` block |
| `reliability.py` | reliability summary per cluster (P3.5) → `reliability` block |
| `clusters.py` | canonical course clusters A–H with display names; maps cost DB labels (incl. the legacy `Special Contruction`) |
| `results_writer.py` | results JSON (`<timestamp>.json` + `latest.json`, schema = AutoTVD `results/SCHEMA.md`) |
| `history.py` | named history snapshots (with tracking `event`/`note`, P3.5) and the `tracking` table |
| `alert.py` | budget-overrun webhook (env vars, see below) |
| `rules.py` | excluded categories (the quantity rules live in the cost DB since P3.4) |
| `cli.py` | `python -m engines.tvd` / `concho-tvd` |

The HTML/PDF dashboard is rendered by `dashboards/tvd/legacy_render.py` (copy of the AutoTVD
renderer; team name and GSF come from the config since P3.2; replaced in P7.1).

### Quantity rules

Since P3.4 each cost DB row names its rule (`quantity_rule`: `takeoff`, `fixed`, `per_gsf`,
`pct_of_subtotal`, `mirror:<AC>`, `count_codes:<AC,...>`); keyword splits come from
`split_keywords`. Format, rules and examples:
[docs/engines/tvd.md](../../docs/engines/tvd.md#cost-db-format-cost_dbcsv-p34).

Before aggregation: elements with `DNC` in Family/Type/Mark/Comments are skipped, elements in
`EXCLUDE_CATEGORIES` don't contribute quantities (they still count for `count_codes`), and the
keyword split routes elements of a base code to its sub-codes (e.g. `B2010` → `B2010.CW` /
`B2010.PW`).

## How to run

```bash
pip install -e .
concho-tvd --config path/to/project_config.json \
           --arch path/to/Architecture_TakeOff.csv \
           --struct path/to/Structural_Schedule.csv \
           --cost path/to/cost_db.csv \
           --out path/to/output            # or: python -m engines.tvd ...
```

| Flag | Meaning |
|---|---|
| `--config FILE` | `project_config` JSON (**required**): targets, GSF, project/team name ([docs/config.md](../../docs/config.md)) |
| `--arch`, `--struct` | QTO exports (**required**, local paths only) |
| `--cost` | cost DB (`cost_db.csv`); default `files.cost_db` of the config. Validated first: errors stop the run |
| `--out DIR` | output folder (**required**): `DIR/results/`, `DIR/history/`, `DIR/TVD_Dashboard.html` |
| `--ci` | CI mode: dashboard to `DIR/docs/index.html`, no browser, no demo snapshot |
| `--snapshot LABEL` | save a named snapshot to the history folder |
| `--event LABEL`, `--note TEXT` | tracking event and note of this run (course **TVD Tracking**, P3.5): stored in the snapshot (with `--snapshot`) and in the `tracking` table of the results JSON |
| `--history DIR` | history folder (default `OUT/history`) |

Without `--ci`, the dashboard opens in the browser and, if the history folder is empty, a demo
"Test Version" snapshot is created (same as AutoTVD).

Budget alert: if the grand total exceeds the total target and `CONCHO_ALERT_WEBHOOK_URL` is set,
the engine POSTs a `budget_overrun` event there, with `CONCHO_ALERT_WEBHOOK_TOKEN` in the header
`CONCHO_ALERT_WEBHOOK_HEADER` (default `X-Concho-Token`). Unset URL = no alert.

## Input file contract

**QTO CSVs** (Revit schedules, one row per element; column names are case-sensitive):

| Column | Notes |
|---|---|
| `ElementId` | unique Revit element ID, used to deduplicate across the two files |
| `Category` | Revit category (e.g. `Walls`, `Floors`, `Structural Columns`) |
| `Family` | Revit family name |
| `Type` | Revit type name |
| `Assembly Code` | CSI Uniformat code (e.g. `B2010`); rows without it count as unmapped |
| `Level` | level of the element |
| `Area` | area in SF (e.g. `6590 SF`) |
| `Length` | length in LF (e.g. `12.5 LF` or `10' - 6"`) |
| `Volume` | volume in CF (e.g. `42.75 CF`) |

`Mark`, `Material` and `Comments` are optional; they appear in the unmapped-elements download,
and `Mark`/`Comments` are checked for the `DNC` marker. Other columns are ignored.

**Cost DB CSV**: `cost_db.csv` format (P3.4), see
[docs/engines/tvd.md](../../docs/engines/tvd.md#cost-db-format-cost_dbcsv-p34). An old AutoTVD
`cost_data.csv` is rejected with a pointer to `scripts/migrate_cost_data.py`, which converts
it.

## Tests

- `tests/tvd/test_tvd_units.py`: quantity rules and the dedup, on the invented fixture in
  `tests/fixtures/tvd_synthetic/`.
- `tests/tvd/test_tvd_quantity_rules.py` (P3.4): each `quantity_rule`, the keyword split,
  `qty_label`, the `cost_db_validation` block and the stop on an invalid cost DB, on a small
  synthetic project.
- `tests/tvd/test_cost_db_migration.py` (P3.4): `scripts/migrate_cost_data.py` on invented
  old-format rows; in reference mode it converts the fetched Island `cost_data.csv` (0 errors,
  D5030/D5090 mislabel warnings). Validator unit tests: `tests/common/test_cost_db.py`.
- `tests/tvd/test_tvd_project_config.py` (P3.2): the Island example config vs. an invented
  second config (`tests/fixtures/configs/river_test.project_config.json`) change exactly the
  project values (targets, GSF, names) in the results JSON and the dashboard.
- `tests/tvd/test_tvd_target_consistency.py` (P3.3): the target check (mismatch fails with
  the gap in $ and %, `target_sum_override` passes with status `override`, `carved_out` vs.
  `on_top`) and the `target_consistency` block, on the invented fixture.
- `tests/tvd/test_tvd_equivalence.py`: runs this engine and the original `tvd_analysis.py` on
  `AUTOTVD_DIR/qto/*.csv` + `AUTOTVD_DIR/cost_data.csv` (this engine: converted to `cost_db.csv`
  in a temporary folder, P3.4) and compares the results JSON (all fields
  except timestamps, label, paths, the project/team names and the `target_consistency` and
  `cost_db_validation` blocks),
  the history snapshot and the
  dashboard HTML. The new engine runs with `engines/common/examples/island_2026.project_config.json`.
  Masked since P3.2: the cluster name (`Special Contruction` → `Special Construction`), the team
  name and the GSF expressions in the dashboard. With the reference inputs it also checks grand
  total 16,065,644.29, `unmapped_count` 1693 and `dnc_count` 75, and pins the Island
  `target_consistency` block separately (P3.3). Skipped unless `AUTOTVD_DIR` is set:

  ```bash
  git clone --branch island-2026-final https://github.com/mxngl/AutoTVD /tmp/AutoTVD
  AUTOTVD_DIR=/tmp/AutoTVD pytest tests/tvd
  ```

## Changes from AutoTVD

- The remote fetch (`GITHUB_REPO_RAW = "https://https://..."`, which never worked) is removed.
  Input files are required arguments; no data lives in this repo.
- Output paths are explicit (`--out`, `--history`) instead of the script folder.
- `data_source` in the results JSON lists the three input files relative to the working
  directory (file name only if outside it), never absolute paths.
- The webhook env vars are read when the alert fires, not at import time.
- P3.2: project values (targets, GSF, project/team name) come from `project_config`
  (`--config`) instead of constants; course clusters use canonical names (`Special Construction`).
- P3.3: the engine checks the cluster targets against the total target (fails outside
  `tvd.target_sum_tolerance` unless `tvd.target_sum_override` is set) and writes a
  `target_consistency` block into the results JSON
  ([docs/config.md](../../docs/config.md#cluster-target-consistency-p33)).
- P3.4: the cost DB is a `cost_db.csv` with plain numbers and one `quantity_rule` per row; the
  hardcoded rule tables (takeoff clusters, `QUANTITY_MIRRORS`, `TOILET_ACS`,
  `AC_KEYWORD_SPLIT`) are gone from the engine (only in the migration script). The engine
  validates the cost DB before the run and writes a `cost_db_validation` block.
