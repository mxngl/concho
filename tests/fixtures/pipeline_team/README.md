# pipeline_team

**Invented** data for the team-pipeline tests (`tests/pipeline/`, P5.2): tiny Revit exports in
the add-in's file naming and a 5-row cost DB. Every ElementId, quantity and unit cost is made
up; nothing comes from RSMeans, the course workbooks or the Island project.

The tests copy `template/` into a temporary team repo and put these files on top.

- `exports/Demo_ARCH_Architecture_TakeOff.csv`: walls (C1010, B2010), one floor (B1010) and a
  `DNC` wall that TVD skips.
- `exports/Demo_STR_Structural_Schedule.csv`: two footings (A1010) and floor `5004`, which is
  also in the architecture export (counted once).
- `exports/Demo_MEP_MEP_TakeOff.csv`: two copper pipes (STV only).
- `cost_db.csv`: one takeoff row per code plus a fixed lump sum.

Expected TVD grand total: 27 × 2 × 20 (footings) + 1,000 × 15 (floor) + 720 × 40 (facade)
+ 600 × 10 (partitions) + 1,000 (lump sum) = **51,880.00**.
