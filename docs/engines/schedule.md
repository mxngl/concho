# Schedule engines

The schedule engines (`engines/schedule/`) turn Revit exports and an ALICE macro schedule
into a central BIM model with takt zones, an element-level micro schedule, a takt plan,
delivery analyses and the optional ALICE / Fuzor / Manufacton exports. The pipeline, its 15
steps, the inputs and the known findings are described in
[`engines/schedule/README.md`](../../engines/schedule/README.md).

## Golden test (P2.6)

`tests/schedule/test_schedule_golden.py` reruns all 15 steps (`python -m engines.schedule
<step>`) on the IPD_Challenge@989a6b7 inputs. The Island rules and BIM map come from
`engines/schedule/examples/island/` (byte-identical to the 989a6b7 copies). It compares
every output with `tests/fixtures/schedule_golden.json`:

- **Exit status per step.** `manufacton-orders` fails on this data (README finding 3), so
  its error line is pinned. `delivery-windows` therefore reads the committed Manufacton
  workbooks, as in the P1.7 equivalence test.
- **The set of output files** (44).
- **sha256 per file**, after the P1.7 masking: run-root paths, random P6 GUIDs and the
  relative FBX link. xlsx files are hashed by cell values. The 8 PNG charts only have to
  exist, because matplotlib rendering is not stable across machines.
- **Readable metrics per file**: rows and columns; tasks, first/last date, span in calendar
  days and weekdays; per-task start/end of the micro schedule; takt zones and hours; crew
  utilisation; delivery days and peak production orders per window; part and element counts.
  A metric failure prints `key: golden -> actual`.

No output files are committed. The reference is the JSON file, not the original scripts,
so the test keeps working after IPD_Challenge is archived: only its inputs are read, through
the P2.1 fixture. The test runs in the CI job `reference` (~50 s) and is skipped elsewhere.

The **current** `Micro_Schedule.csv` is the golden micro schedule. It is regenerated from the
current central BIM model: 6,625 rows, 37 tasks, 120 micro-task ids, 2,496 BIM elements,
2029-10-01 09:00 → 2030-03-15 19:40. The committed IPD_Challenge copy is stale (built from
an older BIM model) and stays a strict `xfail` in `test_schedule_equivalence.py`. The golden
`Macro_Schedule.csv` and `Takt_Schedule.csv` hashes are the roadmap §1 reference checksums
(`d267a9…`, `17fa80…`).

After an **intended** output change (for example a P3B refactor that fixes a finding),
regenerate the file and review the diff in the PR:

```bash
python scripts/fetch_fixtures.py
python tests/schedule/test_schedule_golden.py --update
git diff tests/fixtures/schedule_golden.json
```

**Mutation check** (2026-09-26). We changed the curing lag "Basement Retaining Walls →
Foundational Columns" in `examples/island/micro_schedule_rules.json` from 7 to 14 days.
9 of 95 tests failed:

- the metrics of `micro/Micro_Schedule.csv`: A1270 Foundational Columns, A1210 Grade Beams,
  A1240 Basement Slab on Grade and A1280 Rocking Walls move by +7 days (for example A1270
  2029-11-19 12:40 → 2029-11-26 12:40);
- the sha256 of the 7 files derived from the micro schedule: `Micro_Schedule.csv`,
  `ALICE_Task_Schedule.xml`, `ALICE_Task_Schedule_Macro_View.csv`, `Fuzor_Micro_Schedule.xml`,
  `Revit_4D_Build_Code_Map.csv`, `Micro_Schedule_Takt_Viewer.html` and
  `spatial_visualizer_micro.html`;
- `test_current_micro_schedule_is_golden_reference`.

The project start, the end date and the row counts did not change: this lag is not on the
critical path. The framing waits for the backfill chain. Without the per-task windows, only
the hashes would have caught the change.

## Island 2026 reference facts (regenerated run)

| Output | Value |
|---|---|
| Macro schedule (ALICE, `Macro_Schedule.csv`) | 37 tasks, 2029-10-01 09:00 → 2030-07-05 17:00 (278 calendar days, 200 weekdays) |
| Micro schedule | 6,625 rows, 37 tasks → 54 task × level activities (P6 / macro view), 2029-10-01 09:00 → 2030-03-15 19:40 (166 calendar days, 120 weekdays); without the Hurricane Contingency Buffer (A1880) it ends 2030-02-26 11:40 |
| Superstructure (A1330 Columns, A1350 Beams, A1340 Floor, A1420 Roof) | 2029-12-28 10:40 → 2030-01-03 10:40; Rocking Walls (A1280, bamboo) 2029-11-22 14:39 → 2029-11-26 16:00 |
| Close-out | Integrated Systems Testing ends 2030-02-18 15:40, Final Inspections end 2030-02-26 11:40 |
| Takt plan Level 1 (`--rooms-per-zone 2`) | 16 zones (32 rooms), 192.36 working hours, 2030-01-02 09:00 → 2030-01-23 12:21; utilisation: interior walls 100 %, interior finishes 93.2 %, MEP 63.9 %, doors 31.1 %, ceiling 28.2 % |
| Deliveries (601 production orders from the committed Manufacton workbooks) | peak orders per delivery: 1 day 44, 3 days 87, 1 week 155; delivery days 38 / 20 / 11 |
| Manufacton parts | 325 parts covering 2,481 elements |

