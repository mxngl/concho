# agent_eval

The Concho evaluation (roadmap P6.8). How it works and how to run it: [`docs/agent.md`](../../docs/agent.md#evaluation-p68).

- `questions.yaml`: 54 question templates (50 runnable, 4 schedule questions marked `tier: 2`) with
  entities and fact recipes. **No expected numbers and no project, course or RSMeans data**:
  `scripts/eval_questions.py` fills names and numbers in from the results of one snapshot.
- `test_eval_questions.py`, `test_eval_scoring.py`: offline tests of the file, the generator
  (on the invented data of `tests/data_api/`), the scorer and `scripts/run_eval.py` (against a
  stand-in agent). The Island fixtures are optional: `CONCHO_EVAL_DB=<concho.db built from them>`
  adds a check that the whole file resolves on that data.
- Run it: `python scripts/run_eval.py --repo path/to/team-repo` (needs the stack of
  `agent/docker-compose.yml` running; `--generate-only` sends nothing).
