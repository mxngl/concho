# TVD engine

The Target Value Design (TVD) engine (`engines/tvd/`) prices the Revit quantity takeoff with
a cost DB (unit cost × quantity per Uniformat subcode), sums the line items per cluster and
compares them with the cluster targets from `project_config`. Usage (CLI, inputs, outputs,
tests) is in [`engines/tvd/README.md`](../../engines/tvd/README.md); the config fields and the
cluster target check (P3.3) are in [`docs/config.md`](../config.md).

## Cost DB format: `cost_db.csv` (P3.4)

The engine reads one cost DB per project: `files.cost_db` of `project_config` (or `--cost`).
It is **validated before the run**: errors stop the engine, warnings are printed and written
to the `cost_db_validation` block of the results JSON (see below). The old AutoTVD
`cost_data.csv` is not read by the engine any more; convert it with
`scripts/migrate_cost_data.py` (below).

> ⚠️ Cost DBs with RSMeans-derived unit costs (like the Island one) are licensed data and are
> never committed. The repo only has the empty template (`template/cost_db.csv`), an invented
> example (`template/examples/cost_db.example.csv`) and invented test rows.

One CSV row per cost line item, UTF-8, comma-separated, header row with these names (order
free). Lines starting with `#` are comments; blank lines are skipped. Row numbers in messages
are file line numbers (header = row 1 when there are no comments above it). JSON Schema of one
row: [`docs/schema/cost_db.schema.json`](../schema/cost_db.schema.json) (pydantic model
`CostDbRow` in `engines/tvd/cost_db.py`; `concho costdb schema`).

| Column | Required | Content |
|---|---|---|
| `cluster` | yes | course cluster letter or name (`B`, `Shell`, case-insensitive; legacy `Special Contruction` is read as `Special Construction` with a warning), or a custom cluster from `tvd.custom_clusters` |
| `assembly_code` | yes | Uniformat code (see "Codes"), or a sub-code `B2010.CW` |
| `group` | – | group label (free text) |
| `description` | yes¹ | line item description |
| `unit` | yes¹ | `SF`, `GSF`, `MSF`, `LF`, `EA`, `FLIGHT`, `CY`, `CF` (takeoff units), `SY`, `STORY`, `LS`, `TON`, `LB`, `GAL`, `HR`, `DAY`, `WEEK`, `MONTH`, `%` (only `pct_of_subtotal`); case-insensitive |
| `unit_cost` | – | cost per unit, **plain decimal** (`1670000.00`); empty = unpriced (priced 0, warning) |
| `quantity_rule` | yes | see "Quantity rules" |
| `quantity_value` | rule | plain decimal: the quantity (`fixed`), factor (`per_gsf`), percent (`pct_of_subtotal`); empty otherwise |
| `qty_reliability`, `cost_reliability` | – | **1 = high, 2 = medium, 3 = low** (course scale, cluster sheets rows 26–28 in 'A Substructure', `M26:M28`); empty = not rated (warning; used by the reliability summary, see below) |
| `source` | – | where the unit cost comes from (free text) |
| `split_keywords` | – | sub-code rows only, see "Keyword split" |
| `qty_label` | – (optional column) | label shown as the quantity source (`qty_src`) instead of the engine's generic label |

¹ Not required for a **placeholder row**: `description`, `unit` and `unit_cost` all empty
(a code that has no price yet). It is priced 0, reported as a warning and listed as
`unpriced` in the results JSON.

Plain decimals: digits with an optional `.` and decimals. No currency symbol, no thousands
separator, no decimal comma, no negative values: `6184.22`, `25`, `1670000.00` are valid;
`$6.184,22`, `1,000.00`, `25,00` are errors.

### Quantity rules

