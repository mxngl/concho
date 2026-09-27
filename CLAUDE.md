# CLAUDE.md – rules for every Claude Code session in this repo

## Roadmap
- The source of truth is `docs/ROADMAP.md`; Max and Ash change it via PRs. The roadmap artifact is a read-only mirror.
- In the PR for a task: tick the task's checkbox / status in `docs/ROADMAP.md` and add one line
  to the progress log (date, what was done, PR link). Don't rewrite other parts of the roadmap.

## Workflow
- One task (roadmap ID, e.g. P1.2) per branch + PR; put the ID in the PR title.
- Never push to `main`, never force-push, never rewrite history.
- CI must be green (`ruff check .`, `pytest`, `python scripts/check_forbidden.py`) before asking for a merge.

## Hard rules (from `docs/ROADMAP.md` §0)
This list mirrors `docs/ROADMAP.md` §0 (rules 1–6); rule 3 (no force-push/history rewrite) is under Workflow.

- No secrets (API keys, webhook URLs, tokens, Discord IDs): use `.env` / GitHub secrets.
- No course or licensed data: no course workbooks (`.xlsx`), no RSMeans-derived cost data.
  Tests needing them read paths from env vars (`COURSE_STV_XLSX`, `CONCHO_FIXTURES_DIR`)
  and are skipped when unset.
- Do not modify or deactivate the live n8n workflow ("Island AI Agent") without explicit
  approval from Max or Ash. The n8n MCP access has write scope; use it read-only unless told
  otherwise.
- No meeting transcripts or other personal data.
- Keep the course logic of the engines untouched. Team-specific logic goes into config and
  mapping files, clearly marked as "not course data".
