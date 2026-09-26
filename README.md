# Concho

Concho is an AI project agent for AEC Global Teamwork teams. It answers questions about a
project's cost (Target Value Design), carbon (Sustainable Target Value), quantities and
schedule, backed by engines that compute those numbers from Revit exports.

This repo consolidates the Island Team 2026 prototype (AutoTVD, AutoSTV, IPD_Challenge and
the n8n agent) into one monorepo, so that each team in the next cohort can set it up for
its own project.

**Status: prototype, not yet usable by teams.**

See the [roadmap](docs/ROADMAP.md) for the plan and [decisions](docs/decisions.md) for the
decision log.

## Layout

| Folder | Purpose |
|---|---|
| `engines/` | Python package: `common`, `tvd`, `stv`, `schedule` |
| `revit-addin/` | Revit QTO export add-in |
| `data-api/` | Per-team data API |
| `agent/` | n8n workflows, prompts, Discord bot |
| `dashboards/` | Static TVD / STV / schedule pages |
| `template/` | Per-team data repo template |
| `docs/` | Roadmap, decisions, docs |
| `tests/` | pytest suite |

## Development

```sh
pip install -e ".[dev]"
ruff check .
pytest
python scripts/check_forbidden.py
```

This repo is public: never commit secrets, course workbooks, RSMeans-derived data or
meeting transcripts (see roadmap §0).
