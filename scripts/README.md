# scripts

Repo tooling.

- `check_forbidden.py`: fails if tracked files contain secrets, local paths or forbidden files (course workbooks, transcripts). Runs in CI. Under `agent/` it also fails on Discord snowflake IDs (17–20 digit numbers) unless the line uses a `$env` placeholder.
- `export_config_schema.py`: writes `docs/schema/project_config.schema.json` and the generated field reference in `docs/config.md` from `engines/common/config.py` (P3.1). `--check` fails if either is out of date; runs in CI.
