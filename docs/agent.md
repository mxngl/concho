# Concho agent (n8n workflow, prompts, memory, model config), Tier 1 (P6.2, P6.3, P6.4, P6.7)

The rebuilt Concho answers from the **data API** ([`data-api.md`](data-api.md)) only: no raw
files, no GitHub URLs, nothing project-specific in the workflow. Code and files:

| Path | What |
|---|---|
| [`agent/workflows/concho.json`](../agent/workflows/concho.json) | the n8n workflow "Concho" (42 nodes, id `concho-main`) |
| [`agent/workflows/error-handler.json`](../agent/workflows/error-handler.json) | global error workflow (`id` `concho-error-handler`) |
| [`agent/prompts/*.md`](../agent/prompts/) | prompts with `{{PLACEHOLDERS}}` (router, cost, carbon, quantity, general, fallback, shared rules in `common.md`) |
| [`agent/memory.sql`](../agent/memory.sql) | the chat-memory table in Postgres (P6.4) |
| [`agent/docker-compose.yml`](../agent/docker-compose.yml), [`agent/bot/`](../agent/bot/) | the deployment bundle and the Discord bot (P6.6, [`agent-deployment.md`](agent-deployment.md)) |
| [`agent/.env.example`](../agent/.env.example) | every variable the workflows, scripts and the bundle read |
| [`scripts/render_agent.py`](../scripts/render_agent.py) | fills prompts and webhook path for one team, writes `agent/build/` |
| [`scripts/import_workflows.sh`](../scripts/import_workflows.sh) | renders, creates the credentials and imports the workflows (P6.6) |
| [`tests/agent_eval/questions.yaml`](../tests/agent_eval/questions.yaml), [`scripts/run_eval.py`](../scripts/run_eval.py) | the evaluation (P6.8, [`agent-eval.md`](agent-eval.md)) |
| `tests/agent/`, `tests/agent_eval/` | offline tests (workflow JSON, prompts, rendering, memory SQL, bundle, scorer) |

Scope is **Tier 1** (D13): cost, carbon, quantities, general/data questions. `SCHEDULE` is
recognised and answered with "not available in this version" (P6.5 follows with Tier 2).
Memory (P6.4), the deployment bundle (P6.6) and the evaluation harness (P6.8) are built (🟡:
nothing of them has run against a live n8n and an LLM yet); the legacy workflow `agent/workflows/legacy/` is untouched and **not** replaced in n8n by this
PR (roadmap rule 4).

## Flow

```
Webhook (POST, header auth, answers via "Respond to caller")
  ▶ Normalize input        one Set node: message, user_id, user_name, channel_id, guild_id,
  │                        message_id, source, attachments
  ▶ Load history           Postgres: last 6 messages of this user + channel, < 30 days (P6.4)
  ▶ With history           merge by position (history + normalized fields)
  ▶ Router                 agent + structured output {category, language}; chat model, no tools
  ▶ Router + context       merge by position (Router output + the item with history)
  ▶ Classified             category (upper case, default OTHER), language, history
  ▶ Route (Switch)         COST | CARBON | QUANTITY | GENERAL | SCHEDULE | fallback = OTHER
       ├─ Cost Agent      get_cost_summary, list_cost_clusters, get_cost_items, cost_what_if
       ├─ Carbon Agent    get_carbon_summary, get_carbon_items, carbon_what_if
       ├─ Quantity Agent  get_quantities, count_elements
       ├─ General Agent   get_cost_overview, get_carbon_overview, get_quality,
       │                  list_snapshots, compare_snapshots
       └─ Fallback Agent  no tools (SCHEDULE and OTHER)
  ▶ Attach answer          merge by position (Classified + agent output)
  ▶ Compose reply ▶ Respond to caller ┬▶ Reply on Discord? ▶ Send reply (Discord)
                                      └▶ Remember turn? ▶ Save turn (Postgres, P6.4)
every agent: error output ▶ Error reply (user-readable, de/es/pl/en) ▶ Compose reply
```

