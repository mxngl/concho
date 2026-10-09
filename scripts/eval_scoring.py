"""Scoring of the Concho eval (roadmap P6.8): numeric match, language match, latency, tool size.

Pure functions, no network: ``scripts/run_eval.py`` posts the questions, this module judges the
answers. Offline tests: ``tests/agent_eval/test_eval_scoring.py``.

Numeric match
    An expected number is found when *some* number in the reply is within tolerance. Numbers are
    read the way a chat reply writes them in en/de/es/pl: ``16,081,484``, ``16.081.484``,
    ``16 081 484``, ``1,5`` / ``1.5``, ``16.1 million``, ``16,1 Mio.``, ``16 mln``. An ambiguous
    token such as ``1.234`` yields both readings (1.234 and 1234); a magnitude word adds the
    scaled reading next to the plain one (``12 m`` stays 12 as well as 12 000 000), so a unit
    cannot hide a right answer. Dates and the question's own entity names ("Level 2") are removed
    first, so they cannot satisfy a small count by accident. The sign is ignored (an answer says
    "over by"/"under by").
Language match
    Stop-word and diacritic count for en/de/es/pl; the language with a clear lead wins.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- numbers

REL_TOL = 0.01    # amounts (money, kgCO2e, areas ...): within 1 %  ("about 16.1 million")
COUNT_TOL = 0.01  # counts must be exact (42 and 42.0 are the same, 41.9 is not)

_THOUSAND = r"k|tsd|tausend|thousand|tys|tysi[aą]c\w*|mil"
_MILLION = r"mm|m|mio|mill?|million\w*|mill[oó]n\w*|mln|milion\w*"
_BILLION = r"bn|billion\w*|mrd|mld|milliard\w*|miliard\w*"
_MAGNITUDE = re.compile(rf"\s?(?P<k>{_THOUSAND})\b\.?|\s?(?P<m>{_MILLION})\b\.?"
                        rf"|\s?(?P<b>{_BILLION})\b\.?", re.IGNORECASE)
_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9}

_SEP = r"[   .,']"
_NUMBER = re.compile(
    rf"(?<![\w.,])(?P<num>\d{{1,3}}(?:{_SEP}\d{{3}})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?![\d])")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?\b"
                   r"|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b")


def _readings(token: str) -> set[float]:
    """Every plausible value of a number token (see module docstring)."""
    t = token.replace(" ", " ").replace(" ", " ").replace("'", " ")
    out: set[float] = set()

    def add(s: str) -> None:
        try:
            out.add(float(s))
        except ValueError:
            pass

    if " " in t:  # space = thousands separator; a decimal separator may follow
        head, _, tail = t.rpartition(" ")
        m = re.fullmatch(r"(\d{3})([.,]\d+)?", tail)
        if m:
            add(re.sub(r"[ .,]", "", head + m.group(1)) + (
                "." + m.group(2)[1:] if m.group(2) else ""))
            return out
        add(re.sub(r"[ ]", "", t).replace(",", "."))
        return out
    seps = re.findall(r"[.,]", t)
    if not seps:
        add(t)
    elif "." in seps and "," in seps:
        dec = t[max(t.rfind("."), t.rfind(","))]
        thousands = "," if dec == "." else "."
        add(t.replace(thousands, "").replace(dec, "."))
    elif len(seps) > 1:  # 16.081.484 or 16,081,484: thousands only
        add(re.sub(r"[.,]", "", t))
    else:  # one separator
        head, _, tail = t.partition(seps[0])
        add(f"{head}.{tail}")
        if len(tail) == 3 and 1 <= len(head) <= 3:  # 1,234 / 1.234 could also be 1234
            add(head + tail)
    return out


def extract_numbers(text: str, ignore: Iterable[str] = ()) -> list[float]:
    """Absolute values of every number reading in ``text`` (dates and ``ignore`` removed)."""
    for s in ignore:
        if s:
            text = re.sub(re.escape(str(s)), " ", text, flags=re.IGNORECASE)
    text = _DATE.sub(" ", text)
    values: list[float] = []
    for m in _NUMBER.finditer(text):
        base = _readings(m.group("num"))
        values.extend(base)
        mag = _MAGNITUDE.match(text, m.end())
        if mag:
            scale = _SCALE[next(k for k in ("k", "m", "b") if mag.group(k))]
            values.extend(v * scale for v in base)
    return [abs(v) for v in values]


def number_matches(expected: float, found: Sequence[float], kind: str = "amount",
                   rel_tol: float = REL_TOL) -> bool:
    expected = abs(expected)
    if kind == "count":
        return any(abs(v - expected) <= COUNT_TOL for v in found)
    tol = max(expected * rel_tol, 0.5 if expected >= 100 else 0.0, 1e-9)
    return any(abs(v - expected) <= tol for v in found)


# --------------------------------------------------------------------------- language

_WORDS: dict[str, set[str]] = {
    "en": set("the is are of and to for with this that we you has have there from it which "
              "total about by was were not currently cost costs per than your our".split()),
    "de": set("der die das und ist sind von mit für nicht ein eine einen den dem im auf zu "
              "wir sie es dass wie hat haben gibt auch bei aus nach noch gesamt insgesamt".split()),
    "es": set("el la los las de del y es son un una para con por que en se no hay al lo su "
              "como más total actualmente tiene tenemos".split()),
    "pl": set("jest są nie to na w z i do się dla jak co czy ale po przez ponad poniżej "
              "około razem łącznie całkowity koszt ma mamy".split()),
}
_CHARS = {"pl": "ąćęłńśźż", "de": "äöüß", "es": "ñ¿¡"}


def language_scores(text: str) -> dict[str, float]:
    words = re.findall(r"[^\W\d_]+", text.lower())
    scores = {lang: float(sum(w in vocab for w in words)) for lang, vocab in _WORDS.items()}
    for lang, chars in _CHARS.items():
        scores[lang] += 1.5 * sum(text.lower().count(c) for c in chars)
    return scores


def detect_language(text: str) -> str | None:
    """en / de / es / pl, or None when no language leads clearly (too short, mixed, other)."""
    scores = language_scores(text)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (best, top), (_, second) = ranked[0], ranked[1]
    return best if top >= 2 and top >= second + 1.5 else None


# --------------------------------------------------------------------------- scoring

TOOL_CHAR_CAP = 24_000  # the data API's own cap: 8,000 tokens at 3 characters per token


@dataclass
class Score:
    id: str
    numeric_ok: bool
    text_ok: bool
    language_ok: bool
    tools_ok: bool
    failed: bool
    latency_s: float
    tool_chars_max: int
    overflow: bool
    detected_language: str | None
    router_category: str | None = None
    category_ok: bool | None = None
    missing: list[str] = field(default_factory=list)

    @property
    def correct(self) -> bool:
        return (self.numeric_ok and self.text_ok and self.language_ok and self.tools_ok
                and not self.failed)


def score_reply(question: Mapping[str, Any], response: Mapping[str, Any] | None,
                latency_s: float) -> Score:
    """Judge one answer. ``question`` is a resolved question of ``eval_questions``;
    ``response`` is the webhook's JSON (``reply``, ``category``, ``language``, ``tools``,
    ``tool_response_chars``, ``failed``), or None when the call itself failed."""
    no_response = response is None
    response = response or {}
    reply = str(response.get("reply") or "")
    failed = no_response or not reply.strip() or bool(response.get("failed"))
    tools = list(response.get("tools") or [])
    chars = [int(c) for c in (response.get("tool_response_chars") or [])]
    found = extract_numbers(reply, question.get("ignore", ()))
    missing_numbers = [f"{exp['fact']}={exp['value']:g}" for exp in
                       question.get("expect_numbers", ())
                       if not number_matches(exp["value"], found, exp.get("kind", "amount"))]
    low = reply.lower()
    missing_text = [f"text:{needle}" for needle in question.get("expect_text", ())
                    if needle.lower() not in low]
    missing = [*missing_numbers, *missing_text]
    wanted = question.get("tools")  # "none" | "some" | None
    tools_ok = (len(tools) == 0 if wanted == "none"
                else len(tools) > 0 if wanted == "some" else True)
    if wanted == "none" and tools:
        missing.append("tools:" + ",".join(tools))
    if wanted == "some" and not tools:
        missing.append("tools:none called")
    detected = detect_language(reply)
    expected_lang = question.get("lang")
    category = response.get("category")
    expected_cat = question.get("category")
    return Score(
        id=question["id"],
        numeric_ok=not missing_numbers, text_ok=not missing_text,
        language_ok=expected_lang is None or detected == expected_lang,
        tools_ok=tools_ok, failed=failed, latency_s=latency_s,
        tool_chars_max=max(chars, default=0),
        overflow=any(c > TOOL_CHAR_CAP for c in chars),
        detected_language=detected, router_category=category,
        category_ok=(None if not expected_cat or no_response
                     else str(category).upper() == expected_cat),
        missing=missing)


def p95(values: Sequence[float]) -> float:
    """Nearest-rank 95th percentile (0.0 for no values)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


