"""Run the Concho evaluation against a live n8n webhook (roadmap P6.8).

    python scripts/run_eval.py --repo path/to/team-repo            # cases from this repo's data
    python scripts/run_eval.py --cases cases.json --report out.json
    python scripts/run_eval.py --repo path/to/team-repo --dry-run  # resolve and print, no calls

Every question of ``tests/agent_eval/questions.yaml`` is POSTed to the webhook
(``$CONCHO_EVAL_WEBHOOK_URL``, header ``X-Concho-Token: $CONCHO_WEBHOOK_TOKEN``, ``source`` =
``eval`` so nothing is posted to Discord) in its own channel, so the conversation memory of
one question never leaks into another. A follow-up first asks its `after` question in the same
channel. The workflow answers ``{reply, category, language, tools, tool_response_chars,
failed}``. Per question it scores

- numbers: every expected number (or one of ``any_of``) appears in the reply, within the
  tolerance of its ref; thousands/decimal separators of en/de/es/pl and "1.2M"/"Mio."/"mln"
  suffixes are understood; signs are ignored;
- language: the reply is in the language of the question (word-list heuristic);
- category: the router's category is one of the expected;
- tools: out-of-scope questions call no data tool; no tool response is over the API cap;
- no workflow error (``failed``).

and overall: share correct (>= 90 %), context overflows (0), p95 latency (< 20 s). The expected
numbers come from ``scripts/eval_cases.py`` (the API's own queries on the same database the
agent's API serves); run it right after ``concho-api ingest``, with the same snapshot.
Exit code 0 = acceptance criteria met, 1 = not met, 2 = could not run.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import eval_cases  # noqa: E402

from engines.api.caps import CHARS_PER_TOKEN, MAX_TOKENS  # noqa: E402

TOKEN_HEADER = "X-Concho-Token"
MIN_CORRECT = 0.90
MAX_P95_S = 20.0
# the API refuses to send more than this (engines/api/caps.py); a bigger tool response means
# the cap is broken and the model context is at risk
TOOL_RESPONSE_CAP_CHARS = int(MAX_TOKENS * CHARS_PER_TOKEN)

# --- numbers -----------------------------------------------------------------------------------

_SEP = r"[   '’,.]"
NUMBER_RE = re.compile(
    rf"(?<![\w.,])(\d{{1,3}}(?:{_SEP}\d{{3}})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?:\s?(mrd|bn|billion|mio|mln|million(?:es|s)?|milion(?:y|ów)?|millón|M|"
    r"tsd|tys|thousand|mil|k)(?![a-zA-Zäöüß]))?",
    re.IGNORECASE)
_MILLION = {"mio", "mln", "million", "millions", "millones", "millón", "milion", "miliony",
            "milionów", "m"}
_THOUSAND = {"tsd", "tys", "thousand", "mil", "k"}
_BILLION = {"mrd", "bn", "billion"}
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b|\b\d{8}T\d{6}Z\b")


def _candidates(token: str) -> set[float]:
    """The values a number token can mean ('1,234' is 1234 in en and 1.234 in de)."""
    t = re.sub(r"[   '’]", "", token)
    if t.isdigit():
        return {float(t)}
    seps = [i for i, ch in enumerate(t) if ch in ".,"]
    last = seps[-1]
    kinds = {t[i] for i in seps}
    tail = t[last + 1:]
    out: set[float] = set()
    if len(kinds) == 2 or (len(kinds) == 1 and len(seps) == 1 and len(tail) != 3):
        # decimal separator is the last one; the others are thousands separators
        out.add(float(re.sub(r"[.,]", "", t[:last]) + "." + tail))
    elif len(kinds) == 1 and len(seps) > 1:
        out.add(float(re.sub(r"[.,]", "", t)))  # 1.234.567: thousands separators only
    else:  # one separator followed by exactly three digits: thousands and/or decimal
        whole = t[:last]
        if whole != "0":
            out.add(float(whole + tail))
        if len(whole) <= 3:
            out.add(float(whole + "." + tail))
    return out


def extract_numbers(text: str, noise: list[str] | tuple[str, ...] = ()) -> list[float]:
    """Every value a number in ``text`` can mean (absolute values; ISO dates, snapshot ids
    and the question's own words in ``noise`` are removed first)."""
    text = ISO_DATE_RE.sub(" ", text)
    for n in noise:
        text = re.sub(re.escape(n), " ", text, flags=re.IGNORECASE)
    values: list[float] = []
    for m in NUMBER_RE.finditer(text):
        suffix = (m.group(2) or "").lower()
        scale = (1e6 if suffix in _MILLION and (suffix != "m" or m.group(2) == "M") else
                 1e3 if suffix in _THOUSAND else 1e9 if suffix in _BILLION else 1.0)
        for v in _candidates(m.group(1)):
            values.append(v)
            if scale != 1.0:
                values.append(v * scale)
    return values


def number_matches(expected: dict[str, Any], found: list[float]) -> bool:
    want = abs(expected["value"])
    tol = max(expected.get("rel_tol", 0.0) * want, expected.get("abs_tol", 0.0))
    return any(abs(abs(v) - want) <= tol + 1e-9 for v in found)


# --- language ----------------------------------------------------------------------------------

STOPWORDS = {
    "en": "the is are of and to in on for with this that it we you what how much many your our "
          "there has have was be at from by about total".split(),
    "de": "der die das und ist sind nicht von zu im in auf für mit wie viele hoch ein eine "
          "wir sie es den dem des gibt wurde sich auch bei".split(),
    "es": "el la los las de y es son en con para por un una que del se hay al como más "
          "cuántos cuánto este esta total".split(),
    "pl": "i w na z do jest są nie to się że jak ile dla przez oraz ten ta całkowity "
          "poziomie projektu wynosi jest".split(),
}
DIACRITICS = {"de": "äöüß", "es": "ñ¿¡áéíóú", "pl": "ąćęłńóśźż"}


def detect_language(text: str) -> str | None:
    """en/de/es/pl by stop words and diacritics; None when there is too little text."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < 3:
        return None
    score = {lang: sum(w in set(sw) for w in words) for lang, sw in STOPWORDS.items()}
    for lang, chars in DIACRITICS.items():
        score[lang] += sum(text.lower().count(c) for c in chars) * 0.5
    ranked = sorted(score.items(), key=lambda kv: -kv[1])
    if ranked[0][1] == 0 or ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


# --- scoring -----------------------------------------------------------------------------------


def score_case(case: dict[str, Any], response: dict[str, Any] | None, latency_s: float
               ) -> dict[str, Any]:
    """Checks of one answer. ``response`` None = no usable answer (HTTP error, timeout)."""
    exp = case["expect"]
    res: dict[str, Any] = {"id": case["id"], "type": case["type"], "lang": case["lang"],
                           "latency_s": round(latency_s, 2), "checks": {}, "detail": []}
    if response is None:
        res.update(ok=False, overflow=False, failed=True, category=None, tools=[],
                   max_tool_chars=0)
        res["checks"]["answered"] = False
        res["detail"].append("no usable answer from the webhook")
        return res
    reply = str(response.get("reply") or "")
    chars = [int(c) for c in response.get("tool_response_chars") or []]
    tools = list(response.get("tools") or [])
    failed = bool(response.get("failed"))
    checks = res["checks"]
    checks["answered"] = bool(reply.strip()) and not failed
    if not checks["answered"]:
        res["detail"].append("workflow error" if failed else "empty reply")

    found = extract_numbers(reply, case.get("noise", ()))
    missing = [n for n in exp["numbers"] if not number_matches(n, found)]
    checks["numbers"] = not missing and (not exp["any_of"] or any(
        number_matches(n, found) for n in exp["any_of"]))
    for n in missing:
        res["detail"].append(f"missing {n['ref']}={n['value']:g}")
    if exp["any_of"] and not any(number_matches(n, found) for n in exp["any_of"]):
        res["detail"].append("none of " + ", ".join(f"{n['ref']}={n['value']:g}"
                                                    for n in exp["any_of"]))
    detected = detect_language(reply)
    checks["language"] = detected == exp["language"]
    if not checks["language"]:
        res["detail"].append(f"language {detected!r}, expected {exp['language']!r}")
    wanted = exp.get("category")
    wanted = [wanted] if isinstance(wanted, str) else list(wanted or [])
    got = str(response.get("category") or "").upper()
    checks["category"] = not wanted or got in wanted
    if not checks["category"]:
        res["detail"].append(f"category {got!r}, expected {wanted}")
    if exp.get("max_tools") is not None:
        checks["tools"] = len(tools) <= exp["max_tools"]
        if not checks["tools"]:
            res["detail"].append(f"called {tools}, expected at most {exp['max_tools']}")
    overflow = any(c > TOOL_RESPONSE_CAP_CHARS for c in chars)
    checks["tool_size"] = not overflow
    if overflow:
        res["detail"].append(f"tool response of {max(chars)} chars (cap {TOOL_RESPONSE_CAP_CHARS})")
    res.update(ok=all(checks.values()), overflow=overflow, failed=failed, category=got,
               tools=tools, max_tool_chars=max(chars, default=0))
    return res


def p95(values: list[float]) -> float | None:
    """Nearest-rank 95th percentile."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


def summarize(results: list[dict[str, Any]], skipped: list[dict[str, str]]) -> dict[str, Any]:
    n = len(results)
    correct = sum(1 for r in results if r["ok"])
    lat = [r["latency_s"] for r in results]
    overflows = sum(1 for r in results if r["overflow"])
    by_type: dict[str, list[int]] = {}
    for r in results:
        tot = by_type.setdefault(r["type"], [0, 0])
        tot[0] += 1
        tot[1] += r["ok"]
    summary = {
        "scored": n, "correct": correct, "correct_pct": round(100 * correct / n, 1) if n else 0.0,
        "overflows": overflows, "failed": sum(1 for r in results if r["failed"]),
        "latency_p50_s": sorted(lat)[len(lat) // 2] if lat else None, "latency_p95_s": p95(lat),
        "latency_max_s": max(lat, default=None),
        "max_tool_response_chars": max((r["max_tool_chars"] for r in results), default=0),
        "by_type": {k: f"{v[1]}/{v[0]}" for k, v in sorted(by_type.items())},
        "skipped": len(skipped),
    }
    summary["pass"] = bool(n) and correct / n >= MIN_CORRECT and overflows == 0 and (
        summary["latency_p95_s"] is not None and summary["latency_p95_s"] < MAX_P95_S)
    return summary


# --- calling the webhook -----------------------------------------------------------------------


def post(url: str, token: str, payload: dict[str, Any], timeout: float
         ) -> tuple[dict[str, Any] | None, float]:
    """``(response JSON or None, seconds)``; never raises on HTTP/network errors."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json",
                                          TOKEN_HEADER: token})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
        return (body if isinstance(body, dict) else None), time.monotonic() - start
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None, time.monotonic() - start


def payload_for(text: str, channel: str, user: str) -> dict[str, Any]:
    return {"content": text, "author_id": user, "author_name": "concho-eval",
            "channel_id": channel, "message_id": uuid.uuid4().hex, "source": "eval"}


def run_case(case: dict[str, Any], url: str, token: str, run_id: str, timeout: float
             ) -> dict[str, Any]:
    channel = f"eval-{run_id}-{case['id']}"
    user = f"eval-{run_id}"  # memory is per user AND channel: a fresh channel per question
    if case.get("after"):
        post(url, token, payload_for(case["after"], channel, user), timeout)
    response, seconds = post(url, token, payload_for(case["text"], channel, user), timeout)
    result = score_case(case, response, seconds)
    result["reply"] = (response or {}).get("reply", "")
    return result


def format_report(results: list[dict[str, Any]], skipped: list[dict[str, str]],
                  summary: dict[str, Any]) -> str:
    lines = []
    for r in results:
        lines.append(f"{'PASS' if r['ok'] else 'FAIL'}  {r['id']:<26} {r['latency_s']:>6.1f}s  "
                     + ("; ".join(r["detail"]) if r["detail"] else ""))
    for s in skipped:
        lines.append(f"SKIP  {s['id']:<26} {s['reason']}")
    lines += ["", f"correct: {summary['correct']}/{summary['scored']} "
              f"({summary['correct_pct']} %, need >= {MIN_CORRECT * 100:.0f} %)",
              f"context overflows: {summary['overflows']} (need 0); workflow errors: "
              f"{summary['failed']}",
              f"latency p50 {summary['latency_p50_s']} s, p95 {summary['latency_p95_s']} s "
              f"(need < {MAX_P95_S:g} s), max {summary['latency_max_s']} s",
              f"largest tool response: {summary['max_tool_response_chars']} chars "
              f"(cap {TOOL_RESPONSE_CAP_CHARS})", f"by type: {summary['by_type']}",
              f"skipped (tier 2): {summary['skipped']}",
              "RESULT: " + ("PASS" if summary["pass"] else "FAIL")]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path,
                        help="team repo (ingested), source of the expected values")
    parser.add_argument("--db", type=Path, help="data-API database file instead of --repo")
    parser.add_argument("--cases", type=Path, help="cases.json from scripts/eval_cases.py --out")
    parser.add_argument("--questions", type=Path, default=eval_cases.QUESTIONS_PATH)
    parser.add_argument("--snapshot", help="snapshot id the agent answers from (default latest)")
    parser.add_argument("--url", default=os.environ.get("CONCHO_EVAL_WEBHOOK_URL"),
                        help="webhook URL (default $CONCHO_EVAL_WEBHOOK_URL)")
    parser.add_argument("--token", default=os.environ.get("CONCHO_WEBHOOK_TOKEN"),
                        help="header token (default $CONCHO_WEBHOOK_TOKEN)")
    parser.add_argument("--only", help="comma separated question ids")
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds per call")
    parser.add_argument("--report", type=Path, help="write the full results as JSON")
    parser.add_argument("--dry-run", action="store_true", help="resolve and print, no calls")
    args = parser.parse_args(argv)
    try:
        if args.cases:
            doc = json.loads(args.cases.read_text(encoding="utf-8"))
            cases, dropped = doc["cases"], doc.get("dropped", [])
        else:
            conn = eval_cases.open_db(args.repo, args.db)
            cases, dropped = eval_cases.build_cases(
                conn, eval_cases.load_questions(args.questions), args.snapshot)
    except (eval_cases.CaseError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    skipped = [{"id": c["id"], "reason": c["skip"]} for c in cases if c.get("skip")]
    skipped += [{"id": d["id"], "reason": "dropped: " + d["reason"]} for d in dropped]
    todo = [c for c in cases if not c.get("skip")]
    if args.dry_run:
        for c in todo:
            nums = [f"{n['ref']}={n['value']:g}" for n in c["expect"]["numbers"]
                    + c["expect"]["any_of"]]
            print(f"{c['id']:<26} {c['text'][:70]!r} {' '.join(nums)}")
        print(f"{len(todo)} questions, {len(skipped)} skipped")
        return 0
    if not args.url or not args.token:
        print("error: set --url/--token or CONCHO_EVAL_WEBHOOK_URL / CONCHO_WEBHOOK_TOKEN",
              file=sys.stderr)
        return 2
    run_id = uuid.uuid4().hex[:8]
    results = []
    for case in todo:
        r = run_case(case, args.url, args.token, run_id, args.timeout)
        results.append(r)
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['id']} ({r['latency_s']}s)", flush=True)
    summary = summarize(results, skipped)
    print()
    print(format_report(results, skipped, summary))
    if args.report:
        args.report.write_text(json.dumps({"summary": summary, "results": results,
                                           "skipped": skipped}, indent=2, ensure_ascii=False),
                               encoding="utf-8")
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
