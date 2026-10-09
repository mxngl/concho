# agent

Concho agent: n8n workflows, prompts, model configuration; the Discord bot and the
`docker-compose` deployment bundle follow (P6.6).

Design, flow, input contract and what is still untested: [`docs/agent.md`](../docs/agent.md).

- `workflows/concho.json`: the rebuilt workflow (data API tools only, project-neutral). Do not import it directly: `scripts/render_agent.py` fills the prompts and the webhook path first.
- `workflows/error-handler.json`: global error workflow (details to the debug channel).
- `prompts/*.md`: prompts with `{{PROJECT_NAME}}`, `{{LOCATION}}`, `{{COMPLETION_DATE}}`, `{{TEAM}}` placeholders (P6.3); `common.md` holds the shared rules.
- `.env.example`: every variable (models, data API, webhook, Discord); copy to `.env`.
- `workflows/legacy/`: reference snapshot of the Island 2026 "Island AI Agent" workflow (P1.5), not for import by new teams; see its README.

```sh
cp agent/.env.example .env      # fill in, never commit
python scripts/render_agent.py --config path/to/team-repo/project_config.json   # -> agent/build/
```
