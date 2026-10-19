"""P6.8: the scorer of ``scripts/run_eval.py`` (numbers, language, latency, tool size), offline."""

from __future__ import annotations

import eval_helpers  # noqa: F401
import pytest
import run_eval as ev


def num(value, rel=0.005, abs_=0.0, ref="x"):
    return {"ref": ref, "args": {}, "value": value, "rel_tol": rel, "abs_tol": abs_}


def case(numbers=(), any_of=(), language="en", category=None, max_tools=None, noise=()):
    return {"id": "q", "type": "cost", "lang": language, "noise": list(noise),
            "expect": {"numbers": list(numbers), "any_of": list(any_of), "language": language,
                       "category": category, "max_tools": max_tools}}


def reply(text, **kw):
    return {"reply": text, "category": "COST", "language": "en", "tools": ["get_cost_summary"],
            "tool_response_chars": [1200], "failed": False, **kw}


# --- numbers ---------------------------------------------------------------------------------


@pytest.mark.parametrize("text, value", [
    ("The total is $79,200.00 (Snapshot: Week 3, 2027-01-17).", 79200),
    ("Die Gesamtkosten liegen bei 79.200,00 USD.", 79200),
    ("El costo total es de 79.200 dólares.", 79200),
    ("Całkowity koszt to 79 200 zł.", 79200),
    ("Total cost: 79200", 79200),
    ("about $79.2k", 79200),
    ("It is $16.1M", 16.1e6),
    ("16,1 Mio. USD", 16.1e6),
    ("16,1 mln", 16.1e6),
    ("2,459,374.64 kgCO2e", 2459374.64),
    ("2.459.374,64 kgCO2e", 2459374.64),
    ("12 walls", 12),
    ("1,234.5 SF", 1234.5),
    ("1.234,5 SF", 1234.5),
])
def test_extract_numbers_understands_separators_and_suffixes(text, value):
    found = ev.extract_numbers(text)
    assert any(abs(v - value) <= 0.0006 * abs(value) for v in found), (text, found)


def test_ambiguous_group_counts_as_thousands_and_as_decimal():
    assert {1234.0, 1.234} <= set(ev.extract_numbers("1,234 and 1.234"))
    assert 0.5 in ev.extract_numbers("0,500")


def test_dates_snapshot_ids_and_question_words_are_not_numbers():
    text = "Snapshot: Run (2027-01-17T09:30:00), id 20270117T093000Z. On Level 2 there are 12."
    found = ev.extract_numbers(text, noise=["Level 2"])
    assert 12.0 in found and 2.0 not in found
    assert 2027.0 not in found and 17.0 not in found and 20270117.0 not in found


def test_number_matching_uses_tolerance_and_ignores_sign():
    assert ev.number_matches(num(79200), [79210.0])  # +0.0126 %
    assert not ev.number_matches(num(79200), [80000.0])
    assert ev.number_matches(num(-800), [800.0])  # told as "800 under"
    assert ev.number_matches(num(12, rel=0.0), [12.0])
    assert not ev.number_matches(num(12, rel=0.0), [12.5])
    assert ev.number_matches(num(1000.4, rel=0.0, abs_=0.5), [1000.0])


def test_all_numbers_are_required_but_any_of_needs_one():
    c = case(numbers=[num(100, ref="a"), num(200, ref="b")])
    ok = ev.score_case(c, reply("a is 100 and b is 200"), 1.0)
    bad = ev.score_case(c, reply("a is 100"), 1.0)
    assert ok["checks"]["numbers"] and not bad["checks"]["numbers"]
    assert "missing b=200" in bad["detail"]
    c = case(any_of=[num(100, ref="a"), num(200, ref="b")])
    assert ev.score_case(c, reply("the change is 200 in total"), 1.0)["checks"]["numbers"]
    assert not ev.score_case(c, reply("the change is 300"), 1.0)["checks"]["numbers"]


# --- language --------------------------------------------------------------------------------