| `quantity_rule` | Quantity | Generic `qty_src` label |
|---|---|---|
| `takeoff` | takeoff quantity of the row's code, by unit: `SF`/`GSF` area, `MSF` area/1000, `LF` length, `EA`/`FLIGHT` count, `CY` volume/27, `CF` volume. Only takeoff units are allowed. | `Area (SF)`, `Length (LF)`, …, `No takeoff match` |
| `fixed` | `quantity_value` (empty = 0, warning). Lump sums: unit `LS`/`EA`, quantity 1. | `Fixed`, `Fixed (no quantity set)` |
| `per_gsf` | `project.gross_sf` × `quantity_value` (empty = 1) | `GSF × 1` |
| `pct_of_subtotal` | `quantity_value` % of the subtotal = sum of all other (non-`pct_of_subtotal`) line totals. Unit `%`, `unit_cost` empty; the line gets `qty` = percent and `unit_cost` = 1 % of the subtotal. | `5 % of subtotal` |
| `mirror:<AC>` | the takeoff quantity of `<AC>` for this row's unit; if `<AC>` is not in the takeoff, the `fixed` quantity of an `<AC>` row; else 0. No chains (a mirror of a mirror is an error). | `Mirror: C1010 area`, `Mirror: B1020 (Fixed)`, `Mirror source B1010 not in takeoff` |
| `count_codes:<AC,...>` | number of takeoff elements with one of these codes, **all categories** (also the excluded `Furniture`) | `Count of codes (D2010)` |

`quantity_rule` replaces the AutoTVD tables that were hardcoded in the engine until P3.4:
takeoff only for clusters A–C (→ explicit `takeoff`/`fixed` per row), `QUANTITY_MIRRORS`
(→ `mirror:`), `TOILET_ACS` (→ `count_codes:D2010` on the C1030 row), `AC_KEYWORD_SPLIT`
(→ `split_keywords`) and the GC/contingency lump sums (→ `fixed` rows). The engine keeps
only the DNC marker and the excluded categories (`engines/tvd/rules.py`).

Notes on the line items: `No unit cost` for an empty `unit_cost`; for `takeoff` rows also
`Zero qty from takeoff` and `AC not in takeoff`.

**Several lines with the same code** (e.g. A2020 with two SF lines and one LF line) each get
the **full** takeoff quantity of that code for their own unit: both SF lines get the whole
A2020 area, the LF line the whole A2020 length. Quantities are not divided between the lines
(same as AutoTVD). Use a keyword split (sub-codes) if elements of one code must go to
different lines.

**`qty_label`**: when set, it replaces the generic label for every run of that row. Use it
only for rules whose label does not depend on the takeoff (`fixed`, `per_gsf`,
`count_codes`, `pct_of_subtotal`); on `takeoff`/`mirror` rows it would hide outcomes such as
`No takeoff match` (warning). The migration sets it to the old AutoTVD wording for the
Island rows (`Toilet elements (D2010)`, `Fixed only (none set)`), so no Island wording lives
in the engine. The legacy dashboard shows the "fixed" badge only for `qty_src` = `Fixed`.

### Keyword split

A sub-code row (`<base>.<suffix>`, e.g. `B2010.CW`) with `split_keywords` routes takeoff
elements of the base code to the sub-code: keywords are `|`-separated and matched
case-insensitively against Category + Family + Type; `*` catches everything not matched by
another sub-code of that base. Sub-codes are tried in file order, the `*` sub-code last;
first match wins. Without a `*` sub-code, unmatched elements keep the base code. Rows of the
same sub-code must have the same keywords; one `*` per base code.

```csv
cluster,assembly_code,group,description,unit,unit_cost,quantity_rule,quantity_value,qty_reliability,cost_reliability,source,split_keywords,qty_label
Shell,B2010.CW,Exterior Walls,Invented curtain wall,SF,150.00,takeoff,,2,2,invented,storefront|curtain wall|glazing,
Shell,B2010.PW,Exterior Walls,Invented plaster wall,SF,15.00,takeoff,,2,2,invented,*,
```

### Codes

`engines/common/uniformat.csv` is UNIFORMAT II levels 1–3 from NISTIR 6389 (public domain,
source in the file header). A cost DB code is valid when its base code (sub-codes are checked
through it) is

