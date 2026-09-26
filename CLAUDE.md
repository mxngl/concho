# CLAUDE.md – rules for every Claude Code session in this repo

## Roadmap
- The source of truth is the roadmap artifact maintained by Max/Ash; `docs/ROADMAP.md` is its copy.
- If the prompt includes a newer roadmap, first replace `docs/ROADMAP.md` with it (unchanged).
- In the PR for a task: tick the task's checkbox / status in `docs/ROADMAP.md` and add one line
  to the progress log (date, what was done, PR link). Don't rewrite other parts of the roadmap.

## Workflow
- One task (roadmap ID, e.g. P1.2) per branch + PR; put the ID in the PR title.
- Never push to `main`, never force-push, never rewrite history.
- CI must be green (`ruff check .`, `pytest`, `python scripts/check_forbidden.py`) before asking for a merge.

## Hard rules (from `docs/ROADMAP.md` §0)
- No secrets (API keys, webhook URLs, tokens, Discord IDs): use `.env` / GitHub secrets.
- No course or licensed data: no course workbooks (`.xlsx`), no RSMeans-derived cost data.
  Tests needing them read paths from env vars (`COURSE_STV_XLSX`, `CONCHO_FIXTURES_DIR`)
  and are skipped when unset.
- No meeting transcripts or other personal data.
- Keep the course logic of the engines untouched. Team-specific logic goes into config and
  mapping files, clearly marked as "not course data".
