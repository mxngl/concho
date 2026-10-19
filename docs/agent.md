# Concho agent (workflow, prompts, models, memory, bundle, eval), Tier 1 (P6.2–P6.4, P6.6–P6.8)

The rebuilt Concho answers from the **data API** ([`data-api.md`](data-api.md)) only: no raw
files, no GitHub URLs, nothing project-specific in the workflow. Code and files:

| Path | What |
|---|---|
| [`agent/workflows/concho.json`](../agent/workflows/concho.json) | the n8n workflow "Concho" (37 nodes) |
| [`agent/workflows/error-handler.json`](../agent/workflows/error-handler.json) | global error workflow (`id` `concho-error-handler`) |
| [`agent/prompts/*.md`](../agent/prompts/) | prompts with `{{PLACEHOLDERS}}` (router, cost, carbon, quantity, general, fallback, shared rules in `common.md`) |
| [`agent/.env.example`](../agent/.env.example) | every variable the workflows, the bundle and the scripts read |
| [`agent/sql/`](../agent/sql/) | `memory.sql` (conversation memory table), `memory_purge.sql` (30-day retention) |
| [`agent/docker-compose.yml`](../agent/docker-compose.yml) | n8n, Postgres, memory purge, data API, Discord bot (profile `discord`) |
| [`agent/Dockerfile.api`](../agent/Dockerfile.api), [`agent/bot/`](../agent/bot/) | images of the data API and of the Discord bot |
| [`scripts/render_agent.py`](../scripts/render_agent.py) | fills prompts and webhook path for one team, writes `agent/build/` |
| [`scripts/import_workflows.sh`](../scripts/import_workflows.sh), [`scripts/n8n_credentials.py`](../scripts/n8n_credentials.py) | start the bundle, create the credentials from the env, import and activate the workflows |
| [`tests/agent_eval/questions.yaml`](../tests/agent_eval/questions.yaml), [`scripts/eval_cases.py`](../scripts/eval_cases.py), [`scripts/run_eval.py`](../scripts/run_eval.py) | the evaluation (P6.8) |
| `tests/agent/`, `tests/agent_eval/` | offline tests (workflow JSON, prompts, rendering, memory SQL, bundle, bot, scorer, generator) |

Scope is **Tier 1** (D13): cost, carbon, quantities, general/data questions. `SCHEDULE` is
recognised and answered with "not available in this version" (P6.5 follows with Tier 2).
Memory (P6.4), the deployment bundle (P6.6) and the evaluation harness (P6.8) are in the second
Phase-6 PR; the legacy workflow `agent/workflows/legacy/` and the live n8n "Island AI Agent" are
untouched and **not** replaced (roadmap rule 4): everything here targets the n8n of the
compose bundle.

## Flow

```
Webhook (POST, header auth, answers via "Respond to caller")
  ▶ Normalize input        one Set node: message, user_id, user_name, channel_id, guild_id,
  │                        message_id, source, attachments, session_id (user:channel)
  ▶ Load history           Postgres query, last 6 messages of this session (read only, P6.4)
  ▶ Router input           merge by position (message + history)
  ▶ Router                 agent + structured output {category, language}; chat model, no tools
  ▶ Router + context       merge by position (Router output + normalized fields)
  ▶ Classified             category (upper case, default OTHER), language
  ▶ Route (Switch)         COST | CARBON | QUANTITY | GENERAL | SCHEDULE | fallback = OTHER
       ├─ Cost Agent      get_cost_summary, get_cost_items, cost_what_if
       ├─ Carbon Agent    get_carbon_summary, get_carbon_items, carbon_what_if
       ├─ Quantity Agent  get_quantities, count_elements
       ├─ General Agent   get_cost_overview, get_carbon_overview, get_quality,
       │                  list_snapshots, compare_snapshots
       └─ Fallback Agent  no tools (SCHEDULE and OTHER)
       (every subagent has a Postgres Chat Memory: reads and stores the last 6 messages)
  ▶ Attach answer          merge by position (Classified + agent output)
  ▶ Compose reply ▶ Respond to caller ▶ Reply on Discord? ▶ Send reply (Discord)
every agent: error output ▶ Error reply (user-readable, de/es/pl/en) ▶ Compose reply
```

