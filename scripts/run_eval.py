"""Concho evaluation harness (roadmap P6.8): post the questions to the n8n webhook and score
the answers.

    # 1. the data the agent answers from (same team repo as the data API of the compose bundle)
    concho-api ingest --repo path/to/team-repo
    # 2. look at the questions and expected numbers generated from it (nothing is sent)
    python scripts/run_eval.py --repo path/to/team-repo --generate-only
    # 3. run them against the running Concho (token + webhook path from agent/.env)
    python scripts/run_eval.py --repo path/to/team-repo

Questions: ``tests/agent_eval/questions.yaml`` (templates; ``scripts/eval_questions.py`` fills in
names and expected numbers from the snapshot's results, nothing is typed in). Questions that
cannot be built from the snapshot are listed as *unavailable*, schedule questions (tier 2) as
*skipped*; neither counts. Questions of one chat (``after:``) are sent in order from the same
user and channel, so the workflow's memory sees the earlier messages. The eval posts with
``source: eval``: the workflow answers the HTTP call and posts nothing to Discord.

Acceptance (P6.8): >= 90 % correct, 0 context overflows (a tool response over the data API's
cap of 24,000 characters), p95 latency < 20 s. Exit code 0 = met, 1 = missed, 2 = setup error.
The report (``--report``, default ``eval-report.json``, git-ignored) contains answers built on
project data: do not commit it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_questions as eq  # noqa: E402
import eval_scoring as es  # noqa: E402
from agent_env import load_env  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / "agent" / ".env"
DEFAULT_REPORT = Path("eval-report.json")
TOKEN_HEADER = "X-Concho-Token"
TIMEOUT_S = 130

PostFn = Callable[[str, str, dict[str, Any], float], "tuple[int, dict[str, Any] | None]"]


def post_json(url: str, token: str, payload: dict[str, Any],
              timeout: float = TIMEOUT_S) -> tuple[int, dict[str, Any] | None]:
    """POST ``payload``; return ``(HTTP status, parsed JSON body or None)``. Never raises on
    HTTP or network errors (status 0 = no connection)."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", TOKEN_HEADER: token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, body = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except ValueError:
        return status, None
    return status, parsed if isinstance(parsed, dict) else None


def select(questions: Sequence[eq.ResolvedQuestion], only: Sequence[str] = (),
           groups: Sequence[str] = ()) -> list[eq.ResolvedQuestion]:
    """The ready questions to run, in file order. ``only`` / ``groups`` narrow the set; the
    earlier questions of a chosen follow-up's chat come along (they set up its context)."""
    by_id = {q.id: q for q in questions}
    wanted = {q.id for q in questions
              if (not only or q.id in only) and (not groups or q.group in groups)}
    for qid in list(wanted):
        q = by_id[qid]
        while q.after:
            q = by_id[q.after]
            wanted.add(q.id)
    return [q for q in questions if q.id in wanted and q.status == "ready"]


def run_questions(questions: Sequence[eq.ResolvedQuestion], url: str, token: str,
                  post: PostFn = post_json, *, run_id: str | None = None,
                  timeout: float = TIMEOUT_S,
                  clock: Callable[[], float] = time.monotonic) -> list[dict[str, Any]]:
    """Send the questions one by one (a chat's messages in order) and score each answer."""
    run_id = run_id or uuid.uuid4().hex[:8]
    results = []
    for q in questions:
        payload = {"content": q.text, "author_id": f"eval-{run_id}",
                   "author_name": "Concho eval", "channel_id": f"eval-{run_id}-{q.conv}",
                   "message_id": f"eval-{run_id}-{q.id}", "source": "eval"}
        start = clock()
        status, body = post(url, token, payload, timeout)
        latency = clock() - start
        if status != 200:
            body = None
        score = es.score_reply(q.asdict(), body, latency)
        results.append({"id": q.id, "group": q.group, "lang": q.lang, "question": q.text,
                        "http_status": status, "reply": (body or {}).get("reply"),
                        "tools": (body or {}).get("tools"), "score": score})
    return results


def report(results: Sequence[dict[str, Any]], skipped: Sequence[eq.ResolvedQuestion],
           summary: es.Summary) -> dict[str, Any]:
    def row(r: dict[str, Any]) -> dict[str, Any]:
        s = r["score"]
        return {"id": r["id"], "group": r["group"], "correct": s.correct,
                "http_status": r["http_status"], "latency_s": round(s.latency_s, 2),
                "missing": s.missing, "language_ok": s.language_ok,
                "detected_language": s.detected_language, "router_category": s.router_category,
                "category_ok": s.category_ok, "tools": r["tools"],
                "tool_chars_max": s.tool_chars_max, "overflow": s.overflow,
                "failed": s.failed, "question": r["question"],
                "reply": (r["reply"] or "")[:600]}

    return {"summary": summary.__dict__,
            "results": [row(r) for r in results],
            "not_run": [{"id": q.id, "status": q.status, "reason": q.reason} for q in skipped]}


