# Legacy n8n workflow: "Island AI Agent" (reference only)

`island-ai-agent.json` is a **reference snapshot** of the Concho workflow that Island Team 2026
ran on n8n, exported on **2026-09-26** (roadmap task P1.5). It documents how Concho worked
before the rebuild.

**Not meant to be imported as-is for new teams.** It is hardcoded to the Island project
(prompts, raw GitHub URLs of personal repos, model per node) and has the known issues listed
below. The per-team workflow is rebuilt in Phase 6 (`agent/workflows/concho.json`, P6.2).

The export was scrubbed before committing: Discord guild/channel IDs are `$env` placeholders,
the webhook path is `REPLACE_WITH_RANDOM_WEBHOOK_PATH`, `webhookId`s are removed, and the
old GitHub raw token is no longer in the `get_stv_dashboard` URL. Credentials are never part
of an n8n export. `scripts/check_forbidden.py` fails CI on Discord IDs under `agent/`.

## Architecture

```
Discord bot ──POST──▶ Webhook w/ Auth (header auth)
                      ▶ Edit Fields Discord (message = body.content, source = "discord")
                      ▶ Merge2 ▶ Router Agent (gpt-4o, replies with one category word;
                                               Simple Memory keyed on author_id)
                      ▶ Switch (COST | CARBON | SCHEDULE | BIM | MATERIAL)
                          ├─ Cost Agent      (gpt-4o-mini) ─ get_tvd_dashboard
                          ├─ Carbon Agent    (gpt-4o-mini) ─ get_stv_dashboard
                          ├─ Schedule Agent  (gpt-4o-mini) ─ get_alice_macro, get_micro_schedule
                          ├─ BIM Agent       (gpt-4o)      ─ get_central_model
                          └─ Material        (not connected)
                      ▶ Merge ▶ Send a message (Discord, #askbim)
```

Errors of the router model and of Simple Memory go to the "Send debug msg" nodes (Discord
debug channel). The Telegram input was removed from the live workflow before the export.

## Tools and data sources

All tools are plain HTTP requests to `raw.githubusercontent.com` files on `main`; the LLM reads
the whole file.

| Tool | Source file | Size | ≈ tokens | Status |
|---|---|---|---|---|
| `get_tvd_dashboard` | AutoTVD `results/latest.json` | 16 KB | 4k | OK |
| `get_stv_dashboard` | AutoSTV `outputs/stv_project/stv_results.json` | 20 KB | 5k | OK, but **different numbers than the STV dashboard** (P2.3) |
| `get_central_model` | IPD_Challenge `outputs/takt_zones/central_bim_model_llm_context.csv` | 417 KB | 104k | **causes context overflow** |
| `get_micro_schedule` | IPD_Challenge `Micro_Schedule.csv` | 2.7 MB | 670k | **always exceeds context** |
| `get_alice_macro` | IPD_Challenge `ALICE_macro.xlsx` | binary | – | **model can't read XLSX** |
| `get_material_data` | AutoTVD `materials.json` | 5 KB | – | disabled, not connected |

(Table from roadmap §1 "Concho today". The token GHSAT query was removed from the
`get_stv_dashboard` URL in P0.2.)

## Known issues

From roadmap §1 "Live bugs" and P6.1, as of this snapshot:

1. **MATERIAL branch not connected:** the router can return `MATERIAL`, but that Switch output
   (and the 5th Merge input) has no connection, so those questions get no answer.
2. **Non-existent tool in the BIM prompt:** the BIM Agent prompt references
   `get_alice_bim_map`, which does not exist. (The Cost and Carbon prompts also reference
   `get_material_data`, which is disabled and not attached.)
3. **Case-sensitive Switch without fallback:** exact, case-sensitive `equals` on the router
   output; anything else (`Cost`, `COST.`, a sentence) is dropped silently.
4. **`sendAndWait` debug nodes:** the debug nodes use Discord `sendAndWait`, which blocks the
   execution; errors from the subagents are not caught at all.
5. **Memory only on the router:** Simple Memory (session key = Discord `author_id`) is
   attached only to the Router Agent, which just classifies, so subagents don't see earlier
   messages and follow-ups still fail. It is in-process and lost on n8n restart.
6. **`get_alice_macro` reads XLSX:** the model can't parse the binary file; should read
   `Macro_Schedule.csv` instead.
7. **Context overflow:** `get_central_model` (~104k tokens) and `get_micro_schedule`
   (~670k tokens) exceed the context window. Fixed properly by the data API (Phase 5).
8. **Everything hardcoded:** "Island Team 2026", "San Juan, Puerto Rico",
   "September 30, 2030", data URLs of personal repos, model per node.

Fixed before the export (P0.2): webhook header auth, GitHub raw token removed from the
`get_stv_dashboard` URL, Simple Memory re-pointed and enabled.

## Importing it anyway

Only for inspection or a throwaway test instance, never for a new team's production use.

Environment variables read by the placeholders (set them in the n8n container):

| Variable | Used by | Value |
|---|---|---|
| `DISCORD_GUILD_ID` | `Send a message`, `Send debug msg`, `Send debug msg1` | Discord server (guild) ID |
| `DISCORD_CHANNEL_ID_ASK` | `Send a message` | channel for answers (Island: `#askbim`) |
| `DISCORD_CHANNEL_ID_DEBUG` | `Send debug msg`, `Send debug msg1` | channel for error messages |

n8n must allow `$env` in expressions (`N8N_BLOCK_ENV_ACCESS_IN_NODE=false`; newer n8n
versions block it by default).

Also required after import (not stored in the export):

- **Webhook path:** replace `REPLACE_WITH_RANDOM_WEBHOOK_PATH` in `Webhook w/ Auth` with a
  long random string; the Discord bot posts to `https://<n8n-host>/webhook/<path>`.
- **Header Auth credential** on `Webhook w/ Auth` (Island used header `X-Concho-Token`; the
  bot sends the same token from its `.env`).
- **OpenAI credential** on the five chat model nodes.
- **Discord bot credential** on the three Discord nodes.

Keep all these values in `.env` / n8n credentials, never in the repository.