- **Input contract.** The caller (Discord bot, later Telegram, the eval) POSTs JSON to
  `/webhook/<CONCHO_WEBHOOK_PATH>` with the header `X-Concho-Token`:
  `content` (or `message`), `author_id` (or `user_id`), `author_name`, `channel_id`,
  optional `thread_id` (wins over `channel_id`: a Discord thread is a channel, so the reply
  lands in the thread), `guild_id`, `message_id`, `source` (default `discord`; the eval sends
  `eval` and gets no Discord post), `attachments`. Only `Normalize input` reads the webhook
  body; downstream nodes use `$json`, never `$('Node')`. Agent nodes drop the item's fields, so
  the two merge nodes carry the context through; nothing needs a node reference.
- **Router.** `COST|CARBON|QUANTITY|SCHEDULE|GENERAL|OTHER` as a JSON-schema enum in a
  Structured Output Parser; the Switch compares case-insensitively with a fallback output, so
  an unexpected value ends in OTHER instead of being dropped (legacy bug 3). Retry once on
  failure.
- **Subagents** (`maxIterations` 3 = 2 tool calls + the answer; the prompt says the same):
  only HTTP tools on the data API, `Authorization: Bearer $CONCHO_API_TOKEN`, URL
  `$CONCHO_API_URL`. "Never error" is on, so the API's `{"error": …, "hint": …}` bodies
  (including `too_many_results`, which is HTTP 200) reach the model. A test compares every
  tool's path and parameters with the OpenAPI schema of the real app.
- **Answer rules** (shared `common.md`): the user's language; only numbers from tool results;
  one closing line naming the snapshot; custom-material / proxy / estimated rows and what-if
  scenarios are labelled; on `too_many_results` ask the user to narrow (level, category,
  cluster, Assembly Code) instead of retrying; at most 1800 characters (Discord limit 2000).
  STV units are exactly the data's: kgCO2e, MJ, water in kg, ozone in kg CFC-11e.
- **Reply.** Discord node → `channel_id` of the normalizer (thread or channel), content
  `<@user_id> reply`. The webhook answers the caller first with
  `{reply, category, language, tools, tool_response_chars, failed}` (the eval reads this).
- **Errors.** Each agent has an error output → short readable message to the user. Anything
  else (Discord send, normalizer, …) runs the global error workflow, which posts workflow,
  node, message and execution link (no user text) to `DISCORD_CHANNEL_ID_DEBUG`.

## Prompts and rendering (P6.3)

Prompts are files with four placeholders: `{{PROJECT_NAME}}`, `{{LOCATION}}`,
`{{COMPLETION_DATE}}`, `{{TEAM}}`. The workflow holds `@@PROMPT:<name>@@` markers, prompts pull
in the shared rules with `@@INCLUDE:common@@`. At import time:

```sh
python scripts/render_agent.py --config path/to/team-repo/project_config.json   # -> agent/build/
```

Values come from `CONCHO_PROJECT_NAME` / `_LOCATION` / `_COMPLETION_DATE` / `_TEAM` if set,
else from `project.name`, `.location`, `.completion_date`, `.team_name` of the config. The
script also sets the webhook path from `CONCHO_WEBHOOK_PATH` (≥ 24 random characters) and
refuses values with `{{`, `}}`, `@@` or line breaks. `agent/build/` is git-ignored. The import
script of P6.6 imports from there. The rendered prompts contain no braces (braces break the
prompt template of the n8n agent).

A test fails if a prompt contains `Island`, `San Juan`, `Puerto Rico`, any course team name or
any project/team/location name found in the configs of this repo, an unknown placeholder, or
a unit other than MJ and kg for STV energy and water.

## Models (P6.7)

One place: the env (`agent/.env.example`). The chat-model nodes read it at run time, so a
change needs a restart of n8n only, no re-import:

| Variable | Used by | Default |
|---|---|---|
| `CONCHO_MODEL_ROUTER` | Router Model | `gpt-4o-mini` |
| `CONCHO_MODEL_SUBAGENT` | the five subagent models | `gpt-4o-mini` |
| `CONCHO_MODEL_TTS` | reserved for voice replies, no node uses it yet | `gpt-4o-mini-tts` |

