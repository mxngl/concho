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
| `cost_db.py` | cost DB parsing incl. German number format (`$6.184,22`) |
| `quantities.py` | aggregation (DNC marker, excluded categories, keyword AC split) and quantity rules |
| `summary.py` | cluster summary, console formatting |
| `engine.py` | `compute()` / `run_files()`: inputs + project config → `TvdRun` (line items, summary, counts, results dict) |
| `targets.py` | `ProjectTargets`: project values from `project_config` (names, GSF, total and cluster targets, custom clusters, tolerance) |
| `clusters.py` | canonical course clusters A–H with display names; maps cost DB labels (incl. the legacy `Special Contruction`) |
| `results_writer.py` | results JSON (`<timestamp>.json` + `latest.json`, schema = AutoTVD `results/SCHEMA.md`) |
| `history.py` | named history snapshots |
| `alert.py` | budget-overrun webhook (env vars, see below) |
| `rules.py` | engine default rule tables (takeoff clusters, mirrors, keyword split, toilet codes, excluded categories); move to the cost DB in P3.4 |
| `cli.py` | `python -m engines.tvd` / `concho-tvd` |

The HTML/PDF dashboard is rendered by `dashboards/tvd/legacy_render.py` (copy of the AutoTVD
renderer; team name and GSF come from the config since P3.2; replaced in P7.1).

### Quantity rules (priority order)

1. **Fixed Quantity** in the cost DB always wins.
2. **Toilet count**: `C1030` = number of elements with an AC in `TOILET_ACS` (all categories,
   incl. excluded ones).
3. Clusters outside `TAKEOFF_CLUSTERS` (course clusters A–C) without a fixed quantity → 0.
4. **Quantity mirror** (`QUANTITY_MIRRORS`): take another AC's takeoff area, or its fixed quantity.
5. **Takeoff lookup** by unit: `SF`/`GSF` → Area, `MSF` → Area/1000, `LF` → Length,
   `EA`/`Flight` → count, `CY` → Volume/27, `CF` → Volume.

Before aggregation: elements with `DNC` in Family/Type/Mark/Comments are skipped, elements in
`EXCLUDE_CATEGORIES` don't contribute quantities, and `AC_KEYWORD_SPLIT` routes one AC to
sub-codes by keywords in Category + Family + Type (e.g. `B2010` → `B2010.CW` / `B2010.PW`).

## How to run

```bash
pip install -e .
concho-tvd --config path/to/project_config.json \
           --arch path/to/Architecture_TakeOff.csv \
           --struct path/to/Structural_Schedule.csv \
           --cost path/to/cost_data.csv \
           --out path/to/output            # or: python -m engines.tvd ...
```

| Flag | Meaning |
|---|---|
| `--config FILE` | `project_config` JSON (**required**): targets, GSF, project/team name ([docs/config.md](../../docs/config.md)) |
| `--arch`, `--struct` | QTO exports (**required**, local paths only) |
| `--cost` | cost DB; default `files.cost_db` of the config |
| `--out DIR` | output folder (**required**): `DIR/results/`, `DIR/history/`, `DIR/TVD_Dashboard.html` |
| `--ci` | CI mode: dashboard to `DIR/docs/index.html`, no browser, no demo snapshot |
| `--snapshot LABEL` | save a named snapshot to the history folder |
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

**Cost DB CSV** (AutoTVD `cost_data.csv` format):

| Column | Notes |
|---|---|
| `Cluster Name` | course cluster letter (`A`–`H`) or name (`Substructure` … `General Conditions`; the legacy typo `Special Contruction` is read as `Special Construction`), or the name of a custom cluster from the config |
| `Assembly Code` | Uniformat code or synthetic sub-code (`B2010.CW`); blank rows are skipped |
| `Assembly Group Name` | group label |
| `Description             ` | description; **the header has 13 trailing spaces** |
| `Unit             ` | unit (see rules above); **the header has 13 trailing spaces** |
| `Total O&P` | unit cost; `$6.184,22`, `$25,00`, `$1,000.00` and `750` all parse |
| `Fixed Quantity` | optional; overrides the takeoff |

The new cost DB format with plain numbers and a validator comes in P3.4.

## Tests

- `tests/tvd/test_tvd_units.py`: every quantity rule and the dedup, on the invented fixture in
  `tests/fixtures/tvd_synthetic/`.
- `tests/tvd/test_tvd_project_config.py` (P3.2): the Island example config vs. an invented
  second config (`tests/fixtures/configs/river_test.project_config.json`) change exactly the
  project values (targets, GSF, names) in the results JSON and the dashboard.
- `tests/tvd/test_tvd_target_consistency.py` (P3.3): the target check (mismatch fails with
  the gap in $ and %, `target_sum_override` passes with status `override`, `carved_out` vs.
  `on_top`) and the `target_consistency` block, on the invented fixture.
- `tests/tvd/test_tvd_equivalence.py`: runs this engine and the original `tvd_analysis.py` on
  `AUTOTVD_DIR/qto/*.csv` + `AUTOTVD_DIR/cost_data.csv` and compares the results JSON (all fields
  except timestamps, label, paths, the project/team names and the `target_consistency` block),
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
