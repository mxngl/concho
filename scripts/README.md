# scripts

Repo tooling.

- `check_forbidden.py`: fails if tracked files contain secrets, local paths or forbidden files (course workbooks, transcripts). Runs in CI. Under `agent/` it also fails on Discord snowflake IDs (17–20 digit numbers) unless the line uses a `$env` placeholder.
- `export_config_schema.py`: writes `docs/schema/project_config.schema.json` and the generated field reference in `docs/config.md` from `engines/common/config.py` (P3.1), and `docs/schema/cost_db.schema.json` from `engines/tvd/cost_db.py` (P3.4). `--check` fails if any is out of date; runs in CI.
- `run_pipeline.py` (P5.2, P5.5): the Tier-1 team pipeline (validate → TVD → STV → `results/` + `results/index.json` → site). Called by a team repo's `.github/workflows/pipeline.yml` (`template/`) and by `tests/pipeline/`; see [`docs/pipeline.md`](../docs/pipeline.md).
- `migrate_cost_data.py` (P3.4): converts an old AutoTVD `cost_data.csv` into the `cost_db.csv` format and validates the result (format and rules: [`docs/engines/tvd.md`](../docs/engines/tvd.md)). Never commit a converted RSMeans-derived file.
- `render_agent.py` (P6.3, P6.7): fills the agent prompts (`{{PROJECT_NAME}}`, `{{LOCATION}}`, `{{COMPLETION_DATE}}`, `{{TEAM}}`, from env or `project_config.json`) and the webhook path into `agent/workflows/*.json`, writes `agent/build/`. See [`docs/agent.md`](../docs/agent.md).
- `import_workflows.sh`, `n8n_credentials.py` (P6.6): start the agent bundle (`agent/docker-compose.yml`), create the n8n credentials from `agent/.env` (`concho-openai`, `concho-discord`, `concho-webhook-auth`, `concho-postgres`), import and activate the workflows. `--dry-run` shows the steps; only touches the n8n of the compose project.
- `eval_cases.py`, `run_eval.py` (P6.8): the question generator (templates in `tests/agent_eval/questions.yaml` + a data-API database -> cases with expected numbers computed by the API's own queries) and the runner/scorer that posts them to the webhook (numbers, language, latency, tool-response size; acceptance: >= 90 %, 0 overflows, p95 < 20 s). See [`docs/agent.md`](../docs/agent.md).
