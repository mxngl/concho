# Deployment bundle (P6.6): n8n + Postgres + Discord bot + data API

`agent/docker-compose.yml` runs the whole Concho agent for **one team**. Nothing in it has been
started on a real Docker host or against a real n8n / OpenAI / Discord yet (🟡): it is
validated with `docker compose config`, static tests and a stub run of the import script.

```
 Discord ──▶ bot ──POST /webhook/<CONCHO_WEBHOOK_PATH>, X-Concho-Token──▶ n8n ──▶ OpenAI
              ▲  (ignores the response body)                              │  │
              └──────── n8n posts the reply into the channel/thread ◀─────┘  └▶ data-api (concho-api serve)
                                                  Postgres: n8n's database + chat memory ◀┘     │
                                                                                     team repo results/ (read-only)
```

| Service | Image | Reachable from | Notes |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | the compose network only | n8n's database and `concho_memory` ([`agent/memory.sql`](../agent/memory.sql), created on first start) |
| `data-api` | built from [`agent/Dockerfile.api`](../agent/Dockerfile.api) | the compose network only (`expose`, no `ports`) | `concho-api serve` on the team repo mounted read-only at `/data`; the SQLite database is in the `apidata` volume; bearer token `CONCHO_API_TOKEN`; it ingests new snapshots when it starts |
| `n8n` | `n8nio/n8n:2.43.8` (`N8N_VERSION`) | editor on `127.0.0.1:5678` only | the version the workflow was tested on; reads the settings the workflows use with `$env` |
| `bot` | built from [`agent/bot/`](../agent/bot/) | nobody (only outbound) | forwards messages of the ask channel(s) to the webhook; needs the *Message Content* intent |

Not exposed publicly: the data API and Postgres have no published port; the n8n editor is bound
to the loopback interface. The bot and n8n only open outbound connections (Discord, OpenAI). A
public webhook (hosting, D2) is not part of this bundle.

## Variables

[`agent/.env.example`](../agent/.env.example) lists every variable; secrets are empty there.
`cp agent/.env.example .env` in the repo root (git-ignored) and fill in:

