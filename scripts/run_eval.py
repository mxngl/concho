"""Run the Concho evaluation (roadmap P6.8): post each question to the webhook and score it.

    python scripts/build_eval_set.py --repo path/to/team-repo       # once per data change
    python scripts/run_eval.py --url http://localhost:5678/webhook/<CONCHO_WEBHOOK_PATH>

The URL defaults to ``$CONCHO_EVAL_URL`` or is built from ``$N8N_PORT`` and
``$CONCHO_WEBHOOK_PATH``; the header ``X-Concho-Token`` is ``$CONCHO_WEBHOOK_TOKEN``. Each
question is a message from the user ``eval-user`` in its own channel ``eval-<run>-<id>`` with
``source: eval`` (n8n posts nothing to Discord for it); earlier messages of a follow-up
question (``setup``) are sent first in the same channel, so the chat memory (P6.4) is tested.

Per question (see :func:`score_question`)
  numbers     every expected number occurs in the reply (tolerance, locale-tolerant parser)
  status      the reply says "over" / "under" target as the data does (heuristic, per language)
  names       valid names the reply must mention (e.g. a cluster instead of a guessed one)
  language    the reply is in the language of the question (word-list heuristic), and so is the
              ``language`` the router reported
  tool error  a tool error is detected from the reply text and ``tool_response_chars``, not only
              from ``failed`` (an error comes back as ``failed: false`` and a polite reply)
  transport   no answer from the workflow (HTTP 404, connection refused, timeout, not JSON) is
              its own failure: "transport error: HTTP 404, is the workflow active / webhook
              registered?", not an agent error
  size        the largest tool response is under the cap (8,000 tokens ~ 24,000 characters);
              a context overflow in the reply or above the cap counts as an overflow
  latency     seconds until the webhook answered
Acceptance (docs/agent-eval.md, roadmap P6.8): accuracy >= 90 %, 0 context overflows, p95
latency < 20 s. Exit code 0 if all three hold, else 1. Heuristic verdicts (status, language) are
listed with the reply in the JSON report so they can be reviewed.
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
DEFAULT_SET = REPO_ROOT / "tests" / "agent_eval" / "generated" / "eval_set.json"
DEFAULT_REPORT = REPO_ROOT / "tests" / "agent_eval" / "generated" / "eval_report.json"
TOOL_CHARS_CAP = 24_000  # engines/api/caps.py: 8,000 tokens x 3 characters
MIN_TOOL_CHARS = 40      # a real tool answer is longer than this; less means "nothing came back"
REQUEST_TIMEOUT_S = 150

# ------------------------------------------------------------------ numbers

_NUMBER = re.compile(
    r"(?<![\w.,])(?:"
    r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?"   # 4 467 302,5 (pl, fr)
    r"|\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?"             # 4,467,302.5 / 4.467.302,5 / 1,234
    r"|\d+(?:[.,]\d+)?"                               # 618515.6 / 12,5
    r")(?:(?P<scale>[kKmM])\b|\s(?P<word>mio|mln|mil|millones|millions?|milion\w*|mrd)\b)?",
    re.IGNORECASE)
_SCALE = {"k": 1e3, "m": 1e6, "mio": 1e6, "mln": 1e6, "million": 1e6, "millions": 1e6,
          "millones": 1e6, "mil": 1e3, "mrd": 1e9}
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?\b")


def _candidates(token: str) -> list[float]:
    """Every plausible value of a number token (the separators are ambiguous: ``1,234``)."""
    token = token.replace(" ", " ").replace(" ", " ")
    values: list[float] = []

    def add(text: str) -> None:
        try:
            values.append(float(text))
        except ValueError:
            pass

    if " " in token:  # space = thousands separator; the rest is the decimal part
        grouped = token.replace(" ", "")
        add(grouped.replace(",", "."))
        return values
    seps = [c for c in token if c in ".,"]
    if not seps:
        add(token)
        return values
    kinds = set(seps)
    if len(kinds) == 2:  # the last separator is the decimal one
        decimal = token[max(token.rfind("."), token.rfind(","))]
        thousands = "," if decimal == "." else "."
        add(token.replace(thousands, "").replace(decimal, "."))
        return values
    sep = seps[0]
    head, _, tail = token.rpartition(sep)
    if len(seps) > 1:  # 4,467,302 / 4.467.302: thousands only
        add(token.replace(sep, ""))
    else:
        add(token.replace(sep, "."))                        # decimal reading: 1.234 / 12,5
        if len(tail) == 3 and head.isdigit():
            add(token.replace(sep, ""))                     # thousands reading: 1,234 -> 1234
    return values


def extract_numbers(text: str) -> list[list[float]]:
    """The numbers of ``text``, each as the list of its candidate values. ISO dates are left out
    (the snapshot line); ``12k``, ``1.2M`` and ``3 Mio`` are scaled."""
    out: list[list[float]] = []
    for m in _NUMBER.finditer(_ISO_DATE.sub(" ", text)):
        suffix = m.group("scale") or m.group("word")
        group = "scale" if m.group("scale") else "word"
        core = m.group(0)[: m.start(group) - m.start()] if suffix else m.group(0)
        values = _candidates(core.strip())
        if suffix:
            key = suffix.lower()
            factor = _SCALE.get(key, 1e6 if key.startswith("milion") else 1)
            values = [v * factor for v in values]
        if values:
            out.append(values)
    return out


def number_matches(expected: float, tol: float, exact: bool, found: list[list[float]]) -> bool:
    """Is ``expected`` among the numbers in the reply? Negative expected values match by size
    (the reply says "20 percent cheaper")."""
    target = abs(expected)
    if exact:
        slack = 0.0
    elif target < 100:
        slack = max(tol * target, 0.005)
    else:
        slack = max(tol * target, 0.5)
    return any(abs(abs(c) - target) <= slack + 1e-9 for cands in found for c in cands)


# ------------------------------------------------------------------ language

_STOPWORDS = {
    "en": "the and is are of to in for with that this on at by you we our it be as from have has "
          "was were what which how many much there about total than can will not".split(),
    "de": "der die das und ist sind von zu im in für mit dass auf bei sie wir unser es nicht ein "
          "eine den dem des wie viele wird werden auch oder noch".split(),
    "es": "el la los las es son de del en para con que por una un se no al lo como más pero su "
          "sus está están hay ha y o".split(),
    "pl": "i w z na do jest są nie to się że jak dla od po przez oraz ale lub co czy jego jej "
          "ich tym tego ma mają był było będzie".split(),
}
_DIACRITICS = {"de": "äöüß", "es": "¿¡ñáéíóú", "pl": "ąćęłńóśźż"}


def detect_language(text: str) -> tuple[str | None, dict[str, float]]:
    """``(language, scores)`` by stop words and diacritics among en/de/es/pl; ``None`` if the
    text is too short or the best two are tied."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < 5:
        return None, {}
    scores: dict[str, float] = {}
    for lang, stop in _STOPWORDS.items():
        stop_set = set(stop)
        hits = sum(1 for w in words if w in stop_set)
        marks = sum(text.lower().count(c) for c in _DIACRITICS.get(lang, ""))
        scores[lang] = hits + 0.5 * marks
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if ranked[0][1] == 0 or ranked[0][1] == ranked[1][1]:
        return None, scores
    return ranked[0][0], scores


