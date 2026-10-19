# Deployment bundle (P6.6): n8n + Postgres + Discord bot + data API

`agent/docker-compose.yml` runs the whole Concho agent for **one team**. First real run (Max,
Windows 11, Docker Desktop, n8n 2.43.8, gpt-4o-mini, Island data): the bundle starts, the workflow
imports and answers, eval 40/45 = 88.9 %, p95 9.5 s, 0 overflows, memory follow-ups pass. That run
showed the problems fixed afterwards (webhook URL, Postgres version, prompts, see below); the
fixed bundle has **not been run again** and the Discord bot and thread are still untested (🟡).

```
 Discord ──▶ bot ──POST /webhook/<CONCHO_WEBHOOK_PATH>, X-Concho-Token──▶ n8n ──▶ OpenAI
              ▲  (ignores the response body)                              │  │
              └──────── n8n posts the reply into the channel/thread ◀─────┘  └▶ data-api (concho-api serve)
                                                  Postgres: n8n's database + chat memory ◀┘     │
                                                                                     team repo results/ (read-only)
```

| Service | Image | Reachable from | Notes |
|---|---|---|---|
| `postgres` | `postgres:17-alpine` | the compose network only | n8n's database and `concho_memory` ([`agent/memory.sql`](../agent/memory.sql), created on first start) |
| `data-api` | built from [`agent/Dockerfile.api`](../agent/Dockerfile.api) | the compose network only (`expose`, no `ports`) | `concho-api serve` on the team repo mounted read-only at `/data`; the SQLite database is in the `apidata` volume; bearer token `CONCHO_API_TOKEN`; it ingests new snapshots when it starts |
| `n8n` | `n8nio/n8n:2.43.8` (`N8N_VERSION`) | editor on `127.0.0.1:5678` only | the version the workflow was tested on; reads the settings the workflows use with `$env` |
| `bot` | built from [`agent/bot/`](../agent/bot/) | nobody (only outbound) | forwards messages of the ask channel(s) to the webhook; needs the *Message Content* intent |

Not exposed publicly: the data API and Postgres have no published port; the n8n editor is bound
to the loopback interface. The bot and n8n only open outbound connections (Discord, OpenAI). A
public webhook (hosting, D2) is not part of this bundle.

## Webhook URL

The Webhook node of `concho.json` has a fixed `webhookId`. Without one n8n registers the
production webhook at `/webhook/<workflow id>/<node name lowercased>/<path>` (here
`/webhook/concho-main/webhook/<path>`) instead of `/webhook/<path>`, and the bot and the eval,
which both use `/webhook/<CONCHO_WEBHOOK_PATH>`, got **HTTP 404** until the long URL was used.
The bot (`CONCHO_WEBHOOK_URL` in the compose file), `scripts/run_eval.py` and these docs use the
short URL. **The short URL is unverified until the fixed export is imported again and tested**:

```sh
bash scripts/import_workflows.sh        # same ids: updates the workflow, restarts n8n
curl -i -X POST -H "X-Concho-Token: $CONCHO_WEBHOOK_TOKEN" -H "Content-Type: application/json" \
  -d '{"content":"Hi","author_id":"t","channel_id":"t","source":"eval"}' \
  "http://localhost:5678/webhook/$CONCHO_WEBHOOK_PATH"      # expect 200 and a JSON reply, not 404
```

If an old import is still registered under the long URL (an n8n that keeps the old webhook
entry), deactivate and activate the workflow once, or restart n8n. An eval question that gets
HTTP 404 is reported as `transport error: HTTP 404, is the workflow active / webhook
registered?`, not as an agent error.

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

**Postgres version.** n8n 2.43.8 supports Postgres 17 and warned at start that 16 is outside its
supported range, so the bundle uses `postgres:17-alpine` (`agent/memory.sql` was re-checked on
17.5). An existing `pgdata` volume created by Postgres 16 does **not** start on 17. For local test
setups remove the volumes once and start again (this deletes n8n's database in it: owner account,
workflows, credentials, executions, and the chat memory; then create the owner account and run
`import_workflows.sh` again):

```sh
docker compose --env-file .env -f agent/docker-compose.yml down -v
docker compose --env-file .env -f agent/docker-compose.yml up -d --build
```

For a database that must be kept, `pg_dump` it from the old container and restore into the new
one instead.

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

Tested by Max on Windows 11 with Docker Desktop (route A). Two routes:

**A. Docker Desktop (recommended; the full bundle).**

