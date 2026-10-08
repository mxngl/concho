# Decisions

Decision records for D1–D10, D13 and D14 from [ROADMAP.md §2](ROADMAP.md#2-decisions-needed-human-settle-these-before-or-during-phase-0), plus decisions taken in later tasks (D11, D12, D15).
State as of 2026-09-27 (Max + Ash sync). Owners: Max Nagel, Ashmitha Jaysi Sivakumar. Updating these records is task P0.5.

Status values: **decided** · **working assumption** (acted on, still to be confirmed) · **deferred** (not needed yet) · **open** (not settled; recommended default listed).

| ID | Decision | Status |
|---|---|---|
| D1 | Scope for 2027 | decided |
| D2 | Hosting model | open (asked 2026-09-27) |
| D3 | Where the new code lives | decided |
| D4 | License (own code only) | open (asked 2026-09-27) |
| D5 | Course data redistribution | open (asked 2026-09-27) |
| D6 | LLM provider, keys and cost | open |
| D7 | Support owner during the semester | open (asked 2026-09-27) |
| D8 | Tool access 2027 | open (asked 2026-09-27) |
| D9 | Transcript agent and ClashBot | decided |
| D10 | Origin of `6.38e6` / `1.51e8` | open (asked 2026-09-27) |
| D11 | Urinal `null` vs. `0` in `project_config` (P3.10 item 3) | decided |
| D12 | Rainwater credit cap (P3.10 item 2) | decided |
| D13 | Rollout in tiers | decided |
| D14 | Schedule and Manufacton positioning | decided |
| D15 | Duplicates across exports and Revit Parts (P3.9) | decided |

---

## D1: Scope for 2027

- **Status:** decided (2026-09-26)
- **Decision:** Main scope is TVD + STV + takeoff Q&A + schedule (macro/micro schedule, takt planning, deliveries). Meeting transcripts and ClashBot are extensions (Phase 10).
- **Consequences:** Phase 3B (schedule generalization) is part of the main scope.

## D2: Hosting model

- **Status:** open; asked in the mail to the course lead (Renate) on 2026-09-27
- **Context:** Main open risk for the Concho chat (sync 2026-09-27): n8n workflows and the
  Discord bot must run on a server, otherwise the bot is offline whenever the host laptop is
  off. Not blocking Phases 1–4; the dashboards (GitHub Pages) don't need it.
- **Options asked:** (a) server run by the PBL Lab, (b) small hosting budget per team,
  (c) an industry sponsor provides a VPS.
- **Fallback:** each team runs the `docker-compose` bundle locally (works only while that
  computer runs, no phone access, data synced via git).

## D3: Where the new code lives

- **Status:** decided (2026-09-26)
- **Decision:** `github.com/mxngl/concho` (public), Ash as collaborator. Old repos are archived after Phase 2. A later transfer to a neutral org stays possible.

## D4: License (own code only)

- **Status:** open; asked in the mail to the course lead (Renate) on 2026-09-27
- **Current state:** no LICENSE file until Renate confirms there are no Stanford/course IP
  rules against it; "all rights reserved" meanwhile. Max prefers MIT, Ash undecided (sync
  2026-09-27).
- **Context:** If the course workbooks were ever committed, an MIT license would cover them
  too, so they stay out unless Renate says otherwise (D5). Not blocking.

## D5: Course data redistribution

- **Status:** open; asked in the mail to the course lead (Renate) on 2026-09-27
- **Current state (workaround):** engines read the course workbooks from a local path at
  runtime (env var), tests skip without them, and nothing course-owned is committed; teams
  copy the workbooks from the course Drive into their local folder.
- **Asked:** may teams use the workbooks through the tool, and may they be shipped with the
  repo (then they need a separate license note)?

## D6: LLM provider, keys and cost

- **Status:** open
- **Recommended default:** each team uses its own API key with a spending cap; default model
  gpt-4o-mini, configurable; cap amount after P9.2.
- **Context (sync 2026-09-27):** Stanford students have Claude education access, other
  members mostly have their own AI subscriptions; chat subscriptions don't pay for API calls
  of the n8n agents, so the key question is tied to D2. Tier-2 skills (D14) also work with
  whatever coding assistant a team uses.

## D7: Support owner during the semester

- **Status:** open; asked in the mail to the course lead (Renate) on 2026-09-27
- **Current plan:** Max and Ash as maintainers and for onboarding (tier introductions,
  possibly short videos); Ash asks a possible TA from the 2026 cohort.

## D8: Tool access 2027

- **Status:** open; asked in the mail to the course lead (Renate) on 2026-09-27
- **Working assumption (Max, 2026-09-26):** ALICE, Fuzor and Manufacton will be available in
  2027; to be confirmed by Renate. Manufacton import templates are public, so no question
  there.
- **Asked:** Resolve or Autodesk's own tool for clash review (ClashBot needed Autodesk
  Platform Services credentials, set up with help from the Stanford Autodesk admin).
  ACC/APS access is still open.
