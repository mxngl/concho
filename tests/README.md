# tests

pytest suite. Run with `pytest`.

`tests/agent/` and `tests/agent_eval/` test the Concho agent bundle and the eval harness offline (no n8n, LLM or Docker daemon needed); see `docs/agent.md`.

Only non-sensitive fixtures go under `tests/fixtures/`. Tests that need course workbooks or RSMeans-derived data read a local path from an env var and are skipped when it is unset.

## Reference fixtures (Island 2026)

Equivalence and golden tests against the original repos need their files (AutoTVD, AutoSTV, IPD_Challenge). They contain course workbooks and RSMeans-derived cost data, so they live in the **private** repo `mxngl/concho-fixtures` (a snapshot of exactly the files the tests read, same layout as the original repos) and are never committed here:

```bash
python scripts/fetch_fixtures.py   # clones mxngl/concho-fixtures into .fixtures/ at the pinned commit
pytest
```

- **Access.** Max and Ash: plain `git` with your own GitHub login is enough (credential helper / `gh auth login`). CI and scripts: set `CONCHO_FIXTURES_TOKEN` (fine-grained PAT, read-only on `concho-fixtures`; the Actions secret of the same name); the script uses it for the clone only and never prints or stores it. Without access the script says so and exits 0, the tests that need fixtures are skipped; with `CONCHO_REQUIRE_FIXTURES=1` (or a token set) it exits 1.
- **Pin and checks.** The commit is `private.commit` in `tests/fixtures/checksums.json`. The script verifies every entry of the snapshot's `MANIFEST.json` and the roadmap §1 / P2.3 checksums in `checksums.json`; any mismatch is fatal.
- **Fixture root** is `CONCHO_FIXTURES_DIR` (default `.fixtures/`); the folder itself is the clone. A folder that holds the old public clones must be deleted first (or use `--dest`). `AUTOTVD_DIR` (TVD, P1.3) and `IPD_CHALLENGE_DIR` (IPD_Challenge@989a6b7, STV golden and schedule engines, P1.7) override single checkouts. With `CONCHO_REQUIRE_FIXTURES=1` (CI jobs `reference`, `reference-pandas3`) a missing fixture fails instead of skipping.
- **Old way, until roadmap P1.6:** `python scripts/fetch_fixtures.py --source public` clones the three public repos at their pinned refs. Only needed to build the snapshot.

### Updating the private snapshot (Max/Ash)

Needed when a test starts reading another fixture file, or the reference state changes. The list of files is `SNAPSHOT_FILES` in `scripts/build_fixture_snapshot.py` (recorded by tracing every file the full suite opens, including those the original AutoTVD/IPD scripts read).

```bash
python scripts/fetch_fixtures.py --source public --dest ../concho-fixtures-public   # the three original repos (outside this repo)
python scripts/build_fixture_snapshot.py --src ../concho-fixtures-public --out ../concho-fixtures-snapshot
cd ../concho-fixtures-snapshot
git init -b main && git add -A && git commit -m "Island 2026 fixtures"
git remote add origin https://github.com/mxngl/concho-fixtures.git && git push -u origin main
git rev-parse HEAD   # paste into private.commit in tests/fixtures/checksums.json
```

Test a fresh push before pinning it with `python scripts/fetch_fixtures.py --private-commit <sha> --dest /tmp/fx`. **Never** copy the snapshot folder into this repo.

## Course-equivalence tests (course workbooks)

These compare the engines with the course workbooks, which are course data and never committed (roadmap §0, hard rule 2). Each test is skipped unless its env var points to a local copy:

| Env var | Workbook | Tests |
|---|---|---|
| `COURSE_STV_XLSX` | `CEE_222_STV_V12.xlsx` | STV step of the team pipeline in `tests/pipeline/test_pipeline.py` (P5.2; without the workbook the tests check that STV is skipped with a note), `tests/stv/test_stv_course_equivalence.py` (P2.4, P3.10; P3.7 custom material, P3.8 filled use phase incl. PV via `project_config`), `tests/stv/test_stv_course_workbook.py` (P1.2), catalog checks of the shipped tables in `tests/stv/test_stv_default_mapping.py` (P3.6) |
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
