"""P6.8: the question file and its generator, offline.

The generator turns ``questions.yaml`` into concrete questions with expected numbers read from
the results of one snapshot. Here that snapshot is the invented data of ``tests/data_api``; the
same file resolves against the Island fixture results when ``CONCHO_FIXTURES_DIR`` is set (see
the last test, skipped otherwise).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "data_api"))

pytest.importorskip("fastapi")
import api_synthetic as syn  # noqa: E402
import eval_questions as eq  # noqa: E402

from engines.api.ingest import ingest_repo  # noqa: E402

FIRST, SECOND = "20270110T090000Z", "20270117T093000Z"


@pytest.fixture(scope="module")
def data():
    return eq.load_questions()


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    repo = syn.make_repo(tmp_path_factory.mktemp("eval_gen") / "team", snapshots=(FIRST, SECOND))
    return eq.open_database(Path(ingest_repo(repo)["db"]))


@pytest.fixture(scope="module")
def resolved(data, conn):
    return {q.id: q for q in eq.resolve_questions(data, conn)}


# ------------------------------------------------------------------ the file itself


def test_file_has_40_plus_questions_in_all_required_groups(data):
    questions = data["questions"]
    runnable = [q for q in questions if q.get("tier", 1) == 1]
    assert len(runnable) >= 40
    groups = {q["group"] for q in questions}
    assert {"cost", "carbon", "quantities", "what-if", "multilingual", "follow-up",
            "out-of-scope", "schedule", "general"} <= groups
    assert {q["lang"] for q in questions} == {"en", "de", "es", "pl"}
    assert {"DE", "ES", "PL"} == {q["id"][:2].upper() for q in questions
                                  if q["id"][:2] in ("de", "es", "pl")}


def test_schedule_questions_are_tier_2_and_nothing_else_is(data):
    for q in data["questions"]:
        assert (q.get("tier", 1) == 2) == (q["group"] == "schedule"), q["id"]
        assert (q["category"] == "SCHEDULE") == (q["group"] == "schedule"), q["id"]


def test_follow_ups_follow_a_question_of_the_same_language(data):
    by_id = {q["id"]: q for q in data["questions"]}
    follow = [q for q in data["questions"] if q.get("after")]
    assert len(follow) >= 3
    for q in follow:
        assert by_id[q["after"]]["lang"] == q["lang"]
        assert by_id[q["after"]]["category"] == q["category"]
        # a follow-up does not repeat the topic; it is short
        assert len(q["text"].split()) <= 6


def test_no_number_is_typed_into_the_file(data):
    """Expected values come from the script: no fact holds a literal result, and the question
    texts carry only the numbers the user asks with (what-if percentages, week/date numbers)."""
    for name, fact in data["facts"].items():
        assert set(fact) <= {"sql", "api", "kind", "abs"}, name
        if "sql" in fact:
            assert not re.search(r"=\s*-?\d+(\.\d+)?\s*(?:$|\s)(?!\w)", fact["sql"].replace(
                "dnc=0", "").replace("pct", "")), name
    for q in data["questions"]:
        assert "expect_numbers" not in q and "value" not in q
        for number in re.findall(r"\d[\d.,]*", re.sub(r"\{\w+\}", "", q["text"])):
            assert number.strip(".,") in {"10", "15", "12", "2", "1"}, (q["id"], number)


def test_file_has_no_course_or_licensed_data_markers():
    text = (REPO_ROOT / "tests" / "agent_eval" / "questions.yaml").read_text(encoding="utf-8")
    assert not re.search(r"RSMeans|\.xlsx|workbook", text.replace("no RSMeans", ""), re.I) or \
        "NO expected numbers" in text
    assert not re.search(r"\b\d{17,20}\b", text)  # no Discord ids


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d["questions"].append(dict(d["questions"][0])), "unique"),
    (lambda d: d["questions"][0].update(lang="fr"), "lang"),
    (lambda d: d["questions"][0].update(text="Cost of {nothing}?"), "unknown placeholder"),
    (lambda d: d["questions"][0].update(expect=["no_such_fact"]), "unknown fact"),
    (lambda d: d["questions"][0].update(category="MISC"), "category"),
    (lambda d: d["questions"][0].pop("expect"), "expectation"),
    (lambda d: d["facts"]["cost_total"].update(api={"fn": "compare"}), "exactly one"),
    (lambda d: d["facts"]["cost_total"].update(sql="SELECT :ghost"), "unknown entity"),
    (lambda d: d["questions"][0].update(after="nope"), "unknown question"),
])
def test_validation_catches_file_mistakes(data, mutate, message):
    broken = yaml.safe_load(yaml.safe_dump(data))
    mutate(broken)
    with pytest.raises(eq.QuestionFileError, match=message):
        eq.validate(broken)


# ------------------------------------------------------------------ resolving


def test_expected_numbers_come_from_the_snapshot(resolved):
    cost = resolved["cost-total"]
    assert cost.status == "ready"
    assert cost.expect_numbers == [{"fact": "cost_total", "value": syn.GRAND_TOTAL,
                                    "kind": "amount"}]
    gap = {e["fact"]: e["value"] for e in resolved["cost-target-gap"].expect_numbers}
    assert gap == {"cost_target": syn.TARGET, "cost_gap": abs(syn.GRAND_TOTAL - syn.TARGET)}
    assert resolved["cost-total"].tools == "some"


def test_entities_fill_the_placeholders(resolved, conn):
    q = resolved["qty-level"]
    assert q.status == "ready" and "{" not in q.text
    assert q.text.startswith("How many ") and q.text.endswith("?")
    # the question names a category and a level that exist, and its entities are ignored by the
    # scorer so "Level 2" cannot stand in for the number 2
    assert len(q.ignore) == 2 and all(i in q.text for i in q.ignore)
    count = q.expect_numbers[0]
    assert count["kind"] == "count" and count["value"] == float(int(count["value"])) > 0
    n = conn.execute("SELECT COUNT(*) FROM elements WHERE snapshot_id=? AND dnc=0 "
                     "AND lower(category)=lower(?) AND lower(level)=lower(?)",
                     (SECOND, q.ignore[0], q.ignore[1])).fetchone()[0]
    assert count["value"] == n


def test_cluster_questions_name_the_clusters_and_expect_their_estimates(resolved, conn):
    top = resolved["cost-top-cluster"]
    row = conn.execute("SELECT cluster, estimate FROM tvd_clusters ORDER BY estimate DESC, "
                       "cluster LIMIT 1").fetchone()
    assert top.expect_text == [row["cluster"]]
    assert top.expect_numbers[0]["value"] == row["estimate"]
    assert resolved["fu-cost-2"].text == f"And for {resolved['cost-cluster'].ignore[0]}?"


def test_what_if_numbers_are_computed_by_the_api_functions(resolved, conn):
    from engines.api import queries
    snap = queries.resolve_snapshot(conn, None)
    expect = queries.cost_what_if(conn, snap, "B30", 10)
    got = {e["fact"]: e["value"] for e in resolved["whatif-roof"].expect_numbers}
    assert got["roof_plus_10_total"] == pytest.approx(expect["grand_total_after"])
    assert got["roof_plus_10_gap"] == pytest.approx(abs(expect["delta_to_target_after"]))
    assert resolved["whatif-roof"].expect_numbers[0]["value"] != syn.GRAND_TOTAL


def test_carbon_and_compare_questions_resolve_on_a_full_snapshot(resolved):
    for qid in ("carbon-life-cycle", "carbon-embodied", "carbon-top-assembly",
                "gen-snapshots", "qty-area"):
        assert resolved[qid].status == "ready", (qid, resolved[qid].reason)
    assert resolved["gen-snapshots"].expect_numbers[0]["value"] == 2


def test_an_expected_zero_makes_the_question_unavailable(resolved):
    # two identical snapshots: the cost change is 0, the use phase is not modeled (0)
    for qid in ("gen-compare", "carbon-use-phase", "gen-missing-level"):
        assert resolved[qid].status == "unavailable"
        assert "expected value is 0" in resolved[qid].reason


def test_follow_ups_share_a_conversation_and_need_their_first_question(resolved):
    assert resolved["fu-qty-1"].conv == resolved["fu-qty-2"].conv == "fu-qty-1"
    assert resolved["fu-qty-2"].after == "fu-qty-1"
    assert resolved["cost-total"].conv == "cost-total"
    assert len({q.conv for q in resolved.values()}) < len(resolved)


def test_out_of_scope_questions_expect_no_tool_call(resolved):
    for qid in ("oos-weather", "oos-joke", "oos-capital", "oos-code"):
        q = resolved[qid]
        assert q.status == "ready" and q.tools == "none" and not q.expect_numbers
        assert q.category == "OTHER"


def test_schedule_questions_are_skipped(resolved):
    sched = [q for q in resolved.values() if q.group == "schedule"]
    assert len(sched) >= 3 and all(q.status == "skipped" for q in sched)
    assert all("tier 2" in q.reason for q in sched)


def test_questions_that_the_data_cannot_answer_are_unavailable_not_wrong(tmp_path, data):
    """One snapshot without STV and without a predecessor: carbon, compare unavailable."""
    syn.write_exports(tmp_path / "team")
    syn.add_snapshot(tmp_path / "team", SECOND, stv=None)
    repo = tmp_path / "team"
    conn = eq.open_database(Path(ingest_repo(repo)["db"]))
    by_id = {q.id: q for q in eq.resolve_questions(data, conn)}
    assert by_id["cost-total"].status == "ready"
    assert by_id["gen-compare"].status == "unavailable"
    assert "second, older snapshot" in by_id["gen-compare"].reason
    assert conn.execute("SELECT stv_present FROM snapshots").fetchone()[0] == 0
    for qid in ("carbon-life-cycle", "carbon-material", "whatif-material", "fu-carbon-2"):
        assert by_id[qid].status == "unavailable", qid
    assert by_id["fu-carbon-2"].reason.startswith(("fact", "entity", "depends"))
    assert by_id["fu-carbon-1"].status == "unavailable"
    assert by_id["fu-carbon-2"].status == "unavailable"


def test_a_follow_up_is_unavailable_when_its_first_question_is(data, conn):
    broken = yaml.safe_load(yaml.safe_dump(data))
    broken["entities"]["level_a"]["sql"] = "SELECT level FROM elements WHERE 0"
    by_id = {q.id: q for q in eq.resolve_questions(broken, conn)}
    assert by_id["fu-qty-1"].status == "unavailable"
    assert by_id["fu-qty-2"].status == "unavailable"
    assert by_id["cost-total"].status == "ready"


def test_sql_errors_in_the_file_are_reported_not_swallowed(data, conn):
    broken = yaml.safe_load(yaml.safe_dump(data))
    broken["facts"]["cost_total"]["sql"] = "SELECT nonsense FROM nowhere"
    with pytest.raises(eq.QuestionFileError, match="SQL failed"):
        eq.resolve_questions(broken, conn)


def test_generation_is_deterministic(data, conn):
    a = [q.asdict() for q in eq.resolve_questions(data, conn)]
    b = [q.asdict() for q in eq.resolve_questions(data, conn)]
    assert a == b


def test_island_fixture_resolves_when_available():
    """With the Island fixtures the whole file must resolve (needs the fixture DB)."""
    import os
    if not os.environ.get("CONCHO_EVAL_DB"):
        pytest.skip("set CONCHO_EVAL_DB to a concho.db built from the Island fixtures")
    conn = eq.open_database(Path(os.environ["CONCHO_EVAL_DB"]))
    resolved = eq.resolve_questions(eq.load_questions(), conn)
    ready = [q for q in resolved if q.status == "ready"]
    assert len(ready) >= 40, [(q.id, q.reason) for q in resolved if q.status == "unavailable"]
