# tests

pytest suite. Run with `pytest`.

Only non-sensitive fixtures go under `tests/fixtures/`. Tests that need course workbooks or RSMeans-derived data read a local path from an env var (e.g. `CONCHO_FIXTURES_DIR`, `COURSE_STV_XLSX`) and are skipped when it is unset.

Filled by: Phase 2 (golden and course-equivalence tests), and every later task.
