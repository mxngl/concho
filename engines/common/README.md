# engines/common

Shared helpers used by all engines: project config loading, QTO (Revit export) parsing, unit conversions and the Uniformat reference list (`uniformat.csv`).

- `config.py` (P3.1): `project_config` schema (pydantic v2), loader and validation. Field reference and rules: [`docs/config.md`](../../docs/config.md); JSON Schema: [`docs/schema/project_config.schema.json`](../../docs/schema/project_config.schema.json). CLI: `concho config validate FILE`, `concho config schema`. The engines do not read the config yet (P3.2 / P3B.2).
- `examples/island_2026.project_config.json`: the Island 2026 values from the current engine defaults (`engines/tvd/island_defaults.py`, schedule README). Team data, not course data. `cost_db` and `macro_schedule` are left unset because the Island files are RSMeans-derived / private fixtures; the Discord entries are env var names only.

Still to come: P3.4 (Uniformat reference + cost DB validator).
