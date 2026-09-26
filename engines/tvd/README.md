# engines/tvd

Target Value Design (cost) engine, migrated from [AutoTVD](https://github.com/mxngl/AutoTVD)
(tag `island-2026-final`, `tvd_analysis.py`) in P1.3. It reads Revit quantity take-off (QTO)
CSV exports and a cost database, prices every cost line item and compares the estimate with the
TVD targets per cluster. Results are identical to AutoTVD (see "Tests" below).

> ⚠️ **Never commit cost data.** The Island `cost_data.csv` is RSMeans-derived (licensed).
> Cost DBs, QTO exports, `results/`, `history/` and generated dashboards stay outside this repo.

## Modules

| Module | Content |
|---|---|
| `loading.py` | CSV reading (BOM cleanup), quantity string parsing, `merge_takeoffs` (dedup by `ElementId`, structural wins) |
| `cost_db.py` | cost DB parsing incl. German number format (`$6.184,22`) |
| `quantities.py` | aggregation (DNC marker, excluded categories, keyword AC split) and quantity rules |
| `summary.py` | cluster summary, console formatting |
| `engine.py` | `compute()` / `run_files()`: inputs → `TvdRun` (line items, summary, counts, results dict) |
| `results_writer.py` | results JSON (`<timestamp>.json` + `latest.json`, schema = AutoTVD `results/SCHEMA.md`) |
| `history.py` | named history snapshots |
| `alert.py` | budget-overrun webhook (env vars, see below) |
| `island_defaults.py` | Island constants: targets, GSF, rule tables. **Temporary**, replaced by `project_config` in P3.1/P3.2 |
| `cli.py` | `python -m engines.tvd` / `concho-tvd` |

The HTML/PDF dashboard is rendered by `dashboards/tvd/legacy_render.py` (unchanged copy of the
AutoTVD renderer, replaced in P7.1).

### Quantity rules (priority order)

1. **Fixed Quantity** in the cost DB always wins.
2. **Toilet count**: `C1030` = number of elements with an AC in `TOILET_ACS` (all categories,
   incl. excluded ones).
3. Clusters outside `TAKEOFF_CLUSTERS` (A–C) without a fixed quantity → 0.
4. **Quantity mirror** (`QUANTITY_MIRRORS`): take another AC's takeoff area, or its fixed quantity.
5. **Takeoff lookup** by unit: `SF`/`GSF` → Area, `MSF` → Area/1000, `LF` → Length,
   `EA`/`Flight` → count, `CY` → Volume/27, `CF` → Volume.

Before aggregation: elements with `DNC` in Family/Type/Mark/Comments are skipped, elements in
`EXCLUDE_CATEGORIES` don't contribute quantities, and `AC_KEYWORD_SPLIT` routes one AC to
sub-codes by keywords in Category + Family + Type (e.g. `B2010` → `B2010.CW` / `B2010.PW`).

## How to run

```bash
pip install -e .
concho-tvd --arch path/to/Architecture_TakeOff.csv \
           --struct path/to/Structural_Schedule.csv \
           --cost path/to/cost_data.csv \
           --out path/to/output            # or: python -m engines.tvd ...
```

| Flag | Meaning |
|---|---|
| `--arch`, `--struct`, `--cost` | input files (**required**, local paths only) |
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
| `Cluster Name` | must match the keys of `CLUSTER_TARGETS` (incl. the typo `Special Contruction`) |
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
- `tests/tvd/test_tvd_equivalence.py`: runs this engine and the original `tvd_analysis.py` on
  `AUTOTVD_DIR/qto/*.csv` + `AUTOTVD_DIR/cost_data.csv` and compares the results JSON (all fields
  except timestamps, label and paths), the history snapshot and the dashboard HTML. With the
  reference inputs it also checks grand total 16,065,644.29, `unmapped_count` 1693 and
  `dnc_count` 75. Skipped unless `AUTOTVD_DIR` is set:

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
