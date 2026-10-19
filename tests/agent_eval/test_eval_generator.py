"""P6.8: the question templates and the generator (``scripts/eval_cases.py``), offline.

The data is the invented data-API test repo (``tests/data_api/api_synthetic.py``): no Island,
course or RSMeans data. The templates themselves must hold no number."""

from __future__ import annotations

import json
import re

import eval_cases as ec
import eval_helpers  # noqa: F401
import pytest
import yaml

QUESTIONS = ec.QUESTIONS_PATH


@pytest.fixture(scope="module")
def questions():
    return ec.load_questions()


@pytest.fixture(scope="module")
def built(eval_conn, questions):
    return ec.build_cases(eval_conn, questions)


# --- the template file -----------------------------------------------------------------------


def test_at_least_40_scored_questions_covering_every_required_kind(questions):
    tier1 = [q for q in questions if q.get("tier", 1) == 1]
    assert len(tier1) >= 40
    types = {q["type"] for q in tier1}
    assert {"cost", "carbon", "quantity", "whatif", "multilang", "followup",
            "out_of_scope"} <= types
    assert {q["lang"] for q in tier1} == {"en", "de", "es", "pl"}
    for lang in ("de", "es", "pl"):
        assert sum(1 for q in tier1 if q["lang"] == lang and q["type"] != "out_of_scope") >= 3


def test_schedule_questions_are_tier2_and_skipped(questions, built):
    sched = [q for q in questions if q["type"] == "schedule"]
    assert len(sched) >= 3 and all(q["tier"] == 2 and q["skip"] for q in sched)
    cases, _ = built
    assert all(c.get("skip") for c in cases if c["type"] == "schedule")
    assert not any(c.get("skip") for c in cases if c["type"] != "schedule")
    assert not any(c["tier"] == 2 for c in cases if not c.get("skip"))


def test_ids_are_unique_and_categories_known(questions):
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))
    for q in questions:
        cats = q["expect"].get("category")
        for cat in [cats] if isinstance(cats, str) else cats or []:
            assert cat in ec.CATEGORIES
        assert q["lang"] in ec.LANGUAGES


def test_followups_name_an_existing_first_question_with_its_text(questions):
    by_id = {q["id"]: q for q in questions}
    follow = [q for q in questions if q["type"] == "followup"]
    assert len(follow) >= 3
    for q in follow:
        first = by_id[q["after_id"]]
        assert q["after"] == first["text"], q["id"]  # the primer is the real first question
        assert first["lang"] == q["lang"]


def test_templates_contain_no_typed_numbers_or_project_data(questions):
    """Expected values are refs; the only digits allowed are in params (what-if percents)."""
    raw = QUESTIONS.read_text(encoding="utf-8")
    body = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"\d[\d.,]{3,}", body)  # no 1,234 / 79200 style number
    assert not re.search(r"\b(value|expected)\s*:", body)
    for q in questions:
        for key in ("numbers", "any_of"):
            for spec in q["expect"].get(key, []):
                assert set(spec) <= {"ref", "args", "tol"}
                assert spec["ref"] in ec.REFS
        # digits in the wording only come from params (what-if percents), never typed values
        # (tier 2 asks about dates and weeks that have no expected value yet)
        wording = re.sub(r"CO2e?", "", q["text"])
        assert q.get("tier", 1) == 2 or not re.search(r"\d", wording), q["id"]
    low = raw.lower()
    for word in ("island", "san juan", "puerto rico", "rsmeans", "kgco2e per"):
        assert word not in low
    # the file must stay a plain YAML mapping
    assert yaml.safe_load(raw)["version"] == 1


# --- the generator ---------------------------------------------------------------------------


def test_every_template_resolves_on_the_synthetic_data(built, questions):
    cases, dropped = built
    assert dropped == []
    assert len(cases) == len(questions)
    scored = [c for c in cases if not c.get("skip")]
    assert len(scored) >= 40