- **Consequences:** The schedule engine must work without these licenses (tool-agnostic CSV
  input); ALICE/Fuzor/Manufacton become optional adapters (Phase 3B). ACC/APS access decides
  ClashBot (Phase 10).

## D9: Transcript agent and ClashBot

- **Status:** decided (2026-09-27)
- **Decision:** the transcript agent and ClashBot are deferred until after the core rollout
  (Phase 10, Tier 3 in D13).
- **Consequences:** the old workflows are located and exported only then.

## D10: Origin of `6.38e6` / `1.51e8`

- **Status:** open; asked in the mail to the course lead (Renate) on 2026-09-27
- **Context:** Both constants come from the course workbook `CEE_222_STV_V12.xlsx` (roadmap §1); their derivation is unknown.
- **Next step:** document the answer in the engine docs.

## D11: Urinal `null` vs. `0` in `project_config` (P3.10 item 3)

- **Status:** decided (2026-09-26, with P3.1)
- **Context:** The course STV workbook applies the 0.75 toilet factor whenever the urinal
  cell is non-blank, even when it holds 0. The engine applies it only when `urinal_gpf > 0`
  (found in P2.4). A plain number cannot tell "no urinals" from "urinal cell = 0".
- **Decision:** `stv.use_phase.water.urinal_gpf` in `project_config`:
  - `null` = the building has no urinals → toilet factor 1.0 (course: blank cell);
  - a number, **including an explicit `0`** = course behaviour → toilet factor 0.75
    (course: non-blank cell);
  - the key must be present unless `use_phase.not_modeled` is true, so the choice is always
    explicit.
- **Rationale:** follow the course (roadmap §0, hard rule 6: course logic untouched in the
  engines); `null` only adds the "blank cell" case that a number cannot express.
- **Consequences:** The schema (P3.1) distinguishes the two. **Implemented in P3.10**
  (2026-09-26): `WaterUseInputs.urinal_gpf` is optional; the engine applies 0.75 for any
  number (incl. 0) and 1.0 for `None`; `project_config` passes the value through;
  `--stv-workbook-input` reads a blank urinal cell as `None`. Course-equivalence cases for
  urinal = 0 and blank (`test_toilet_factor_matches_course`). Island results unchanged (no
  use phase); the River test config uses `null`.

## D12: Rainwater credit cap (P3.10 item 2)

- **Status:** decided (2026-09-26, P3.10)
- **Context:** P2.4 found that the course STV workbook caps the rainwater credit at toilet +
  urinal + landscaping water (`Use Phase` H40 = `-MIN(D40 × …, H32 + H33 + H38)`), while the
  engine capped it at the total water use (all fixtures incl. sinks and showers). With more
  rainwater than toilet + urinal + landscaping need, the engine netted out sink and shower
  water too and reported less use-phase water than the course.
- **Decision:** follow the course (roadmap §0, hard rule 6): the credit is
  `min(collected, toilet + urinal + landscaping water)`; sink and shower water is never
  offset.
- **Consequences:** `engines/stv/engine.py` changed in P3.10; course-equivalence case
  `test_rainwater_cap_matches_course`. Rainwater below both caps gives the same result as
  before. Island results unchanged (no use phase); the Island LAMARCASINA workbook variant
  (396,183 gal rainwater, below its toilet water) is unchanged as well.

## D13: Rollout in tiers

- **Status:** decided (2026-09-27, Max + Ash)
- **Context:** Teams first have to learn the course tools themselves; everything at once
  would be used by nobody.
