# data-api

The FastAPI data API (one tenant per team, bearer token) serving small, computed query results
to the agent, with hard response caps, and the SQLite ingest behind it.

The code is the package [`engines/api/`](../engines/api/) (installed as `concho`, command
`concho-api`), so it ships with the other engines; this folder only keeps the pointer. Schema,
endpoints, caps and how to run it: [`docs/data-api.md`](../docs/data-api.md).

Filled by: Phase 5 (P5.3, P5.4; Tier 1 done, schedule endpoints follow with Tier 2).