def print_table(results: Sequence[dict[str, Any]], skipped: Sequence[eq.ResolvedQuestion],
                summary: es.Summary, out=None) -> None:
    out = out or sys.stdout
    for r in results:
        s = r["score"]
        flag = "ok  " if s.correct else "FAIL"
        why = "" if s.correct else "  <- " + ("; ".join(s.missing) or "")
        if not s.language_ok:
            why += f"  language: got {s.detected_language}"
        if s.failed:
            why += f"  (no usable answer, HTTP {r['http_status']})"
        print(f"{flag} {r['id']:<22} {s.latency_s:6.1f}s  tool<= {s.tool_chars_max:>6} chars"
              f"{why}", file=out)
    for q in skipped:
        print(f"skip {q.id:<22} {q.status}: {q.reason}", file=out)
    routing = "n/a" if summary.routing_accuracy is None else f"{summary.routing_accuracy:.0%}"
    print(f"\n{summary.correct}/{summary.total} correct ({summary.accuracy:.0%}); "
          f"language {summary.language_accuracy:.0%}; routing {routing}; "
          f"overflows {summary.overflows}; p95 {summary.p95_latency_s:.1f} s; "
          f"largest tool response {summary.max_tool_chars} chars", file=out)
    print("RESULT: " + ("PASS" if summary.passed else "FAIL (" + "; ".join(summary.reasons) + ")"),
          file=out)


def webhook_url(env: dict[str, str], url: str | None) -> str:
    if url:
        return url
    if env.get("CONCHO_EVAL_URL"):
        return env["CONCHO_EVAL_URL"]
    path = env.get("CONCHO_WEBHOOK_PATH")
    if not path:
        raise SystemExit("error: give --url, or set CONCHO_EVAL_URL or CONCHO_WEBHOOK_PATH "
                         "(agent/.env)")
    return f"http://127.0.0.1:{env.get('N8N_PORT') or 5678}/webhook/{path}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--repo", type=Path, metavar="DIR",
                     help="team repo: ingests new snapshots, then reads its database")
    src.add_argument("--db", type=Path, metavar="FILE", help="a concho.db built by concho-api")
    parser.add_argument("--snapshot", metavar="ID", help="default: the latest")
    parser.add_argument("--questions", type=Path, default=eq.QUESTIONS_FILE, metavar="FILE")
    parser.add_argument("--url", help="webhook URL (default: from agent/.env)")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, metavar="FILE")
    parser.add_argument("--only", nargs="+", default=[], metavar="ID", help="only these ids")
    parser.add_argument("--group", nargs="+", default=[], metavar="GROUP",
                        help="only these groups (cost, carbon, follow-up, ...)")
    parser.add_argument("--generate-only", action="store_true",
                        help="print the resolved questions and expected numbers, send nothing")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, metavar="FILE")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_S)
    parser.add_argument("--min-accuracy", type=float, default=0.90)
    parser.add_argument("--max-p95", type=float, default=20.0, help="seconds")
    args = parser.parse_args(argv)

    try:
        data = eq.load_questions(args.questions)
        if args.repo:
            from engines.api.ingest import ingest_repo
            db = Path(ingest_repo(args.repo)["db"])
        else:
            db = args.db
        conn = eq.open_database(db)
        resolved = eq.resolve_questions(data, conn, args.snapshot)
    except (eq.QuestionFileError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # ApiError (empty db, unknown snapshot) and friends
        print(f"error: {exc}", file=sys.stderr)
        return 2

    to_run = select(resolved, args.only, args.group)
    not_run = [q for q in resolved if q.status != "ready"]
    if args.generate_only:
        print(json.dumps([q.asdict() for q in resolved], indent=2, ensure_ascii=False))
        print(f"\n{len(to_run)} ready, {len(not_run)} not run "
              f"({sum(q.status == 'unavailable' for q in not_run)} unavailable, "
              f"{sum(q.status == 'skipped' for q in not_run)} skipped)", file=sys.stderr)
        return 0

    env = load_env(args.env_file if args.env_file.is_file() else None)
    url = webhook_url(env, args.url)
    token = env.get("CONCHO_WEBHOOK_TOKEN", "")
    if not token:
        print("error: CONCHO_WEBHOOK_TOKEN is not set (agent/.env or the environment)",
              file=sys.stderr)
        return 2
    if not to_run:
        print("error: no question to run", file=sys.stderr)
        return 2

    results = run_questions(to_run, url, token, timeout=args.timeout)
    summary = es.summarize([r["score"] for r in results], min_accuracy=args.min_accuracy,
                           max_p95_s=args.max_p95)
    print_table(results, not_run, summary)
    args.report.write_text(json.dumps(report(results, not_run, summary), indent=2,
                                      ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"report: {args.report}")
    return 0 if summary.passed else 1


if __name__ == "__main__":
    sys.exit(main())