# ------------------------------------------------------------------ status, labels, errors

_OVER = {
    "en": ["over target", "over its target", "over the target", "above", "exceed", "over budget",
           "higher than", " over "],
    "de": ["über", "überschreit", "oberhalb", "höher als"],
    "es": ["por encima", "supera", "excede", "sobrepasa", "sobre el objetivo"],
    "pl": ["powyżej", "ponad", "przekracza", "przekroczy"],
}
_UNDER = {
    "en": ["under target", "under its target", "under the target", "below", "within",
           "under budget", "less than", "remains under", " under "],
    "de": ["unter", "unterhalb", "innerhalb", "niedriger", "weniger als"],
    "es": ["por debajo", "debajo", "dentro de", "inferior", "menor que"],
    "pl": ["poniżej", "pod celem", "w ramach", "mniej niż"],
}
_SCENARIO = re.compile(r"what[- ]?if|scenario|szenario|escenario|hipot[eé]tic|scenariusz|"
                       r"hypothe|simulaci", re.IGNORECASE)
_NARROW = re.compile(r"narrow|specific|filter|too (?:many|much)|level|category|cluster|"
                     r"eingrenz|genauer|konkret|zu viele|restring|más específic|demasiad|"
                     r"zawęź|doprecyz|zbyt wiele|konkretn", re.IGNORECASE)