Models are not in `project_config.json` (the `agent.models` block was removed in the second Phase-6 PR;
a config that still has it fails validation: delete the block).

## Memory (P6.4)

Follow-ups ("and on Level 2?") work because the last **6 messages per user and channel** are
persisted in Postgres and given to the model:

- **Table** `concho_chat_history` ([`agent/sql/memory.sql`](../agent/sql/memory.sql)): the layout of
  the n8n Postgres Chat Memory node (`id`, `session_id`, `message` JSON) plus `created_at`.
  Idempotent; Postgres creates it on first start (`docker-entrypoint-initdb.d`), the purge
  service re-applies it at every start (it also adds `created_at` if the n8n node created the
  table first).
- **Session** `session_id = <user_id>:<channel_id>` from `Normalize input` (a Discord thread is
  its own channel; nobody identified ⇒ `anon-<execution id>`, never one shared bucket).
- **Subagents** (all five) have a *Postgres Chat Memory* node on that session with the table
  above: they read and store the last 6 messages (the node counts question/answer pairs, so the
  context window is 3). All five share the session, so a follow-up routed to a different
  subagent still sees the conversation. Only the question and the final answer are stored,
  not tool results; the prompt (`common.md`, "FOLLOW-UPS") says earlier numbers are not a
  source: the follow-up calls the tool again.
- **Router** has *no* memory node (it would store its own JSON output). Instead `Load history`
  reads the same table with one query (last 6 rows of the session, newer than 30 days, one
  text block `User: … / Concho: …`) and `Router input` merges it with the message; the router
  prompt classifies the new message with that context. If the database is unreachable the
  query node continues with an empty history instead of stopping the answer.
- **Retention.** The `memory-purge` compose service deletes rows older than
  `CONCHO_MEMORY_RETENTION_DAYS` (default 30) once a day
  ([`memory_purge.sql`](../agent/sql/memory_purge.sql)); the router query also filters on age.
  Messages are personal data of chat users: they stay in your Postgres volume only.

## Deployment bundle (P6.6)

[`agent/docker-compose.yml`](../agent/docker-compose.yml) (project `concho`):

| Service | What | Reachable from |
|---|---|---|
| `postgres` | n8n's database and the memory table | the compose network only |
| `memory-purge` | daily retention delete | – |
| `data-api` | `concho-api serve` on `CONCHO_TEAM_REPO` (read-only mount), image from `agent/Dockerfile.api` | the compose network only (no port) |
| `n8n` | the workflows; port 5678 on `127.0.0.1` | this machine (`N8N_BIND_ADDRESS`) |
| `bot` (profile `discord`) | forwards Discord messages to the webhook, **ignores the response body** (n8n posts the reply) | outbound only |

Nothing is published to the internet. The bot calls `http://n8n:5678/webhook/<CONCHO_WEBHOOK_PATH>`
over the compose network with the header `X-Concho-Token`, and n8n's Discord node posts the reply
itself, so Discord needs no inbound connection. The bot (`agent/bot/bot.py`, discord.py)
forwards messages in `DISCORD_CHANNEL_ID_ASK` (and threads under it) and any @mention, sends the
input contract above (thread: `thread_id` + parent `channel_id`), shows "typing" while n8n works
and logs the HTTP status; it needs the *message content* intent in the Discord developer portal.

**Variables:** [`agent/.env.example`](../agent/.env.example) lists every variable (secrets are
empty; the model names and `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` keep their defaults).
`docker compose` and the import script read `agent/.env`.

**Credentials.** The workflows refer to four credentials by fixed id; `scripts/import_workflows.sh`
creates them from the env with `n8n import:credentials` (JSON through a pipe, never a file):

| Id | Type | From |
|---|---|---|
| `concho-openai` | OpenAI | `OPENAI_API_KEY` |
| `concho-discord` | Discord bot | `DISCORD_BOT_TOKEN` (empty ⇒ placeholder, Discord replies fail; fine for the eval) |
| `concho-webhook-auth` | Header auth `X-Concho-Token` | `CONCHO_WEBHOOK_TOKEN` |
| `concho-postgres` | Postgres | `POSTGRES_USER/_PASSWORD/_DB` (host `postgres`); **fourth credential, needed by the memory nodes** |

