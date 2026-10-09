"""P5.3 / P5.4: ingest of a team repo's pipeline results into SQLite and the local data API.

- :mod:`engines.api.ingest`: ``results/`` (+ ``exports/``) -> ``concho.db`` (docs/data-api.md)
- :mod:`engines.api.queries`: the parameterized, capped queries behind the endpoints
- :mod:`engines.api.app`: the FastAPI app (``concho-api serve``), needs ``concho[api]``

Nothing here recomputes engine logic: totals come from the results JSON, only the
deduplicated element rows are aggregated (levels, categories, Assembly Codes).
"""

SCHEMA_VERSION = 1
