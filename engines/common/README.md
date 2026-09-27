# engines/common

Shared helpers used by all engines: project config loading, QTO (Revit export) parsing, unit conversions and the Uniformat reference list (`uniformat.csv`).

- `config.py` (P3.1): `project_config` schema (pydantic v2), loader and validation. Field reference and rules: [`docs/config.md`](../../docs/config.md); JSON Schema: [`docs/schema/project_config.schema.json`](../../docs/schema/project_config.schema.json). CLI: `concho config validate FILE`, `concho config schema`. Read by `concho-tvd --config` and `concho-stv --config` (P3.2); the schedule engines follow in P3B.2.
- `examples/island_2026.project_config.json`: the Island 2026 values (formerly hardcoded in the TVD engine and dashboard, schedule README). With it, the TVD and STV golden/equivalence tests reproduce the Island reference numbers. Team data, not course data. `cost_db` and `macro_schedule` are left unset because the Island files are RSMeans-derived / private fixtures; the Discord entries are env var names only.

- `uniformat.csv` (P3.4): UNIFORMAT II levels 1–3 from NISTIR 6389 (public domain; source in the file header). `uniformat_extensions.csv`: the course's cluster H codes (`H1000`–`H5000`) with our own titles and an `origin` column; not NIST, not copied from course data. `uniformat.py`: loader and code checks (sub-codes via their base code, course 4-digit form of level-2 codes such as `F1000` by rule). Used by the cost DB validator (`engines/tvd/cost_db.py`, `concho costdb validate`); format in [`docs/engines/tvd.md`](../../docs/engines/tvd.md).