@pytest.mark.parametrize("lang, text", [
    ("en", "The total cost of the project is 79,200 dollars and we are under the target."),
    ("de", "Die Gesamtkosten des Projekts betragen 79.200 USD und wir liegen unter dem Ziel."),
    ("es", "El costo total del proyecto es de 79.200 dólares y estamos por debajo del objetivo."),
    ("pl", "Całkowity koszt projektu wynosi 79 200 zł i jesteśmy poniżej celu."),
])
def test_detect_language(lang, text):
    assert ev.detect_language(text) == lang


def test_detect_language_gives_up_on_tiny_text():
    assert ev.detect_language("79200") is None
    assert ev.detect_language("12 walls") is None


def test_language_check_fails_for_the_wrong_language():
    c = case(numbers=[num(79200)], language="de")
    english = ev.score_case(c, reply("The total cost of the project is 79,200 dollars."), 1.0)
    german = ev.score_case(c, reply("Die Gesamtkosten des Projekts betragen 79.200 USD."), 1.0)
    assert not english["checks"]["language"] and german["checks"]["language"]


# --- the other checks ------------------------------------------------------------------------


def test_category_tools_and_failure_checks():
    c = case(category=["OTHER", "GENERAL"], max_tools=0, language="en")
    text = "I can only help with questions about this project and its data."
    ok = ev.score_case(c, reply(text, category="other", tools=[], tool_response_chars=[]), 1.0)
    assert ok["ok"]
    wrong_cat = ev.score_case(c, reply(text, category="COST", tools=[]), 1.0)
    assert not wrong_cat["checks"]["category"]
    used_tool = ev.score_case(c, reply(text, category="OTHER"), 1.0)
    assert not used_tool["checks"]["tools"]
    failed = ev.score_case(c, reply(text, category="OTHER", tools=[], failed=True), 1.0)
    assert not failed["ok"] and "workflow error" in failed["detail"]
    assert not ev.score_case(c, None, 130.0)["ok"]


def test_oversized_tool_response_is_a_context_overflow():
    c = case(numbers=[num(100)])
    text = "The value is 100 and that is the total of it."
    big = ev.score_case(c, reply(text, tool_response_chars=[500, ev.TOOL_RESPONSE_CAP_CHARS + 1]),
                        1.0)
    assert big["overflow"] and not big["ok"]
    at_cap = ev.score_case(c, reply(text, tool_response_chars=[ev.TOOL_RESPONSE_CAP_CHARS]), 1.0)
    assert not at_cap["overflow"] and at_cap["ok"]
    assert ev.TOOL_RESPONSE_CAP_CHARS == 24000  # 8000 tokens x 3 chars (engines/api/caps.py)


# --- summary ---------------------------------------------------------------------------------


def results(n, wrong=0, latency=2.0, overflow=0):
    out = []
    for i in range(n):
        out.append({"id": f"q{i}", "type": "cost", "ok": i >= wrong, "overflow": i < overflow,
                    "failed": False, "latency_s": latency, "max_tool_chars": 100})
    return out


def test_p95_is_nearest_rank():
    assert ev.p95([]) is None
    assert ev.p95(list(range(1, 21))) == 19  # ceil(0.95 * 20) = 19th value
    assert ev.p95([5.0]) == 5.0
    assert ev.p95([1, 1, 1, 1, 1, 1, 1, 1, 1, 100]) == 100  # 10 values: the 10th


def test_acceptance_criteria():
    assert ev.summarize(results(40, wrong=4), [])["pass"]  # 90 %
    assert not ev.summarize(results(40, wrong=5), [])["pass"]  # 87.5 %
    assert not ev.summarize(results(40, overflow=1), [])["pass"]
    slow = results(40)
    for r in slow[-3:]:
        r["latency_s"] = 25.0
    s = ev.summarize(slow, [])
    assert s["latency_p95_s"] == 25.0 and not s["pass"]
    assert not ev.summarize([], [])["pass"]  # nothing run is not a pass
    s = ev.summarize(results(10), [{"id": "x", "reason": "tier2"}])
    assert s["skipped"] == 1 and s["by_type"] == {"cost": "10/10"}
