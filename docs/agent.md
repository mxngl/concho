# Concho agent (n8n workflow, prompts, memory, deployment bundle, eval), Tier 1 (P6.2 to P6.4, P6.6 to P6.8)

The rebuilt Concho answers from the **data API** ([`data-api.md`](data-api.md)) only: no raw
files, no GitHub URLs, nothing project-specific in the workflow. Code and files:

| Path | What |
|---|---|
| [`agent/workflows/concho.json`](../agent/workflows/concho.json) | the n8n workflow "Concho" (37 nodes) |
| [`agent/workflows/error-handler.json`](../agent/workflows/error-handler.json) | global error workflow (`id` `concho-error-handler`) |
| [`agent/prompts/*.md`](../agent/prompts/) | prompts with `{{PLACEHOLDERS}}` (router, cost, carbon, quantity, general, fallback, shared rules in `common.md`) |
| [`agent/.env.example`](../agent/.env.example) | every variable the workflows, scripts and compose bundle read (secrets empty) |
| [`agent/memory.sql`](../agent/memory.sql) | chat-memory table + 30-day purge function (P6.4) |
| [`agent/docker-compose.yml`](../agent/docker-compose.yml), [`agent/bot/`](../agent/bot/), [`agent/api/`](../agent/api/) | the deployment bundle: n8n, Postgres, Discord bot, data API (P6.6) |
| [`scripts/render_agent.py`](../scripts/render_agent.py) | fills prompts and webhook path for one team, writes `agent/build/` |
| [`scripts/import_workflows.sh`](../scripts/import_workflows.sh), [`scripts/agent_credentials.py`](../scripts/agent_credentials.py) | creates the n8n credentials from `.env`, imports and activates the workflows (P6.6) |
| [`tests/agent_eval/questions.yaml`](../tests/agent_eval/questions.yaml), [`scripts/run_eval.py`](../scripts/run_eval.py) | the evaluation harness (P6.8) |
| `tests/agent/`, `tests/agent_eval/` | offline tests (workflow JSON, prompts, rendering, memory, bundle, bot, eval scorer and question generator) |

Scope is **Tier 1** (D13): cost, carbon, quantities, general/data questions. `SCHEDULE` is
recognised and answered with "not available in this version" (P6.5 follows with Tier 2).
Memory (P6.4), the deployment bundle (P6.6) and the evaluation harness (P6.8) are described
below. The legacy workflow `agent/workflows/legacy/` is untouched and **not** replaced in n8n
(roadmap rule 4): everything here runs in a separate, new n8n (the compose bundle).

## Flow

```
Webhook (POST, header auth, answers via "Respond to caller")
  ▶ Normalize input        one Set node: message, user_id, user_name, channel_id, guild_id,
  │                        message_id, source, attachments, session_id (memory key)
  ▶ Router                 agent + structured output {category, language}; chat model, no tools;
  │                        Postgres chat memory (own session: the earlier questions + categories)
  ▶ Router + context       merge by position (Router output + normalized fields)
  ▶ Classified             category (upper case, default OTHER), language
  ▶ Route (Switch)         COST | CARBON | QUANTITY | GENERAL | SCHEDULE | fallback = OTHER
       ├─ Cost Agent      get_cost_summary, get_cost_items, cost_what_if
       ├─ Carbon Agent    get_carbon_summary, get_carbon_items, carbon_what_if
       ├─ Quantity Agent  get_quantities, count_elements
       ├─ General Agent   get_cost_overview, get_carbon_overview, get_quality,
       │                  list_snapshots, compare_snapshots
       └─ Fallback Agent  no tools (SCHEDULE and OTHER)
  ▶ Attach answer          merge by position (Classified + agent output)
  ▶ Compose reply ▶ Respond to caller ▶ Reply on Discord? ▶ Send reply (Discord)
every subagent: Postgres chat memory (last 6 messages of this user in this channel/thread)
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

`agent.models` was **removed** from `project_config.json` (schema, examples, template, docs
and tests): the file is committed per team, a model name there would be a second place that
nothing reads. Config files that still carry `agent.models` now fail validation with
"agent.models: unknown field": delete the key.

## Memory (P6.4)

A follow-up such as "and on Level 2?" needs the previous question. Every agent has an n8n
**Postgres Chat Memory** node on table `concho_chat_history` ([`agent/memory.sql`](../agent/memory.sql)):

- **Key:** `concho:<thread id or channel id>:<user id>` (`session_id`, built in `Normalize input`),
  so each user has their own conversation per channel, and a Discord thread is its own
  conversation. If the channel or the user is missing the key is `nomemory:<execution id>`: no
  shared bucket. The five subagents share the key, so a follow-up works across topics (a cost
  answer, then a carbon follow-up); the router uses the key plus `:router` (its history is the
  earlier questions with the categories it gave them, the subagents' answers do not mix into it).
- **Window:** the last **6 messages** = 3 question/answer pairs (`contextWindowLength` 3; n8n counts
  pairs). Tool calls and tool results are not stored, only the chat text, so the window stays small
  and numbers are fetched again (the prompt says so: "Numbers from earlier answers are not a
  source").
- **Retention:** 30 days. The memory node cannot filter by age, so the service
  `memory-maintenance` of the compose bundle applies `memory.sql` at start (idempotent) and calls
  `concho_purge_chat_history()` once a day (`CONCHO_MEMORY_RETENTION_DAYS`, default 30).
  `memory.sql` was run against PostgreSQL 16 (table, indexes, purge at 31 / 29 days, run twice).
- **Privacy:** the table holds chat text of team members for 30 days (n8n's execution log is pruned
  after the same time). Mention it in the team's data note (P8.1 "Data and privacy").

## Deployment bundle (P6.6)

```
                       127.0.0.1:5678 (editor, /webhook/…)