### Run it locally (Max)

```sh
cp agent/.env.example agent/.env      # fill: OPENAI_API_KEY, CONCHO_API_TOKEN, CONCHO_WEBHOOK_PATH (>= 24 random
                                      # chars), CONCHO_WEBHOOK_TOKEN, POSTGRES_PASSWORD, N8N_ENCRYPTION_KEY,
                                      # CONCHO_TEAM_REPO (a team repo / pipeline output with results/index.json);
                                      # CONCHO_EVAL_WEBHOOK_URL=http://127.0.0.1:5678/webhook/<CONCHO_WEBHOOK_PATH>
scripts/import_workflows.sh --dry-run --config path/to/team-repo/project_config.json   # shows the steps
scripts/import_workflows.sh --config path/to/team-repo/project_config.json             # does them
```

The script renders the prompts (`agent/build/`), starts postgres + data-api + n8n
(`up -d --build --wait`), creates the credentials, imports `error-handler.json` and
`concho.json`, activates them and restarts n8n. n8n asks for an owner account on first visit
(`http://127.0.0.1:5678`). It only touches the n8n of this compose project.

1. **Smoke test** (no Discord needed):
   ```sh
   curl -s -X POST "$CONCHO_EVAL_WEBHOOK_URL" -H "X-Concho-Token: $CONCHO_WEBHOOK_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"content":"What is the total project cost?","author_id":"u1","channel_id":"c1","source":"eval"}'
   ```
   Expect `{"reply": "...", "category": "COST", ...}`; no token ⇒ 403.
2. **Memory:** ask the same user/channel `How many <category> are on <level>?` and then
   `And on <other level>?`; the second answer must be about the other level. Restart the
   containers and ask another follow-up: the memory survives (Postgres volume).
   `docker compose -f agent/docker-compose.yml exec postgres psql -U concho -c 'select session_id, count(*) from concho_chat_history group by 1'`
3. **Eval:** `python scripts/run_eval.py --repo path/to/team-repo` (needs the same `CONCHO_API_TOKEN`
   data as the bundle; see below).
4. **Discord** (optional): set `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_CHANNEL_ID_ASK`
   and `_DEBUG`, then `docker compose -f agent/docker-compose.yml --env-file agent/.env --profile discord up -d`
   and ask in the channel and in a thread.

## Evaluation (P6.8)

```sh
python scripts/run_eval.py --repo path/to/team-repo --dry-run   # resolve the questions, no calls
python scripts/run_eval.py --repo path/to/team-repo --report eval.json
```

[`tests/agent_eval/questions.yaml`](../tests/agent_eval/questions.yaml) holds 49 question
templates (43 scored): cost, carbon, quantities, what-if (cost and material swap), general,
German / Spanish / Polish, follow-ups (the memory test), out-of-scope, and 6 **tier 2**
schedule questions that are listed and skipped until P6.5 and the schedule tables exist.

- **No number is typed.** The templates say *what* is asked (`{level_a}`, `{category_a}`,
  `ref: cost.grand_total`, ...). [`scripts/eval_cases.py`](../scripts/eval_cases.py) picks the
  slots from the data API database (largest first, so reruns are stable) and computes every
  expected number with the API's own query functions (`engines.api.queries`) on the snapshot the
  agent answers from. So the file holds no Island, course or RSMeans data; the resolved cases
  (`eval_cases.py --out`, git-ignored) do. A template that cannot be resolved (e.g. no STV data)
  is dropped and listed.
- **Scoring** ([`scripts/run_eval.py`](../scripts/run_eval.py)): each question runs in its own
  channel (a follow-up first asks its first question in that channel); the response of the
  workflow (`reply, category, language, tools, tool_response_chars, failed`) is checked for
  *numbers* (all expected numbers, or one of `any_of`, within 0.5 % for money/areas and exact for
  counts; sign ignored; `1,234.5`, `1.234,5`, `1 234,5`, `$1.2M`, `Mio.`, `mln` are understood),
  *language* (word-list heuristic for en/de/es/pl), *category*, *tools* (out-of-scope: none),
  *tool-response size* (over 24,000 chars = over the API cap = context overflow) and *no
  workflow error*. Latency is the wall time of the call.
