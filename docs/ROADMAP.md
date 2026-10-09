# Concho 2027 – Handover Roadmap for Claude Code

> **Goal:** turn Concho (Island Team 2026's AI project agent) and the data pipeline behind it (AutoTVD, AutoSTV, IPD_Challenge) into a tool that **each team of the next AEC Global Teamwork cohort can set up and run for its own project**, as a per-team template.
>
> **Owners:** Max Nagel and Ashmitha Jaysi Sivakumar (equal co-owners). **Stakeholder:** Prof. Renate Fruchter (Stanford PBL Lab).
> **Status of this document:** planning baseline, created 2026-09-26 from a review of all repos, deployments, the n8n workflow and the course workbooks.
> **Source of truth (since 2026-09-27):** `docs/ROADMAP.md` in the repo. Max and Ash change it via PRs; each task PR ticks its task and adds one progress-log line (see `CLAUDE.md`). The roadmap artifact is a read-only mirror.

---

## Progress log

**Overall status:** Phase 0 almost done (P0.1–P0.3 ✅, P0.4 🟡 waiting for Ash's IPD tag, P0.5 🟡 decisions partly open) · Phase 1 done except P1.6 (archive old repos; blocked while the golden tests still clone AutoTVD/AutoSTV/IPD_Challenge publicly and Concho still reads from them) · Phase 2 ✅ · Phase 3 almost done (P3.1–P3.11 ✅; P3.9 via concho #23, D15; open for Ash: DNC in STV, bamboo floor Parts proxy) · Phase 3B (now **Tier 2**, D13/D14): P3B.8 ✅ (#14); P3B.7/P3B.4 can start, the rest is reshaped around templates + skills (P3B.9, Ash) · Phase 4: P4.1–P4.3 ✅, P4.5 🟡 (add-in part done, INSTALL.md wording fixed in #20) · Phase 5: P5.1/P5.2/P5.5 Tier-1 part merged (#24), team pipeline pinned to `v0.1.0` · Phase 7: P7.1/P7.2/P7.4 Tier-1 part merged (#26; follow-ups open).

| Date | Update | Tasks |
|---|---|---|
| 2026-09-26 | Roadmap created; this page shared with Ash | – |
| 2026-09-26 | **Repo created: [`mxngl/concho`](https://github.com/mxngl/concho)** (public, empty, default branch `main`). Ash invited as collaborator. | D3 ✅, P1.1 🟡 |
| 2026-09-26 | **Concho webhook secured:** header auth enabled on the n8n webhook (unauthenticated POST → 403, with token → 200); Discord bot on the VPS sends the token from its `.env`; end-to-end test in `#askbim` answered correctly ($16,065,644.29). Telegram nodes removed from the live workflow. Open: remove the old GitHub raw token from the `get_stv_dashboard` URL. | P0.2 🟡 |
| 2026-10-09 | **P6.4/P6.6/P6.8 (Tier 1) done offline, PR link to be added when opened.** Chat memory (Postgres, last 6 messages per user and channel, 30-day purge, wired into router and subagents), deployment bundle (`agent/docker-compose.yml` with n8n, Postgres, bot, internal-only data API; `scripts/import_workflows.sh` creates the credentials), eval harness (54 questions, generated expected numbers, scorer), `agent.models` removed from `project_config.json`. Not run here: Docker, n8n, an LLM. **Open for Max:** the checklist in `docs/agent.md`. | P6.4 🟡, P6.6 🟡, P6.8 🟡, P6.7 🟡 |
| 2026-10-09 | **P6.2/P6.3/P6.7 (Tier 1) PR opened: [concho #30](https://github.com/mxngl/concho/pull/30).** Rebuilt Concho on the data API: `agent/workflows/concho.json` (webhook, one normalizer Set node, structured-output router, Switch with fallback, cost / carbon / quantity / general subagents on the P5.4 tools only with max 2 calls, no-tools fallback agent for SCHEDULE ("not available in this version") and OTHER, reply to the originating channel/thread, error branches) and `error-handler.json`; `agent/prompts/*.md` with the four placeholders rendered by `scripts/render_agent.py`; models from env (default gpt-4o-mini). 62 offline tests, no n8n or LLM run possible here. **Open for Max:** import the rendered workflows into a clean n8n and walk the checklist in `docs/agent.md`. Next: PR 2 (P6.4 memory, P6.6 bundle, P6.8 eval). | P6.2 🟡, P6.3 🟡, P6.7 🟡 |
| 2026-10-09 | **P5.3/P5.4 (Tier 1) PR opened: [concho #29](https://github.com/mxngl/concho/pull/29).** `engines/api/`: ingest of a team repo's `results/` + exports into SQLite (`elements` on the D15 rows, `tvd_line_items`, `tvd_clusters`, `stv_items`, `stv_summary`, `snapshots`, `data_quality`, precomputed `quantity_summary`, summary JSON < 10 KB) and a local FastAPI app (`concho-api serve`: bearer token from env, `/cost`, `/carbon`, `/quantities`, `/elements/count`, `/quality`, `/snapshots`, `/compare`, server-side what-if, `POST /sql` behind a flag; ≤ 50 rows / ~8k tokens, else `too_many_results`). Schema and endpoints in `docs/data-api.md`. No hosting, no n8n changes (D2 open); schedule/takt/deliveries follow with Tier 2. | P5.3 🟡, P5.4 🟡 |
| 2026-10-09 | **P7 follow-ups PR opened:** [concho #31](https://github.com/mxngl/concho/pull/31). `tvd_results.json` gets `unmapped_rows` (top 100 by area/volume/length + total), `stv_results.json` gets `project_name`, `mapping_coverage.rules[]` gets `proxy_note`; TVD/STV pages show them. Totals unchanged; with fixtures 894 passed, 102 skipped (all need the course workbooks, not available here). | P7.1 🟡, P7.2 🟡 |
| 2026-10-09 | **Merged: #27 (P2.1 follow-up) and #26 (P7.1/P7.2/P7.4 Tier-1 dashboards).** Island fixtures now live in the private repo `mxngl/concho-fixtures` (snapshot pinned in `checksums.json`, CI reads it via `CONCHO_FIXTURES_TOKEN`; `--source public` stays until P1.6). Static TVD/STV/overview pages ship as package data of `dashboards/`. Review fixes in #26: null-safe page content (no `nullnull`), the within-tolerance note, and the test folder `tests/dashboards/` renamed to `tests/site/` because it shadowed the real `dashboards` package (single-folder runs failed). Suite with fixtures and both course workbooks: 941 passed, 2 skipped (CI-only installed-package tests), 1 xfail. **Open follow-ups from #26:** unmapped TVD rows missing from the results JSON, `project_name` missing in `stv_results.json`, proxy-rule note missing in `mapping_coverage.rules`. | P2.1 ✅, P7.1 🟡, P7.2 🟡, P7.4 🟡 |
| 2026-10-08 | **P7.1/P7.2/P7.4 (Tier 1) PR opened:** [concho #26](https://github.com/mxngl/concho/pull/26). Static dashboards in `dashboards/site/` (overview, TVD, STV; vanilla JS, one stylesheet, no CDN) that read `results/` in the browser; `run_pipeline.py site` copies them, the legacy TVD page stays as `tvd/legacy.html` for one release; shipped as package data. | P7.1 🟡, P7.2 🟡, P7.4 🟡 |
| 2026-10-08 | **P2.1 follow-up PR opened:** [concho #27](https://github.com/mxngl/concho/pull/27). Island fixtures move to the private repo `mxngl/concho-fixtures`: `scripts/build_fixture_snapshot.py` copies exactly the files the suite reads (62 files, 28.5 MB, incl. the 13.9 MB `.fbx` that `test_schedule_equivalence.py` globs; found by tracing the full suite with `strace`, then validated by running it on the snapshot), `scripts/fetch_fixtures.py --source private` (default; `$CONCHO_FIXTURES_TOKEN` or own login, MANIFEST + checksums verified), `--source public` stays until P1.6; CI `reference` jobs get the token. 886 passed, 38 skipped, 1 xfail on the public clones and on the snapshot alone. **Open for Max:** push the snapshot and paste its SHA into `checksums.json` (CI on the PR is red until then). | P2.1 🟡, P1.6 precondition (0) |
| 2026-10-08 | **Merged: #24 (P5.1/P5.2/P5.5 Tier-1 template + pipeline), #23 (P3.9 duplicates across exports and Revit Parts, D15), #14 (P3B.8 schedule bug fixes).** CI on main green (all 7 jobs). Island references now: TVD 16,081,484.40 (legacy 16,065,644.29); STV per-trade 2,517,183.14, STV one run 2,459,374.64 (D15); schedule 2,776 zoned elements, 456 orders, delivery peaks 80 / 176 / 229. Open from #23 for Ash: DNC rows in STV (TVD skips them, STV counts them) and the bamboo floor Parts proxy (Concrete vs Wood System). The team pipeline pins Concho `v0.1.0`; the tag is still to be created. | P3B.8 ✅, P3.9 ✅, P5.1 🟡, P5.2 🟡, P5.5 🟡 |
| 2026-09-28 | **P5.1/P5.2/P5.5 (Tier 1) PR opened:** [concho #24](https://github.com/mxngl/concho/pull/24). Team repo template (`template/`: config, empty cost DB, default STV mapping, `exports/` + `course/` READMEs, private-repo quickstart) and `pipeline.yml` + `scripts/run_pipeline.py`: validate → TVD → STV (one run, all exports; skipped without the course workbook) → `results/<UTC ts>/` + `results/index.json` snapshots → index page + legacy TVD dashboard → Pages / artifact. Packaging fix: `engines/common/*.csv` now in the wheel. Budget alert (step 9) is a TODO. Open: Max creates the first tag (`v0.1.0`) after the merge. | P5.1 🟡, P5.2 🟡, P5.5 🟡 |
| 2026-09-28 | **P3.9 PR opened:** [concho #23](https://github.com/mxngl/concho/pull/23). One shared duplicate / Parts rule (D15, `engines/common/dedup.py`) for TVD and STV: Parts over their host; per ElementId, row with code > (STV) mapped row > owning discipline's export; `deduplication` block in both results JSONs; STV maps Parts via `Original Category`; `--combine-results` warns it cannot deduplicate; STV lists DNC rows (`dnc_rows`, DNC handling unchanged, separate decision for Ash). **Island:** TVD unchanged (no shared ElementIds / Parts in the AutoTVD exports, equivalence still byte-identical, no legacy switch); STV per-trade golden 2,517,183.14 unchanged, one run of the six Current exports 2,459,374.64 (−4,866 sf floor concrete counted twice before: 1789623, 1789655). 837 passed, 37 skipped (course workbooks), 1 xfail. | P3.9 🟡, D15 ✅ |
| 2026-09-27 | **P3.11 done, P4.5 engine part done** (concho #21 merged). Island TVD reference is now 16,081,484.40 (legacy/submitted 16,065,644.29 via `--legacy-length-parsing`). **Mail to the course lead sent** with the open questions D2, D4, D5, D7, D8 and D10. | P3.11 ✅, P3.10 ✅, P4.5 🟡 |
| 2026-09-27 | **Max + Ash sync (18:00, notes: Notion "Concho pilot meeting").** Decisions: **#14 merge as is** (Ash reviews the comments and merges); **D13 tiered rollout** (Tier 1 from course start: Revit add-in → takeoffs → TVD + STV automatically + Concho chat on them; Tier 2 later, released to teams that ask or in the second half: ALICE macro → micro schedule, Manufacton production orders / prefab assemblies / kit of parts / delivery windows; Tier 3: meeting transcripts, ClashBot); **D14 schedule positioning** (structured data + templates + Claude skills with defined inputs/outputs and the Island outputs as examples, no plugins; Manufacton is import-only, never synced back to Revit; ALICE only as macro-schedule source; Fuzor dropped from Tier 2); **D9 closed**: transcripts and ClashBot deferred until after the core rollout. Context: the course lead expects a productionised Concho that teams actually use; Stanford students have Claude education access, other members bring their own AI subscriptions; teams must enter their own RSMeans cost data (only a guideline is provided); STV needs no team data beyond the takeoffs. Hosting (D2) is the main open risk for the Discord/n8n part: lab server, per-team budget or a sponsor VPS, with local n8n per team as a limited fallback. Manufacton templates are public (not raised with Renate). The roadmap moves into the repo (`docs/ROADMAP.md`) as the shared source both owners edit via PRs; this page mirrors it. Mail to Renate drafted (Max sends, Ash in CC after her feedback). | #14 decided, D9 ✅, D13 ✅, D14 ✅, D2/D4–D8/D10 🟡 |
| 2026-09-27 | **P4.5 engine part + P3.11 PR opened:** [concho #21](https://github.com/mxngl/concho/pull/21), CI green. Shared tolerant quantity parser `engines/common/quantities.py` (plain decimals, feet-inch with whole/decimal/fractional inches, feet or inches only, SF/CF/LF/ft²/ft³ suffixes; metric m/mm/cm/m²/m³ converted and flagged `metric_converted`; unknown unit, wrong dimension, no number and ambiguous commas count 0 and are listed in a new `quantity_parse_warnings` block, raw cell text only); TVD uses it by default. **Island TVD corrected: 16,065,644.29 → 16,081,484.40 (+15,840.11, +0.099 %)**; only one priced line changes (C1010 interior partitions, 782.58 → 820.63 LF, Interiors +1.03 %), unmapped 1693 and DNC 75 unchanged; 16,065,644.29 kept as the legacy (submitted) reference. The AutoTVD equivalence test still proves byte-identical migration via the hidden `--legacy-length-parsing` flag; a new golden pins the corrected numbers. Old vs new layouts: no column was renamed or removed (MEP 60 → 71, TVD exports 44/47/56 → 58 columns); every column TVD/STV read exists in all layouts, new old/new-pair test gives identical totals; mapping in `docs/model-requirements.md`. **Independently verified:** no conflict with main or #14; ruff/forbidden/schema clean; **849 passed, 0 skipped, 1 xfail** with both course workbooks; own parser on the Island exports gives the same C1010 LF (coded LF overall 4,868.42 → 4,976.11, also in A1010, A1030, B1010, B2010, but those lines are priced per CY/SF, so only C1010 moves the total); Island exports produce 0 parse warnings; no cost-DB rows committed. Known limits (accepted): `1,234 SF` and German `12,5 m²` in old display-string exports count 0 with a warning instead of being guessed (not present in the Island exports; new add-in exports are invariant decimals). | P3.11 🟡, P4.5 🟡 |
| 2026-09-27 | **#20 merged** (P4.2 follow-up: INSTALL.md says **Run** / German **Ausführen** for `install.cmd`, plus German SmartScreen labels; docs only). **#14 re-verified after Max merged main into it** (`03f6c94`, `ci.yml` conflict resolved by keeping both new jobs `revit-addin` and `reference-pandas3`): content identical to the tested merge (only a missing final newline in `ci.yml`), no conflict with main incl. #20; ruff/forbidden/schema clean, **751 passed, 0 skipped, 1 xfail** on pandas 2.3.3 with both course workbooks (now available to this chat as project files, never committed), schedule golden + pipeline **128 passed** on pandas 3.0.6. Only Ash's review is left. **Finding for P3B.7:** the `schedule` section of `project_config` (start date, calendar, blocked windows, target completion, rooms per zone, trade sequence, adapter flags) already exists since P3.1, but no schedule step reads it yet; the micro schedule still has a hardcoded "Hurricane Contingency Buffer" task and a 2029-01-01 fallback anchor. | P3B.8 🟡, P3B.7 🟡, P4.5 🟡 |
| 2026-09-27 | **P4.1–P4.3 + P4.5 add-in part done** (concho #18 merged). Portable Revit add-in (Revit 2025/2026, NuGet API refs, CI build, release zips with `install.cmd`), export contract `docs/model-requirements.md`, unit-safe numeric export (imperial = metric, tested in Revit by Max), language-independent (English categories + `Category (local)`, built-in parameters), Parts with quantities, source code and `Part Source Id`. Open from P4.5: tolerant parsing of old display-string exports (with P3.11, PR #21), localized `Parameter Snapshot`, ~20 unverified rare category names (need an English Revit). Tiny follow-up: INSTALL.md button wording "Run"/"Ausführen" for install.cmd (done in #20). | P4.1–P4.3 ✅, P4.5 🟡 |
| 2026-09-27 | **P3.7 + P3.8 done** (concho #19 merged). Remaining Phase 3: P3.9 (Parts / double counting, decision at the Max/Ash sync), P3.11 (low priority). | P3.7 ✅, P3.8 ✅ |
| 2026-09-27 | **Revit retest of #18 (`fe30bad`, German Revit 2026) passed.** Categories English with `Category (local)` next to them; structural: 166 Parts now with Area/Volume, Assembly Code B1010 (from source) and `Part Source Id`, columns and foundations with Length, Assembly Code coverage 64.1 % → 96.8 %; architecture: 96 Parts of ceiling 1928172 are exported now (the German UI used to drop them via the English "ceiling" filter, so that ceiling was missing entirely before), no code because the ceiling type has none; every other element unchanged vs. the first test. Install: double-click on `.ps1` opens an editor and right-click → Run with PowerShell is blocked for downloaded scripts → `install.cmd` wrapper requested. **Data for P3.9:** structural Parts come from 3 floors (631022, 646198, 646504; ~58,900 sf / 29,400 cf together) that appear in neither export as whole elements; floor 1241457 (6,848 sf) is only in the architecture export in the current models. | P4.1–P4.3 🟡, P4.5 🟡 |
| 2026-09-27 | **P3.7 + P3.8 PR opened:** [concho #19](https://github.com/mxngl/concho/pull/19), CI green. Custom materials finalised (schema, validator, `is_course_data=false`, source required), results flag custom and proxy materials (Island: **570,612.51 kgCO₂e = 22.7 % of embodied rests on the bamboo → glulam proxy**); use phase must be set explicitly or `not_modeled`; PV as construction item; combining runs takes the use phase once (`--no-use-phase` deprecated). Bamboo: no public EPD readable from the session (candidate: GREEZU glued laminated bamboo, EPD-IES-0025126:001), so the proxy stays, flagged. Island reference unchanged (2,517,183.14). **New example `island_2026_use_phase`:** construction + 50 years = 2,769,566 kgCO₂e = 37.4 % of target (sensitivities: 44.4 % if PV only ~150,000 kWh/yr; 131.4 % without PV netting); use phase matches the team workbook exactly. Open data questions: PV area vs output; water (course formula 756,000 gal/yr gross, 359,817 net vs slide 187,000); annual PV netting; D5090 as the PV code. **Independently verified:** no conflict with main or #18; template custom materials empty; ruff/forbidden/schema clean; **695 passed, 0 skipped, 1 xfail** with both course workbooks. | P3.7 🟡, P3.8 🟡 |
| 2026-09-27 | **Revit test of #18 by Max** (Revit 2026, German UI, Island models ARCH / STR / MEP). Install script ok (asks before overwriting), exports and summary dialogs work. **Imperial vs metric: identical** in all four CSVs (rows, columns and every value incl. MEP `Size`/`Length`), only `Parameter Snapshot` differs, as intended — compared here column by column. Findings for #18: (1) German UI → localized category names (`Wände`, `Luftkanäle`), which the STV table and TVD can't match → export English category names from BuiltInCategory; (2) all 166 structural Parts export without Length/Area/Volume and without Assembly Code → part parameters + code from the source element; (3) other empty quantities: Tragwerksstützen Length 135, Wände Volume 76 (likely curtain walls), Möbel/Türen/Fassadenelemente Length (expected); (4) installer window closes on double-click; (5) vendor/assembly metadata. Short re-test needed after these fixes. | P4.1–P4.3 🟡, P4.5 🟡 |
| 2026-09-27 | **#18 updated (P4.1–P4.3 + P4.5 add-in part), CI + release workflow green.** Same numbers for imperial and metric projects (internal units → ft / SF / CF / kg; MEP dims in inches, flows m³/s); missing values stay empty and are counted in the summary dialog; Assembly Code via `UNIFORMAT_CODE` (Revit 2026: `ASSEMBLY_CODE`); new test `tests/revit_addin/test_export_format.py` shows TVD and STV read the new format unchanged. Side effects: some MEP numeric columns that used to hold text are now empty; Manufacton parts labels now decimal feet (check against the schedule/Manufacton steps). Test zips for Revit 2025/2026 in the PR. **Waiting for the human Revit test** (incl. imperial-vs-metric comparison). Island TVD under-read (P3.11): not relevant for Island any more, low priority. | P4.1–P4.3 🟡, P4.5 🟡 |
| 2026-09-27 | **P4.5 add-in part pushed to #18** (numeric export from Revit internal units, `UNIFORMAT_CODE` / Revit 2026 `ASSEMBLY_CODE`, main quantities via BuiltInParameter; MEP `Length`/`Size` as generated feet-inch text so STV needs no change). **New finding:** TVD's display-string parser drops fractional inches, so the old Island exports are ~3.5 % short in linear feet; this is inside the Island TVD reference too → new task P3.11. | P4.5 🟡, P3.11 ⬜ |
| 2026-09-27 | **P4.5 promoted:** teams with project sites outside the US likely model in metric, so the silent unit bug matters for the pilot. The add-in part (numeric export in the course's imperial units via `UnitUtils`, `BuiltInParameter.UNIFORMAT_CODE`) is added to PR #18 before the human Revit test. | P4.5 🟡 |
| 2026-09-27 | **P4.1–P4.3 PR opened:** [concho #18](https://github.com/mxngl/concho/pull/18), CI green incl. new Windows jobs `revit-addin (R25)` / `(R26)`. Revit API via Nice3point NuGet reference packages (compile only, no Revit needed), build configs for Revit 2025 and 2026, export folder from `concho_addin.json` next to the DLL (folder dialog on first run, no upward path search), release workflow (zip per Revit version with DLL, `.addin`, `install.ps1`, INSTALL.md; GitHub Release only on `v*` tags, PR runs only build artifacts), `docs/model-requirements.md` (every CSV column), MEP export gets `Assembly Code` as last column (STV importer checked: identical results), summary dialog after export, `.addin` descriptions fixed; Push Kit / Assembly / Manufacton unchanged pending the schedule-positioning decision. **Independently checked:** no conflict with main, no personal paths, install script asks before overwriting and unblocks the DLL, release job only runs on tags with `contents: write` scoped to it (no local .NET here, so the build itself relies on CI). **Needs a human test in Revit 2025/2026** (7-step checklist in the PR). New findings → P4.5. | P4.1–P4.3 🟡 |
| 2026-09-27 | **P3.6 done** (concho #17 merged). Next: P3.7 + P3.8 in one session (STV custom materials + use phase, incl. the `--no-use-phase` follow-up from P3.2); P3.9 after the Max/Ash sync decides which export counts for the 35 cross-discipline elements and the Parts. | P3.6 ✅ |
| 2026-09-27 | **P3.6 PR opened:** [concho #17](https://github.com/mxngl/concho/pull/17). STV importers (architecture, structural, MEP) now driven by `stv_mapping.csv` (discipline, Uniformat prefix, category, keywords with `a\|b` / `a&b`, priority, named quantity fields incl. `weight`/`airflow`, named conversions, fallback estimates flagged) + validator `concho stvmap validate` + JSON Schema; Island mapping file and a 23-rule default table in `template/`; `mapping_coverage` block per discipline. **Island identical:** 2,517,183.14 kgCO₂e, all 4,007 rows of the six exports map to the same material and amount as the old code. Coverage by element count: architecture 67.0 %, structural 66.9 %, MEP 88.8 % (11.2 % of MEP kgCO₂e rests on estimates); 166 structural Parts listed; **35 ElementIds appear in two disciplines** (e.g. 1241457), input for P3.9. Bamboo walls/floors are now explicit proxy rules (→ P3.7). **Independently verified:** no conflict with main or #14, ruff/forbidden/schema clean, **644 passed, 0 skipped, 1 xfail** with both course workbooks (incl. all STV course tests and the check of both tables against the course catalog); default table reviewed (keyword precedence: `\|` binds tighter than `&`, level-2 codes like D2000 match by prefix). | P3.6 🟡 |
| 2026-09-27 | **P3.5 done** (concho #16 merged). TVD now follows the course method end to end: budget, target derivation, reliability summary, tracking. Remaining Phase 3: P3.6 (running), P3.7, P3.8, P3.9; P3.10 item 6 (course mail). | P3.5 ✅ |
| 2026-09-27 | **P3.4 done** (concho #15 merged). **P3.5 PR opened:** [concho #16](https://github.com/mxngl/concho/pull/16). Reliability scale flipped to the course convention (1 = High … 3 = Low; overall = worse of quantity/cost); budget formula; cluster-split derivation (reference average K, owner shares G from value items rated per owner, owner-adjusted L = K × (1 − p) + G × p, team adjustment M, explicit `target_shares` = course column N) with a `target_derivation` block; `reliability` block (Low/Medium/High $ for quantity, cost, overall + not rated); tracking with `--event` / `--note` and a `tracking` table; Island example gets the 2029 hurricane window (schedule engines don't read it yet). Island: grand total unchanged, targets unchanged (A–H 16,705,852, shares sum 1.00035), everything "not rated", tracking delta +634,355.71. The session used a read-only download of the course TVD workbook from the course Drive; no workbook values committed (checked). Deviations from the course, documented in `docs/engines/tvd.md`: owner term (course G / C22 / 100 is only right at 10 %; at 25 % its shares sum to 0.79), `TVD Reliability` E14 → W30 and LOW totals without H. **Independently verified:** no conflict with main or #14; scan of the diff finds no workbook sample values or event names; ruff/forbidden/schema clean; **564 passed, 0 skipped, 1 xfail** with both course workbooks (incl. 7/7 TVD course-equivalence and 9/9 new course-method tests). | P3.4 ✅, P3.5 🟡 |
| 2026-09-26 | **P3.4 PR opened:** [concho #15](https://github.com/mxngl/concho/pull/15). New `cost_db.csv` format (+ `qty_label`, `split_keywords`) with pydantic model + JSON Schema, `concho costdb validate`, `engines/common/uniformat.csv` (NISTIR 6389 levels 1–3, public domain) + `uniformat_extensions.csv` (course codes H1000–H5000 only; X##00 level-2 codes accepted by rule), `scripts/migrate_cost_data.py`, empty template + invented example. Decisions taken in the session: duplicate key incl. description; unknown codes = error; TVD engine stops on validation errors and writes a `cost_db_validation` block (warnings + `unpriced` placeholder rows); old AutoTVD wording kept via `qty_label` set by the migration (no Island text in the engine); placeholder rows exempt from the description rule. Migrated Island DB: 48 rows, **0 errors**, 8 warnings (3 unpriced: A1020, C3030, F1000; Equipment Rental code check skipped; reliability not rated; D5030/D5090 mislabels listed, codes kept). **Independently verified:** no conflict with main or #14; no Island/RSMeans cost data committed (template and test rows invented); ruff/forbidden/schema clean; **524 passed, 0 skipped, 1 xfail** with both course workbooks (incl. the TVD course-equivalence test the session couldn't run); Island TVD unchanged (16,065,644.29 / 1693 / DNC 75). `uniformat.csv` has 7 / 22 / 79 entries on levels 1 / 2 / 3, which matches the UNIFORMAT II structure; titles follow NIST (they differ from the course's wording for D3050, E1020, E2010, G1030, G2040, which doesn't affect the code check). Optional: spot-check against the NISTIR 6389 PDF (nist.gov blocked from here). | P3.4 🟡 |
| 2026-09-26 | **P3.3 + P3.10 done** (concho #13 merged; P3.10 item 6, the mail to the course about TVD Summary C25, is still open for Max). **P3B.8 PR opened:** [concho #14](https://github.com/mxngl/concho/pull/14), CI green incl. new job `reference-pandas3`, one commit per fix. (1) Takt calibrator closes each polygon ring: 901 of 3,971 elements change zone (900 gain a zone, 1 moves; elements with zone 1,876 → 2,776); micro schedule only changes its copied `takt_id` column (931 rows), takt plan unchanged. (2) New step `room-takt-zones` (step 12, before `takt-plan`); rebuilds the committed file except 5 values from an older export (Zone 8 area +0.095 SF); takt schedule still 16 zones / 192.36 h. (3) Manufacton orders: root cause = sequential prefab group ids shifted by 16 new L -1 groups; mapping now keyed on `host_wall_element_id` (Revit ElementId, no UniqueId in any export); all four workbooks regenerate; 464 → 456 orders, 227 SL elements; **delivery peaks change from 44 / 87 / 155 to 80 / 176 / 229** (old workbooks came from an older model). (4) Delivery windows run without Manufacton inputs. (5) SL assemblies moved to `examples/island/prefab_assemblies.csv`, validated both ways. (6) pandas pin → `>=2.3.3,<4`; `reference` job stays on 2.3.3 via `ci/constraints-pandas2.txt`; equivalence test skipped locally on pandas 3, but fails under `CONCHO_REQUIRE_FIXTURES`. **Independently verified:** #14 merged with current main (incl. #13): ruff/forbidden/schema clean, **449 passed, 0 skipped, 1 xfail** on pandas 2.3.3 with both course workbooks; on pandas 3.0.6 all 143 schedule golden/pipeline tests pass and the equivalence guard behaves as designed. No conflict with main. **Ash to review before merge** (changes her code and the Island schedule reference). Follow-ups: 6 L -1 mapping rows skipped while L -1 exterior walls are unscheduled (→ P3B.2/P3B.3); room boundary plots not regenerated (unused). | P3.3 ✅, P3.10 🟡 (item 6), P3B.8 🟡 |
| 2026-09-26 | **P3.2 done** (concho #12 merged). **P3.3 + P3.10 PR opened:** [concho #13](https://github.com/mxngl/concho/pull/13), CI green (6 jobs), 11 commits. TVD engine checks A–H + carved-out clusters against the total target (`tvd.target_sum_tolerance`; explicit `tvd.target_sum_override` with a reason string), stops before writing results when outside tolerance; new `target_consistency` block in the results JSON. Island: A–H 16,705,852 vs 16,700,000 → gap 5,852 (0.035 %, within 0.1 %), Equipment Rental 400,000 on top → 405,852 incl. on-top, status `within_tolerance`. STV fixes: cogeneration water/ODP now read from `Cogen Data` G/H; rainwater cap follows the course (D12); toilet factor per D11 (urinal `null` = no urinals, `0` = course 0.75). TVD cent rounding documented, not changed. **No Island number changed** (TVD equivalence, STV golden, LAMARCASINA variant identical). **Independently verified:** no conflict with main, ruff/forbidden/schema clean, **course-equivalence tests with both workbooks 21/21 pass** (incl. new cogeneration, rainwater-cap and urinal-0 cases, which the session and CI couldn't run), full suite **429 passed, 0 skipped, 1 xfail**. Open from P3.10: Max tells the course about the TVD Summary C25 bug. | P3.2 ✅, P3.3 🟡, P3.10 🟡 |
| 2026-09-26 | **P3.2 PR opened:** [concho #12](https://github.com/mxngl/concho/pull/12), CI green (3 jobs). TVD engine, TVD dashboard and STV engine read `project_config` (`concho-tvd --config` required, `concho-stv --config` optional, `--team` stays as override); `island_defaults.py` removed; canonical cluster names ("Special Construction"); STV ruff ignores removed; new `meta.project_name`/`team_name` in the results JSON; second test config (River, 12,500 SF, $5M) changes exactly targets/deltas/$ per SF/names. Island numbers unchanged (16,065,644.29 / 2,517,183.14). AC grep: no project values left outside examples/docs (schedule hits belong to P3B). Fixes/decisions for the P3B.8 session: Q1 stable key (Revit UniqueId, else ElementId) for the 4D build-code mapping; Q2 separate `prefab_assemblies.csv`. **Independently verified:** fetched `refs/pull/12/head`, ruff clean, forbidden check + schema check OK, **402 passed, 0 skipped, 1 xfail** with fixtures and both course workbooks (the STV course-equivalence tests run fine here with LibreOffice), no conflict with main. Follow-ups: `--no-use-phase` is a workaround for double-counted use phase when combining per-trade STV runs (→ P3.7/P5: take use phase once from config at combine time); pre-existing `DeprecationWarning` (invalid escape `\s`) in `dashboards/tvd/legacy_render.py` (→ P7.1/P7.2); old history snapshots with "Special Contruction" lose colour/target in the comparison view; `derive_from_references` stops with a pointer to P3.5; on-top clusters stay outside the total (→ P3.3). | P3.2 🟡 |
| 2026-09-26 | **P3.1 and P2.6 done** (concho #10 and #11 merged). **Phase 2 complete.** Schedule refactors (P3B.2, P3B.8) unblocked. Next: P3.2 (TVD/STV/dashboards read `project_config`) and P3B.8 (schedule bug fixes) in parallel. | P3.1 ✅, P2.6 ✅ |
| 2026-09-26 | **P2.6 PR opened:** [concho #11](https://github.com/mxngl/concho/pull/11). `tests/fixtures/schedule_golden.json` pins all 43 outputs of the 14 schedule steps (masked sha256 + readable metrics incl. per-task start/end); `test_schedule_golden.py` reruns them in the CI `reference` job; `--update` regenerates after intended changes. New current `Micro_Schedule.csv` reference: 6,625 rows, 2029-10-01 → 2030-03-15. Mutation check (one curing lag 7 → 14 days) caught by 9 tests. Deck-vs-files table in `docs/engines/schedule.md`: several presentation values are **not reproducible** (end Mar 22 vs. engine Mar 15; substantial completion Feb 21; 246 → 177 days; the deck's own numbers give 28 %, not 41 %; delivery counts paired with the windows in reverse and are production orders, not assemblies). Independently verified: 180 schedule tests pass + 1 xfail, no conflict with main or #10. Follow-up: mention the golden test in `engines/schedule/README.md`. | P2.6 🟡 |
| 2026-09-26 | **P3.1 PR opened:** [concho #10](https://github.com/mxngl/concho/pull/10), CI green (6 jobs incl. schema-drift check). pydantic v2 schema + JSON Schema export, validator with actionable errors/warnings and a secret check, `concho config validate` / `schema`, Island + template examples, `docs/config.md`, D11 (urinal null vs 0) recorded. Island example validates with 5 warnings (A–H 5,852 over target within 0.1 % tolerance; Equipment Rental on top; use phase not modeled; cost DB and macro schedule not set). Independently verified: examples validate, 67 config tests pass, no conflict. Review notes → P3.5: course owner ratings are per value item from 2 owners (averaged per cluster), not one per cluster; course budget inputs confirmed at `TVD Targets` C5–C11 (targets col. N, reallocation % `TVD Owners` C22). Island example should also block the **2029** hurricane season (construction starts 2029-10-01, inside peak). | P3.1 🟡 |
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

**Next up:** (1) Tier 1: data API (P5.3 ingest + P5.4 FastAPI, one tenant per team, built and tested locally; hosting after D2), then the Concho workflow rebuild (Phase 6) on top of it; small #26 follow-ups can ride along; (2) P1.6 (old repos private/archived) once the golden tests no longer need the public clones (`--source public`) and the live n8n Concho no longer reads AutoTVD/AutoSTV; Ash tags IPD_Challenge; (3) Tier 2 by Ash: P3B.9 skills + README + examples, P3B.7/P3B.4; answers to the two #23 questions (DNC, bamboo proxy); (4) wait for the course lead's answers (D2, D4, D5, D7, D8, D10).

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
| TVD grand total | **$16,065,644.29** (legacy, submitted; after P3.11 / #21 the engine default gives **$16,081,484.40**, fractional inches read correctly) | AutoTVD `results/latest.json` (run 2026-05-01) |
| TVD total target | $16,700,000 | `tvd_analysis.py` |
| STV carbon target (Island) | **7,396,873.85 kgCO₂e** | course formula, team "Island" |
| STV energy target | 155,969,076.59 MJ | course formula |
| STV water target | 271,387,397.26 kg | course table |
| STV project carbon (file Concho reads) | 1,960,143.66 kgCO₂e: **stale** snapshot of 2026-03-30 (early exports, IPD `519a5c0`) | AutoSTV `outputs/stv_project/stv_results.json` |
| STV project carbon (dashboard "Current") | **2,517,183.14 kgCO₂e: current reference** (2026-05-15, `revit_schedules/Current/*`, trades combined) | AutoSTV `outputs/Current-.../project/stv_results.json` |
| STV project carbon (IPD `outputs/stv_project`) | 2,350,871.62 kgCO₂e: unused intermediate (2026-05-07, older arch export + LAMARCASINA use phase) | IPD_Challenge |

Schedule reference (P2.6, see `docs/engines/schedule.md`): current engine output runs 2029-10-01 → 2030-03-15 (166 days); takt L1 16 zones / 192.36 h; delivery-window peaks 44 / 87 / 155 production orders (1 day / 3 days / 1 week; **after P3B.8: 80 / 176 / 229**, 456 orders, 2,776 elements with a takt zone); several deck schedule values are not reproducible from the repo.

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
| D2 🟡 | Hosting model | **Main open risk for the Concho chat** (sync 2026-09-27): n8n workflows and the Discord bot must run on a server, otherwise the bot is offline whenever the host laptop is off. Options, asked in the Renate mail: (a) server run by the PBL Lab, (b) small hosting budget per team, (c) an industry sponsor provides a VPS. Fallback: each team runs the `docker-compose` bundle locally (works only while that computer runs, no phone access, data synced via git). Not blocking Phases 1–4; the dashboards (GitHub Pages) don't need it. |
| D3 ✅ | Where the new code lives | **Decided 2026-09-26: `github.com/mxngl/concho`** (public), Ash as collaborator. Old repos to be archived after Phase 2. A later transfer to a neutral org stays possible. |
| D4 🟡 | License (own code only) | **No LICENSE file until Renate confirms** there are no Stanford/course IP rules against it (default "all rights reserved" meanwhile). Max prefers MIT, Ash undecided (sync 2026-09-27). Asked in the Renate mail. Note: if the course workbooks were ever committed, an MIT license would cover them too, so they stay out unless Renate says otherwise (D5). Not blocking. |
| D5 🟡 | Course data redistribution | Workaround in place: engines read the course workbooks from a local path at runtime (env var), tests skip without them, nothing course-owned is committed; teams copy the workbooks from the course Drive into their local folder. Asked in the Renate mail: may teams use them through the tool, and may they be shipped with the repo (then they need a separate license note)? |
| D6 🟡 | LLM provider, keys and cost | Default stays: each team uses its own API key with a spending cap; default model gpt-4o-mini, configurable; cap amount after P9.2. Input from the sync: Stanford students have Claude education access, other members mostly have their own AI subscriptions; chat subscriptions don't pay for API calls of the n8n agents, so the key question is tied to D2. Tier-2 skills also work with whatever coding assistant a team uses. |
| D7 🟡 | Support owner during the semester | Max and Ash as maintainers and for onboarding (tier introductions, possibly short videos); Ash asks a possible TA from the 2026 cohort; asked in the Renate mail. |
| D8 🟡 | Tool access 2027 | **Working assumption (Max, 2026-09-26): ALICE, Fuzor and Manufacton will be available in 2027**; to be confirmed by Renate (mail). Manufacton import templates are public, so no question there. Asked: Resolve or Autodesk's own tool for clash review (ClashBot needed Autodesk Platform Services credentials, set up with help from the Stanford Autodesk admin). ACC/APS still open. Either way, the schedule engine must work **without** these licenses (tool-agnostic CSV input); ALICE/Fuzor/Manufacton become optional adapters (Phase 3B). ACC/APS access decides ClashBot (Phase 10). |
| D9 ✅ | Transcript agent and ClashBot | **Decided 2026-09-27: deferred until after the core rollout** (Phase 10, Tier 3). Locate and export the old workflows only then. |
| D10 🟡 | Origin of `6.38e6` / `1.51e8` | Asked in the Renate mail; document the answer in the engine docs |
| D13 ✅ | Rollout in tiers | **Decided 2026-09-27 (Max + Ash).** One monorepo, but the docs release it in tiers. **Tier 1 (course start):** Revit add-in → takeoffs → TVD + STV computed automatically (dashboards) + Concho chat on TVD/STV/quantities; teams provide `project_config` and their own RSMeans-based cost DB (guideline only), STV needs nothing beyond the takeoffs. **Tier 2 (on request or in the second half, when teams schedule):** ALICE macro → micro schedule, takt, Manufacton production orders / prefab assemblies / kit of parts / delivery windows, schedule questions in Concho. **Tier 3:** meeting transcripts, ClashBot (Phase 10). Reason: teams first have to learn the course tools themselves; everything at once would be used by nobody. |
| D14 ✅ | Schedule and Manufacton positioning | **Decided 2026-09-27.** Data, templates and skills instead of plugins: the takeoff and schedule data are structured so any AI agent can query them; each Tier-2 step is a Claude skill with defined input and output files plus the Island outputs as examples, so teams encode their own logic (the Island logic was design-specific). Manufacton is import-only (templates for production orders, prefab assemblies, kit of parts; nothing syncs back to Revit). ALICE provides the macro schedule (export → CSV). Fuzor is dropped from Tier 2. Owner: Ash (P3B.9). |

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
- [x] ✅ **P1.4 [CC] Migrate the Revit add-in source** *(done 2026-09-26: concho #6 merged; not compiled, see P4.1)* (`QTO/*.cs`, `.csproj`, `.addin`) without build artifacts.
- [x] ✅ **P1.5 [CC] Migrate the n8n workflow as a reference.** *(done 2026-09-26: concho #5; scrubbed export + README, Discord-ID check for `agent/` in `check_forbidden.py`)* Export "Island AI Agent" (read-only via n8n MCP `get_workflow_details`) to `agent/workflows/legacy/island-ai-agent.json`.
  - **Scrub first:** webhook path, the GHSAT token, and Discord guild and channel IDs → placeholders.
  - AC: the file contains no secrets or IDs (add a grep check to CI).
- [x] ✅ **P1.7 [CC] Migrate the schedule engines** *(done 2026-09-26: concho #9)* from `IPD_Challenge/src/Planning_engine` (ALICE_BIM_mapper, Micro_Schedule_Generator, Prefab_BIM_Mapper, Fuzor_Mapper, Logistics_Analysis), `src/Takt_engine` and `src/takt_zone_calibrator.py` into `engines/schedule/`, **without** generated outputs (the 16 MB Fuzor XML, the 2.7 MB micro schedule, HTML viewers, FBX).
  - Replace path constants that walk up the repo (`PROJECT_DIR = ...parents[2]`) with explicit input/output arguments.
  - AC: each generator runs from the package via a CLI with explicit paths.
- [ ] **P1.6 [HUMAN] Archive the old repos** after Phase 2 passes. Add a README banner pointing to the new repo.
  - **AutoTVD: set to private** (replaces the GitHub Support request from P0.3; old commits stay reachable via PR refs until then). Preconditions (0) ✅ met with [concho #27](https://github.com/mxngl/concho/pull/27) once merged (the commit is pinned in `tests/fixtures/checksums.json`): the golden-test fixtures (P2.1) no longer clone AutoTVD publicly, i.e. they moved to the private fixture repo `mxngl/concho-fixtures`; (1) the fork count is 0, since forks of a public repo stay public; (2) Concho and the dashboards no longer read from AutoTVD (GitHub Pages and `raw.githubusercontent.com` URLs stop working for private repos).
  - **IPD_Challenge:** Ash may make it private later (sync 2026-09-27); same precondition (0) ✅ (met with #27): `scripts/fetch_fixtures.py` cloned it publicly, the default source is now the private fixture repo (`--source public` stays until P1.6).

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
- [x] ✅ **P2.6 [CC] Golden tests for schedule.** *(done 2026-09-26: concho #11; golden file for all 43 outputs, current micro schedule as reference, deck-vs-files table)* Pin the Island outputs of the migrated schedule engines:
  - macro schedule (`Macro_Schedule.csv`: 37 tasks, first task starts 2029-10-01; the deck mentions 32 tasks → 48 parallelized tasks, so clarify which set is meant);
  - micro schedule row count and first/last dates (the deck states Oct 1, 2029 – Mar 22, 2030 and 246 → 177 days after parallelization; **verify against the files and document any mismatch**);
  - takt planner Level 1: 16 zones, 192.36 working hours, crew utilization per trade;
  - delivery-window summary metrics.
  - AC: the tests pass on the migrated engines; any deck-vs-file differences are written down in `docs/engines/schedule.md`.

---

## Phase 3: Configuration and generalization

- [x] ✅ **P3.1 [CC] `project_config` schema** *(done 2026-09-26: concho #10)* (pydantic + exported JSON Schema, `template/project_config.example.json`). Fields:
  - `project`: name, team_name, location, currency, gross_sf, completion_date
  - `stv`: `course_team` (enum of the 7 course teams), `lifetime_years` (default 50), `use_phase` (grid_kwh, onsite_renewable_kwh, natural_gas_m3, cogeneration{...}, water fixtures{...}, landscaping_gal, rainwater_gal)
  - `tvd`: `budget` (grant, grant_year, construction_year, inflation, roi) **or** an explicit `total_target`; `cluster_split` (explicit % or `derive_from_references` with the reference columns and `owner_ratings` + `reallocation_pct`, mirroring the course sheets); optional `custom_clusters` (flagged non-course)
  - `agent`: language defaults, model names, discord channel mapping (by env var name, not value)
  - AC: the schema validates the Island example; a clear error on any missing required field.
- [x] ✅ **P3.2 [CC] Remove every hardcoded project value.** *(done 2026-09-26: concho #12)* Also remove the temporary per-file ruff ignores for `engines/stv/*.py` (added in P1.2 to keep the migrated code verbatim) and fix the lint findings.
  - `TOTAL_TARGET`, `CLUSTER_TARGETS`, `GROSS_SF`, `grandTotal / 30000` in JS, all "Island Team 2026" strings (HTML, PDF, image export).
  - Fix `GITHUB_REPO_RAW` or remove it.
  - Handle "Special Contruction" via a canonical cluster enum (A–H per the course) + display names.
  - AC: `grep -ri "island\|30000\|16_700_000\|san juan" engines/ dashboards/` finds nothing outside fixtures and examples.
- [x] ✅ **P3.3 [CC] Cluster target consistency.** *(done 2026-09-26: concho #13)*
  - The engine validates that cluster targets sum to the total target (tolerance configurable) and fails otherwise.
  - Custom clusters (e.g. "Equipment Rental") must be either carved out of the total or explicitly marked "on top".
  - AC: the Island config either passes with an explicit override or reports the $405,852 gap.
- [x] ✅ **P3.4 [CC] New cost DB format + validator.** *(done 2026-09-27: concho #15; reliability scale corrected to the course convention in P3.5)*
  - `cost_db.csv` with columns `cluster, assembly_code, group, description, unit, unit_cost, quantity_rule, quantity_value, qty_reliability, cost_reliability, source`.
  - Plain decimal numbers only.
  - `quantity_rule` ∈ `takeoff | fixed | per_gsf | pct_of_subtotal | mirror:<AC> | count_codes:<AC,...>`, which replaces the hardcoded GC/contingency lump sums, `QUANTITY_MIRRORS`, `TOILET_ACS` and `AC_KEYWORD_SPLIT` (keyword split becomes `split_keywords`).
  - Validator: Uniformat code exists in the reference list (`engines/common/uniformat.csv`), unit is known, number parses, no duplicates, the reliability ratings are 1–3.
  - Include a migration script from the old `cost_data.csv`, and emit a warning list for the D5030/D5090 mislabels.
  - Ship the template with an **empty cost DB** (no RSMeans data).
  - AC: the Island fixture converts, and the golden test still passes (with the old codes kept in the fixture).
- [x] ✅ **P3.5 [CC] TVD course features.** *(done 2026-09-27: concho #16)* *(From the P3.1 review: extend `owner_ratings` to the course structure: value items per cluster, each rated 0–10 by several owners, averaged per cluster, share × `reallocation_pct`; map inputs to `TVD Targets` C5–C11, reference columns G–J, team input M, targets N, `TVD Owners` C22. Also add the 2029 hurricane window, or recurring annual windows, to the Island example.)*
  - Target derivation per the course (budget formula, reference average, owner reallocation) from config.
  - Reliability summary (Low/Medium/High by cluster) in the results JSON.
  - Tracking events (label + note per snapshot).
  - AC: with the course workbook's sample inputs, the engine reproduces the course `TVD Targets` budget (C10), reference average (K5:K12), owner-adjusted split (L5:L12) and the $ rows (G16:N23). Note (checked 2026-09-26): column N is typed in by the team, not computed, so the engine takes an explicit split or derives L + M.
  - Findings from reading the course workbook (2026-09-26): (1) the course reliability scale is **1 = High, 2 = Medium, 3 = Low** (cluster sheets, rows 26–28), and "overall" = the worse of quantity and cost (`MAX`); P3.4 documented 1 = low, which must be flipped. (2) `TVD Owners` H = G / C22 / 100 equals G × C22 only for C22 = 10 %; for other values the shares no longer sum to 100 %. (3) `TVD Reliability`: E14 points to `'H Gen. Cond.'!W30` instead of N30, and the LOW totals C6/C18 leave out the H row. Engine follows the intended logic; (2) and (3) go into the note to the course with the C25 bug.
- [x] ✅ **P3.6 [CC] STV mapping table keyed on Uniformat.** *(done 2026-09-27: concho #17; decisions: optional `discipline` column, `a|b` / `a&b` keywords + `priority` column instead of negation, tie = same element matched at equal priority, `weight`/`airflow` quantity fields, fallback estimates flagged; elements in several discipline exports listed for P3.9)*
  - `stv_mapping.csv`: `assembly_code, [category], [keyword], stv_assembly, stv_material_type, quantity_field (area|volume|length|count), conversion (e.g. cf_to_cy, density_kg_per_cf=...), note`.
  - Replace the family-name and keyword logic in `revit_architecture.py`, `revit_structural.py` and `revit_mep.py` with this table.
  - Ship a default table for common codes.
  - Output a coverage report: mapped % by element count and by quantity, plus a list of unmapped types.
  - AC: the Island results reproduce within tolerance using an Island mapping file, and the coverage report shows in the results JSON.
- [x] ✅ **P3.7 [CC] Custom materials extension.**
  - `custom_materials.csv` with the same columns as `LCA Data` plus `source` (EPD reference) and `is_course_data=false`.
  - Engineered bamboo becomes an explicit entry. The Island fixture keeps the glulam proxy by default but documents it.
  - Dashboards and Concho answers must label results that rely on custom materials.
  - AC: a unit test with a custom material; the dashboard shows the flag.
- [x] ✅ **P3.8 [CC] Use-phase completeness.**
  - Use-phase inputs are required in the config (explicit 0 allowed but must be stated).
  - Warn in CI and on the dashboard when all use-phase values are 0.
  - Allow PV as an `Energy` construction item (the course catalog has "Photovoltaics (sf)").
  - AC: the Island config either contains the slide values (162,000 kWh/yr use, 216,992 kWh/yr PV, 187,000 gal/yr water, 12,610 SF collection area) or an explicit "not modeled" flag.
- [x] ✅ **P3.9 [CC] Document the "Parts" decision** *(done 2026-10-08, [concho #23](https://github.com/mxngl/concho/pull/23) merged; open for Ash: DNC in STV, bamboo floor Parts proxy: shared rule `engines/common/dedup.py` for TVD + STV, decision D15)* (also from P2.3: three floor elements may be counted twice, in both the architecture and structural exports; deduplicate by ElementId across disciplines) (note from P1.4: the add-in exports Revit parts and skips a floor/ceiling that has parts, so parts are the counted representation there) (166 unmapped structural `Parts`): excluded to avoid double counting, or mapped. Implement the decision as a mapping rule.

- [x] ✅ **P3.11 [CC] TVD length parsing of old exports** *(found in the P4.5 work, 2026-09-27; done 2026-09-27, concho #21 merged: corrected Island TVD 16,081,484.40, legacy 16,065,644.29 via `--legacy-length-parsing`)*. TVD's display-string parser drops fractional inches (`9' - 7 3/4"` → 9 ft), so the old Island exports give about 3.5 % too few linear feet. The Island reference 16,065,644.29 was produced by AutoTVD with the same bug (ARCH coded elements: 3,638 instead of 3,771 LF; structural bamboo export ~2 %). **Low priority:** the Island number no longer matters (course finished, Max 2026-09-27), and new add-in exports carry exact numbers; this only affects exports from the old add-in. Fix together with the engine part of P4.5 (fractions, feet-inch), report the Island delta and re-pin the golden value with a before/after note.
- [x] ✅ **P3.10 [CC] Engine fixes and decisions from the course-equivalence tests (P2.4/P2.5).** *(items 1–5 done in concho #13; item 6 done 2026-09-27: reported in the mail to the course lead)*
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

**Reshaped 2026-09-27 (D13, D14): Phase 3B is Tier 2.** It is released to teams later than TVD/STV. Its shape is templates + Claude skills + example data, not generic engines: the Island engines stay as the reference implementation and example, the skills let each team encode its own sequencing and prefab logic. All 3B code sessions wait until #14 is merged (same files).

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
- [ ] **P3B.5 [CC] Deliveries and logistics (Tier 2).** Delivery-window analysis (window lengths from config; Island used 1 day / 3 days / 1 week, the sync mentioned 1 / 3 / 5 days) driven by config; outputs per-day deliveries and on-site inventory as JSON.
- [ ] **P3B.6 [CC] Tool imports (reshaped by D14).** Two small, import-only pieces: ALICE macro export → `macro_schedule.csv` (P3B.1) and Manufacton import templates (production orders, prefab assemblies, kit of parts) written from takeoff + schedule data. Fuzor 4D export and the Revit "push 4D build code / kit / assembly" commands move to the backlog (not in Tier 2).
  - AC: the core pipeline passes with all imports disabled; the templates validate against the public Manufacton import format.
- [ ] **P3B.9 [HUMAN: Ash, with CC] Tier-2 skills, README and examples (D14).** Claude skills with defined input and output files: (1) ALICE macro → micro schedule (sequencing rules as the team's own logic, e.g. interiors on a lower level while the structure goes up above); (2) micro schedule + takeoffs → Manufacton production orders, prefab assemblies (Island rule: elements at the same location, bounding-box midpoint, and of matching types such as wall + glazing form one prefab), kit of parts; (3) delivery windows (e.g. 1 / 3 / 5 days) and peaks. Plus a Tier-2 README and an `examples/island/` folder with the Island outputs as reference.
  - AC: a fresh Claude session can produce the output files for the Island inputs from the skills alone; the README names inputs, outputs and the prompts to use.
- [x] ✅ **P3B.8 [CC] Fix the bugs found in P1.7** *(done 2026-10-08, concho #14 merged; `--rooms-per-zone` → config moves to P3B.2)* (each with a test and a before/after note on Island numbers): takt calibrator drops the last polygon corner; add a generator for `room_takt_zones.csv`; Manufacton orders step fails on the reference data; delivery windows must run without Manufacton outputs; remove hardcoded Island assemblies from the Manufacton code; make the micro schedule work on pandas 3 (then lift the 2.3.3 pin). Make `--rooms-per-zone` a config value (Island used 2, default is 1).
- [ ] 🟡 **P3B.7 [CC] Schedule configuration in `project_config`:** *(schema part done in P3.1: `schedule.start_date`, `calendar`, `blocked_windows`, `target_completion`, `rooms_per_zone`, `trade_sequence`, `adapters`; open: the schedule steps read it (incl. replacing the hardcoded "Hurricane Contingency Buffer" task and the 2029-01-01 fallback anchor), starts after #14 is merged)* start date, work calendar (hours/day, workdays, holidays), hurricane or weather windows as blocked periods (Island example: Jun–Oct, peak Aug–Oct), and the target completion date.

---

## Phase 4: Revit extraction that any team can install

- [x] ✅ **P4.1 [CC] Make the add-in portable.**
  - `.addin` with a relative `<Assembly>` path.
  - Replace the hardcoded `HintPath` with a Revit API NuGet reference (e.g. `Nice3point.Revit.Api.RevitAPI`) and multi-target:
    - `net8.0-windows` for Revit 2025/2026
    - `net48` for Revit 2024 and older, if D8/D2 require it
  - Choose the output folder via a config file next to the DLL or a folder dialog, instead of searching upward for `revit_schedules`.
  - AC: builds without Revit installed (CI on `windows-latest`).
- [x] ✅ **P4.2 [CC] Release pipeline.**
  - A GitHub Action builds the DLL per Revit version and attaches a zip to each GitHub Release (DLL + `.addin` + `install.ps1`).
  - `install.ps1` copies the files to `%AppData%\Autodesk\Revit\Addins\<version>\`.
  - AC: a release artifact is produced for each supported version.
- [x] ✅ **P4.3 [CC] Export contract.**
  - Document the CSV columns (`docs/model-requirements.md`), including the required `Assembly Code`.
  - The add-in shows a summary dialog after export: element count, % with Assembly Code, and a list of missing codes by category.
  - Add the missing `Assembly Code` column to the **MEP** export (found in P1.4); Structural and Architecture already have it.
  - Decide whether Push Kit / Push Assembly get registered in the `.addin` or are removed (they're a subset of Push Manufacton Parameters), and update the `.addin` descriptions that still refer to `src\Planning_engine\...`.
  - AC: the dialog text is implemented; the doc lists every column.
- [ ] 🟡 **P4.5 [CC] Unit-safe and language-independent export** *(engine part in PR #21: tolerant parser, metric strings converted and flagged, old/new layout mapping documented and tested; left: localized `Parameter Snapshot`, ~20 rare category names to verify in an English Revit; from the P4 PR review, 2026-09-27; **high priority**: Max expects teams with project sites outside the US to model in metric units. Add-in part folded into PR #18 so the Revit test covers both: numeric values converted from Revit internal units to the course's imperial units (ft, sf, cf) regardless of the project's display units, so the engines stay unchanged)*.
  - Today TVD reads the first number from Revit's display strings, so a **metric model gives wrong quantities without any error** (the docs now require imperial project units). Export numeric values in Revit internal units converted explicitly (`UnitUtils`) plus a unit column, and make the engines reject or convert unknown units.
  - The add-in finds `Assembly Code` by its English parameter name; a non-English Revit exports empty codes. Use the built-in parameter (`BuiltInParameter.UNIFORMAT_CODE`) instead. *(In PR #18: Assembly Code and main quantities via BuiltInParameter, names as fallback. Localized category names stay a low-priority follow-up: Max knows of no one using a non-English Revit, and localized categories show up as unmapped in the STV coverage report, not as silent wrong numbers.)*
  - The Island fixture exports have 60 columns, the current add-in writes 69 (older add-in version); document the mapping between both and keep the importers tolerant of the old layout.
  - AC: a metric test export gives the same quantities as the imperial one; empty-code check on a non-English parameter name.
- [ ] **P4.4 [CC, optional, time-boxed 2 days] Spike: cloud extraction via the APS Model Derivative API** (properties incl. Assembly Code and quantities from ACC). Deliver a written go/no-go only.

---

## Phase 5: Pipeline and data layer (fixes the context-window problem)

**Principle: the LLM never reads raw files. Tools call parameterized queries that return small, computed results.**

**Scope by tier (D13):** build Phase 5–7 for **Tier 1 first** (TVD, STV, quantities, snapshots, dashboards P7.1/P7.2, Concho on those); schedule tables, endpoints, P6.5 and P7.3 follow with Tier 2. The pipeline and dashboards run on GitHub Actions/Pages and don't need D2; the data API and the Concho chat do (D2).

Measured on the Island central model: raw 3.4 MB (~860k tokens) → aggregate by category × type × level × Assembly Code = 218 rows (~2.9k tokens).

- [ ] 🟡 **P5.1 [CC] Team data repo template** (`template/`): *(Tier-1 part in PR: config, empty cost DB / custom materials, default STV mapping, `exports/` + `course/` READMEs, `pipeline.yml`; `macro_schedule.csv` / `schedule_rules.json` follow with Tier 2)*
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
- [ ] 🟡 **P5.2 [CC] Pipeline** (`pipeline.yml`), on push to `exports/**`, the config or the DBs: *(Tier-1 part in PR: steps 1–4, 6, 7 via `scripts/run_pipeline.py`, see `docs/pipeline.md`; 3b, 5, 8 open, 9 is a TODO)*
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
- [ ] 🟡 **P5.3 [CC] Ingest + summaries.** *(Tier-1 part in PR: `engines/api/`, `docs/data-api.md`; open: the schedule tables)* Normalize all element data into `elements` and all results into `tvd_line_items`, `tvd_clusters`, `stv_items`, `stv_summary`, `schedule_tasks`, `schedule_element_tasks`, `takt_zones`, `deliveries`, `snapshots` and `data_quality` tables.
  - Precompute: totals, per cluster, per level, per category × level × AC, and data quality (unmapped %, missing parameters).
  - AC: a schema doc exists, and a summary JSON stays under 10 KB.
- [ ] 🟡 **P5.4 [CC] Data API** (FastAPI, one tenant per team, bearer token). *(Tier-1 part in PR: `concho-api serve`, local only; open: `/schedule`, `/takt`, `/deliveries`, hosting per D2)* Endpoints:
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
- [ ] 🟡 **P5.5 [CC] Snapshots and history.** *(in PR: `results/index.json` per run, index page lists all snapshots; the new TVD/STV dashboards read it in P7)*
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
- [ ] 🟡 **P6.2 [CC] New workflow design** (`agent/workflows/concho.json`): *(PR 1 of Phase 6: workflow + error workflow + offline tests, see `docs/agent.md`; Discord first, Telegram/voice not built; **Max still has to import and run it in a clean n8n with an OpenAI key**, checklist in `docs/agent.md`)*
  - **Input normalizer:** Discord / Telegram (voice → Whisper) → `{message, user_id, channel_id, source, attachments}` in one Set node, so no node references like `$('Edit Fields Discord')` are needed downstream.
  - **Router:** gpt-4o-mini with **structured output** (enum `COST|CARBON|QUANTITY|SCHEDULE|GENERAL|OTHER`; extensions add `TRANSCRIPT` and `CLASH` when enabled), plus a fallback branch that asks a clarifying question.
  - **Subagents** use **only data API tools** (P5.4). Max 2 tool calls, answer in the user's language, cite numbers and snapshot dates, label custom-material or proxy results.
  - **Reply** to the originating channel or thread and mention the user.
  - **Global error handler:** an error workflow posts a readable message to the user and details to the debug channel.
  - AC: the workflow imports into a clean n8n instance with only `.env` values set.
- [ ] 🟡 **P6.3 [CC] Prompts as files.** *(done and tested offline: `agent/prompts/`, `scripts/render_agent.py`, no project string; 🟡 until the rendered prompts are seen answering in n8n)*
  - `agent/prompts/*.md` with placeholders (`{{PROJECT_NAME}}`, `{{LOCATION}}`, `{{COMPLETION_DATE}}`, `{{TEAM}}`), filled from config or env at import time by a script.
  - AC: no project-specific string in any prompt file.
- [ ] 🟡 **P6.4 [CC] Memory.** *(built and tested offline: Postgres Chat Memory on every agent, 6 messages, `agent/memory.sql`, daily 30-day purge; `memory.sql` run on PostgreSQL 16; 🟡 until the follow-up works in a running n8n and in the eval, see `docs/agent.md`)*
  - A window of the last N=6 messages per user and channel, persisted (Postgres) with 30-day retention.
  - AC: a follow-up question ("and on Level 2?") works in the eval.
- [ ] **P6.5 [CC] Schedule subagent.** Uses only the `/schedule`, `/takt` and `/deliveries` endpoints; answers with dates, durations, task names and the snapshot date; states the work calendar and blocked weather windows when relevant.
  - AC: "What's happening on Level 1 on Dec 15?", "When is superstructure complete?" and "How many deliveries in week X?" answer correctly in the eval without any tool response over the cap.
- [ ] 🟡 **P6.6 [CC] Deployment bundle.** *(files, `docker compose config` and the import script tested offline; **no `docker compose up`, n8n import or Discord run was possible here**: Max still has to run the local test in `docs/agent.md`; a fourth credential `concho-postgres` is created for the chat memory)*
  - `agent/docker-compose.yml` with n8n, Postgres, the Discord bot (from the existing `bot.py` pattern) and the data API.
  - `.env.example` listing every variable.
  - `scripts/import_workflows.sh` (`n8n import:workflow`).
  - AC: `docker compose up` + the import script yields a working Concho against the fixture data.
- [ ] 🟡 **P6.7 [CC] Model configuration** in one place (env) *(env variables in `agent/.env.example`, read by the chat-model nodes at run time; `agent.models` removed from `project_config.json`; 🟡 until run in n8n)*: router model, subagent model and TTS model. Default: gpt-4o-mini everywhere.
- [ ] 🟡 **P6.8 [CC] Evaluation harness.** *(`tests/agent_eval/questions.yaml` (54 questions, 4 schedule ones skipped as tier 2), `scripts/run_eval.py`, scorer and question generator tested offline; expected numbers are generated from the snapshot, none typed; 🟡 until Max runs it against a live Concho and the AC is met: ≥ 90 %, 0 overflows, p95 < 20 s)*
  - `tests/agent_eval/questions.yaml` with 40+ questions and expected answers from the Island fixture: cost, carbon, quantities, schedule (dates, tasks, takt zones, deliveries), what-if, multi-language (DE/ES/PL), follow-up and out-of-scope.
  - `scripts/run_eval.py` posts each question to the webhook and scores numeric match, language match, latency and tool-response size.
  - AC: ≥ 90% correct, 0 context overflows, p95 latency < 20 s.

---

## Phase 7: Dashboards

- [ ] 🟡 **P7.1 [CC] TVD dashboard as a static page** *(Tier-1 part in PR: `dashboards/site/tvd/`; JPG export dropped, PDF = print CSS; open: the unmapped-row list is not in the results JSON)* reading `results/*.json` (no HTML in Python f-strings). Keep the existing features (clusters, line items, history, compare, PDF/JPG export, dark mode), and add the reliability summary and the target-sum warning.
- [ ] 🟡 **P7.2 [CC] STV dashboard** *(in PR: `dashboards/site/stv/`)* on the same data contract. Fix the units found in P2.3: the old dashboard labels energy as kWh and water as L, but the engine reports **MJ** and **kg**; the old PDF export falls back to the February run.
  - Show a "construction vs use phase" split, a use-phase-missing warning, a custom/proxy-material flag and mapping coverage.
- [ ] **P7.3 [CC] Schedule dashboard:** macro Gantt, milestones, blocked weather windows, takt planner for all levels (zone map + utilization), and deliveries per day. It replaces the current Takt Planner page. The 3D viewer is optional; its FBX goes to release assets, not git.
- [ ] 🟡 **P7.4 [CC] One design system and project name from config** for all dashboards and the PDF export. *(in PR: shared `assets/concho.css` + header for index, TVD and STV; the schedule page (P7.3) will reuse them)*
- AC for Phase 7: all dashboards render from the fixture and from an empty new project without errors.

---

## Phase 8: Documentation and onboarding

- [ ] **P8.1 [CC] `docs/` site** (GitHub Pages, MkDocs or similar), **released per tier (D13):** a Tier-1 quickstart at course start, the Tier-2 guide later (P3B.9 README); optionally short walkthrough videos by Max/Ash:
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
- [ ] **P9.4 [HUMAN] Pilot with 1–2 teams**, starting with Tier 1; offer Tier 2 to teams that ask for it or once they build schedules; collect feedback weekly; triage it into a backlog.

---

## Phase 10: Extensions (after the main scope works) – Tier 3

*Confirmed 2026-09-27 (D9): only after the core rollout. ClashBot depends on the clash tool used in 2027 (Resolve or Autodesk's own, asked in the Renate mail) and on Autodesk Platform Services credentials per team.*

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
