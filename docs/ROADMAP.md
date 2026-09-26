# Concho 2027 – Handover Roadmap for Claude Code

> **Goal:** turn Concho (Island Team 2026's AI project agent) and the data pipeline behind it (AutoTVD, AutoSTV, IPD_Challenge) into a tool that **each team of the next AEC Global Teamwork cohort can set up and run for its own project**, as a per-team template.
>
> **Owners:** Max Nagel and Ashmitha Jaysi Sivakumar (equal co-owners). **Stakeholder:** Prof. Renate Fruchter (Stanford PBL Lab).
> **Status of this document:** planning baseline, created 2026-09-26 from a review of all repos, deployments, the n8n workflow and the course workbooks.

---

## Progress log

**Overall status:** Phase 0 almost done (P0.1–P0.3 ✅, P0.4 🟡 waiting for Ash's IPD tag, P0.5 🟡 decisions partly open) · Phase 1 done except P1.6 (archive old repos, after Phase 2) · Phase 2 almost done (P2.1–P2.5 ✅, P2.6 🟡 mostly covered) · Phase 3 next (P3.1).

| Date | Update | Tasks |
|---|---|---|
| 2026-09-26 | Roadmap created; this page shared with Ash | – |
| 2026-09-26 | **Repo created: [`mxngl/concho`](https://github.com/mxngl/concho)** (public, empty, default branch `main`). Ash invited as collaborator. | D3 ✅, P1.1 🟡 |
| 2026-09-26 | **Concho webhook secured:** header auth enabled on the n8n webhook (unauthenticated POST → 403, with token → 200); Discord bot on the VPS sends the token from its `.env`; end-to-end test in `#askbim` answered correctly ($16,065,644.29). Telegram nodes removed from the live workflow. Open: remove the old GitHub raw token from the `get_stv_dashboard` URL. | P0.2 🟡 |
| 2026-09-26 | **P3.1 PR opened:** [concho #10](https://github.com/mxngl/concho/pull/10). `engines/common/config.py` (pydantic v2 + JSON Schema in `docs/schema/`, drift check in CI), validation (cluster sums with carved_out/on_top, shares = 1.0, use phase complete or `not_modeled`, date order, files, secret scan), `concho config validate/schema`, neutral template + Island example (validates; $405,852 on-top gap = warning), `docs/config.md`, decision D11 (urinal `null` vs `0`). Engines not wired yet (P3.2/P3B.2). | P3.1 ✅ |
| 2026-09-26 | **P1.7 done** (concho #9 merged). **Migration complete:** TVD, STV and schedule engines, Revit add-in and legacy n8n workflow are in `mxngl/concho`, all reproducing the Island 2026 results. Next: P3.1 (`project_config`). | P1.7 ✅ |
| 2026-09-26 | **P2.4/P2.5 done** (concho #8 merged). **P1.7 PR opened:** [concho #9](https://github.com/mxngl/concho/pull/9) (one PR, ~12.6k lines, ~95 % verbatim; commit `bbdd3b1` = byte-identical copy, `4b1c961` = all changes). 14 pipeline steps via `python -m engines.schedule <step>` / `concho-schedule`, pipeline diagram + reads/writes table in `engines/schedule/README.md`. Equivalence: all 14 steps reproduce the original outputs; migration-diff test 15/15; checksums match for `Macro_Schedule.csv`, `Takt_Schedule.csv` (with `--rooms-per-zone 2`) and `central_bim_model_with_takt.csv`; `Micro_Schedule.csv` is **stale** (built from an older BIM model, not reproducible even by the original code; pinned as expected failure). Schedule tests run in the CI `reference` job. Independently verified: no conflict with main, 185 passed / 1 xfailed in reference mode. Bugs found in the original (unchanged, listed for P3B): takt calibrator drops the last polygon corner (901 of 3,971 elements would change zone); no generator for `room_takt_zones.csv`; Manufacton orders step fails on the 989a6b7 data; delivery windows crash without Manufacton outputs; hardcoded Island assemblies in Manufacton code; pandas pinned to 2.3.3 (micro schedule breaks on pandas 3). | P2.4/P2.5 ✅, P1.7 🟡, P2.6 🟡 |
| 2026-09-26 | **P2.4/P2.5 PR opened:** [concho #8](https://github.com/mxngl/concho/pull/8), CI green. Course-workbook equivalence via LibreOffice headless (needs **libreoffice-calc**). STV embodied/use phase/targets and TVD line/subcode/cluster/summary totals all match (max. rel. error 3e-10 STV, 9.6e-8 TVD from cent rounding). **Findings:** (1) **engine bug**: cogeneration water/ODP read one column off in `engines/stv/reference.py`; (2) rainwater credit cap differs from the course; (3) toilet 0.75 factor: course applies it when urinal cell is 0, engine only when > 0; (4) **bug in the course TVD workbook**: TVD Summary C25 "C3030 Ceiling Finishes" points to `'B Shell'!T30` (B3010) instead of C Interiors; (5) supplied STV workbook stores some small ODP values as 0. Independently verified: 19/19 course tests pass with both workbooks, cogen column offset and TVD C25 reference confirmed in the workbooks, no conflict with main. Follow-ups → P3.10. | P2.4/P2.5 🟡 |
| 2026-09-26 | **P2.1, P2.2, P2.3 done:** concho #7 merged (P2.2 TVD part covered by the P1.3 equivalence test, STV part by the new golden test). **Live n8n change (approved by Max):** `get_stv_dashboard` now reads the current AutoSTV result (2,517,183.14 kgCO₂e) instead of the stale March snapshot; verified via n8n MCP. Remaining mismatch: the Carbon Agent prompt still calls energy "kWh" and water "L" (engine: MJ, kg). | P2.1–P2.3 ✅ |
| 2026-09-26 | **P2.1/P2.3/P2.2-STV PR opened:** [concho #7](https://github.com/mxngl/concho/pull/7). `scripts/fetch_fixtures.py` (3 repos at pinned refs, 20 checksums), shared fixture helper, CI job `reference` (fails instead of skipping via `CONCHO_REQUIRE_FIXTURES=1`), `docs/engines/stv.md`, STV golden test pinned to 2,517,183.14. Independently verified: fixtures fetched, 100/100 tests pass incl. the course-workbook test. **Open decision:** point Concho's `get_stv_dashboard` at the current result (needs approval, live n8n change). | P2.1/P2.3 🟡 |
| 2026-09-26 | **Phase 2 started in parallel to P1.7:** session C = P2.1 (fixture fetch script + CI reference job) + P2.3 (STV discrepancy) + STV part of P2.2; session D = P2.4 + P2.5 (course-workbook equivalence, workbooks attached to the session, never committed). TVD part of P2.2 is effectively covered by the P1.3 equivalence test. P2.6 waits for P1.7. | P2.1–P2.5 🟡 |
| 2026-09-26 | **P1.5 done** (concho #5 merged). **P1.4 PR opened:** [concho #6](https://github.com/mxngl/concho/pull/6), CI green. Revit add-in source from IPD_Challenge `989a6b7` in `revit-addin/` (11 `.cs` + `.csproj` byte-identical; `.addin`: local-path comment removed, all 5 `<Assembly>` → `QTO.dll`; `Concho.QTO.sln`). Findings: MEP export has **no `Assembly Code` column**; Push Kit / Push Assembly exist in code but aren't registered in `.addin`; `.addin` descriptions still mention the old repo layout; IPD exports Revit parts and skips floors/ceilings that have parts (relevant for P3.9). Not compiled (no Revit/.NET here). Independently verified: sources identical, no personal paths left, no merge conflict with main. | P1.5 ✅, P1.4 🟡 |
| 2026-09-26 | **P1.5 PR opened:** [concho #5](https://github.com/mxngl/concho/pull/5). Scrubbed "Island AI Agent" export committed unchanged as `agent/workflows/legacy/island-ai-agent.json` + README (architecture, tools, known issues, env vars); `check_forbidden.py` now fails on Discord snowflake IDs under `agent/` unless the line uses `$env` (nothing found in the repo). Independently verified: JSON byte-identical to the export, 93 tests pass, a raw Discord ID under `agent/` is caught. README note to verify in Phase 6: `$env` in nodes may need `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` (untested). | P1.5 ✅ |
| 2026-09-26 | **P1.3 done** (concho #4 merged). P1.5 prepared: scrubbed export of the live workflow created via n8n MCP (Discord IDs → `$env` placeholders, webhook path replaced, webhookIds removed; passes `check_forbidden.py`), handed to a Claude Code session for committing. | P1.3 ✅, P1.5 🟡 |
| 2026-09-26 | **P1.2 done** (concho #3 merged). **P1.3 ready to merge:** main merged into the #4 branch (merge commit, no force-push), `pyproject.toml` conflict resolved (both CLIs `concho-stv`/`concho-tvd`), `AUTOTVD_DIR` now resolved to an absolute path. Independently verified: **78/78 tests pass with nothing skipped** (TVD equivalence vs. `island-2026-final` with a relative path + STV course-workbook test). | P1.2 ✅, P1.3 🟡 |
| 2026-09-26 | **P1.3 PR opened:** [concho #4](https://github.com/mxngl/concho/pull/4), CI green. TVD engine split into `engines/tvd/` + `dashboards/tvd/legacy_render.py` (byte-identical renderer); CLI `concho-tvd` with `--out DIR`; broken remote fetch removed; synthetic fixture only. Equivalence test 4/4 against `island-2026-final` (results JSON, history snapshot, dashboard HTML; grand total 16,065,644.29, unmapped 1693, DNC 75). Independently verified: 62 tests pass with an absolute `AUTOTVD_DIR`; with a **relative** path the equivalence fixtures error (small fix requested). **#3 and #4 conflict in `pyproject.toml`**: merge #3 first, then rebase #4. | P1.3 🟡 |
| 2026-09-26 | **P1.2 PR opened:** [concho #3](https://github.com/mxngl/concho/pull/3), CI green on 3.11/3.12. STV engine migrated from IPD_Challenge `989a6b7`; calculation modules byte-identical. Workbook path via `--template` / `COURSE_STV_XLSX`; `--output-dir` now required; CLI `concho-stv`. Independently verified: 37 tests pass **incl. the Island target test run against the course workbook** (7,396,873.85 / 155,969,076.59 / 271,387,397.26). Deviations accepted: per-file ruff ignores for the verbatim STV code (41 lint findings, cleanup in Phase 3); CI installs `.[dev,stv]`. The canonical CLI adds `--central-bim-model`, `--stv-workbook-input`, `--architecture-history-dir` over the AutoSTV copy. | P1.2 🟡 |
| 2026-09-26 | **P1.1 done:** concho #1 merged; session rules added as `CLAUDE.md` (concho #2, merged). `docs/decisions.md` in place (records current status of D1–D10). | P1.1 ✅, P0.5 🟡 |
| 2026-09-26 | **P1.1 PR opened:** [concho #1](https://github.com/mxngl/concho/pull/1). Skeleton (engines/{common,tvd,stv,schedule}, revit-addin, data-api, agent, dashboards, template, docs, tests), `pyproject.toml`, CI (ruff + pytest on 3.11/3.12 + forbidden-content check), `docs/ROADMAP.md`, `docs/decisions.md` (covers P0.5). Independently verified: ruff clean, 21 tests pass, the check catches a real GHSAT token. Deviations (all accepted): token/path patterns match real values only so the roadmap text passes; case-insensitive file checks incl. `*.vtt.*`; extra ignore entries for build/test caches. | P1.1 🟡, P0.5 🟡 |
| 2026-09-26 | **Decisions updated:** D8 working assumption = ALICE/Fuzor/Manufacton available in 2027; D2 deferred to Phase 5; D4 = own code only, LICENSE added once Renate confirms; D5 handled by runtime loading of course workbooks. **Phases 1–4 unblocked.** | D2 ⏸, D4/D5/D8 🟡 |
| 2026-09-26 | **P0.3 done:** AutoTVD #6 and AutoSTV #1 merged, Actions green. Ash has no local AutoTVD clone, so nothing to re-clone there. | P0.3 ✅ |
| 2026-09-26 | **P0.3 cleanup PRs opened:** [AutoTVD #6](https://github.com/mxngl/AutoTVD/pull/6) (only relative paths in `data_source`; 9 result JSONs + dashboard footer cleaned) and [AutoSTV #1](https://github.com/mxngl/AutoSTV/pull/1) (removes `.claude/settings.local.json`, adds `.gitignore`). The AutoSTV settings file stays in history (local paths only, not rewritten; AutoSTV gets archived in P1.6). Waiting for merge + green Actions run. | P0.3 🟡 |
| 2026-09-26 | **P0.3:** Max's OneDrive working copy of AutoTVD replaced with a fresh clone (`4201147`); the old copy is renamed `AutoTVD_OLD_before_P0.3` (clean, no unpushed work; never push from it). Remaining: the two cleanup PRs; Ash re-clones if she has a local AutoTVD copy. | P0.3 🟡 |
| 2026-09-26 | **Decision (P0.3):** no GitHub Support request. Instead, AutoTVD is set to **private** at archiving time (P1.6), after checking it has no forks and only once Concho no longer reads from it (Pages + raw URLs would break). Remaining for P0.3: re-clone old local copies + the two cleanup PRs. | P0.3 🟡 |
| 2026-09-26 | **P0.3 (history rewrite) done:** the 3 transcript files were removed from the whole AutoTVD history with `git filter-repo` (run locally by Max, backup bundle kept offline), and all branches + tags were force-pushed. **AutoTVD `main` is now `4201147`** (was `41e9e8c`); `island-2026-final` → `4201147`. Verified on a fresh clone. 4 affected old commits are recorded for GitHub Support. Open: GitHub Support request (PR refs/caches), re-clone old local copies, cleanup PRs (relative paths in `results/*.json`, remove `.claude/` from AutoSTV). | P0.3 🟡 |
| 2026-09-26 | **P0.4:** tags `island-2026-final` pushed by Max: AutoTVD → `41e9e8c`, AutoSTV → `dde2a01` (verified via `git ls-remote`). Open: Ash tags IPD_Challenge (`989a6b7`). | P0.4 🟡 |
| 2026-09-26 | **P0.4 partly done:** reference checksums recorded (see §1, "Reference file checksums"). Annotated tags `island-2026-final` created locally for AutoTVD (`41e9e8c`) and AutoSTV (`dde2a01`), but the Claude Code session may only push to its own branch (tag push → 403). Open: Max pushes the two tags locally; Ash tags IPD_Challenge (`989a6b7`). **Consequence for P0.3:** the history rewrite + force-push must also run locally (not from a Claude Code session). | P0.4 🟡 |
| 2026-09-26 | **P0.1 done:** [AutoTVD PR #5](https://github.com/mxngl/AutoTVD/pull/5) merged (`41e9e8c`), Actions run #49 green. No webhook URL in the code any more; alerts are off until the secrets `CONCHO_ALERT_WEBHOOK_URL`/`_TOKEN` are set (no code change needed to re-enable). | P0.1 ✅ |
| 2026-09-26 | **P0.1:** the old budget-alert webhook (`ce8a4a9c-…`) is **not registered** in n8n (workflow no longer exists), so the leaked URL is dead and no rotation is needed. Patch prepared: `tvd_analysis.py` reads `CONCHO_ALERT_WEBHOOK_URL`/`_TOKEN` from env, `deploy.yml` passes them from secrets; alerts stay off until secrets exist. Open: apply patch + push to AutoTVD. Budget alerts return via P5.2. | P0.1 🟡 |
| 2026-09-26 | **P0.2 done:** GitHub raw token removed from the `get_stv_dashboard` URL. Simple Memory re-pointed to `Webhook w/ Auth` and **enabled** (attached to the Router Agent only). | P0.2 ✅, P6.1 (6) ✅ |
| 2026-09-26 | **Scope decided:** main scope = TVD + STV + takeoff Q&A + **schedule**. Meeting transcripts and ClashBot are extensions (Phase 10). Added Phase 3B (schedule generalization). | D1 ✅ |

**Next up:** **P3.1 (`project_config` schema) → P3.2 / P3.4 / P3.10 → P3B in parallel.** P2.6 leftovers and P4 (Revit add-in) can run alongside. Nothing in Phases 3–4 is blocked. In parallel: Ash tags IPD_Challenge (P0.4); short email to Renate on D4 (license), D5 (workbook redistribution) and D8 (confirm tool access). D2 (hosting) is only needed before Phase 5.

⚠️ **The repo is public.** Course workbooks, RSMeans-derived cost data (incl. the Island `cost_data.csv`), meeting transcripts and secrets must never be committed there. Island fixtures that contain such data go to a private location (see P2.1).

Legend: ✅ done · 🟡 in progress · ⏸ deferred · ⬜ open

---

## 0. How to use this document (read first, Claude Code)

- Work **phase by phase, task by task**. Each task has an ID, the steps, and **acceptance criteria (AC)**. A task is only done when its AC are met.
- Tasks marked **[HUMAN]** need Max or Ash (credentials, decisions, destructive git operations, n8n UI). Prepare everything you can, then stop and ask.
- Tasks marked **[CC]** can be done by Claude Code alone.
- One branch + one PR per task (or small group of related tasks). Reference the task ID in the PR title, e.g. `P3.2: remove hardcoded project values`.
- **Phase 2 (regression baseline) must be finished before any refactoring in Phases 3–7.** The Island 2026 numbers must stay reproducible.

### Hard rules
1. **Never commit secrets** (API keys, webhook URLs, tokens, Discord IDs). Use `.env` + `.env.example` and GitHub Actions secrets.
2. **Never commit course or licensed data** to a public repo: the course workbooks (`CEE_222_STV_V12.xlsx`, `PBL_Lab_TVD-collaboration_tool.xlsx`) and RSMeans-derived cost data. Tests that need them read a local path from an env var and are skipped if it's absent.
3. **Never force-push or rewrite git history without explicit approval** from Max or Ash in the conversation.
4. **Do not modify or deactivate the live n8n workflow** ("Island AI Agent") without explicit approval. The n8n MCP access has write scope; use it read-only unless told otherwise.
5. **Never commit meeting transcripts** or other personal data.
6. Keep the **course logic untouched** in the engines. Team-specific logic goes into config and mapping files, clearly marked as "not course data".

---

## 1. Context: what exists today

### Repositories and deployments
| Component | Repo | Deployment | Update mechanism |
|---|---|---|---|
| TVD engine + dashboard | `mxngl/AutoTVD` | mxngl.github.io/AutoTVD | GitHub Action on push ✅ |
| STV dashboard (+ **older** STV engine copy, QTO add-in copy) | `mxngl/AutoSTV` | mxngl.github.io/AutoSTV (**currently empty/broken**) | manual (Drive zip → commit) ❌ |
| STV engine (**canonical**), QTO Revit add-in, planning engine (ALICE, Fuzor, Manufacton, takt, logistics) | `ashjs2003/IPD_Challenge` | ashjs2003.github.io/IPD_Challenge (Takt Planner, Level 1 only) | manual ❌ |
| Concho agent | n8n workflow "Island AI Agent" on the Hostinger VPS (Docker) | Discord `#askbim` (+ disabled Telegram) | not version-controlled ❌ |
| Transcript agent, ClashBot | **location unknown**: not in the shared workflow | – | – |

### Concho today (n8n workflow "Island AI Agent")
- Webhook (Discord bot → POST) → Router Agent (gpt-4o, returns one word) → Switch → 4 subagents (Cost, Carbon, Schedule: gpt-4o-mini; BIM: gpt-4o) → Merge → Discord.
- Tools are HTTP requests to `raw.githubusercontent.com` files on `main` of two personal repos:

| Tool | Source file | Size | ≈ tokens | Status |
|---|---|---|---|---|
| `get_tvd_dashboard` | AutoTVD `results/latest.json` | 16 KB | 4k | OK |
| `get_stv_dashboard` | AutoSTV `outputs/stv_project/stv_results.json` (URL contains an old GitHub raw token) | 20 KB | 5k | OK, but **different numbers than the STV dashboard** |
| `get_central_model` | IPD `outputs/takt_zones/central_bim_model_llm_context.csv` | 417 KB | 104k | **causes context overflow** |
| `get_micro_schedule` | IPD `Micro_Schedule.csv` | 2.7 MB | 670k | **always exceeds context** |
| `get_alice_macro` | IPD `ALICE_macro.xlsx` | binary | – | **model can't read XLSX** |
| `get_material_data` | AutoTVD `materials.json` | 5 KB | – | disabled, not connected |

**Live bugs:**
1. The router can return `MATERIAL`, but that Switch output is not connected, so those questions get no answer.
2. The BIM prompt references a non-existent tool `get_alice_bim_map`.
3. The Switch does a case-sensitive exact match and has no fallback.
4. The debug nodes use Discord `sendAndWait`, which blocks the execution; errors from the subagents aren't caught at all.
5. Memory is disabled, so follow-up questions don't work.
6. The webhook has no authentication.
7. Everything is hardcoded: "Island Team 2026", "San Juan, Puerto Rico", "September 30, 2030", Discord server and channel IDs, models per node.

### Engines, validated against the course workbooks
- **STV engine** (`IPD_Challenge/src/STV_Engine`) is a faithful port of the course workbook `CEE_222_STV_V12.xlsx`. It reads `LCA Data` rows 8–107 (86 materials, SimaPro/ReCiPe), team rows 115–121 (Pacific, Atlantic, Ridge, **Island**, River, Central, Express) and `Cogen Data`, and it reproduces the target, embodied, use-phase and water formulas.
  - The constants `6.38e6` (carbon) and `1.51e8` (energy) **come from the course workbook**.
  - LCA and cogen data in the team workbooks are identical to the course template, except some tiny ODP (ozone) cached values that differ between the workbooks (found in P2.3; carbon, energy and water are unaffected). The engine reads cached values, so the app that last recalculated a workbook matters for ODP.
  - One small divergence: the course applies the 0.75 toilet factor whenever the urinal cell is non-blank (even at 0); the engine applies it only when `urinal_gpf > 0`.
- **Island-specific parts of STV** are only the Revit → (assembly, material type) mapping in `revit_*.py`, plus unit conversions. Known issues:
  - Bamboo isn't in the course catalog; it is booked as **Glulam Column/Beam (kg)** as a proxy (undocumented).
  - The **use phase is 0** in the project result (no kWh, water or PV entered), while the target covers construction + 50 years of operation.
  - 166 structural "Parts" elements are unmapped.
  - MEP mapping uses literal Revit family names.
- **TVD course method** (`PBL_Lab_TVD-collaboration_tool.xlsx`):
  1. budget = grant × (1 − inflation + ROI)^years, with the target set by the team;
  2. cluster % = average of the RSMeans reference and 3 previous projects, then **10% reallocated by owner value ratings** (`TVD Owners`);
  3. cluster sheets: Total O&P × quantity by Uniformat subcode;
  4. **reliability ratings** (quantity and cost, 1–3);
  5. tracking over time.

  **AutoTVD implements only 3 and 5.** Targets are hardcoded constants.
- **AutoTVD data issues:**
  - Cluster targets A–H sum to $16,705,852 ≈ the $16.7M total, but a non-course cluster "Equipment Rental" ($400k) was added on top, so the targets sum to $17,105,852.
  - `cost_data.csv` mislabels `D5030` as fire protection (course: Communications & Security; fire protection is D40xx) and `D5090` as HVAC (course: Other Electrical; HVAC is `D3050`).
  - It uses German number formats (`$6.184,22`).
  - It has hardcoded GC/contingency lump sums (10%/8% of 16.7M).
  - The cluster name typo "Special Contruction" must match between code and CSV.
  - `GITHUB_REPO_RAW = "https://https://..."` means the remote fetch silently never works.
  - 1,693 of 2,608 takeoff elements are unmapped (no Assembly Code); in the central BIM model 77.5% of 3,971 elements lack an Assembly Code.
  - The course README says its sample cost database comes from **RSMeans CostWorks**, which is licensed data.

### Security and hygiene findings
- **AutoTVD:**
  - A live n8n webhook URL is hardcoded in `tvd_analysis.py`.
  - The meeting transcripts `Dryrun1-Transcript.txt` and `Dryrun2-Transcript.txt` (full names) are public, including in the git history.
  - `results/*.json` contain a local Windows path with a user name.
- **AutoSTV:**
  - `.claude/settings.local.json` is committed and contains a local path.
  - `QTO/bin`, `QTO/obj` and `__pycache__` are committed.
  - The README is copied from IPD_Challenge and describes files that don't exist.
- **IPD_Challenge:**
  - 93 MB, including a 13.9 MB FBX committed twice, a 16 MB Fuzor XML and build artifacts.
  - The README describes `aps_rvt_download.py`, `revit_extract.py` and `Planning_DB/`, which don't exist.
- **Revit add-in:**
  - `.addin` points to `C:\Ashmitha\...\QTO.dll`.
  - `QTO.csproj` hardcodes the path to `RevitAPI.dll` for Revit 2026.
  - Teams must compile .NET 8 themselves.
- **No LICENSE** in any repo.

### Reference numbers (for regression tests)
| Metric | Value | Source |
|---|---|---|
| TVD grand total | **$16,065,644.29** | AutoTVD `results/latest.json` (run 2026-05-01) |
| TVD total target | $16,700,000 | `tvd_analysis.py` |
| STV carbon target (Island) | **7,396,873.85 kgCO₂e** | course formula, team "Island" |
| STV energy target | 155,969,076.59 MJ | course formula |
| STV water target | 271,387,397.26 kg | course table |
| STV project carbon (file Concho reads) | 1,960,143.66 kgCO₂e: **stale** snapshot of 2026-03-30 (early exports, IPD `519a5c0`) | AutoSTV `outputs/stv_project/stv_results.json` |
| STV project carbon (dashboard "Current") | **2,517,183.14 kgCO₂e: current reference** (2026-05-15, `revit_schedules/Current/*`, trades combined) | AutoSTV `outputs/Current-.../project/stv_results.json` |
| STV project carbon (IPD `outputs/stv_project`) | 2,350,871.62 kgCO₂e: unused intermediate (2026-05-07, older arch export + LAMARCASINA use phase) | IPD_Challenge |

Resolved in P2.3 (see `docs/engines/stv.md`): the migrated engine reproduces all three files exactly, so the differences come from inputs, not code. The golden test is pinned to **2,517,183.14**. Note: the Island scorecard (−73.5 %) used the stale 1,960,144 value; with the current value, construction uses ~34 % of the life-cycle carbon target.

### Reference file checksums (sha256, recorded 2026-09-26, task P0.4)
Taken from `main` at AutoTVD `41e9e8c` (after the P0.3 rewrite: **`4201147`**, same file contents), AutoSTV `dde2a01`, IPD_Challenge `989a6b7`.

| Repo | File | sha256 |
|---|---|---|
| AutoTVD | `results/latest.json` | `bcdc917a38bc96ad2a7a497d3e44220c2323cfa7f789ccd27ff2f068670014f1` |
| AutoTVD | `cost_data.csv` | `65538af77d051625c493995246e69f51a3203b0278940491bdef57eda92d6358` |
| AutoTVD | `qto/Architecture_TakeOff.csv` | `67ea680db1f30cfde05b677658b471ca6e06fe2370e117e027789bb43f35a9d6` |
| AutoTVD | `qto/Structural_Schedule.csv` | `1583cfe473d9142cbec67e7e78639874181ac2e26ae1349aabadfb3dc55fa641` |
| AutoSTV | `outputs/stv_project/stv_results.json` | `d9dbb2082b8119906113ceebfe6a9072ba680e9f8e5ffec02761d05367990caf` |
| AutoSTV | `outputs/Current-20260515T191939Z-3-001/Current/project/stv_results.json` | `ed8d496273261830aeffc16ea643c28832cd0bacf8c2ae9597a0ab7eca396584` |
| IPD_Challenge | `src/Planning_engine/ALICE_BIM_mapper/outputs/Macro_Schedule.csv` | `d267a913b33513586eba4a8a8b7128fce9122b816f51a6435399631ffad529b2` |
| IPD_Challenge | `src/Planning_engine/Micro_Schedule_Generator/outputs/Micro_Schedule.csv` | `7841a4b740587d41149227e92b3f6f76f276c2556350e102735ad0135511b7f4` |
| IPD_Challenge | `src/Takt_engine/outputs/Takt_Schedule.csv` | `17fa8009033019405aff0fda921f011bb0f821426a2c4d5eb9042e0a60b8379b` |
| IPD_Challenge | `outputs/takt_zones/central_bim_model_with_takt.csv` | `ff008794690305678f0eaf09b9dc79e053fe40751713f2f90abacc8118d7b09b` |

---

## 2. Decisions needed [HUMAN]: settle these before or during Phase 0

| ID | Decision | Recommended default |
|---|---|---|
| D1 ✅ | Scope for 2027 | **Decided 2026-09-26. Main scope:** TVD + STV + takeoff Q&A + schedule (macro/micro schedule, takt planning, deliveries). **Extensions (Phase 10):** meeting transcripts, ClashBot. |
| D2 ⏸ | Hosting model | **Deferred until Phase 5** (not blocking Phases 1–4; the agent ships as `docker-compose` and runs on any host). Default: shared host run by the PBL Lab, one n8n workflow set + credentials + data API tenant per team. |
| D3 ✅ | Where the new code lives | **Decided 2026-09-26: `github.com/mxngl/concho`** (public), Ash as collaborator. Old repos to be archived after Phase 2. A later transfer to a neutral org stays possible. |
| D4 🟡 | License (own code only) | Max + Ash decide; **no LICENSE file until Renate confirms** there are no Stanford/course IP rules against it (default "all rights reserved" meanwhile). Preferred: MIT. Course workbooks and RSMeans data are never in the repo, so they don't affect the license. Not blocking. |
| D5 🟡 | Course data redistribution | Workaround in place: engines read the course workbooks from a local path at runtime (env var), tests skip without them, nothing course-owned is committed. Still ask Renate whether teams may receive the workbooks (relevant for the pilot, not the prototype). |
| D6 | LLM provider, keys and cost | Each team uses its own API key with a spending cap; default model gpt-4o-mini, configurable |
| D7 | Support owner during the semester | A named TA or PBL Lab contact, plus Max/Ash as maintainers |
| D8 🟡 | Tool access 2027 | **Working assumption (Max, 2026-09-26): ALICE, Fuzor and Manufacton will be available in 2027**; to be confirmed by Renate. ACC/APS still open. Either way, the schedule engine must work **without** these licenses (tool-agnostic CSV input); ALICE/Fuzor/Manufacton become optional adapters (Phase 3B). ACC/APS access decides ClashBot (Phase 10). |
| D9 | Where are the transcript agent and ClashBot? | Max shares them via n8n MCP or exports JSON |
| D10 | Origin of `6.38e6` / `1.51e8` | Ask Renate or the TA; document the answer in the engine docs |

---

## Phase 0: Safety and freeze

- [x] ✅ **P0.1 [HUMAN+CC] Rotate the AutoTVD budget-alert webhook.** *(done 2026-09-26: old webhook was not registered in n8n; URL removed from code via AutoTVD PR #5, run #49 green)*
  - HUMAN: create a new webhook in n8n with header auth and deactivate the old path.
  - CC: remove `N8N_WEBHOOK_URL` from `tvd_analysis.py`, read it from the env var `CONCHO_ALERT_WEBHOOK_URL` (plus an optional header token), and add both to GitHub Actions secrets.
  - AC: no webhook URL in any tracked file; the alert still fires in CI with the secret set.
- [x] ✅ **P0.2 [HUMAN+CC] Secure the Concho webhook.** *(done 2026-09-26: header auth `X-Concho-Token` live, 403/200 and Discord end-to-end verified, STV URL token removed)*
  - Enable header auth on the "Webhook" node.
  - The Discord bot sends the header from its `.env`.
  - Remove the `?token=GHSAT...` query from the `get_stv_dashboard` URL.
  - AC: an unauthenticated POST returns 401/403.
- [x] ✅ **P0.3 [HUMAN runs locally] Remove personal data from AutoTVD.** *(done 2026-09-26: history rewrite + force-push verified, local copies replaced, cleanup PRs AutoTVD #6 / AutoSTV #1 merged; GitHub Support request replaced by making AutoTVD private in P1.6.)* *(Claude Code sessions cannot force-push or push tags, so the rewrite runs on Max's machine. Three transcript files are in history, incl. the deleted `GMT20260419-160103_Recording.transcript.vtt.txt`. PR refs keep old commits, so a GitHub Support "remove sensitive data" request is needed afterwards.)*
  - Prepare a `git filter-repo` script that removes `Dryrun1-Transcript.txt`, `Dryrun2-Transcript.txt` and any `*.vtt*` from the entire history. Run it only after Max or Ash approves, then force-push.
  - Remove `.claude/settings.local.json` from AutoSTV.
  - Strip absolute paths from `results/*.json` (`data_source` → relative).
  - AC: `git log --all -- '*Transcript*'` is empty, and there are no `C:\Users` paths in tracked files.
- [ ] 🟡 **P0.4 [CC → HUMAN pushes] Tag a reference state.** *(2026-09-26: checksums recorded in §1; tags pushed for AutoTVD and AutoSTV; **waiting for Ash to tag IPD_Challenge** at `989a6b7`)* Tag all three repos `island-2026-final` before any change. Copy the reference inputs and outputs listed in §1 into a private fixture location (see P2.1).
  - AC: the tags exist, and the fixture files are checksummed.
- [ ] 🟡 **P0.5 [HUMAN] Settle the decisions D1–D10** in §2 and record the answers in `docs/decisions.md` (ADR style). *(file exists since concho #1; D1/D3 decided, D2 deferred, D4/D5/D8 working assumptions, D6/D7/D9/D10 open)*

---

## Phase 1: Consolidate into one repository

- [x] ✅ **P1.1 [CC] Create the monorepo skeleton** in `mxngl/concho` *(done 2026-09-26: concho #1 + CLAUDE.md in #2)*:
  ```
  concho/
    engines/
      common/        # config loading, QTO parsing, units, Uniformat reference
      tvd/           # from AutoTVD (compute only, no HTML)
      stv/           # from IPD_Challenge/src/STV_Engine (canonical)
      schedule/      # from IPD_Challenge planning + takt engines (Phase 3B)
    revit-addin/     # from IPD_Challenge/QTO
    data-api/        # Phase 5
    agent/           # n8n workflows, prompts, Discord bot, docker-compose (Phase 6)
    dashboards/      # static TVD / STV / schedule pages reading JSON (Phase 7)
    template/        # the per-team data repo template (Phase 5)
    docs/
    tests/
  ```
  - `pyproject.toml` (Python 3.11+), pinned dependencies, `ruff`, `pytest`, and a CI workflow running lint + tests.
  - `.gitignore` covering `bin/`, `obj/`, `__pycache__/`, `.claude/`, `.env`, `*.fbx`, `exports/**/raw/`.
  - AC: `pip install -e .` works and CI is green on an empty test.
- [x] ✅ **P1.2 [CC] Migrate the STV engine** *(done 2026-09-26: concho #3 merged; course-workbook target test passes; the "identical output on the fixture" check follows in P2.2)* from `IPD_Challenge/src/STV_Engine`. It is more complete than the AutoSTV copy, which is missing `central_bim.py` and `workbook_inputs.py` and has a different `cli.py`.
  - Diff both `cli.py` files and document the differences in the PR.
  - AC: the engine runs from the new package with identical output on the fixture (after P2.2).
- [x] ✅ **P1.3 [CC] Migrate the TVD engine** *(done 2026-09-26: concho #4 merged; equivalence 4/4 vs. `island-2026-final`, 78/78 tests verified)* from AutoTVD. Split out the computation (reading QTO + cost DB → results dict) from the HTML rendering; keep the rendering temporarily as `dashboards/tvd/legacy_render.py`.
  - AC: identical `results/latest.json` on the fixture (after P2.2).
- [ ] 🟡 **P1.4 [CC] Migrate the Revit add-in source** *(PR concho #6 open, CI green, verified; tick after merge)* (`QTO/*.cs`, `.csproj`, `.addin`) without build artifacts.
- [x] ✅ **P1.5 [CC] Migrate the n8n workflow as a reference.** *(done 2026-09-26: concho #5; scrubbed export + README, Discord-ID check for `agent/` in `check_forbidden.py`)* Export "Island AI Agent" (read-only via n8n MCP `get_workflow_details`) to `agent/workflows/legacy/island-ai-agent.json`.
  - **Scrub first:** webhook path, the GHSAT token, and Discord guild and channel IDs → placeholders.
  - AC: the file contains no secrets or IDs (add a grep check to CI).
- [x] ✅ **P1.7 [CC] Migrate the schedule engines** *(done 2026-09-26: concho #9)* from `IPD_Challenge/src/Planning_engine` (ALICE_BIM_mapper, Micro_Schedule_Generator, Prefab_BIM_Mapper, Fuzor_Mapper, Logistics_Analysis), `src/Takt_engine` and `src/takt_zone_calibrator.py` into `engines/schedule/`, **without** generated outputs (the 16 MB Fuzor XML, the 2.7 MB micro schedule, HTML viewers, FBX).
  - Replace path constants that walk up the repo (`PROJECT_DIR = ...parents[2]`) with explicit input/output arguments.
  - AC: each generator runs from the package via a CLI with explicit paths.
- [ ] **P1.6 [HUMAN] Archive the old repos** after Phase 2 passes. Add a README banner pointing to the new repo.
  - **AutoTVD: set to private** (replaces the GitHub Support request from P0.3; old commits stay reachable via PR refs until then). Preconditions (0): the golden-test fixtures (P2.1) no longer clone AutoTVD publicly, i.e. they moved to a private fixture repo; (1) the fork count is 0, since forks of a public repo stay public; (2) Concho and the dashboards no longer read from AutoTVD (GitHub Pages and `raw.githubusercontent.com` URLs stop working for private repos).

---

## Phase 2: Regression baseline (before any refactor)

- [x] ✅ **P2.1 [CC] Build a private fixture set.** *(done 2026-09-26: concho #7)* *(Plan 2026-09-26: while AutoTVD/AutoSTV/IPD_Challenge are public, `scripts/fetch_fixtures.py` clones them at `island-2026-final` / `989a6b7` into a git-ignored `.fixtures/` and verifies the §1 checksums; a CI job runs the golden tests from there. Switch to a private fixture repo before AutoTVD goes private in P1.6.)* Because `mxngl/concho` is public, fixtures containing course or RSMeans-derived data go to a **private** location (e.g. a private `concho-fixtures` repo or a local path via env var `CONCHO_FIXTURES_DIR`; tests skip if unset). Only non-sensitive fixtures go under `tests/fixtures/`. Contents:
  - the Island QTO CSVs used for the 2026-05-01 run;
  - `cost_data.csv` as-is (with its known errors, for reproducibility);
  - the STV structural, MEP and architecture schedules used for `stv_project`;
  - the expected output JSONs.
- [x] ✅ **P2.2 [CC] Golden tests.** *(done 2026-09-26: TVD via the P1.3 equivalence test, STV via concho #7)*
  - TVD: grand total `16,065,644.29`, per-cluster estimates, and `unmapped_count = 1693`.
  - STV: targets (7,396,873.85 / 155,969,076.59 / 271,387,397.26) and the project breakdown.
  - AC: the tests pass against the migrated engines.
- [x] ✅ **P2.3 [CC] Resolve the STV discrepancy** (1,960,144 vs 2,517,183 kgCO₂e). *(done 2026-09-26, concho #7: 2,517,183.14 is current, 1,960,144 is a stale March snapshot; Concho switched to the current value.)*
  - Identify the inputs and code version that produced each file and document which one is "current".
  - Pin the golden test to the correct one.
  - AC: a short written explanation in `docs/engines/stv.md`.
- [x] ✅ **P2.4 [CC] Course-equivalence test for STV.** *(done 2026-09-26: concho #8; follow-ups in P3.10)*
  - Load the course workbook from `COURSE_STV_XLSX` (env var; skip if unset).
  - Write the fixture construction items and use-phase inputs into `Construction and Materials` and `Use Phase`.
  - Recalculate with LibreOffice headless (`soffice --headless --convert-to xlsx`) or the `formulas` library.
  - Compare against the engine within 1e-6 relative.
  - Also cover the toilet-factor edge case (see §1) and decide whether to match the course behavior.
  - AC: the test passes locally with the workbook present.
- [x] ✅ **P2.5 [CC] Course-equivalence test for TVD line items.** *(done 2026-09-26: concho #8)* Given the same line items (unit cost × quantity per Uniformat subcode), the engine totals match the course cluster sheets.
- [ ] 🟡 **P2.6 [CC] Golden tests for schedule.** *(Largely covered by the P1.7 equivalence tests in concho #9: macro schedule and takt schedule checksums, all 14 steps reproduced. Still open: regenerate a current `Micro_Schedule.csv` as the new reference, and write down the deck-vs-file differences.)* Pin the Island outputs of the migrated schedule engines:
  - macro schedule (`Macro_Schedule.csv`: 37 tasks, first task starts 2029-10-01; the deck mentions 32 tasks → 48 parallelized tasks, so clarify which set is meant);
  - micro schedule row count and first/last dates (the deck states Oct 1, 2029 – Mar 22, 2030 and 246 → 177 days after parallelization; **verify against the files and document any mismatch**);
  - takt planner Level 1: 16 zones, 192.36 working hours, crew utilization per trade;
  - delivery-window summary metrics.
  - AC: the tests pass on the migrated engines; any deck-vs-file differences are written down in `docs/engines/schedule.md`.

---

## Phase 3: Configuration and generalization

- [x] ✅ **P3.1 [CC] `project_config` schema** *(done 2026-09-26: [concho #10](https://github.com/mxngl/concho/pull/10))* (pydantic + exported JSON Schema, `template/project_config.example.json`). Fields:
  - `project`: name, team_name, location, currency, gross_sf, completion_date
  - `stv`: `course_team` (enum of the 7 course teams), `lifetime_years` (default 50), `use_phase` (grid_kwh, onsite_renewable_kwh, natural_gas_m3, cogeneration{...}, water fixtures{...}, landscaping_gal, rainwater_gal)
  - `tvd`: `budget` (grant, grant_year, construction_year, inflation, roi) **or** an explicit `total_target`; `cluster_split` (explicit % or `derive_from_references` with the reference columns and `owner_ratings` + `reallocation_pct`, mirroring the course sheets); optional `custom_clusters` (flagged non-course)
  - `agent`: language defaults, model names, discord channel mapping (by env var name, not value)
  - AC: the schema validates the Island example; a clear error on any missing required field.
- [ ] **P3.2 [CC] Remove every hardcoded project value.** Also remove the temporary per-file ruff ignores for `engines/stv/*.py` (added in P1.2 to keep the migrated code verbatim) and fix the lint findings.
  - `TOTAL_TARGET`, `CLUSTER_TARGETS`, `GROSS_SF`, `grandTotal / 30000` in JS, all "Island Team 2026" strings (HTML, PDF, image export).
  - Fix `GITHUB_REPO_RAW` or remove it.
  - Handle "Special Contruction" via a canonical cluster enum (A–H per the course) + display names.
  - AC: `grep -ri "island\|30000\|16_700_000\|san juan" engines/ dashboards/` finds nothing outside fixtures and examples.
- [ ] **P3.3 [CC] Cluster target consistency.**
  - The engine validates that cluster targets sum to the total target (tolerance configurable) and fails otherwise.
  - Custom clusters (e.g. "Equipment Rental") must be either carved out of the total or explicitly marked "on top".
  - AC: the Island config either passes with an explicit override or reports the $405,852 gap.
- [ ] **P3.4 [CC] New cost DB format + validator.**
  - `cost_db.csv` with columns `cluster, assembly_code, group, description, unit, unit_cost, quantity_rule, quantity_value, qty_reliability, cost_reliability, source`.
  - Plain decimal numbers only.
  - `quantity_rule` ∈ `takeoff | fixed | per_gsf | pct_of_subtotal | mirror:<AC> | count_codes:<AC,...>`, which replaces the hardcoded GC/contingency lump sums, `QUANTITY_MIRRORS`, `TOILET_ACS` and `AC_KEYWORD_SPLIT` (keyword split becomes `split_keywords`).
  - Validator: Uniformat code exists in the reference list (`engines/common/uniformat.csv`), unit is known, number parses, no duplicates, the reliability ratings are 1–3.
  - Include a migration script from the old `cost_data.csv`, and emit a warning list for the D5030/D5090 mislabels.
  - Ship the template with an **empty cost DB** (no RSMeans data).
  - AC: the Island fixture converts, and the golden test still passes (with the old codes kept in the fixture).
- [ ] **P3.5 [CC] TVD course features.**
  - Target derivation per the course (budget formula, reference average, owner reallocation) from config.
  - Reliability summary (Low/Medium/High by cluster) in the results JSON.
  - Tracking events (label + note per snapshot).
  - AC: with the course workbook's sample inputs, the engine reproduces the course `TVD Targets` column N values.
- [ ] **P3.6 [CC] STV mapping table keyed on Uniformat.**
  - `stv_mapping.csv`: `assembly_code, [category], [keyword], stv_assembly, stv_material_type, quantity_field (area|volume|length|count), conversion (e.g. cf_to_cy, density_kg_per_cf=...), note`.
  - Replace the family-name and keyword logic in `revit_architecture.py`, `revit_structural.py` and `revit_mep.py` with this table.
  - Ship a default table for common codes.
  - Output a coverage report: mapped % by element count and by quantity, plus a list of unmapped types.
  - AC: the Island results reproduce within tolerance using an Island mapping file, and the coverage report shows in the results JSON.
- [ ] **P3.7 [CC] Custom materials extension.**
  - `custom_materials.csv` with the same columns as `LCA Data` plus `source` (EPD reference) and `is_course_data=false`.
  - Engineered bamboo becomes an explicit entry. The Island fixture keeps the glulam proxy by default but documents it.
  - Dashboards and Concho answers must label results that rely on custom materials.
  - AC: a unit test with a custom material; the dashboard shows the flag.
- [ ] **P3.8 [CC] Use-phase completeness.**
  - Use-phase inputs are required in the config (explicit 0 allowed but must be stated).
  - Warn in CI and on the dashboard when all use-phase values are 0.
  - Allow PV as an `Energy` construction item (the course catalog has "Photovoltaics (sf)").
  - AC: the Island config either contains the slide values (162,000 kWh/yr use, 216,992 kWh/yr PV, 187,000 gal/yr water, 12,610 SF collection area) or an explicit "not modeled" flag.
- [ ] **P3.9 [CC] Document the "Parts" decision** (also from P2.3: three floor elements may be counted twice, in both the architecture and structural exports; deduplicate by ElementId across disciplines) (note from P1.4: the add-in exports Revit parts and skips a floor/ceiling that has parts, so parts are the counted representation there) (166 unmapped structural `Parts`): excluded to avoid double counting, or mapped. Implement the decision as a mapping rule.

- [ ] **P3.10 [CC] Engine fixes and decisions from the course-equivalence tests (P2.4/P2.5).**
  1. **Fix (bug):** `engines/stv/reference.py` reads cogeneration fuel water from `Cogen Data` column F (MJ) and ODP from G (H₂O); the course uses G (H₂O) and H (ODP). Fix, then extend the P2.4 cogeneration test to water and ODP. Island itself uses no cogeneration, so the Island golden values stay unchanged (verify).
  2. **Decide:** rainwater credit cap. Course: min(collected, toilet + urinal + landscaping water); engine: min(collected, total water use). Proposal: follow the course (course-logic rule).
  3. **Decide:** toilet 0.75 factor. Course applies it whenever the urinal cell is non-blank (even 0). Proposal (with P3.1): `urinal_gpf: null` = no urinals (factor 1.0), explicit `0` = course behavior (0.75).
  4. Round TVD line totals only for display, not in stored results (source of the 9.6e-8 deviation), or document the cent rounding.
  5. Docs: `libreoffice-calc` as a prerequisite for the course-equivalence tests; `tests/README.md` mentions `COURSE_TVD_XLSX`.
  6. **Tell Renate/course:** TVD Summary C25 ("C3030 Ceiling Finishes") references `'B Shell'!T30` (B3010 Roof Coverings) instead of C Interiors, so B3010 is counted twice and C3030 is dropped in the summary.
  - AC: after the fixes, P2.4/P2.5 tests compare water/ODP for cogeneration too and all pass; decisions 2 and 3 recorded in `docs/decisions.md`.

---

## Phase 3B: Schedule generalization (main scope, parallel to Phase 3)

Today the schedule chain is ALICE macro (XLSX) → ALICE_BIM_Map → micro schedule → takt planner / Fuzor 4D / Manufacton production orders / delivery-window analysis. It is tuned to the bamboo design (task sets, 7 days of curing, parallelization rules in code) and depends on licensed tools.

- [ ] **P3B.1 [CC] Tool-agnostic schedule input contract.**
  - `macro_schedule.csv` with `task_id, task_name, start, end, crew_type, equipment_type, predecessors, uniformat_codes`. Teams can author it by hand, in Excel, or export it from any scheduler.
  - An **optional ALICE adapter** converts ALICE exports into this format; an optional P6 XML import/export.
  - AC: the engine runs end-to-end on a hand-written CSV with no ALICE files present.
- [ ] **P3B.2 [CC] Planning rules to config.** Move task sets, curing days, parallelization logic (level-by-level: structure → enclosure → interiors) and crew/equipment productivity from `generate_micro_schedule.py` and code constants into `schedule_rules.json` (extending the existing `micro_schedule_rules.json`), with the Island rules as an example file.
  - AC: `grep` finds no bamboo- or Island-specific task names or durations in engine code.
- [ ] **P3B.3 [CC] Link tasks to elements via Uniformat** (+ optional category/level filters), replacing the family-based `ALICE_BIM_Map.csv`. Report tasks with no elements and elements with no task.
  - AC: coverage report in the results JSON.
- [ ] **P3B.4 [CC] Takt planner for all levels.** Takt zones from config or from room boundaries (`*_Room_Boundaries.csv`) with a configurable rooms-per-zone rule. Trade sequence configurable (today fixed: walls → MEP → ceiling → doors → finishes). Output JSON (zones, schedule, crew utilization) instead of HTML with baked-in values.
  - AC: runs for every level of the fixture; output validates against a schema.
- [ ] **P3B.5 [CC] Deliveries and logistics.** Delivery-window analysis (daily vs. 3-day vs. weekly) driven by config; outputs per-day deliveries and on-site inventory as JSON.
- [ ] **P3B.6 [CC] Optional tool adapters (depend on D8).** Fuzor 4D build-code export/push, Manufacton parts/assembly/order imports, the Revit "push 4D build code / kit / assembly" commands. Keep them as separate modules behind flags so the core runs without them.
  - AC: the core pipeline passes with all adapters disabled.
- [ ] **P3B.8 [CC] Fix the bugs found in P1.7** (each with a test and a before/after note on Island numbers): takt calibrator drops the last polygon corner; add a generator for `room_takt_zones.csv`; Manufacton orders step fails on the reference data; delivery windows must run without Manufacton outputs; remove hardcoded Island assemblies from the Manufacton code; make the micro schedule work on pandas 3 (then lift the 2.3.3 pin). Make `--rooms-per-zone` a config value (Island used 2, default is 1).
- [ ] **P3B.7 [CC] Schedule configuration in `project_config`:** start date, work calendar (hours/day, workdays, holidays), hurricane or weather windows as blocked periods (Island example: Jun–Oct, peak Aug–Oct), and the target completion date.

---

## Phase 4: Revit extraction that any team can install

- [ ] **P4.1 [CC] Make the add-in portable.**
  - `.addin` with a relative `<Assembly>` path.
  - Replace the hardcoded `HintPath` with a Revit API NuGet reference (e.g. `Nice3point.Revit.Api.RevitAPI`) and multi-target:
    - `net8.0-windows` for Revit 2025/2026
    - `net48` for Revit 2024 and older, if D8/D2 require it
  - Choose the output folder via a config file next to the DLL or a folder dialog, instead of searching upward for `revit_schedules`.
  - AC: builds without Revit installed (CI on `windows-latest`).
- [ ] **P4.2 [CC] Release pipeline.**
  - A GitHub Action builds the DLL per Revit version and attaches a zip to each GitHub Release (DLL + `.addin` + `install.ps1`).
  - `install.ps1` copies the files to `%AppData%\Autodesk\Revit\Addins\<version>\`.
  - AC: a release artifact is produced for each supported version.
- [ ] **P4.3 [CC] Export contract.**
  - Document the CSV columns (`docs/model-requirements.md`), including the required `Assembly Code`.
  - The add-in shows a summary dialog after export: element count, % with Assembly Code, and a list of missing codes by category.
  - Add the missing `Assembly Code` column to the **MEP** export (found in P1.4); Structural and Architecture already have it.
  - Decide whether Push Kit / Push Assembly get registered in the `.addin` or are removed (they're a subset of Push Manufacton Parameters), and update the `.addin` descriptions that still refer to `src\Planning_engine\...`.
  - AC: the dialog text is implemented; the doc lists every column.
- [ ] **P4.4 [CC, optional, time-boxed 2 days] Spike: cloud extraction via the APS Model Derivative API** (properties incl. Assembly Code and quantities from ACC). Deliver a written go/no-go only.

---

## Phase 5: Pipeline and data layer (fixes the context-window problem)

**Principle: the LLM never reads raw files. Tools call parameterized queries that return small, computed results.**

Measured on the Island central model: raw 3.4 MB (~860k tokens) → aggregate by category × type × level × Assembly Code = 218 rows (~2.9k tokens).

- [ ] **P5.1 [CC] Team data repo template** (`template/`):
  ```
  project_config.json
  cost_db.csv
  stv_mapping.csv
  custom_materials.csv
  macro_schedule.csv
  schedule_rules.json
  exports/            # Revit CSVs (latest only; history via releases)
  .github/workflows/pipeline.yml
  ```
  The workflow installs the `concho` engines at a **pinned version**.
- [ ] **P5.2 [CC] Pipeline** (`pipeline.yml`), on push to `exports/**`, the config or the DBs:
  1. validate config + DBs + exports;
  2. TVD;
  3. STV;
  3b. schedule (micro schedule, takt, deliveries);
  4. build `results/<timestamp>/` + `results/index.json`;
  5. ingest into SQLite (`concho.db`);
  6. build dashboards;
  7. deploy GitHub Pages;
  8. push the DB/summaries to the data API (per D2);
  9. post to the team's Discord webhook (secret), including a **budget alert** when the TVD estimate exceeds the target (replaces the retired AutoTVD n8n alert, see P0.1).

  AC: a push of a new export updates the dashboards and Concho's data without manual steps.
- [ ] **P5.3 [CC] Ingest + summaries.** Normalize all element data into `elements` and all results into `tvd_line_items`, `tvd_clusters`, `stv_items`, `stv_summary`, `schedule_tasks`, `schedule_element_tasks`, `takt_zones`, `deliveries`, `snapshots` and `data_quality` tables.
  - Precompute: totals, per cluster, per level, per category × level × AC, and data quality (unmapped %, missing parameters).
  - AC: a schema doc exists, and a summary JSON stays under 10 KB.
- [ ] **P5.4 [CC] Data API** (FastAPI, one tenant per team, bearer token). Endpoints:
  - `GET /cost/summary`
  - `GET /cost?cluster=&ac=`
  - `GET /cost/what_if?ac=&change_pct=` (computed server-side, e.g. "roof +10%")
  - `GET /carbon/summary`
  - `GET /carbon?stv_assembly=&material=`
  - `GET /carbon/what_if?material_from=&material_to=&ac=`
  - `GET /quantities?category=&level=&ac=`
  - `GET /elements/count?...`
  - `GET /schedule/summary` (start, finish, duration, milestones, critical dates)
  - `GET /schedule/tasks?date=&level=&trade=` and `GET /schedule/phase?name=`
  - `GET /schedule/element?element_id=` (install date and task)
  - `GET /takt?zone=&level=` and `GET /takt/utilization`
  - `GET /deliveries?date=|week=`
  - `GET /quality`
  - `GET /snapshots` and `GET /compare?a=&b=`
  - `POST /sql` (read-only, SELECT only, row cap; optional, behind a flag)

  **Hard caps:** ≤ 50 rows and ≤ ~8k tokens per response; otherwise return `{"error": "too_many_results", "hint": "filter by level or category"}`.
  AC: every response in the golden eval (P6.8) is under the cap; a unit test covers the caps.
- [ ] **P5.5 [CC] Snapshots and history.**
  - Automatic per pipeline run (timestamp, commit SHA, label from the commit message or config).
  - Dashboards read `results/index.json`, which replaces the hardcoded `RUNS` in the AutoSTV `index.html` (currently broken because the snapshot folders have no `history.json`).
  - AC: the dashboard lists every snapshot with no code change.

---

## Phase 6: Concho agent rebuild

- [ ] **P6.1 [HUMAN+CC] Hotfix the legacy workflow**, only if Island's Concho must keep running meanwhile, and only with approval:
  1. connect or remove the MATERIAL branch;
  2. remove `get_alice_bim_map` from the BIM prompt;
  3. case-insensitive "contains" switch + a fallback output;
  4. debug nodes → `send` + error outputs on all agents;
  5. `get_alice_macro` → `Macro_Schedule.csv`;
  8. ✅ *(done 2026-09-26)* Carbon Agent prompt units corrected to MJ and kg (TOOLS and RULES lines).
  6. ✅ *(done 2026-09-26)* "Simple Memory" session key re-pointed to `Webhook w/ Auth` and memory enabled;
  7. memory is attached only to the Router Agent (which just classifies), so subagents still don't see earlier messages: attach memory to the subagents or pass the history into their prompts. Note that Simple Memory is in-process and is lost when n8n restarts (persistent memory is P6.4).
- [ ] **P6.2 [CC] New workflow design** (`agent/workflows/concho.json`):
  - **Input normalizer:** Discord / Telegram (voice → Whisper) → `{message, user_id, channel_id, source, attachments}` in one Set node, so no node references like `$('Edit Fields Discord')` are needed downstream.
  - **Router:** gpt-4o-mini with **structured output** (enum `COST|CARBON|QUANTITY|SCHEDULE|GENERAL|OTHER`; extensions add `TRANSCRIPT` and `CLASH` when enabled), plus a fallback branch that asks a clarifying question.
  - **Subagents** use **only data API tools** (P5.4). Max 2 tool calls, answer in the user's language, cite numbers and snapshot dates, label custom-material or proxy results.
  - **Reply** to the originating channel or thread and mention the user.
  - **Global error handler:** an error workflow posts a readable message to the user and details to the debug channel.
  - AC: the workflow imports into a clean n8n instance with only `.env` values set.
- [ ] **P6.3 [CC] Prompts as files.**
  - `agent/prompts/*.md` with placeholders (`{{PROJECT_NAME}}`, `{{LOCATION}}`, `{{COMPLETION_DATE}}`, `{{TEAM}}`), filled from config or env at import time by a script.
  - AC: no project-specific string in any prompt file.
- [ ] **P6.4 [CC] Memory.**
  - A window of the last N=6 messages per user and channel, persisted (Postgres) with 30-day retention.
  - AC: a follow-up question ("and on Level 2?") works in the eval.
- [ ] **P6.5 [CC] Schedule subagent.** Uses only the `/schedule`, `/takt` and `/deliveries` endpoints; answers with dates, durations, task names and the snapshot date; states the work calendar and blocked weather windows when relevant.
  - AC: "What's happening on Level 1 on Dec 15?", "When is superstructure complete?" and "How many deliveries in week X?" answer correctly in the eval without any tool response over the cap.
- [ ] **P6.6 [CC] Deployment bundle.**
  - `agent/docker-compose.yml` with n8n, Postgres, the Discord bot (from the existing `bot.py` pattern) and the data API.
  - `.env.example` listing every variable.
  - `scripts/import_workflows.sh` (`n8n import:workflow`).
  - AC: `docker compose up` + the import script yields a working Concho against the fixture data.
- [ ] **P6.7 [CC] Model configuration** in one place (env): router model, subagent model and TTS model. Default: gpt-4o-mini everywhere.
- [ ] **P6.8 [CC] Evaluation harness.**
  - `tests/agent_eval/questions.yaml` with 40+ questions and expected answers from the Island fixture: cost, carbon, quantities, schedule (dates, tasks, takt zones, deliveries), what-if, multi-language (DE/ES/PL), follow-up and out-of-scope.
  - `scripts/run_eval.py` posts each question to the webhook and scores numeric match, language match, latency and tool-response size.
  - AC: ≥ 90% correct, 0 context overflows, p95 latency < 20 s.

---

## Phase 7: Dashboards

- [ ] **P7.1 [CC] TVD dashboard as a static page** reading `results/*.json` (no HTML in Python f-strings). Keep the existing features (clusters, line items, history, compare, PDF/JPG export, dark mode), and add the reliability summary and the target-sum warning.
- [ ] **P7.2 [CC] STV dashboard** on the same data contract. Fix the units found in P2.3: the old dashboard labels energy as kWh and water as L, but the engine reports **MJ** and **kg**; the old PDF export falls back to the February run.
  - Show a "construction vs use phase" split, a use-phase-missing warning, a custom/proxy-material flag and mapping coverage.
- [ ] **P7.3 [CC] Schedule dashboard:** macro Gantt, milestones, blocked weather windows, takt planner for all levels (zone map + utilization), and deliveries per day. It replaces the current Takt Planner page. The 3D viewer is optional; its FBX goes to release assets, not git.
- [ ] **P7.4 [CC] One design system and project name from config** for all dashboards and the PDF export.
- AC for Phase 7: all dashboards render from the fixture and from an empty new project without errors.

---

## Phase 8: Documentation and onboarding

- [ ] **P8.1 [CC] `docs/` site** (GitHub Pages, MkDocs or similar):
  1. **Quickstart** (goal: first Concho answer within 60 min of cloning the template)
  2. **Model requirements** (Uniformat tagging from week 1, required parameters, naming, export)
  3. **Setup** (config, cost DB, STV mapping, custom materials, macro schedule + rules, Discord bot, keys)
  4. **Weekly operation** (export → push → dashboards → Concho)
  5. **Using Concho** (example questions, limits, how to cite)
  6. **Troubleshooting** (unmapped elements, failed pipeline, bot silent, context/size errors)
  7. **Data and privacy** (what goes to the LLM provider, transcripts, retention, GDPR note for EU members)
  8. **How the engines work**: STV mapped to the course workbook cells (targets incl. `6.38e6`/`1.51e8` from the course, embodied, use phase × 50 years, water assumptions of 900 occupants / 250 days) and TVD mapped to the course method (budget, reference split, owner reallocation, cluster sheets, reliability, tracking), the schedule chain (macro → element linking → micro schedule → takt → deliveries, and which tool adapters are optional), plus a "course data vs team data" table
  9. **Known assumptions** (bamboo → glulam proxy, Parts handling, reliability rating meanings)
- [ ] **P8.2 [CC] `README.md`** (short, links to docs), `CONTRIBUTING.md`, `CODEOWNERS` (engines/STV: Ash; engines/TVD + agent: Max; per D7), `CHANGELOG.md`, `LICENSE` (per D4).
- AC: a person who hasn't seen the project can follow the Quickstart on a clean machine (checked in P9.1).

---

## Phase 9: Pilot readiness

- [ ] **P9.1 [CC+HUMAN] End-to-end dry run** with a **non-Island** model (e.g. an Autodesk Revit sample project) from a fresh template clone:
  1. export
  2. push
  3. pipeline
  4. dashboards
  5. 10 Concho questions

  Record the time taken and every friction point; fix them or document them.
- [ ] **P9.2 [CC] Cost and usage estimate** per team per semester: tokens per question × expected questions, plus hosting. Put it in `docs/operations.md` for Renate.
- [ ] **P9.3 [CC] Pilot checklist + a one-page overview for Renate** (what teams get, what they must do, support contact, known limits).
- [ ] **P9.4 [HUMAN] Pilot with 1–2 teams**; collect feedback weekly; triage it into a backlog.

---

## Phase 10: Extensions (after the main scope works)

Extensions are optional modules that a team switches on in `project_config`. The core must pass all tests with them disabled.

- [ ] **P10.1 [CC] Meeting transcript module** (rebuild; see D9 for the old one).
  - A Discord command or attachment upload of a VTT → store privately (never in git) → chunk with speaker + timestamp → embed or use a keyword index.
  - Extract action items once and post them to Discord.
  - Tools: `search_transcript(query, meeting_id)` → top-k chunks with speaker/time; `get_action_items(meeting_id)`. Router enum gains `TRANSCRIPT`.
  - Add a consent notice to the docs and the bot's reply footer; retention limit configurable.
  - AC: "who said X?" answers with speaker + timestamp without loading the full transcript.
- [ ] **P10.2 [CC] ClashBot module** (depends on D8 and D9). Each team needs its own APS app and ACC access. Credentials per team in `.env`; clash status (open/resolved, by discipline) via a `/clashes` endpoint with the same hard caps. Router enum gains `CLASH`.
  - AC: runs against a test ACC project; disabled by default.

---

## Suggested order and rough effort

| Phase | Depends on | Rough effort (part-time) |
|---|---|---|
| 0 Safety & freeze | – | 1–2 days (+ human decisions) |
| 1 Consolidate | 0 | 2–3 days |
| 2 Regression baseline | 1 | 3–4 days |
| 3 Config & generalization (TVD/STV) | 2 | 1.5–2 weeks |
| 3B Schedule generalization | 2 (+ D8) | 2–3 weeks (parallel to 3) |
| 4 Revit add-in | 1 | 3–5 days (parallel to 3) |
| 5 Pipeline & data API | 3, 3B | 1.5–2 weeks |
| 6 Agent rebuild | 5 | 1–1.5 weeks |
| 7 Dashboards | 5 | 1–1.5 weeks (parallel to 6) |
| 8 Docs | 3–7 | 4–5 days |
| 9 Pilot readiness | all | 1 week |
| 10 Extensions | 9 | 1–2 weeks each, optional |

The effort figures are estimates, not measured. With two people working in parallel (e.g. one on TVD/STV, one on schedule) Phases 0–8 fit roughly into 8–11 weeks of part-time work. Target: Phases 0–8 done before the 2027 course kickoff; Phase 9 in the first weeks of the course; extensions only once the core is stable.
