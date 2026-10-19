# Evaluation of the Concho agent (P6.8)

Question set, generator and scorer. First real run (Max, n8n 2.43.8, gpt-4o-mini, Island data):
**40/45 = 88.9 %** (gate ≥ 90 %), p95 9.5 s, 0 overflows, the memory follow-ups pass, and it only
ran on the long webhook URL (the short one answered 404, see below). The five failures were
`general-unmapped` (answered with the total element count), `carbon-swap` ("Concrete" instead of
"Concrete (sf)"), `qty-unknown-level` (count 0 for a level that does not exist), and two scorer
false negatives, `cost-whatif-cluster-over-target` ("Before: … under target. After: … over
target") and `oos-greeting` (router said GENERAL). The fixes are in the follow-up PR; the run is
**not repeated yet** (🟡: needs a live n8n and an OpenAI key). The scorer, the generator and the
runner are tested offline (`tests/agent_eval/`).

| What | Where |
|---|---|
| question templates and expectations by reference | [`tests/agent_eval/questions.yaml`](../tests/agent_eval/questions.yaml) |
| generator: resolves the facts from the data | [`scripts/build_eval_set.py`](../scripts/build_eval_set.py) |
| runner and scorer | [`scripts/run_eval.py`](../scripts/run_eval.py) |
| generated set and report (git-ignored, contain project numbers) | `tests/agent_eval/generated/` |

## Run

```sh
pip install -e ".[dev]"                                       # PyYAML for the generator
python scripts/build_eval_set.py --repo path/to/team-repo     # ingests results/, writes eval_set.json
python scripts/run_eval.py --url http://localhost:5678/webhook/<CONCHO_WEBHOOK_PATH>
```

In PowerShell load `.env` first (one-liner in [`agent-deployment.md`](agent-deployment.md)).
`CONCHO_WEBHOOK_TOKEN` must be set (the header `X-Concho-Token`); `--url` defaults to
`$CONCHO_EVAL_URL` or `http://localhost:$N8N_PORT/webhook/$CONCHO_WEBHOOK_PATH`. `--list` shows
the questions without posting, `--only a,b` / `--group cost` run a part. Questions run one after
the other, as the user `eval-user` in a channel `eval-<run>-<question>` with `source: eval` (the
workflow answers the caller and posts nothing to Discord). The exit code is 0 when the three
gates below hold.

## Questions: 51, 48 run in Tier 1

Cost (totals, target, delta, per SF, clusters, Assembly Codes), carbon (life cycle, embodied,
use phase, top assembly, energy, water), quantities (counts, areas, levels), general (overview,
unmapped elements, snapshots, compare, capabilities), what-if (cost ±, **a cluster that ends
over its own target**, material swap), follow-ups (cost, carbon, quantities: "and on Level 2?"
needs the memory), DE / ES / PL, robustness (unknown cluster, unknown level, `too_many_results`),
out of scope (weather, greeting, poem, trivia in DE/ES/PL), schedule: one Tier-1 question that
must be routed to SCHEDULE and answered "not available", and three **Tier-2** questions
(day on Level 1, milestone, deliveries per week) that are marked `tier: 2` and skipped until P6.5.

## No typed-in numbers

The YAML contains templates and expectations **by reference**: `numbers: [{fact: cost.grand_total}]`,
`bind: {cluster: {fact: cost.top_cluster}}`. `build_eval_set.py` resolves each fact with the same
functions the endpoints use (`engines/api/queries.py`) on the database of the data API, so the
expected number is exactly what the tool returns, which `tests/data_api/test_api_island.py`
ties to the engine results (TVD 16,081,484.40 on the Island fixtures). It also picks the names
(a cluster, a level, a category, an Assembly Code, a material pair) from the data, so the
file holds no project name, no course data and no RSMeans-derived number. The what-if question
of the `Shell` bug is searched in the data: a code and a percent after which one cluster
is over its own target. A question whose fact does not exist in this data (no STV result, one
snapshot only, use phase not modeled, fewer than 51 line items for the `too_many_results` test)
is written with `skip` and the reason, and printed; never dropped silently.

## Scoring

Per question (all *required* checks must pass for "correct"):

| Check | How |
|---|---|
| numbers | every expected number occurs in the reply. Locale-tolerant parser: `4,467,302`, `4.467.302`, `4 467 302`, `16.1M`, `3 Mio`, dates (the snapshot line) ignored. Relative tolerance 0.5 % (2 % for the percent of target), counts exact. Truncation counts as a hit within the tolerance; the prompts demand rounding |
| status | for "over/under target": the status word nearest to the subject (the cluster, else the target) in en/de/es/pl must equal the data's. For a **what-if** reply ("Before: … under target. After: … over target") only the status after `after` / `nach` / `después` / `po` counts. **Heuristic**, the report keeps the reply for review |
| names | valid names the reply must mention (a real cluster instead of a guessed one) |
| scenario label | what-if replies call the result a scenario (what-if / Szenario / escenario / scenariusz) |
| no tools / needs tools | out-of-scope replies call no data tool; data answers call one |
| transport error | the request got no usable answer: HTTP 404/401/500, connection refused, timeout, a body that is not JSON. Reported as its own failure, `transport error: HTTP 404, is the workflow active / webhook registered?` (`401/403`: check `CONCHO_WEBHOOK_TOKEN`), counted in `summary.transport_errors`; it is **not** `failed=true (agent error branch)` |
| tool error | **not** only `failed`: `failed: true`, the generic error reply, an unexpected code in `tool_errors`, tools called but `tool_response_chars` all below 40, or a reply that says the data is not reachable (en/de/es/pl patterns). Codes a question expects (`unknown_cluster`, `too_many_results`, `no_match`) are allowed |
| reply language | stop-word and diacritic heuristic among en/de/es/pl; very short replies are not judged |
| category | reported; required only for out-of-scope and the schedule fallback. A question may accept a set of categories (`category: [GENERAL, OTHER]` for the greeting) |

Reported but not required: the router's `language`, whether the reply has a snapshot line.
Separate gates (roadmap P6.8):

| Gate | Limit |
|---|---|
| accuracy | ≥ 90 % of the questions that ran |
| context overflows | 0: a tool response over 24,000 characters (8,000 tokens × 3) or an overflow message in the reply |
| latency | p95 < 20 s (nearest rank) |

`eval_report.json` holds every reply, the tools it called, the sizes of the tool responses,
each check with its reason, and the skipped questions with theirs.

## Limits

- The language, status and unreachable-data checks are word-list heuristics; read the failing
  replies in the report before changing a prompt.
- A small expected count (like 2) can be matched by an unrelated number in the reply
  (`Level 2`); counts are exact so a wrong count still fails, but a right count can be a false hit.
- LLM answers vary: run twice before trusting one failure.
- The follow-up questions need Postgres and the memory credential; without them they fail.
