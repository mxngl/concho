# Concho agent (n8n workflow, prompts, model config), Tier 1 (P6.2, P6.3, P6.7)

The rebuilt Concho answers from the **data API** ([`data-api.md`](data-api.md)) only: no raw
files, no GitHub URLs, nothing project-specific in the workflow. Code and files:

| Path | What |
|---|---|
| [`agent/workflows/concho.json`](../agent/workflows/concho.json) | the n8n workflow "Concho" (37 nodes) |
| [`agent/workflows/error-handler.json`](../agent/workflows/error-handler.json) | global error workflow (`id` `concho-error-handler`) |
| [`agent/prompts/*.md`](../agent/prompts/) | prompts with `{{PLACEHOLDERS}}` (router, cost, carbon, quantity, general, fallback, shared rules in `common.md`) |
| [`agent/.env.example`](../agent/.env.example) | every variable the workflows and scripts read |
| [`scripts/render_agent.py`](../scripts/render_agent.py) | fills prompts and webhook path for one team, writes `agent/build/` |
| `tests/agent/` | offline tests (workflow JSON, prompts, rendering) |

Scope is **Tier 1** (D13): cost, carbon, quantities, general/data questions. `SCHEDULE` is
recognised and answered with "not available in this version" (P6.5 follows with Tier 2).
Memory (P6.4), the deployment bundle (P6.6) and the evaluation harness (P6.8) are the next PR;
the legacy workflow `agent/workflows/legacy/` is untouched and **not** replaced in n8n by this
PR (roadmap rule 4).

## Flow

```
Webhook (POST, header auth, answers via "Respond to caller")
  ▶ Normalize input        one Set node: message, user_id, user_name, channel_id, guild_id,
  │                        message_id, source, attachments
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

`agent.models` in `project_config.json` (required by the schema since P3.1) is **not** read by
the agent; see the open question in the PR.

## Credentials (created by the import script of P6.6, not part of the export)

The workflow refers to three credentials by fixed id: `concho-openai` (OpenAI API key),
`concho-discord` (Discord bot token), `concho-webhook-auth` (header `X-Concho-Token`).
Until P6.6 exists, create them by hand in n8n with exactly these ids/names or pick them in the
nodes. `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` is required (`$env` in expressions).

## What is tested offline, and what is not

Tested (`pytest tests/agent`, no n8n, no LLM): the JSON is valid and every connection points to
an existing node; every node is reachable; each agent has one model and exactly the intended
tools; no tool outside the data API; tools match the API's endpoints and parameters; no URL,
IP, token or Discord ID in the JSON; no node references; the router enum and the Switch cover
all categories with a fallback; every agent has an error branch; the reply goes to the
originating channel and mentions the user; models come from the env with the default; every
`$env` variable is in `.env.example`; prompts render and contain no project string.

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
   measures this).