_UNREACHABLE = re.compile(
    r"not (?:currently )?(?:reachable|accessible|available right now)|unreachable|"
    r"(?:can(?:'|no)t|cannot|could not|couldn'?t|unable to|failed to) (?:reach|connect|access|"
    r"retrieve|fetch|load|get)|temporarily unavailable|service (?:is )?unavailable|"
    r"connection (?:error|refused|failed)|data (?:source )?is(?: currently)? not (?:reachable|"
    r"accessible)|"
    r"nicht erreichbar|keine verbindung|kein zugriff|nicht auf die daten zugreifen|"
    r"vorübergehend nicht verfügbar|"
    r"no (?:se )?pu(?:do|edo) (?:acceder|conectar|obtener)|no (?:est[áa]|es) accesible|inaccesible|"
    r"no est[áa] disponible en este momento|"
    r"nie mogę (?:uzyskać|połączyć|pobrać)|brak dostępu|niedostępn|nie udało się (?:połączyć|"
    r"pobrać)", re.IGNORECASE)
_ERROR_REPLY = re.compile(
    r"could not answer that right now|konnte ich gerade nicht beantworten|"
    r"no he podido responder|nie uda[łl]o mi si[ęe] teraz odpowiedzie", re.IGNORECASE)
_CONTEXT_OVERFLOW = re.compile(
    r"context[ _]length|maximum context|context window|too many tokens|token limit|"
    r"reduce the length", re.IGNORECASE)


def _segments(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?;:])\s+|\n+", text) if s.strip()]


_TARGET_WORDS = re.compile(r"target|ziel|objetivo|\bcel\b|budget", re.IGNORECASE)


def _status_words(low: str, lang: str) -> list[tuple[int, str]]:
    over, under = _OVER.get(lang, _OVER["en"]), _UNDER.get(lang, _UNDER["en"])
    hits = [(m.start(), "over_target") for w in over for m in re.finditer(re.escape(w), low)]
    hits += [(m.start(), "under_target") for w in under for m in re.finditer(re.escape(w), low)]
    return hits


# A what-if reply states the status twice: "Before: ... under target. After: ... over target".
_AFTER = re.compile(r"\b(?:after(?:wards)?|nach(?:her)?|despu[eé]s|po)\b", re.IGNORECASE)


def check_status(reply: str, lang: str, expected: str, subject: str | None,
                 what_if: bool = False) -> tuple[bool, str]:
    """The reply says ``expected`` (over_target / under_target) about ``subject`` (a cluster) or,
    without subject, about the target. In a segment that mentions several statuses ("the total
    is under target, Shell is over its target") the status word nearest to the subject wins.
    For a ``what_if`` reply only the part that follows "after" / "nach" / "después" / "po" counts
    (the "before" status is the current state); the last such marker that gives a clear answer
    wins, and a reply without marker is read as a whole.
    Heuristic: the JSON report keeps the reply for review."""
    if what_if:
        for marker in reversed(list(_AFTER.finditer(reply))):
            ok, why = _check_status_in(reply[marker.start():], lang, expected, subject)
            if not why.startswith("reply says nothing"):
                return ok, why
    return _check_status_in(reply, lang, expected, subject)


