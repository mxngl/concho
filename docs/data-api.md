# Data layer and data API, Tier 1 (P5.3, P5.4)

The LLM never reads raw files (roadmap Phase 5). Every pipeline run is loaded into a small
SQLite database (`concho.db`); a FastAPI app answers **parameterized, capped** queries on it.
Scope is **Tier 1** (D13): TVD, STV, quantities, snapshots, data quality. Not in it yet (they
follow with Tier 2 / P7.3): the schedule tables (`schedule_tasks`, `schedule_element_tasks`,
`takt_zones`, `deliveries`) and the `/schedule`, `/takt`, `/deliveries` endpoints.

Code: [`engines/api/`](../engines/api/). Local only: no hosting, no deployment, no n8n changes
(D2 is open).

```
team repo                     concho-api ingest                concho-api serve
results/index.json  ───┐
results/<id>/tvd/…  ───┼──►  .concho/concho.db    (SQLite)  ──►  FastAPI on 127.0.0.1
results/<id>/stv/…  ───┤        one DB, all snapshots           bearer token, row/token caps
exports/*.csv       ───┘
```

## Run it

```sh
pip install "concho[api] @ git+https://github.com/mxngl/concho@<tag>"   # or: pip install -e ".[api]"
export CONCHO_API_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
concho-api serve --repo path/to/team-repo            # ingests new snapshots, then serves
curl -H "Authorization: Bearer $CONCHO_API_TOKEN" http://127.0.0.1:8000/cost/summary
```

| Command | What it does |
|---|---|
| `concho-api ingest [--repo DIR] [--db FILE] [--snapshot ID] [--force]` | loads the snapshots of `results/index.json` that are not in the database yet (default DB `<repo>/.concho/concho.db`); `--force` replaces a snapshot |
| `concho-api summary [--repo DIR] [--snapshot ID]` | prints the precomputed summary JSON (below) |
| `concho-api serve [--repo DIR] [--host 127.0.0.1] [--port 8000] [--enable-sql] [--no-ingest]` | the API for this team repo |

- **One tenant per team:** one server process serves one team repo's database.
- **Token:** `$CONCHO_API_TOKEN`, never in the repo; there is no `--token` option (shell
  history). The server does not start without a token. Comparison is constant-time. `/health`
  is the only route without auth and says nothing but `ok`.
- **Host:** `127.0.0.1` by default. Binding another interface is the operator's decision.
- `POST /sql` exists only with `--enable-sql` (or `CONCHO_API_ENABLE_SQL=1`).
- The database is a build artifact, not a result: it lives in `.concho/` (git-ignored by the
  team repo template, so `git add results` in the workflow never picks it up) unless `--db`
  says otherwise. It can be rebuilt with `concho-api ingest` (but see "Stale exports" below).

## Ingest (P5.3)

Nothing of the engines is recomputed (course logic untouched). Totals, clusters, line items,
STV items and the STV summary are copied from the results JSON of the snapshot
(`tvd_results.json`, `stv_results.json`, [`pipeline.md`](pipeline.md)). The one new
aggregation is over the **element rows**, which the results JSON does not hold:

1. the export CSVs listed in the snapshot's `exports` are read (architecture, structural, MEP,
   recognised by file-name ending as in the pipeline; other files are ignored);
2. they go through the shared **D15 rule** (`engines/common/dedup.py`: Parts over their host,
   one row per ElementId; Assembly Code, then the owning discipline's export, then the first
   export); the kept rows are the `elements`;
3. quantities are read with the tolerant parser (`engines/common/quantities.py`);
4. `quantity_summary` sums them per category x level x Assembly Code. Rows with the DNC marker
   are kept in `elements` (`dnc = 1`) but not summed.

