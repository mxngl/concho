# TVD engine

The Target Value Design (TVD) engine (`engines/tvd/`) prices the Revit quantity takeoff with
a cost DB (unit cost × quantity per Uniformat subcode), sums the line items per cluster and
compares them with the cluster targets from `project_config`. Usage (CLI, inputs, outputs,
tests) is in [`engines/tvd/README.md`](../../engines/tvd/README.md); the config fields and the
cluster target check (P3.3) are in [`docs/config.md`](../config.md).

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