def _check_status_in(reply: str, lang: str, expected: str,
                     subject: str | None) -> tuple[bool, str]:
    for segment in _segments(reply):
        low = f" {segment.lower()} "
        if subject:
            anchor = low.find(subject.lower())
            if anchor < 0:
                continue
        else:
            m = _TARGET_WORDS.search(low)
            anchor = m.start() if m else 0
        hits = _status_words(low, lang)
        if not hits:
            continue
        nearest = min(abs(pos - anchor) for pos, _ in hits)
        said = {kind for pos, kind in hits if abs(pos - anchor) == nearest}
        if len(said) != 1:
            continue
        got = said.pop()
        return got == expected, f"reply says {got}, data says {expected}"
    of = f" of {subject}" if subject else ""
    return False, f"reply says nothing clear about the status{of}"


def transport_error_message(what: str) -> str:
    """The failure text for a request that got no answer from the workflow (not an agent error).
    ``what`` is ``HTTP 404``, ``connection refused``, ... A 404 on a webhook URL means the
    workflow is not active or the production webhook is registered under another path."""
    if what.startswith("HTTP 40") and what[-1] in "13":   # 401 / 403
        hint = "is CONCHO_WEBHOOK_TOKEN the token of the Concho webhook credential?"
    elif what.startswith("HTTP"):
        hint = "is the workflow active / webhook registered?"
    else:
        hint = "is n8n running and is the URL right?"
    return f"transport error: {what}, {hint}"


def detect_tool_error(response: dict, allowed: list[str]) -> str | None:
    """A tool error the question did not expect, from ``failed``, ``tool_errors``, the size of
    the tool responses and the reply text. Returns a short reason, or ``None``."""
    reply = response.get("reply") or ""
    if response.get("transport_error"):
        return transport_error_message(response["transport_error"])
    if response.get("failed"):
        return "failed=true (agent error branch)"
    if _ERROR_REPLY.search(reply):
        return "the agent answered with the generic error message"
    codes = [c for c in (response.get("tool_errors") or []) if c not in allowed]
    if codes:
        return "tool error " + ", ".join(codes)
    chars = response.get("tool_response_chars") or []
    if response.get("tools") and (not chars or all(c < MIN_TOOL_CHARS for c in chars)):
        return f"tool called but no data came back (tool_response_chars={chars})"
    if _UNREACHABLE.search(reply):
        return "the reply says the data is not reachable"
    return None


# ------------------------------------------------------------------ scoring