Discord ◀──────────────────────┐
   │ messages                  │ n8n posts the reply
   ▼                           │
discord-bot ──POST /webhook/<path> + X-Concho-Token──▶ n8n ──▶ OpenAI
(default network)              (default + backend)       │
                                                         ▼  (internal network, no outbound)
                                       postgres ◀── n8n DB + chat memory      data-api (concho-api serve)
                                       memory-maintenance (schema + daily purge)   team repo :ro + SQLite volume
```

| Service | What | Notes |
|---|---|---|
| `postgres` | `postgres:16-alpine` | n8n's database and `concho_chat_history`; volume `postgres-data` |
| `memory-maintenance` | `postgres:16-alpine` + `psql` | applies `memory.sql`, purges daily |
| `n8n` | `docker.n8n.io/n8nio/n8n:${N8N_VERSION}` | **no default version on purpose**: set the release the workflows were tested on; port published on 127.0.0.1 only |
| `discord-bot` | [`agent/bot/bot.py`](../agent/bot/bot.py) (discord.py) | only POSTs to the webhook and **ignores the response body**; n8n posts the reply |
| `data-api` | `concho-api serve --repo /team --db /db/concho.db`, image built from this repo | team repo mounted read-only; ingests new snapshots at start; no `ports:`; SQL endpoint off |

The `backend` network is `internal` (no route to the internet) and holds Postgres, the data
API and n8n; the bot is only on the default network. n8n reaches the API as
`http://data-api:8000` with `CONCHO_API_TOKEN`. Telemetry is off, executions are pruned after
30 days.