- **Acceptance (roadmap P6.8):** ≥ 90 % correct, 0 context overflows, p95 latency < 20 s; the
  exit code is 0 only if all three hold (1 = not met, 2 = could not run).
- Limits: the language check is a heuristic; rounding like "16 million" for 16.08 M fails the
  0.5 % tolerance on purpose (the prompt asks for whole units); an ambiguous group like
  "1,234" is read both as 1234 and 1.234.

The harness itself is tested offline against a fake webhook (`tests/agent_eval/`): a good fake
agent passes, one without memory fails exactly the follow-ups, wrong numbers / oversized tool
responses / slowness fail.

## Credentials: see "Deployment bundle"

Until you run the import script, a hand-made import needs the same four ids/names
(`scripts/n8n_credentials.py --list`). `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` is required (`$env`
in expressions).

## What is tested offline, and what is not

Tested (`pytest tests/agent tests/agent_eval`, no n8n, no LLM): the JSON is valid and every connection points to
an existing node; every node is reachable; each agent has one model and exactly the intended
tools; no tool outside the data API; tools match the API's endpoints and parameters; no URL,
IP, token or Discord ID in the JSON; no node references; the router enum and the Switch cover
all categories with a fallback; every agent has an error branch; the reply goes to the
originating channel and mentions the user; models come from the env with the default; every
`$env` variable is in `.env.example`; prompts render and contain no project string.
Memory: five memory nodes on one session key and table, window 6 messages, the router has none
and reads through a SELECT-only query; the SQL files run twice on a real Postgres 16 (window,
30-day filter, session isolation, purge: `CONCHO_TEST_DATABASE_URL`, skipped without it).
Bundle: `docker compose config` (profiles, required variables), only n8n publishes a port and
only on 127.0.0.1, no secret in the compose file, every variable in `.env.example`, credentials
built from the env (ids and names read from the workflows), the import script's `--dry-run`
steps in order and no secret printed, bot logic (which messages, payload, response ignored).
Eval: scorer, question generator and runner against a fake webhook.

**Not tested here (needs a running n8n and an OpenAI key; Max to check):**

1. The JSON imports into n8n (node `typeVersion`s follow the legacy export: agent 3.1, OpenAI
   chat model 1.3, HTTP tool 4.4, Switch 3.4, Merge 3.2, Set 3.4; Structured Output Parser
   1.3, IF 2.2, Respond to Webhook 1.4, Discord 2 are new in this workflow).
2. The agent v3 node emits the parsed router result as `output.category`, and a Merge by
   position behaves as expected when only one route runs.
3. The error output of an agent carries the input item (so `Error reply` knows the channel).
4. `$fromAI` with an empty default sends an empty query parameter (the API ignores empty).
5. A Discord node posts into a **thread** when `channel_id` is a thread id.
6. `settings.errorWorkflow` = `concho-error-handler` is accepted for an imported workflow with
   that id.
7. Answers: language, numbers, snapshot line, labels, `too_many_results` handling (P6.8
   measures this: run `scripts/run_eval.py`, target >= 90 %, 0 overflows, p95 < 20 s).
8. Memory (P6.4): the Postgres Chat Memory node (typeVersion 1.3) accepts the parameters in the
   JSON; `{{ $json.session_id }}` resolves in its session key; a window of 3 gives 6 messages;
   the Postgres node (2.5) runs the history query with `queryReplacement`; a follow-up is
   answered for the other level (smoke test 2 above).
9. Bundle (P6.6): `docker compose up` builds the data-API image and starts everything healthy;
   `n8n import:credentials` accepts the plain JSON; `n8n update:workflow --all --active=true`
   works in the chosen n8n version (pin it with `N8N_VERSION`; the default is `latest`) and the
   webhook answers after the restart; the bot posts and n8n replies in a channel and a thread.
