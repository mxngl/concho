# tests

pytest suite. Run with `pytest`.

Only non-sensitive fixtures go under `tests/fixtures/`. Tests that need course workbooks or RSMeans-derived data read a local path from an env var and are skipped when it is unset.

## Reference fixtures (Island 2026)

Equivalence and golden tests against the original repos need their checkouts:

```bash
python scripts/fetch_fixtures.py   # clones AutoTVD, AutoSTV, IPD_Challenge into .fixtures/
pytest
```

The fixture root is `CONCHO_FIXTURES_DIR` (default `.fixtures/`); `AUTOTVD_DIR` (TVD, P1.3) and `IPD_CHALLENGE_DIR` (IPD_Challenge@989a6b7, STV golden and schedule engines, P1.7) override single checkouts. With `CONCHO_REQUIRE_FIXTURES=1` (CI job `reference`) a missing fixture fails instead of skipping.

## Course-equivalence tests (course workbooks)

These compare the engines with the course workbooks, which are course data and never committed (roadmap §0, hard rule 2). Each test is skipped unless its env var points to a local copy:

| Env var | Workbook | Tests |
|---|---|---|
| `COURSE_STV_XLSX` | `CEE_222_STV_V12.xlsx` | `tests/stv/test_stv_course_equivalence.py` (P2.4, P3.10), `tests/stv/test_stv_course_workbook.py` (P1.2) |
| `COURSE_TVD_XLSX` | `PBL_Lab_TVD-collaboration_tool.xlsx` | `tests/tvd/test_tvd_course_equivalence.py` (P2.5), `tests/tvd/test_tvd_course_method.py` (P3.5: targets, owner reallocation, reliability) |

**Prerequisite: LibreOffice Calc** (`soffice` on the `PATH`) for the two `*_course_equivalence.py` files and parts of `test_tvd_course_method.py` (`test_stv_course_workbook.py` only reads the workbook). They write the inputs into a temporary copy of the workbook and recalculate it headless (`soffice --headless --convert-to xlsx`). Install e.g. `sudo apt-get install libreoffice-calc` (Debian/Ubuntu) or `brew install --cask libreoffice` (macOS). Without `soffice` the tests are skipped; if `soffice` is there but cannot convert (Calc component missing) they fail with the LibreOffice output.

```bash
export COURSE_STV_XLSX=/path/to/CEE_222_STV_V12.xlsx
export COURSE_TVD_XLSX=/path/to/PBL_Lab_TVD-collaboration_tool.xlsx
pytest tests/stv/test_stv_course_equivalence.py tests/tvd/test_tvd_course_equivalence.py \
       tests/tvd/test_tvd_course_method.py -s
```

`-s` shows the max. relative error per case.

Filled by: Phase 2 (golden and course-equivalence tests), and every later task.