Differences to the engines, on purpose: the API has no STV mapping, so D15 step (b) ("a row
the STV mapping maps wins") is skipped, as in TVD; and MEP rows are included although TVD
reads no MEP export, so quantities and counts cover all three exports.

**Stale exports.** `exports/` holds the latest files only. Elements are attached to a snapshot
only when they reproduce it: TVD counted `meta.total_elements` rows (architecture + structural
after D15), so the exports must give the same number. If not, the snapshot gets
`elements_status = 'stale'` and no element rows (`/quantities` and `/elements/count` answer
`elements_unavailable`; everything else works). So run `concho-api ingest` right after the
pipeline run, not months later.

### Tables

Every table except `meta` and `snapshots` has `snapshot_id`; one database holds all snapshots.
DDL: [`engines/api/schema.py`](../engines/api/schema.py). Schema version in `meta`
(`schema_version = 1`); a database of another version is refused (delete and ingest again).

| Table | One row per | Main columns |
|---|---|---|
| `snapshots` | snapshot | `snapshot_id` (UTC timestamp id), `timestamp`, `commit_sha`, `label`, `project_name`, `team_name`, `gross_sf`, `tvd_grand_total`, `tvd_target`, `tvd_status`, `stv_present`, `stv_note`, `stv_carbon_life_cycle/_target/_embodied`, `stv_use_phase_modeled`, `stv_custom_material`, `stv_proxy`, `elements_status` (`loaded` / `stale` / `no_exports`), `elements_note`, `summary_json` |
| `elements` | deduplicated export row (D15) | `element_id`, `export`, `discipline`, `category` (a Part counts with its Original Category), `family`, `type`, `level`, `mark`, `assembly_code`, `material`, `is_part`, `dnc`, `area_sf`, `length_lf`, `volume_cf`, `qty_issues` |
| `quantity_summary` | category x level x AC | `category`, `level`, `ac` (`''` = none), `elements`, `area_sf`, `length_lf`, `volume_cf` |
| `tvd_line_items` | cost line item | `cluster`, `ac`, `grp`, `description`, `unit`, `unit_cost`, `qty`, `qty_src`, `total`, `notes` |
| `tvd_clusters` | cluster | `estimate`, `target`, `delta`, `delta_pct`, `per_sf`, `share_of_total`, `line_items` |
| `stv_items` | STV construction item | `assembly`, `material_type`, `unit` (from `(sf)` in the name), `amount`, `carbon` (kgCO2e), `energy` (MJ), `water` (kg), `ozone` (kg CFC-11e), `carbon_materials/_transport/_construction`, `carbon_per_unit`, `estimated_amount`, `proxy_amount`, `custom_material`, `custom_material_source`, `origin` |
| `stv_summary` | metric (`carbon`, `energy`, `water`, `ozone`) | `target`, `project` (life cycle), `percent_of_target`, `embodied`, `embodied_materials/_transport/_construction`, `use_phase`, `use_electricity/_heating/_water` |
| `data_quality` | metric | `scope` (`tvd`, `stv`, `elements`), `metric`, `value`, `total`, `pct`, `detail` (small JSON) |

Data quality metrics: `tvd`: `unmapped_elements` (no Assembly Code; denominator = counted
elements minus DNC), `dnc_elements`, `duplicates_removed`, `unpriced_line_items`,
`not_rated_reliability`, `quantity_parse_issues`, `target_consistency`; `stv`:
`unmapped_elements`, `zero_quantity_elements`, `mapped_elements`, `estimated_kgco2e`,
`custom_material`, `proxy`, `use_phase_modeled`, `dnc_rows_counted`; `elements` (missing
parameters, with the top categories in `detail`): `missing_level`, `missing_material`,
`no_quantity`, `quantity_unreadable`, `missing_assembly_code` (architecture + structural),
`rows`, and `status` when the elements are stale.

### Summary JSON

`snapshots.summary_json` (`concho-api summary`): snapshot, cost (total, target, delta, status,
clusters), carbon (life cycle, target, embodied, use phase, top assemblies, custom/proxy flags),
quantities (elements per level and category), headline quality numbers. **Always < 10 KB**: the
long lists are cut (largest kept) until it fits (`engines/api/summaries.py`, tested with
hundreds of clusters, assemblies, levels and categories).

## Endpoints (P5.4)

All `GET` unless noted; all take an optional `snapshot=<id>` (default: the latest) except
`/snapshots` and `/compare`. Strings match case-insensitively.

| Endpoint | Answer |
|---|---|
| `/cost/summary` | TVD grand total, target, delta, status, $/SF, one row per cluster, unmapped elements |
| `/cost?cluster=&ac=` | cost line items (largest first) with `matched_lines` / `matched_total`; `ac` is a prefix (`B30`, `B3010`; the course's 4-digit form `B2000` means `B20`) |
| `/cost/what_if?ac=&change_pct=` | scenario, computed server-side: the line items of that code cost `change_pct` % more (e.g. `ac=B30&change_pct=10` = "roof +10 %"); new grand total, delta to target, affected clusters. Percent-of-subtotal lines (contingency) not selected by the code are rescaled with the subtotal; fixed lump sums are unchanged. Labelled `what_if` |
| `/carbon/summary` | STV life cycle / embodied / use phase per metric (kgCO2e, MJ, kg, kg CFC-11e), % of target, top assemblies, use-phase-modeled warning, mapping coverage |
| `/carbon?stv_assembly=&material=` | STV items (`material` = substring of the material type) with amount, unit, kgCO2e, MJ, water |
| `/carbon/what_if?material_from=&material_to=&stv_assembly=` | all of `material_from` replaced by `material_to` (same amount): embodied and life cycle before/after. `ac` is accepted as an alias of `stv_assembly` (STV items are keyed by STV assembly, not by Uniformat code). The per-unit factor of `material_to` is read from this snapshot's results: the API has **no LCA catalog** (course data), so `material_to` must already occur in the project, with the same unit (else `unknown_material_factor`, `unit_mismatch`) |
| `/quantities?category=&level=&ac=` | category x level x AC rows with element count, area (SF), length (LF), volume (CF), and totals |
| `/elements/count?category=&level=&ac=&discipline=` | number of (non-DNC) elements, per discipline |
| `/quality` | the `data_quality` rows; notes whether elements are stale |
| `/snapshots?limit=` | snapshots, newest first (default 20), with totals and element status |
| `/compare?a=&b=` | snapshot `b` against `a`: cost total and per cluster, carbon, element count |
| `POST /sql` `{"query": "SELECT …"}` | **only with the flag.** One SELECT/WITH, read-only connection + authorizer (no PRAGMA, ATTACH, writes), 2 s limit, row cap. The tables hold all snapshots: filter on `snapshot_id` |

### Every response

```json
{
  "snapshot": {"id": "20270117T093000Z", "timestamp": "2027-01-17T09:30:00Z", "label": "Week 3", "commit": "a1b2c3d4e5"},
  "labels": ["custom_material: …", "proxy: …"],
  "rows": [ … ]
}
```

- `snapshot` names where the numbers come from (agents cite it). `/compare` names `b` and lists
  both under `compared`.
- **Labels.** A result that includes custom materials (team EPD values, not course data) or
  proxy-rule quantities says so in `labels`, and each STV row has `custom_material` / `proxy` /
  `estimated`. What-if and free-SQL answers are labelled `what_if` / `sql`.
- Errors are `{"error": code, "hint": …}`: 401 `unauthorized`; 404 `unknown_snapshot`,
  `unknown_cluster`, `no_match`, `no_stv`, `elements_unavailable`, `unknown_material_factor`,
  `no_snapshots`; 409 `ambiguous_factor`; 422 `bad_parameter`, `bad_change_pct`,
  `unit_mismatch`; 400 `not_a_select`, `sql_error`, `query_too_slow`.

### Hard caps

**≤ 50 rows and ≤ ~8,000 tokens per response.** Rows are all objects/lists inside lists of the
answer; tokens are estimated from the JSON text at 3 characters per token (pessimistic, so the
real count is lower; `engines/api/caps.py`). Over either cap the answer is not truncated but
replaced:

```json
{"error": "too_many_results", "hint": "filter by level or category",
 "snapshot": {…}, "at_least_rows": 51, "max_rows": 50, "estimated_tokens": 2572, "max_tokens": 8000}
```

It is **HTTP 200**: it is an answer the agent is meant to read and narrow down, not a failed
call (an n8n HTTP tool would otherwise drop the body). Queries fetch at most 51 rows, so
`at_least_rows` is "at least", not the true match count. Tests: `tests/data_api/` (50 rows pass,
51 do not, the token cap alone, all endpoints on a realistic project, `POST /sql`).

## Tests

`tests/data_api/` (folder name chosen so it cannot shadow a package): unit tests on invented
data (`api_synthetic.py`), an end-to-end test on the output of `scripts/run_pipeline.py` with
the invented pipeline fixtures including a real `concho-api serve` process, and
`test_api_island.py`, which checks the served totals against the engine results on the Island
fixtures and is skipped when `CONCHO_FIXTURES_DIR` is unset: TVD **16,081,484.40**; STV
per trade **2,517,183.14**, one run **2,459,374.64** kgCO2e.

## Known gaps

- Tier 2: schedule tables and endpoints (P7.3 / P6.5 follow).
- Not wired into `pipeline.yml` (step 5 of P5.2: ingest after the run) and not pushed anywhere
  (step 8, D2).
- Quantities are the exported quantities per category / level / Assembly Code, not the
  pricing quantities per cost line (those are in `tvd_line_items`).
- Cost has no level dimension: the TVD results price by Assembly Code, not by element.