| Needed for | Variables |
|---|---|
| prompts | `CONCHO_PROJECT_CONFIG` (path to the team's `project_config.json`), or `CONCHO_PROJECT_NAME/_LOCATION/_COMPLETION_DATE/_TEAM` |
| data API | `CONCHO_API_TOKEN` (generate), `CONCHO_DATA_REPO` (folder of the team repo with `results/`) |
| webhook | `CONCHO_WEBHOOK_PATH` (≥ 24 random characters), `CONCHO_WEBHOOK_TOKEN` |
| OpenAI | `OPENAI_API_KEY` |
| Discord | `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_CHANNEL_ID_ASK`, `DISCORD_CHANNEL_ID_DEBUG` |
| n8n / Postgres | `N8N_ENCRYPTION_KEY` (generate once, keep it), `POSTGRES_PASSWORD` |
| optional | models (`CONCHO_MODEL_*`), memory (`CONCHO_MEMORY_*`), `N8N_VERSION`, `N8N_PORT`, `GENERIC_TIMEZONE` |

Values must be shell-safe (the import script sources the file): generated tokens are.

## Start

```sh
cp agent/.env.example .env                                    # fill in
docker compose --env-file .env -f agent/docker-compose.yml up -d --build
bash scripts/import_workflows.sh                              # see below
```

`import_workflows.sh` (needs bash and Python 3.11+ on the host):

1. renders prompts and webhook path into `agent/build/` (`scripts/render_agent.py`);
2. builds the credentials from the env (`scripts/build_n8n_credentials.py`) into a temp file with
   mode 600, streams it into the container, runs `n8n import:credentials`, deletes it: the four
   credentials `concho-openai`, `concho-discord`, `concho-webhook-auth`, `concho-postgres`
   (the fourth belongs to the memory, P6.4; without `POSTGRES_PASSWORD` it is skipped);
3. `n8n import:workflow` for `concho-error-handler` and `concho-main` (fixed ids, so a second run
   updates instead of duplicating; it never touches a workflow with another id, e.g. the live
   "Island AI Agent");
4. `n8n publish:workflow --id=concho-main` (falls back to `update:workflow --active=true`),
   then restarts n8n so the webhook is registered. If the CLI cannot activate, it says so: open
   the editor, check the credentials on the nodes and switch the workflow to Active.

No secret appears on a command line or stays on disk (checked by `tests/agent/`).

When the pipeline of the team repo produced new results, restart the data API
(`docker compose -f agent/docker-compose.yml restart data-api`) so it ingests them.

## Try it without a team repo

The invented pipeline fixtures give a small, real `results/` (TVD only; STV needs the course
workbook, so carbon questions are skipped by the eval):

```sh
cp -r template ../demo-team
cp tests/fixtures/pipeline_team/exports/* ../demo-team/exports/
cp tests/fixtures/pipeline_team/cost_db.csv ../demo-team/
python scripts/run_pipeline.py run --repo ../demo-team
# .env: CONCHO_DATA_REPO=../demo-team   (an absolute path is safer on Windows)
```

For the Island data use the team repo of Island with its `results/`, then run the eval
([`agent-eval.md`](agent-eval.md)).

## Local test on Windows (for Max)

Docker Desktop is not installed yet. Two routes:

**A. Docker Desktop (recommended; the full bundle).** Install Docker Desktop with the WSL 2
backend, start it, then in PowerShell from the repo root:

```powershell
copy agent\.env.example .env          # fill in with an editor; use / in paths: C:/Users/...
docker compose --env-file .env -f agent/docker-compose.yml up -d --build
docker compose -f agent/docker-compose.yml ps                # all four "running"/"healthy"
bash scripts/import_workflows.sh                              # Git Bash or WSL
```

The script is bash: use Git Bash (comes with Git for Windows) or a WSL shell with Docker
integration. Then open <http://localhost:5678>, create the owner account, check that the workflow
"Concho" is active and has no red credential badge, and write in the Discord ask channel.
`python scripts/run_eval.py` works from PowerShell as well.

**B. `npx n8n` without Docker (workflow only, no bot, no memory).** Good enough to test the
workflow with the eval:

```powershell
# terminal 1: data API on the team repo
pip install -e ".[api]"
$env:CONCHO_API_TOKEN = "<token>"
concho-api serve --repo C:/path/to/team-repo
# terminal 2: n8n (Node 22 LTS), the settings the workflow reads
$env:N8N_BLOCK_ENV_ACCESS_IN_NODE = "false"; $env:CONCHO_API_URL = "http://127.0.0.1:8000"
$env:CONCHO_API_TOKEN = "<token>"; $env:CONCHO_WEBHOOK_PATH = "<24+ random chars>"
npx n8n
# terminal 3 (Git Bash, same variables exported): import and activate
bash scripts/import_workflows.sh --local        # runs `npx n8n import:...` on this machine
```

Without Postgres (`POSTGRES_PASSWORD` unset) the memory nodes fail softly: Concho answers
without history, so the follow-up questions of the eval fail. Everything else works. Restart
`npx n8n` after the import so the webhook is registered; the URL is
`http://localhost:5678/webhook/<CONCHO_WEBHOOK_PATH>`.

*Known problem on this route (reported by Max, not reproduced here):* with npm 11, `npx n8n` /
`npm install n8n` can fail because npm no longer runs the install script of dependencies by
default, so the native `sqlite3` module is not built or downloaded and n8n cannot open its
database. Allow the install script for `sqlite3` (the *allow scripts* setting of npm 11: see
`npm help` for your version, typically in `.npmrc` or on the command line) and install again; or
use Node 22 LTS with npm 10, where install scripts run. Check the exact setting name on your npm
before relying on it. Docker (route A) avoids the problem.

## Checklist for the first run (Max)

1. `docker compose --env-file .env -f agent/docker-compose.yml config` is clean on your machine (it passed here with dummy values; Docker itself could not run).
2. `up -d --build`: `postgres` healthy, then `data-api` healthy (it ingests the team repo),
   `n8n` up, `bot` logged in (`docker compose logs bot`).
3. `import_workflows.sh` ends with "done." and the workflow "Concho" is active. If
   `import:credentials` rejects the plain-text file, or `publish:workflow` does not exist in
   your n8n, paste the error into the PR: both are untested here.
4. The Postgres credential works: ask a question, then
   `docker compose … exec postgres psql -U concho -c "select role, left(content, 60) from concho_memory"`
   shows two rows per answer.
5. Ask a question and its follow-up in the ask channel; the reply appears in the channel or
   thread, with the snapshot line.
6. `python scripts/build_eval_set.py …` and `python scripts/run_eval.py`
   ([`agent-eval.md`](agent-eval.md)).
7. Not yet tested by anyone: the error output of an agent node (stop the data API and ask) and
   the reply inside a Discord thread (write in a thread of the ask channel).