- **Decision:** one monorepo, but the docs release it in tiers.
  - **Tier 1 (course start):** Revit add-in → takeoffs → TVD + STV computed automatically
    (dashboards) + Concho chat on TVD/STV/quantities.
  - **Tier 2 (on request or in the second half, when teams schedule):** ALICE macro → micro
    schedule, takt, Manufacton production orders / prefab assemblies / kit of parts /
    delivery windows, schedule questions in Concho.
  - **Tier 3:** meeting transcripts, ClashBot (Phase 10).
- **Consequences:** for Tier 1, teams provide `project_config` and their own RSMeans-based
  cost DB (guideline only); STV needs nothing beyond the takeoffs. Phase 3B becomes Tier 2.

## D14: Schedule and Manufacton positioning

- **Status:** decided (2026-09-27)
- **Context:** the Island schedule logic was design-specific, so it cannot be shipped as a
  general plugin.
- **Decision:** data, templates and skills instead of plugins. The takeoff and schedule data
  are structured so any AI agent can query them; each Tier-2 step is a Claude skill with
  defined input and output files plus the Island outputs as examples, so teams encode their
  own logic. Manufacton is import-only (templates for production orders, prefab assemblies,
  kit of parts; nothing syncs back to Revit). ALICE provides the macro schedule (export →
  CSV). Fuzor is dropped from Tier 2.
- **Consequences:** owner Ash (P3B.9).

## D15: Duplicates across exports and Revit Parts (P3.9)

- **Status:** decided (2026-09-27, Max, on the recommendation in the meeting notes of the
  Max + Ash sync); implemented in P3.9, Ash reviews the PR.
- **Context:** TVD merged its two takeoffs by ElementId with "structural always wins"; STV only
  listed elements in several discipline exports (35 ElementIds in the Island Current exports,
  e.g. floors 1241457, 1789623, 1789655) and counted them in each. The Revit add-in exports
  Parts (since concho #18 with `Part Source Id`, `Original Category` and the source's Assembly
  Code) and skips a floor/ceiling with Parts within one export, but another export can still
  hold the host as a whole element. In the current Island models the 166 structural Parts come
  from 3 floors that appear in no export as whole elements; the architecture model has 96
  Parts of a ceiling whose type has no Assembly Code.
- **Decision:** one shared rule for TVD and STV (`engines/common/dedup.py`):
  1. **Parts:** count Parts, never a Part and its host together. If a host row (ElementId =
     some Part's `Part Source Id`) and Parts of that host both appear, in the same or
     different exports, keep the Parts and drop the host row.
  2. **Same ElementId in several exports:** keep one row, decided in this order:
     (a) a row with an Assembly Code wins over one without;
     (b) STV only: a row the STV mapping maps wins over an unmapped one (TVD prices by code
     and skips this step);
     (c) the export whose discipline owns the category: structural for Floors, Structural
     Framing, Structural Columns, Structural Foundations (and Parts with such an
     `Original Category`), MEP for the MEP categories, architecture for all others;
     (d) same discipline: the first export given.
  3. Every dropped row is reported in a `deduplication` block of both results JSONs (count
     per reason `host_of_parts`, `duplicate_without_code`, `duplicate_unmapped`,
     `duplicate_other_discipline`, `duplicate_same_discipline`; ElementIds and categories
     only, no quantities).
  4. STV maps a Part with its `Original Category` (`Parts` if empty).
  5. `concho-stv --combine-results` cannot deduplicate (no ElementIds): kept, with a warning
     and a note recommending one run with all discipline exports.
- **Rationale:** Parts are the representation the add-in counts; an element that carries a
  code is the one TVD can price and STV's rules usually key on; the owning discipline's model
  is the authoritative one for its categories. Step (b) was added so that an element is not
  lost from STV only because the owning discipline's row has no rule (Island floor 1241457,
  A1010 in both exports, mapped only in architecture).
- **Consequences:** TVD Island unchanged (the AutoTVD exports share no ElementId, no Parts; no
  legacy merge switch needed). STV per-trade reference 2,517,183.14 kgCO₂e unchanged; a single
  STV run of the six Current exports is 2,459,374.64 (−4,866 sf floor concrete counted twice
  before). DNC handling is not part of this decision (TVD skips DNC rows, STV counts them and
  lists them in `dnc_rows`; separate decision for Ash). ElementIds are unique per Revit model
  only, so exports of different models could collide by chance (none in the Island exports).
  Details: `docs/model-requirements.md` ("How Parts and duplicates are counted"),
  `docs/engines/tvd.md`, `docs/engines/stv.md`.