- a level-3 code (`B2010`),
- the course's 4-digit form of a level-2 code (`B2000` = `B20`, `F1000` = `F10`), by rule, or
- listed in `engines/common/uniformat_extensions.csv`: codes the course uses beyond NIST
  (cluster H: `H1000`–`H5000`), our own titles, column `origin` (`course` / `concho`).
  Not NIST, not copied from course data.

For course clusters A–H the code's letter must match the cluster (`B2010` in `Shell`).
Custom clusters (not A–H, e.g. `Equipment Rental` with `I1000`) skip the code check with one
warning per cluster; with a config (engine, `--config`) a cluster that is neither a course
cluster nor in `tvd.custom_clusters` is an error.

### Examples

```csv
cluster,assembly_code,group,description,unit,unit_cost,quantity_rule,quantity_value,qty_reliability,cost_reliability,source,split_keywords,qty_label
Interiors,C1010,Partitions,Invented gypsum partition,SF,12.50,takeoff,,1,2,invented,,
Interiors,C3010,Wall Finishes,Invented wall paint,SF,1.80,mirror:C1010,,1,2,invented,,
Interiors,C1030,Fittings,Invented toilet partition,EA,950.00,count_codes:D2010,,2,2,invented,,
Services,D5010,Electrical Service & Distribution,Invented electrical,GSF,20.00,per_gsf,,3,3,invented,,
General Conditions,H4000,General Conditions,Invented site overhead,LS,250000.00,fixed,1,2,3,invented,,
General Conditions,H5000,Contingency,Invented design contingency,%,,pct_of_subtotal,5,3,3,invented,,
Substructure,A1020,Special Foundations,,,,takeoff,,,,,,
```

The last row is a placeholder. More: `template/examples/cost_db.example.csv`.

### Validation

```bash
concho costdb validate cost_db.csv [--config project_config.json]  # exit 0 = valid, 1 = errors
concho costdb schema                                                # JSON Schema of one row
```

From Python: `engines.tvd.cost_db.validate_cost_db_file(path, custom_clusters=...)` (returns
errors, warnings, `unpriced`, `not_rated`, `mislabels`) or `load_cost_db(path)` (raises
`CostDbError` with all errors).

| Check | Result |
|---|---|
| Old AutoTVD header; missing, unknown or duplicated column; more cells than columns | error |
| `cluster` empty; unknown non-course cluster (with a config) | error |
| `assembly_code` empty, malformed, not in the reference list (message suggests the closest codes), letter ≠ cluster | error |
| `description` / `unit` empty (not a placeholder), unknown unit | error |
| number not a plain decimal or negative | error |
| reliability not 1, 2, 3 | error |
| duplicate (`cluster`, `assembly_code`, `group`, `description`), case- and whitespace-insensitive, also two identical placeholders | error |
| unknown rule, wrong syntax, `mirror:` of its own code or of a mirror, target neither in the reference list nor in the cost DB | error |
| `quantity_value` on `takeoff`/`mirror:`/`count_codes:`; `takeoff`/`mirror:` with a non-takeoff unit; `pct_of_subtotal` without percent in (0, 100], without unit `%` or with `unit_cost`; unit `%` on another rule | error |
| `split_keywords` on a non-sub-code row, `*` mixed with keywords, different keywords for one sub-code, two `*` sub-codes of one base | error |
| placeholder row; empty `unit_cost`; `fixed` without quantity | warning |
| reliability not rated (one warning per column, with the rows) | warning |
| custom cluster (code check skipped; one per cluster); legacy cluster spelling | warning |
| `D` code whose description names another D group (e.g. D5030 "Fire Protection Systems" → D40, D5090 "HVAC Systems" → D30); the code is kept | warning |
| sub-code without keywords (takeoff 0); base code row while a `*` sub-code takes all its elements; `qty_label` on `takeoff`/`mirror:`; `count_codes` with a unit other than `EA`/`LS`; a code listed twice | warning |

Results JSON (`cost_db_validation`, after `target_consistency`):