0. Prerequisites, once: **virtualization must be on in the BIOS/UEFI** (SVM Mode on AMD CPUs,
   Intel VT-x on Intel; Task Manager > Performance > CPU shows "Virtualization: Enabled"), and
   WSL 2 must be installed: in an administrator PowerShell run `wsl --install`, then restart
   Windows. Then install Docker Desktop with the WSL 2 backend and start it (wait for "Engine
   running"). Without these Docker Desktop does not start.
1. In PowerShell from the repo root:

```powershell
copy agent\.env.example .env          # fill in with an editor; use / in paths: C:/Users/...
docker compose --env-file .env -f agent/docker-compose.yml up -d --build
docker compose -f agent/docker-compose.yml ps                # all four "running"/"healthy"
```

2. **Import in Git Bash** (comes with Git for Windows; `import_workflows.sh` is bash). On Windows
   `python3`/`python` can be the Microsoft Store stub, so name the interpreter (3.11+) with the
   Git-Bash form of its path:

```sh
PYTHON=/c/Users/<you>/AppData/Local/Programs/Python/Python312/python.exe bash scripts/import_workflows.sh
```

3. Open <http://localhost:5678> and **create the n8n owner account in the browser** (first start
   only; n8n asks for e-mail and password), check that the workflow "Concho" is active and has no
   red credential badge, and write in the Discord ask channel.
4. **A new OpenAI key with a spending limit** for this test: create a project key just for it
   (platform.openai.com > the project > Limits), set a monthly budget, and put the key only in
   `.env` (never in chat, an issue or a commit).

**Partial start without the Discord bot** (workflow and eval only, no bot token yet). The compose
file requires `DISCORD_BOT_TOKEN` for every service, even one that is not started, so give it a
dummy value for the command and start the three services; the replies of `source: eval` are never
posted to Discord, so nothing needs the real token:

```powershell
$env:DISCORD_BOT_TOKEN = "dummy"
docker compose --env-file .env -f agent/docker-compose.yml up -d --build postgres data-api n8n
```

(`DISCORD_BOT_TOKEN=dummy` in `.env` does the same; `import_workflows.sh` then creates the Discord
credential with it. Put the real token in later and run the import script again.)

**Run the eval from PowerShell.** `run_eval.py` reads `CONCHO_WEBHOOK_TOKEN` and
`CONCHO_WEBHOOK_PATH` from the environment, PowerShell does not read `.env`. Load it for the
session with this one-liner (skips comments and blank lines, strips quotes):

```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$($k.Trim())" ($v.Trim().Trim('"').Trim("'")) }
python scripts/build_eval_set.py --repo C:/path/to/team-repo
python scripts/run_eval.py
```

**A `project_config.json` from before PR #33 must lose `agent.models`.** The models are only in
the env now (`CONCHO_MODEL_*`). The pipeline and the data API refuse a config that still has the
key: `invalid project_config: agent.models: unknown field`. Delete the `models` entry under
`agent` in the team repo's `project_config.json` (the rest of `agent` stays), then run the
pipeline / restart the data API again.

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

## Checklist (Max): first run, and the re-test after the P6 follow-up PR

Items marked *re-test* are what the first real run could not show; the first run passed items 1-2
and 4-5 (except as noted).

1. `docker compose --env-file .env -f agent/docker-compose.yml config` is clean. *Re-test:* coming
   from the first run, `down -v` first (Postgres 16 volume, see above), `up -d --build`, create
   the owner account again, import again.
2. `up -d --build`: `postgres` (17) healthy, then `data-api` healthy (it ingests the team repo),
   `n8n` up without the "Postgres version" warning, `bot` logged in (`docker compose logs bot`).
3. `import_workflows.sh` ends with "done." and the workflow "Concho" is active. *Re-test:* the
   **short webhook URL** answers (the `curl` in "Webhook URL" above): HTTP 200 and JSON, not 404.
4. The Postgres credential works: ask a question, then
   `docker compose … exec postgres psql -U concho -c "select role, left(content, 60) from concho_memory"`
   shows two rows per answer. *Re-test:* stop the data API (`docker compose … stop data-api`), ask
   a question that needs data, start it again: the reply says the data is not reachable and
   `concho_memory` has **no** new row for that turn.
5. Ask a question and its follow-up in the ask channel; the reply appears in the channel or
   thread, with the snapshot line. *Re-test:* the bot and the thread (write in a thread of the ask
   channel); the reply must land in the thread.
6. `python scripts/build_eval_set.py …` and `python scripts/run_eval.py`
   ([`agent-eval.md`](agent-eval.md)), **twice** (LLM answers vary; the gates are ≥ 90 %, 0
   overflows, p95 < 20 s). The eval must work on the short URL; a 404 is reported as a transport
   error.
7. *Re-test:* the error output of an agent node (stop the data API and ask) answers with the
   readable message; the debug channel gets the details.