def score_question(question: dict, response: dict, latency_s: float) -> dict:
    """Scores for one answered question. ``correct`` needs every required check to pass."""
    expect = question.get("expect") or {}
    reply = response.get("reply") or ""
    lang = question.get("lang") or "en"
    checks: dict[str, dict[str, Any]] = {}

    def record(name: str, ok: bool, detail: str = "", required: bool = True) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail, "required": required}

    error = detect_tool_error(response, expect.get("tool_errors_allowed") or [])
    record("tool_error", error is None, error or "")

    found = extract_numbers(reply)
    for spec in expect.get("numbers") or []:
        ok = number_matches(spec["value"], spec["tol"], spec.get("exact", False), found)
        record(f"number:{spec.get('label')}", ok, f"expected {spec['value']:,.2f}")
    if "status" in expect:
        wanted = expect["status"]
        ok, why = check_status(reply, lang, wanted["value"], wanted.get("subject"),
                               what_if=bool(expect.get("scenario_label")))
        record("status", ok, why)
    low = reply.lower()
    if expect.get("names_any"):
        hit = [n for n in expect["names_any"] if n.lower() in low]
        record("names_any", bool(hit), "" if hit else "none of the valid names is mentioned")
    for name in expect.get("names_all") or []:
        record(f"name:{name}", name.lower() in low, "")
    if expect.get("scenario_label"):
        record("scenario_label", bool(_SCENARIO.search(reply)), "reply must call it a scenario")
    if expect.get("asks_to_narrow"):
        record("asks_to_narrow", bool(_NARROW.search(reply)),
               "reply should ask to narrow the question")
    tools = response.get("tools") or []
    if expect.get("no_tools"):
        record("no_tools", not tools, f"tools called: {tools}" if tools else "")
    if expect.get("needs_tools"):
        record("tools_called", bool(tools), "the answer needs data but no tool was called")
    if question.get("category"):
        accepted = question["category"]
        accepted = [accepted] if isinstance(accepted, str) else list(accepted)
        record("category", response.get("category") in accepted,
               f"router said {response.get('category')}, expected {' or '.join(accepted)}",
               required=bool(expect.get("category_required")))
    detected, scores = detect_language(reply)
    record("reply_language", detected in (None, lang),
           f"detected {detected} {scores}" if detected not in (None, lang) else "")
    router_lang = (response.get("language") or "").lower()
    record("router_language", not router_lang or router_lang.startswith(lang),
           f"router said {router_lang!r}", required=False)

    chars = response.get("tool_response_chars") or []
    biggest = max(chars, default=0)
    overflow = biggest > TOOL_CHARS_CAP or bool(_CONTEXT_OVERFLOW.search(reply))
    snapshot_line = bool(re.search(r"snapshot|stand:|instant[aá]nea|migawka|zrzut", low)) \
        if (expect.get("numbers") and tools) else None
    return {
        "id": question["id"], "group": question.get("group"), "lang": lang,
        "correct": all(c["ok"] for c in checks.values() if c["required"]),
        "checks": checks, "latency_s": round(latency_s, 2), "overflow": overflow,
        "max_tool_chars": biggest, "snapshot_line": snapshot_line,
        "tool_error": error, "transport_error": response.get("transport_error"),
        "reply": reply, "tools": tools,
    }


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (p95 of 40 answers = the 38th)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def summarize(results: list[dict], settings: dict, skipped: list[dict]) -> dict:
    n = len(results)
    correct = sum(r["correct"] for r in results)
    latencies = [r["latency_s"] for r in results if r.get("latency_s") is not None]
    p95 = percentile(latencies, 95)
    overflows = sum(r["overflow"] for r in results)
    lines = [r["snapshot_line"] for r in results if r["snapshot_line"] is not None]
    accuracy = correct / n if n else 0.0
    gates = {
        "accuracy": {"value": round(accuracy, 3), "need": settings.get("min_accuracy", 0.9),
                     "ok": accuracy >= settings.get("min_accuracy", 0.9)},
        "overflows": {"value": overflows, "need": 0, "ok": overflows == 0},
        "p95_latency_s": {"value": round(p95, 2), "need": settings.get("latency_p95_s", 20),
                          "ok": p95 < settings.get("latency_p95_s", 20)},
    }
    by_group: dict[str, list[int]] = {}
    for r in results:
        g = by_group.setdefault(r.get("group") or "-", [0, 0])
        g[0] += r["correct"]
        g[1] += 1
    return {
        "questions": n, "correct": correct, "skipped": len(skipped),
        "tool_errors": sum(r["tool_error"] is not None for r in results),
        "transport_errors": sum(bool(r.get("transport_error")) for r in results),
        "snapshot_line": f"{sum(lines)}/{len(lines)}" if lines else "-",
        "by_group": {g: f"{c}/{t}" for g, (c, t) in sorted(by_group.items())},
        "gates": gates, "passed": all(g["ok"] for g in gates.values()) and n > 0,
    }


# ------------------------------------------------------------------ running


def post(url: str, token: str, payload: dict) -> tuple[dict, float]:
    """POST ``payload``; returns ``(response JSON, seconds)``. A request that gets no usable
    answer (HTTP error status, connection refused, timeout, a body that is not JSON) becomes a
    response with ``transport_error`` so it is scored as its own failure instead of raised."""
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "X-Concho-Token": token})
    started = time.monotonic()

    def transport(what: str, reply: str = "") -> tuple[dict, float]:
        return ({"reply": reply or f"[transport error: {what}]", "failed": False,
                 "transport_error": what, "tools": [], "tool_response_chars": []},
                time.monotonic() - started)

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as handle:
            body = handle.read().decode("utf-8")
        elapsed = time.monotonic() - started
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            return transport("the answer is not JSON", body[:200])
        return parsed, elapsed
    except urllib.error.HTTPError as exc:
        return transport(f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ConnectionRefusedError):
            return transport("connection refused")
        return transport(f"{reason}")
    except TimeoutError:
        return transport(f"no answer within {REQUEST_TIMEOUT_S} s")
    except OSError as exc:
        return transport(str(exc))


