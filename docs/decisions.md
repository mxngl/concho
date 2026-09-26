# Decisions

Decision records for D1–D10 from [ROADMAP.md §2](ROADMAP.md#2-decisions-needed-human-settle-these-before-or-during-phase-0).
State as of 2026-09-26. Owners: Max Nagel, Ashmitha Jaysi Sivakumar. Updating these records is task P0.5.

Status values: **decided** · **working assumption** (acted on, still to be confirmed) · **deferred** (not needed yet) · **open** (not settled; recommended default listed).

| ID | Decision | Status |
|---|---|---|
| D1 | Scope for 2027 | decided |
| D2 | Hosting model | deferred (Phase 5) |
| D3 | Where the new code lives | decided |
| D4 | License (own code only) | working assumption |
| D5 | Course data redistribution | working assumption |
| D6 | LLM provider, keys and cost | open |
| D7 | Support owner during the semester | open |
| D8 | Tool access 2027 | working assumption |
| D9 | Location of the transcript agent and ClashBot | open |
| D10 | Origin of `6.38e6` / `1.51e8` | open |

---

## D1: Scope for 2027

- **Status:** decided (2026-09-26)
- **Decision:** Main scope is TVD + STV + takeoff Q&A + schedule (macro/micro schedule, takt planning, deliveries). Meeting transcripts and ClashBot are extensions (Phase 10).
- **Consequences:** Phase 3B (schedule generalization) is part of the main scope.

## D2: Hosting model

- **Status:** deferred until Phase 5
- **Context:** Not blocking Phases 1–4; the agent ships as `docker-compose` and runs on any host.
- **Default:** a shared host run by the PBL Lab, with one n8n workflow set + credentials + data API tenant per team.

## D3: Where the new code lives

- **Status:** decided (2026-09-26)
- **Decision:** `github.com/mxngl/concho` (public), Ash as collaborator. Old repos are archived after Phase 2. A later transfer to a neutral org stays possible.

## D4: License (own code only)

- **Status:** working assumption
- **Current state:** no LICENSE file until Renate confirms there are no Stanford/course IP rules against it; "all rights reserved" meanwhile. Preferred: MIT. Max + Ash decide.
- **Context:** Course workbooks and RSMeans data are never in the repo, so they don't affect the license. Not blocking.

## D5: Course data redistribution

- **Status:** working assumption
- **Current state:** Engines read the course workbooks from a local path at runtime (env var), tests skip without them, and nothing course-owned is committed.
- **Open question:** ask Renate whether teams may receive the workbooks (relevant for the pilot, not the prototype).

## D6: LLM provider, keys and cost

- **Status:** open
- **Recommended default:** each team uses its own API key with a spending cap; default model gpt-4o-mini, configurable.

## D7: Support owner during the semester

- **Status:** open
- **Recommended default:** a named TA or PBL Lab contact, plus Max/Ash as maintainers.

## D8: Tool access 2027

- **Status:** working assumption (Max, 2026-09-26)
- **Current state:** ALICE, Fuzor and Manufacton will be available in 2027; to be confirmed by Renate. ACC/APS access is still open.
- **Consequences:** The schedule engine must work without these licenses (tool-agnostic CSV input); ALICE/Fuzor/Manufacton become optional adapters (Phase 3B). ACC/APS access decides ClashBot (Phase 10).

## D9: Where are the transcript agent and ClashBot?

- **Status:** open
- **Recommended default:** Max shares them via n8n MCP or exports JSON.

## D10: Origin of `6.38e6` / `1.51e8`

- **Status:** open
- **Context:** Both constants come from the course workbook `CEE_222_STV_V12.xlsx` (roadmap §1); their derivation is unknown.
- **Recommended default:** ask Renate or the TA; document the answer in the engine docs.