**Bot.** It listens in the channel(s) of `DISCORD_CHANNEL_ID_ASK` (comma separated; threads of
them too) and ignores bots, itself and empty messages. Payload: `content`, `author_id`,
`author_name`, `channel_id`, `thread_id` (in a thread, with `channel_id` = the parent), `guild_id`,
`message_id`, `source: discord`, `attachments` (file names and URLs). Ids are strings. The bot
needs the *Message Content* intent. It was written for this bundle from the contract above (the
bot of Island's VPS is not in the repo).

**Variables.** All in [`agent/.env.example`](../agent/.env.example); compose refuses to start when a
required one is empty (`${VAR:?…}`). New ones: `N8N_VERSION`, `N8N_ENCRYPTION_KEY`, `N8N_PORT`,
`POSTGRES_USER` / `_PASSWORD` / `_DB`, `CONCHO_TEAM_REPO` (host path of the team repo the API
serves), `DISCORD_CHANNEL_ID_ASK`, `CONCHO_MEMORY_RETENTION_DAYS`, `CONCHO_EVAL_URL`.

**Import script.** `scripts/import_workflows.sh [--env-file F] [--config project_config.json]
[--dry-run]`: renders prompts and webhook path (`render_agent.py`) → creates the credentials
(`import:credentials`, secrets via stdin into a `0600` file in the container that is deleted
right after) → imports `error-handler.json`, then `concho.json` (ids `concho-error-handler`,
`concho`; re-running replaces them) → `update:workflow --id=concho --active=true` → restarts
n8n. It only addresses the compose project, never another n8n.

### Local test (Max)

```sh
pip install -e ".[dev]"
# 1. a team repo with results/ (the invented demo: TVD only, no STV, so carbon questions are
#    "unavailable"; use the Island team repo for the full set)
DEMO=$(mktemp -d)/demo-team
cp -r template "$DEMO" && cp -r tests/fixtures/pipeline_team/exports/. "$DEMO/exports/" \
  && cp tests/fixtures/pipeline_team/cost_db.csv "$DEMO/"
(cd "$DEMO" && python /path/to/concho/scripts/run_pipeline.py run --repo .)
# 2. configuration
cp agent/.env.example agent/.env      # fill in: OPENAI_API_KEY, tokens, N8N_VERSION, CONCHO_TEAM_REPO=$DEMO …
# 3. start, import
docker compose -f agent/docker-compose.yml --env-file agent/.env up -d --build
scripts/import_workflows.sh --config "$DEMO/project_config.json"
# 4. ask (source "eval": no Discord post)
curl -s -X POST "http://127.0.0.1:5678/webhook/$CONCHO_WEBHOOK_PATH" \
  -H "X-Concho-Token: $CONCHO_WEBHOOK_TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":"What is the total project cost?","author_id":"u1","channel_id":"c1","source":"eval"}'
# 5. the follow-up in the same chat (same author_id + channel_id), then the eval
python scripts/run_eval.py --repo "$DEMO"
```

`docker compose … config` (with dummy values) validates the file offline; it is part of the tests
when the Docker CLI is installed.

## Evaluation (P6.8)

[`tests/agent_eval/questions.yaml`](../tests/agent_eval/questions.yaml): **54 questions**, 50 runnable
and 4 schedule questions marked `tier: 2` (skipped until P6.5): cost, carbon, quantities, what-if
(cost and material swap), general (overview, snapshots, data quality, compare), **DE / ES / PL**
(10 multilingual questions, plus a German follow-up pair and a Spanish out-of-scope one), **follow-ups** (4 pairs: quantity by level, cost by cluster, German, carbon by
assembly) and out-of-scope (4, must not call a tool).

The file holds **no numbers**. It has *entities* (the biggest cluster, the two levels with most
walls, the top material …) and *facts* (the expected value) as SQL on the data API's database, and
`api:` recipes for the scenarios, which call `engines/api/queries.py` (the code behind the agent's
tools) so a what-if is computed, not typed. [`scripts/eval_questions.py`](../scripts/eval_questions.py)
resolves the file for one snapshot; a question that cannot be built from it (no STV result, no
second snapshot, an expected value of 0) is *unavailable* and not scored. The project's own names
are therefore filled in at run time and nothing course- or RSMeans-derived is in the repo.

```sh
concho-api ingest --repo path/to/team-repo                   # (run_eval --repo does it too)
python scripts/run_eval.py --repo path/to/team-repo --generate-only   # review questions + numbers
python scripts/run_eval.py --repo path/to/team-repo          # run against the webhook
```

[`scripts/run_eval.py`](../scripts/run_eval.py) posts each question (`source: eval`, one user,
one channel per chat; follow-ups in the same chat, in order), one at a time, and scores
([`scripts/eval_scoring.py`](../scripts/eval_scoring.py)):

- **numeric match:** every expected number must appear, in any en/de/es/pl notation
  (`16,081,484` / `16.081.484` / `16 081 484` / `16.1 million` / `16,1 Mio.`); amounts within 1 %,
  counts exact; dates and the question's own names ("Level 2") are removed first, so they cannot
  satisfy a small count by accident;
- **language match:** stop-word / diacritic detection of the reply must equal the question's language;
- **tools:** a question with a number must call a tool (a number from the chat history does not
  count), an out-of-scope question must call none;
- **latency** (p95) and **tool-response size**: a *context overflow* is a tool response over
  24,000 characters (the data API's cap of 8,000 tokens at 3 characters per token);
- routing (router category) is reported separately and does not fail a question.

Acceptance (P6.8): ≥ 90 % correct, 0 overflows, p95 < 20 s; exit code 1 otherwise. The report
(`eval-report.json`, git-ignored) holds the answers: do not commit it.

## Credentials (created by the import script, not part of the export)

The workflows refer to four credentials by fixed id: `concho-openai` (OpenAI API key),
`concho-discord` (Discord bot token), `concho-webhook-auth` (header `X-Concho-Token`) and
`concho-postgres` (the chat-memory nodes; **a fourth credential, needed because n8n's Postgres
Chat Memory node cannot work without one**). `scripts/import_workflows.sh` creates all four from
`agent/.env`. `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` is required (`$env` in expressions) and set by
the compose file.

## What is tested offline, and what is not

Tested (`pytest tests/agent tests/agent_eval`, no n8n, no LLM, no Docker daemon): the JSON is
valid and every connection points to an existing node; every node is reachable; each agent has
one model, exactly the intended tools and one Postgres memory with the 6-message window and the
right session key; no tool outside the data API; tools match the API's endpoints and parameters;
no URL, IP, token or Discord ID in the JSON; no node references downstream of the normalizer; the
router enum and the Switch cover all categories with a fallback; every agent has an error branch;
the reply goes to the originating channel and mentions the user; models come from the env with the
default; every `$env` variable is in `.env.example` and passed to the n8n container; prompts
render and contain no project string. Bundle: compose services, networks (data API and Postgres
internal, only n8n published and only on 127.0.0.1), required variables, `docker compose config`
(when the CLI exists), the bot (payload, thread handling, ids as strings, no reply path, body
ignored), the import script against stand-ins for `docker` and `n8n` (order, credentials via stdin
with `0600`, no secret on a command line, `--dry-run` masks secrets), `memory.sql` (statically, and
once by hand on PostgreSQL 16). Eval: the scorer (notations, languages, dates, overflow, p95,
acceptance), the question file (40+ runnable, groups, languages, no typed numbers) and the generator
on invented data (including unavailable and skipped questions), and `run_eval.py` end to end
against a stand-in agent over HTTP.

**Not tested here (needs a running n8n, an OpenAI key, Docker, Discord; Max to check).** Steps 1
to 7 are PR 1's list, 8 to 14 are new:

1. The JSON imports into n8n (node `typeVersion`s follow the legacy export: agent 3.1, OpenAI
   chat model 1.3, HTTP tool 4.4, Switch 3.4, Merge 3.2, Set 3.4; Structured Output Parser
   1.3, IF 2.2, Respond to Webhook 1.4, Discord 2, **Postgres Chat Memory 1.3** are new in this
   workflow).
2. The agent v3 node emits the parsed router result as `output.category`, and a Merge by
   position behaves as expected when only one route runs.
3. The error output of an agent carries the input item (so `Error reply` knows the channel).
4. `$fromAI` with an empty default sends an empty query parameter (the API ignores empty).
5. A Discord node posts into a **thread** when `channel_id` is a thread id.
6. `settings.errorWorkflow` = `concho-error-handler` is accepted for an imported workflow with
   that id.
7. Answers: language, numbers, snapshot line, labels, `too_many_results` handling (P6.8
   measures this).
8. **Memory:** the Postgres Chat Memory node uses the existing `concho_chat_history` table (it
   creates its own table only if missing; our extra `created_at` column must not disturb its
   insert), sends exactly 6 messages (3 pairs) and `sessionKey` expressions resolve in the
   sub-node (`$json.session_id`). Check in the table after two questions; then "and on Level 2?"
   after a Level 1 question.
9. The router with memory still returns the structured output (its history holds JSON answers).
10. `import_workflows.sh`: `import:credentials` accepts the plain (unencrypted) credential JSON and
    encrypts it with `N8N_ENCRYPTION_KEY`; the field names of the four credential types
    (`apiKey`, `botToken`, header `name`/`value`, Postgres `host`...); `update:workflow
    --id=concho --active=true` exists in the chosen `N8N_VERSION` (newer releases may call it
    `publish:workflow`; the script then warns and tells you to activate in the editor).
11. `docker compose up`: images build (the API image installs `.[api]`; the bot pins
    `discord.py==2.5.2`), the data API is healthy and ingests the team repo, n8n reaches
    `http://data-api:8000`, and the `internal` network does not break anything n8n needs.
12. The Discord bot: Message Content intent on, forwards a message, n8n answers in the same
    channel / thread (the bot ignores the HTTP response).
13. The eval against the live webhook with the Island team repo: ≥ 90 %, 0 overflows, p95 < 20 s;
    `--generate-only` first to read the questions and numbers. Tune prompts if the language or
    follow-up questions fail.
14. `memory-maintenance` prints "memory purge: 0 messages deleted" daily (check the logs next day).