def message(question_text: str, run: str, qid: str, n: int) -> dict:
    return {"content": question_text, "author_id": "eval-user", "author_name": "Eval",
            "channel_id": f"eval-{run}-{qid}", "message_id": f"eval-{run}-{qid}-{n}",
            "source": "eval"}


def run_question(question: dict, url: str, token: str, run: str) -> dict:
    for i, text in enumerate(question.get("setup") or []):
        post(url, token, message(text, run, question["id"], i))  # not scored
    response, elapsed = post(url, token, message(question["ask"], run, question["id"], 99))
    return score_question(question, response, elapsed)


def default_url() -> str | None:
    if os.environ.get("CONCHO_EVAL_URL"):
        return os.environ["CONCHO_EVAL_URL"]
    path = os.environ.get("CONCHO_WEBHOOK_PATH")
    if path:
        return f"http://localhost:{os.environ.get('N8N_PORT', '5678')}/webhook/{path}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", type=Path, default=DEFAULT_SET, metavar="FILE",
                        help="generated question set (scripts/build_eval_set.py)")
    parser.add_argument("--url", default=default_url(), help="the production webhook URL")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, metavar="FILE")
    parser.add_argument("--only", metavar="ID[,ID...]", help="run only these question ids")
    parser.add_argument("--group", metavar="NAME", help="run only this group (cost, what-if, ...)")
    parser.add_argument("--list", action="store_true", help="print the questions, post nothing")
    args = parser.parse_args(argv)

    if not args.set.is_file():
        print(f"error: {args.set} not found: run python scripts/build_eval_set.py "
              "--repo <team repo>", file=sys.stderr)
        return 2
    data = json.loads(args.set.read_text(encoding="utf-8"))
    questions = data["questions"]
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    if args.group:
        questions = [q for q in questions if q.get("group") == args.group]
    skipped = [q for q in questions if q.get("skip")]
    runnable = [q for q in questions if not q.get("skip")]
    if args.list:
        for q in runnable:
            print(f"{q['id']:<34} [{q['lang']}] {q['ask']}")
        for q in skipped:
            print(f"{q['id']:<34} SKIPPED ({q['skip']})")
        return 0
    token = os.environ.get("CONCHO_WEBHOOK_TOKEN", "")
    if not args.url or not token:
        print("error: set --url (or CONCHO_EVAL_URL / CONCHO_WEBHOOK_PATH) and "
              "CONCHO_WEBHOOK_TOKEN", file=sys.stderr)
        return 2

    run = uuid.uuid4().hex[:8]
    print(f"snapshot {data['snapshot']['id']}; {len(runnable)} questions, {len(skipped)} skipped; "
          f"run {run}")
    results = []
    for q in runnable:
        result = run_question(q, args.url, token, run)
        results.append(result)
        bad = [f"{k}: {v['detail']}" for k, v in result["checks"].items()
               if v["required"] and not v["ok"]]
        if result["transport_error"]:   # nothing else can be judged without an answer
            bad = [result["tool_error"]]
        mark = "ok  " if result["correct"] else "FAIL"
        print(f"{mark} {q['id']:<34} {result['latency_s']:>5.1f}s"
              + ("" if result["correct"] else "  <- " + "; ".join(bad)))
    summary = summarize(results, data.get("settings") or {}, skipped)
    for q in skipped:
        print(f"skip {q['id']:<34} {q['skip']}")
    print(json.dumps({k: v for k, v in summary.items()}, indent=2))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"run": run, "snapshot": data["snapshot"], "summary": summary,
                                       "skipped": [{"id": q["id"], "reason": q["skip"]}
                                                   for q in skipped], "results": results},
                                      indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"report: {args.report}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