@dataclass
class Summary:
    total: int
    correct: int
    accuracy: float
    overflows: int
    p95_latency_s: float
    max_tool_chars: int
    language_accuracy: float
    routing_accuracy: float | None
    passed: bool
    reasons: list[str]


def summarize(scores: Sequence[Score], *, min_accuracy: float = 0.90, max_overflows: int = 0,
              max_p95_s: float = 20.0) -> Summary:
    """The acceptance criteria of P6.8: >= 90 % correct, 0 context overflows, p95 < 20 s."""
    n = len(scores)
    correct = sum(s.correct for s in scores)
    routed = [s.category_ok for s in scores if s.category_ok is not None]
    summary = Summary(
        total=n, correct=correct, accuracy=correct / n if n else 0.0,
        overflows=sum(s.overflow for s in scores),
        p95_latency_s=p95([s.latency_s for s in scores]),
        max_tool_chars=max((s.tool_chars_max for s in scores), default=0),
        language_accuracy=sum(s.language_ok for s in scores) / n if n else 0.0,
        routing_accuracy=sum(routed) / len(routed) if routed else None,
        passed=False, reasons=[])
    if n == 0:
        summary.reasons.append("no question was run")
    if n and summary.accuracy < min_accuracy:
        summary.reasons.append(f"accuracy {summary.accuracy:.0%} < {min_accuracy:.0%}")
    if summary.overflows > max_overflows:
        summary.reasons.append(f"{summary.overflows} context overflow(s)")
    if n and summary.p95_latency_s >= max_p95_s:
        summary.reasons.append(f"p95 latency {summary.p95_latency_s:.1f} s >= {max_p95_s:g} s")
    summary.passed = not summary.reasons
    return summary
