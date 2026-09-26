# dashboards

Static TVD / STV / schedule pages that read the results JSON (no HTML generated in Python).

- `tvd/legacy_render.py`: the AutoTVD HTML/PDF dashboard, moved in P1.3 and called by
  `concho-tvd`. Since P3.2 the team name and GSF come from the project config (no hardcoded
  project strings). Temporary; replaced by a static page in P7.1.

Filled by: Phase 7.
