# agent

Concho agent: n8n workflows, prompts, chat memory, model configuration, the Discord bot and the `docker-compose` deployment bundle.

Design, flow, input contract and what is still untested: [`docs/agent.md`](../docs/agent.md). Deployment and local test on Windows: [`docs/agent-deployment.md`](../docs/agent-deployment.md). Evaluation: [`docs/agent-eval.md`](../docs/agent-eval.md).

- `workflows/concho.json`: the rebuilt workflow (data API tools only, project-neutral). Do not import it directly: `scripts/render_agent.py` fills the prompts and the webhook path first (`scripts/import_workflows.sh` does both).
- `workflows/error-handler.json`: global error workflow (details to the debug channel).
- `prompts/*.md`: prompts with `{{PROJECT_NAME}}`, `{{LOCATION}}`, `{{COMPLETION_DATE}}`, `{{TEAM}}` placeholders (P6.3); `common.md` holds the shared rules.
- `memory.sql`: the Postgres table of the chat memory (P6.4).
- `docker-compose.yml`, `Dockerfile.api`, `bot/`: n8n + Postgres + data API + Discord bot (P6.6).
- `.env.example`: every variable (models, memory, data API, webhook, Discord, n8n, Postgres); copy to `.env` in the repo root.
- `workflows/legacy/`: reference snapshot of the Island 2026 "Island AI Agent" workflow (P1.5), not for import by new teams; see its README.

```sh
cp agent/.env.example .env      # fill in, never commit
docker compose --env-file .env -f agent/docker-compose.yml up -d --build
bash scripts/import_workflows.sh
```

Without Docker, only the rendered files: `python scripts/render_agent.py --config path/to/team-repo/project_config.json` (writes `agent/build/`).