| Key | Meaning |
|---|---|
| `status` | `ok` (no warnings) or `warnings` (errors stop the run) |
| `rows`, `error_count`, `warning_count` | counts |
| `warnings` | the warning messages |
| `unpriced` | `[{row, cluster, assembly_code}]`: rows without `unit_cost` (incl. placeholders) |
| `not_rated` | `{qty_reliability: n, cost_reliability: n}`: rows without a rating |

### Migration from AutoTVD `cost_data.csv`

```bash
python scripts/migrate_cost_data.py OLD_cost_data.csv NEW_cost_db.csv [--config project_config.json]
```

Numbers become plain decimals (German `$6.184,22` and US `$1,000.00` formats); a fixed
quantity → `fixed` (the Island GC and contingency rows: `fixed`, quantity 1, exact old unit
costs); `C1030` → `count_codes:D2010`; clusters outside A–C without a fixed quantity →
`fixed` without quantity; the old mirrors → `mirror:`; everything else → `takeoff`; the old
B2010 split → `split_keywords`; `qty_label` keeps the old labels where the generic ones
differ; `Special Contruction` → `Special Construction`. Codes are kept, including the Island
D5030/D5090 mislabels (listed as warnings), so the Island results stay reproducible. The
script validates the new file (exit 1 on errors). Never commit the converted Island file.

Island 2026 (reference test, converted into a temporary folder): 48 rows, **0 errors,
8 warnings** (3 placeholders A1020/C3030/F1000, custom cluster Equipment Rental, both
reliability columns not rated, D5030 and D5090 mislabels), no exact duplicates; the TVD run
on it reproduces the AutoTVD results (grand total 16,065,644.29, unmapped 1693, DNC 75).

## Cent rounding of line totals (P3.10 item 4)

The engine rounds each **line total to cents when it computes it**, and every sum is built
from those rounded values. The course workbook (`PBL_Lab_TVD-collaboration_tool.xlsx`) does
not round.

Where it happens:

| Step | Code | What is rounded |
|---|---|---|
| line items | `engines/tvd/quantities.py`, `calculate_costs()` | `total = round(qty × unit_cost, 2)`, computed from the **unrounded** quantity; the stored `qty` is rounded to 2 decimals (display only, not used for the total) |
| cluster summary, grand total | `engines/tvd/summary.py`, `build_cluster_summary()` | nothing new: sums of the already rounded line totals |
| results JSON | `engines/tvd/results_writer.py` | `round(…, 2)` of the line totals, estimates, targets, deltas, $/SF (no-op for the sums of cents) and `round(qty, 4)` |
| history snapshots, dashboard, budget alert | `engines/tvd/history.py`, `dashboards/tvd/legacy_render.py`, `engines/tvd/alert.py` | read the rounded line totals |

Consequences:

- Each line differs from the course's unrounded `quantity × Total O&P` (cluster sheets,
  column T) by at most half a cent; cluster and summary sums accumulate those differences.
  The P2.5 course-equivalence test (`tests/tvd/test_tvd_course_equivalence.py`) therefore
  shows a max. relative deviation of about **1e-7** (9.6e-8 in P2.5), inside its 1e-6
  tolerance. It is not a formula difference.
- A line's `qty × unit_cost` recomputed from the results JSON can differ from its `total` by
  a cent or so, because `qty` is stored rounded.

**Decision (P3.10):** the stored results stay rounded as they are. The Island reference
(grand total 16,065,644.29) and the AutoTVD equivalence test (`test_tvd_equivalence.py`,
identical results JSON, history snapshot and dashboard) depend on this rounding;
rounding only for display would change stored totals by fractions of a cent and break that
comparison. Revisit only together with a new Island reference.

## Course workbook bug found in P2.5

`TVD Summary` C25 ("C3030 Ceiling Finishes") references `'B Shell'!T30` (B3010 Roof
Coverings) instead of the C Interiors sheet, so the course summary counts B3010 twice and
drops C3030. The cluster sheets are right and match the engine; the engine does not copy
the summary bug. The course-equivalence test compares the summary on a case without
B3010/C3030 and pins the bug on a second case. Reporting it to the course is roadmap P3.10
item 6 (Max).
