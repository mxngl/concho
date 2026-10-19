# docs

Project documentation.

- [`ROADMAP.md`](ROADMAP.md): roadmap (source of truth)
- [`decisions.md`](decisions.md): decision records D1–D15
- [`config.md`](config.md): `project_config` reference
- [`pipeline.md`](pipeline.md): the Tier-1 team pipeline (template repo, steps, inputs, outputs, snapshots, private-repo requirement)
- [`data-api.md`](data-api.md): SQLite ingest (`concho.db`) and the local data API (tables, endpoints, hard caps, `concho-api`)
- [`agent.md`](agent.md): the Concho n8n workflow on the data API (flow, prompts, rendering, memory, model config, what is untested)
- [`agent-deployment.md`](agent-deployment.md): the deployment bundle (docker compose: n8n, Postgres, Discord bot, data API), the import script, local test on Windows
- [`agent-eval.md`](agent-eval.md): the evaluation (questions, generator from the data, scorer, gates)
- [`model-requirements.md`](model-requirements.md): Revit model requirements (Assembly Codes, units) and every CSV column of the add-in exports
- [`engines/`](engines/): engine notes ([TVD](engines/tvd.md), [STV](engines/stv.md), [schedule](engines/schedule.md))
- course-equivalence tests (LibreOffice Calc, `COURSE_STV_XLSX`, `COURSE_TVD_XLSX`): [`tests/README.md`](../tests/README.md)

Filled further by: P2.3/P2.6 (`docs/engines/`), Phase 8 (docs site).