def test_expected_numbers_are_the_api_values(built):
    """Invented repo: TVD grand total 79,200, target 80,000, carbon life cycle 11,300."""
    by_id = {c["id"]: c for c in built[0]}

    def value(case_id, ref=None, key="numbers"):
        nums = by_id[case_id]["expect"][key]
        return next(n["value"] for n in nums if ref in (None, n["ref"]))

    assert value("cost-total") == 79200.0
    assert value("cost-target") == 80000.0
    assert value("cost-delta") == -800.0
    assert value("carbon-life-cycle") == 11300.0
    assert value("cost-cluster") == 63000.0  # Shell: 21,000 + 12,000 + 30,000
    # what-if: B3010 (flat roof, 30,000) +10 % = +3,000; the contingency line follows (+300)
    assert value("cost-whatif-up", "cost.whatif_change", "any_of") == 3300.0
    assert value("cost-whatif-up", "cost.whatif_total_after", "any_of") == 82500.0
    assert by_id["cost-whatif-down"]["expect"]["any_of"][0]["args"]["pct"] == "-20"
    # tolerance: money 0.5 %, counts exact
    assert by_id["cost-total"]["expect"]["numbers"][0]["rel_tol"] == 0.005
    assert by_id["qty-count-level"]["expect"]["numbers"][0]["rel_tol"] == 0.0


def test_slots_are_deterministic_and_filled_into_every_language(eval_conn, questions, built):
    cases = {c["id"]: c for c in built[0]}
    assert "{" not in "".join(c["text"] + (c["after"] or "") for c in cases.values())
    assert cases["qty-count-level"]["text"].startswith("How many ")
    assert cases["de-qty"]["text"].startswith("Wie viele")
    assert cases["es-qty"]["text"].startswith("¿Cuántos")
    assert cases["pl-qty"]["text"].startswith("Ile elementów")
    again, _ = ec.build_cases(eval_conn, questions)
    assert again == built[0]


def test_followup_case_carries_the_first_question_and_asks_about_the_other_level(built):
    cases = {c["id"]: c for c in built[0]}
    f = cases["follow-qty-level"]
    assert f["after"] == cases["qty-count-level"]["text"]
    assert f["after_id"] == "qty-count-level"
    first_n = cases["qty-count-level"]["expect"]["numbers"][0]["args"]
    follow_n = f["expect"]["numbers"][0]["args"]
    assert first_n["category"] == follow_n["category"] and first_n["level"] != follow_n["level"]
    assert f["text"].startswith("And on")


def test_noise_words_are_the_slot_values_used_in_the_question(built):
    c = {c["id"]: c for c in built[0]}["qty-count-level"]
    assert c["noise"] and all(n in c["text"] for n in c["noise"])


def test_unresolvable_questions_are_dropped_with_a_reason(eval_conn, questions):
    extra = {"id": "x-missing", "type": "cost", "lang": "en", "text": "How much is {nothing}?",
             "expect": {"category": "COST", "numbers": [{"ref": "cost.grand_total"}]}}
    bad_ref = {"id": "x-badref", "type": "cost", "lang": "en", "text": "total?",
               "expect": {"numbers": [{"ref": "cost.nope"}]}}
    no_cluster = {"id": "x-cluster", "type": "cost", "lang": "en", "text": "{cluster_a}?",
                  "params": {}, "expect": {"numbers": [
                      {"ref": "cost.cluster_estimate", "args": {"cluster": "Does Not Exist"}}]}}
    orphan = {"id": "x-orphan", "type": "followup", "lang": "en", "text": "and?",
              "after": "first?", "after_id": "x-missing",
              "expect": {"numbers": [{"ref": "cost.grand_total"}]}}
    cases, dropped = ec.build_cases(eval_conn, [extra, bad_ref, no_cluster, orphan])
    assert cases == []
    reasons = {d["id"]: d["reason"] for d in dropped}
    assert "nothing" in reasons["x-missing"]
    assert "cost.nope" in reasons["x-badref"]
    assert "Does Not Exist" in reasons["x-cluster"]
    assert "x-missing" in reasons["x-orphan"]


def test_duplicate_ids_are_refused(eval_conn):
    q = {"id": "dup", "type": "cost", "lang": "en", "text": "t",
         "expect": {"numbers": [{"ref": "cost.grand_total"}]}}
    with pytest.raises(ec.CaseError, match="duplicate"):
        ec.build_cases(eval_conn, [q, dict(q)])


def test_cli_writes_cases_json(tmp_path, capsys):
    import api_synthetic as syn
    repo = syn.make_repo(tmp_path / "team")
    out = tmp_path / "cases.json"
    assert ec.main(["--repo", str(repo), "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert len(doc["cases"]) >= 46 and doc["dropped"] == []
    assert ec.main(["--repo", str(tmp_path / "nowhere")]) == 1
    capsys.readouterr()
