# tvd_synthetic

Tiny **invented** QTO exports and cost DB for the TVD unit tests (`tests/tvd/`).
All element IDs, quantities and unit costs are made up; nothing here comes from
RSMeans, the course workbooks or the Island project data.

- `arch.csv` (with a UTF-8 BOM) and `struct.csv`: AutoTVD QTO column layout
  (subset). Element `1020` is in both files (dedup: structural wins).
- `cost_db.csv`: AutoTVD `cost_data.csv` layout, incl. the header columns with
  trailing spaces and German/US number formats.
