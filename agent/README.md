# agent

Concho agent: n8n workflows, prompts, model configuration, chat memory, the Discord bot and the
`docker-compose` deployment bundle.

Design, flow, input contract, memory, deployment, evaluation and what is still untested: [`docs/agent.md`](../docs/agent.md).

- `workflows/concho.json`: the rebuilt workflow (data API tools only, project-neutral, Postgres chat memory). Do not import it directly: `scripts/render_agent.py` fills the prompts and the webhook path first (`scripts/import_workflows.sh` does that for you).
- `workflows/error-handler.json`: global error workflow (details to the debug channel).
- `prompts/*.md`: prompts with `{{PROJECT_NAME}}`, `{{LOCATION}}`, `{{COMPLETION_DATE}}`, `{{TEAM}}` placeholders (P6.3); `common.md` holds the shared rules.
- `memory.sql`: the chat-memory table and the 30-day purge function (P6.4).
- `docker-compose.yml`: n8n, Postgres, `memory-maintenance`, the Discord bot (`bot/`) and the data API (`api/`, `concho-api serve`, not published) (P6.6).
- `.env.example`: every variable (models, data API, webhook, Discord, Postgres, n8n, eval); copy to `agent/.env`.
- `workflows/legacy/`: reference snapshot of the Island 2026 "Island AI Agent" workflow (P1.5), not for import by new teams; see its README.

```sh
cp agent/.env.example agent/.env      # fill in, never commit
docker compose -f agent/docker-compose.yml --env-file agent/.env up -d --build
scripts/import_workflows.sh --config path/to/team-repo/project_config.json
python scripts/run_eval.py --repo path/to/team-repo      # P6.8
```