- **Input contract.** The caller (Discord bot, later Telegram, the eval) POSTs JSON to
  `/webhook/<CONCHO_WEBHOOK_PATH>` with the header `X-Concho-Token` (the Webhook node has a
  fixed `webhookId`; without one n8n registers `/webhook/<workflow id>/<node name>/<path>`, which
  is what gave the bot and the eval HTTP 404 in the first real run; **the short URL is untested
  until Max re-imports**, see below):
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
  scenarios are labelled and opened with an explicit scenario line; on `too_many_results` ask
  the user to narrow (level, category, cluster, Assembly Code) instead of retrying; at most
  1800 characters (Discord limit 2000). Numbers are **rounded, not truncated** (618,515.60 is
  618,516); the model **never judges over/under target itself**: it quotes the `status` /
  `status_after` / delta of the row it talks about (a cluster has its own status, different from
  the grand total's); a call is **never repeated** with the same tool and parameters.
- **Cluster names are never guessed.** `list_cost_clusters` (`GET /cost/clusters`) returns the
  exact names with their Assembly Code groups; `get_cost_items` takes only a name from it or
  from `get_cost_summary`; an `unknown_cluster` error lists the valid names and the agent asks
  which one is meant.
  STV units are exactly the data's: kgCO2e, MJ, water in kg, ozone in kg CFC-11e.
- **Names are exact.** Material names are passed with their unit suffix (`Concrete (sf)`, not
  `Concrete`). `/carbon/what_if` answers `no_match` / `unknown_material_factor` with `similar`
  (names containing the given one) or, if none, `materials` (the project's names); the carbon
  agent retries **once** with the closest name before it asks the user. A level that does not
  exist answers `unknown_level` with the valid `levels` on `/elements/count` (it used to answer
  `count: 0`); the quantity agent says the level does not exist and lists them.
- **Data-quality questions go to GENERAL.** "How many elements have no Assembly Code?" is
  routed to GENERAL (router prompt) and answered from `get_quality` (`unmapped_elements`, scope
  `tvd` = no Assembly Code, scope `stv` = no carbon material); the shared rules say a total
  element count is never the answer to an unmapped / data-gap question.
- **Reply.** Discord node → `channel_id` of the normalizer (thread or channel), content
  `<@user_id> reply`. The webhook answers the caller first with
  `{reply, category, language, tools, tool_response_chars, tool_errors, failed}` (the eval reads
  this). `tool_errors` lists the `"error"` codes of the tool results (`too_many_results`,
  `unknown_cluster`, `unknown_level`, `no_match`, `tool_failed` for a transport error such as
  "The service refused the connection"); `failed` is only true when an agent
  node itself failed, so the eval also looks at the reply and `tool_response_chars`.
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

The models are **only** in the env: `project_config.json` has no model settings (`agent.models`
was removed from the schema; a team config that still has it fails validation, delete the key).

## Memory (P6.4)

Follow-ups ("and on Level 2?") need the earlier messages. Two Postgres nodes keep them in the
table `concho_memory` ([`agent/memory.sql`](../agent/memory.sql)); n8n's own memory nodes are
not used (they would store the router's JSON and the subagents' turns as well, twice, and give
no retention):

- **Load history** runs before the router: the last `CONCHO_MEMORY_MESSAGES` (6) rows of this
  `user_id` + `channel_id` younger than `CONCHO_MEMORY_DAYS` (30), oldest first, as one text
  block `user: …` / `assistant: …` (each cut at 700 characters). It is put in front of the
  question for the router **and** the subagents: `Chat history (oldest first; only to understand
  follow-up questions, its numbers are old): … Latest message: …`.
- **Save turn** runs after the caller got its answer (`Respond to caller`): it inserts the
  user's message and the reply, and deletes everything older than the retention in the same
  statement (retention without a cron job). A turn is stored only if it worked (`Remember turn?`):
  turns where an agent failed, **turns whose reply reports a tool error** (`tool_errors` not
  empty, which includes the data API being down, `too_many_results`, `unknown_cluster`), replies
  that say the data is not reachable (`data_unreachable`, a word-list check of the reply in
  en/de/es/pl), turns without user or channel id and empty replies are **not stored**: neither the
  user's message nor the reply, so a follow-up never sees an error as "history".
- A Discord thread is a channel of its own, so each thread has its own memory.
- Both nodes continue on error: if Postgres is down, Concho answers without history.
- The prompts say the history is only for understanding a follow-up; every number must come from
  a tool call of this turn. The SQL is tested on a real Postgres 17 (`CONCHO_TEST_PSQL`, see
  `tests/agent/test_agent_memory.py`): window of 6, other users and channels excluded, rows older
  than 30 days neither read nor kept, `memory.sql` idempotent.
- Stored: chat text of the team's channel for at most 30 days; nothing is written to the repo.

## Credentials (created by `scripts/import_workflows.sh`, not part of the export)

The workflows refer to four credentials by fixed id: `concho-openai` (OpenAI API key),
`concho-discord` (Discord bot token), `concho-webhook-auth` (header `X-Concho-Token`) and
`concho-postgres` (the memory nodes; the fourth one is new in P6.4). `scripts/import_workflows.sh`
creates them from the env ([`agent-deployment.md`](agent-deployment.md)); by hand, create them in
n8n with exactly these ids/names. `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` is required (`$env` in
expressions).

## What is tested offline, and what is not

Tested (`pytest tests/agent tests/agent_eval`, no n8n, no LLM): the JSON is valid and every connection points to
an existing node; every node is reachable; each agent has one model and exactly the intended
tools; no tool outside the data API; tools match the API's endpoints and parameters; no URL,
IP, token or Discord ID in the JSON; no node references; the router enum and the Switch cover
all categories with a fallback; every agent has an error branch; the reply goes to the
originating channel and mentions the user; models come from the env with the default; every
`$env` variable is in `.env.example`; prompts render and contain no project string; the memory
SQL (static, and on a real Postgres when `CONCHO_TEST_PSQL` is set), the compose file, the
import script against a stub `docker`, the credentials builder, the bot's payload, the eval
scorer and the question generator.

**Not tested here (needs a running n8n and an OpenAI key; Max to check):**

0. The short production URL `/webhook/<CONCHO_WEBHOOK_PATH>` after the `webhookId` fix: import
   again (`import_workflows.sh`), then `curl -i -X POST` with the token must not answer 404.
   The long URL `/webhook/concho-main/webhook/<path>` of the first run should be gone.

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
   measures this).
8. Memory: `queryReplacement` given as an expression that returns an array fills `$1…$6` of the
   Postgres nodes; the follow-up question gets the history; `Save turn` writes two rows.
9. `list_cost_clusters` is called instead of a guessed cluster name; the what-if answer quotes
   the cluster's own `status_after`; no call is repeated.

Checked by Max on n8n 2.43.8 with the Island data: router, tools, snapshot line, labels and
languages work. First real run of the bundle (Docker Desktop, n8n 2.43.8, Postgres 16, gpt-4o-mini,
Island data): eval 40/45 = 88.9 %, p95 9.5 s, 0 overflows, memory follow-ups pass, but only on the
long webhook URL. The failures it showed are fixed in the follow-up PR (webhookId, unmapped
routing, material names, unknown level, no memory for error turns) and still need a second live
run. Still untested: the error output of an agent node after the fix, the Discord thread.
