# engines

Python package `engines` (installed as part of the `concho` distribution). Compute only: no HTML, no dashboards.

| Subpackage | Purpose | Filled by |
|---|---|---|
| `common/` | config loading, QTO parsing, units, Uniformat reference | P3.1, P3.4 |
| `tvd/` | Target Value Design cost engine, from AutoTVD | P1.3 |
| `stv/` | Sustainable Target Value engine, from `IPD_Challenge/src/STV_Engine` (canonical) | P1.2 |
| `schedule/` | takt zones, micro schedule, takt planner, deliveries (`core/`) + optional ALICE / Fuzor / Manufacton adapters, from IPD_Challenge. Exception to "no HTML": `viewers/` and the takt planner still write HTML until P3B.4 / P7.3 | P1.7, Phase 3B |

Course logic stays untouched here; team-specific logic belongs in config and mapping files (hard rule 6).