## Island 2026 reference vs. presentation

The final Island deck is not in any repo; its values below come from the P2.6 task
description. "Current engine" means the regenerated run above. "Committed older output"
means files committed in IPD_Challenge@989a6b7 that the current code and model no longer
produce. They cannot be regenerated, so they only count as a trace, not as a reproduction.

| Deck value | File / engine value | Match? | Explanation |
|---|---|---|---|
| Start Oct 1, 2029 | Macro and micro schedule: 2029-10-01 09:00 | ✅ yes | ALICE project start. |
| End Mar 22, 2030 | Micro schedule: 2030-03-15 19:40 (end of the hurricane buffer). Committed stale micro schedule: also 2030-03-15. Committed older P6 XML / macro view: 2030-03-01 11:00. Macro (ALICE): 2030-07-05 | ❌ no | One week later than any file. **Not reproducible from the repo.** |
| ~24 weeks | Micro schedule: 166 calendar days = 23.7 weeks | ✅ approx. | Matches the file's Mar 15 end. The deck's own Mar 22 end would be 24.7 weeks. |
| Superstructure Nov 23, 2029 – Jan 3, 2030 | Columns / beams / floor / roof: 2029-12-28 → 2030-01-03 10:40. Rocking Walls (bamboo): from 2029-11-22 14:39 | 🟡 partly | The end matches. The start fits only if the bamboo rocking walls count as superstructure, and then it is Nov 22 afternoon, not Nov 23. Nov 22, 2029 is Thanksgiving, and the engine calendar has no holidays. The exact Nov 23 is **not reproducible from the repo**. |
| Substantial completion Feb 21, 2030 | Integrated Systems Testing ends 2030-02-18. Final Inspections end 2030-02-26 11:40 (then the buffer starts) | ❌ no | No task ends on Feb 21. **Not reproducible from the repo.** |
| Schedule 246 → 177 days | Macro 278 → micro 166 calendar days (200 → 120 weekdays). Without the buffer: 260 → 149 calendar days | ❌ no | Neither number appears in any output. Unconfirmed coincidence: 2029-10-01 → 2030-06-04 (end of MEP Rough-In in the macro schedule) is 246 calendar days apart and has 177 weekdays. **Not reproducible from the repo.** |
| 41 % saved | 1 − 166/278 = 40.3 % (calendar days); 1 − 120/200 = 40.0 % (weekdays) | 🟡 approx. | Close to the engine's reduction. It does not follow from the deck's own numbers: 1 − 177/246 = 28 %. |
| 32 tasks → 48 parallelized tasks | Committed older `ALICE_Task_Schedule_Macro_View.csv` / `ALICE_Task_Schedule.xml`: 32 tasks → 48 activities (task × level). Current engine: 37 tasks → 54 activities | ✅ committed older output, ❌ current engine | The deck used an older run. The committed macro view lacks the close-out tasks (A1820–A1880) and ends 2030-03-01; it is older than the committed stale micro schedule (37 tasks). The Fuzor template has 33 tasks (32 without the buffer). |
| 3,106 parts | Committed older macro view: 3,122 elements in the 48 activities, minus 16 non-BIM Basement / Site activities of 1 element each = **3,106 BIM elements**. Current engine: 2,496 BIM elements in the micro schedule; 325 Manufacton parts covering 2,481 elements | ✅ committed older output, ❌ current engine | "Parts" means scheduled BIM elements, not Manufacton parts. The current model has fewer scheduled elements. |
| Takt Level 1: 16 zones, 192.36 h | `Takt_Schedule.csv`: 16 zones, 192.36 h | ✅ yes | Byte-identical to the §1 reference, with `--rooms-per-zone 2`. |
| Delivery windows 155 / 87 / 44 assemblies (1 / 3 / 7 days) | `production_order_count_by_delivery_window.csv`: peak production orders per delivery **1 day 44, 3 days 87, 1 week 155** (601 orders) | 🟡 numbers yes, labels no | The deck pairs the values with the windows in reverse order: 155 is the weekly peak and 44 the daily peak. The unit is production orders (distinct order ids per delivery), not assemblies. The values come from the committed Manufacton workbooks, because `manufacton-orders` fails on the 989a6b7 data. |
| 43 % / 72 % | 1 − 87/155 = 43.9 %, 1 − 44/155 = 71.6 % | ✅ yes | Peak reduction from weekly to 3-day and to daily deliveries. The 43 % is truncated; rounded it would be 44 %. |
