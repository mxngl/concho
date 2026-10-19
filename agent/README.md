# agent

Concho agent: n8n workflows, prompts, model configuration, conversation memory, and the
`docker-compose` deployment bundle with the Discord bot.

Design, flow, input contract, memory, bundle, evaluation and what is still untested:
[`docs/agent.md`](../docs/agent.md).

- `workflows/concho.json`: the rebuilt workflow (data API tools only, project-neutral, Postgres conversation memory). Do not import it directly: `scripts/render_agent.py` fills the prompts and the webhook path first (`scripts/import_workflows.sh` does it).
- `workflows/error-handler.json`: global error workflow (details to the debug channel).
- `prompts/*.md`: prompts with `{{PROJECT_NAME}}`, `{{LOCATION}}`, `{{COMPLETION_DATE}}`, `{{TEAM}}` placeholders (P6.3); `common.md` holds the shared rules.
- `sql/`: `memory.sql` (table `concho_chat_history`) and `memory_purge.sql` (30-day retention), P6.4.
- `docker-compose.yml`: n8n, Postgres, memory purge, the data API (`Dockerfile.api`, not exposed) and the Discord bot (`bot/`, profile `discord`), P6.6.
- `.env.example`: every variable (models, data API, webhook, Discord, n8n, Postgres, eval); copy to `agent/.env`.
- `workflows/legacy/`: reference snapshot of the Island 2026 "Island AI Agent" workflow (P1.5), not for import by new teams; see its README.

```sh
cp agent/.env.example agent/.env      # fill in, never commit
scripts/import_workflows.sh --dry-run --config path/to/team-repo/project_config.json
scripts/import_workflows.sh --config path/to/team-repo/project_config.json
python scripts/run_eval.py --repo path/to/team-repo      # P6.8, needs the bundle running
```
