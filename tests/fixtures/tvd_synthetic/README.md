# tvd_synthetic

Tiny **invented** QTO exports and cost DB for the TVD unit tests (`tests/tvd/`).
All element IDs, quantities and unit costs are made up; nothing here comes from
RSMeans, the course workbooks or the Island project data.

- `arch.csv` (with a UTF-8 BOM) and `struct.csv`: AutoTVD QTO column layout
  (subset). Element `1020` is in both files (dedup: structural wins).
- `cost_db.csv`: `cost_db.csv` format (P3.4, see `docs/engines/tvd.md`) with the rules
  `takeoff`, `fixed` (with and without quantity), `mirror:` (source in the takeoff, source
  with a fixed quantity, source missing), `count_codes:` and a keyword split
  (`B2010.CW` / `B2010.PW`). One row (`B1010`) has no unit cost and no ratings. Until P3.4
  this file used the old AutoTVD `cost_data.csv` layout; the numbers are unchanged.
