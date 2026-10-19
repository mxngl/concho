"""P6.8: the question generator (``scripts/build_eval_set.py``) and ``questions.yaml``.

The generator runs on the INVENTED data of the data-API tests; the expected numbers must come
from the database, never from the YAML.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import api_synthetic as syn
import build_eval_set as gen
import pytest
import yaml

from engines.api import queries, schema
from engines.api.ingest import ingest_repo

QUESTIONS = Path(gen.QUESTIONS)


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    repo = syn.make_repo(tmp_path_factory.mktemp("eval_gen") / "team")
    db = ingest_repo(repo)["db"]
    connection = schema.connect(str(db), readonly=True)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def built(conn):
    return gen.build(conn)


def by_id(built):
    return {q["id"]: q for q in built["questions"]}


# ------------------------------------------------------------------ questions.yaml


def test_the_question_file_is_big_enough_and_covers_every_kind():
    spec = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    questions = spec["questions"]
    assert len({q["id"] for q in questions}) == len(questions)
    runnable = [q for q in questions if q.get("tier", 1) == 1]
    assert len(questions) >= 40 and len(runnable) >= 40
    assert {q["lang"] for q in questions} >= {"en", "de", "es", "pl"}
    groups = {q["group"] for q in questions}
    assert groups >= {"cost", "carbon", "quantities", "what-if", "follow-up", "languages",
                      "out-of-scope", "schedule", "general", "robustness"}
    assert all(q.get("tier") == 2 for q in questions if q["group"] == "schedule"
               and q["id"] != "schedule-not-available"), "schedule questions are tier 2"
    assert sum(q.get("tier") == 2 for q in questions) >= 3
    follow = [q for q in questions if q["group"] == "follow-up"]
    assert len(follow) >= 3 and all(q.get("setup") for q in follow)
    cluster_over = next(q for q in questions if q["id"] == "cost-whatif-cluster-over-target")
    assert cluster_over["expect"]["status"]["value"] == "over_target"


def test_no_number_is_typed_into_the_yaml():
    spec = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    for q in spec["questions"]:
        for n in (q.get("expect") or {}).get("numbers", []):
            assert "fact" in n or "ref" in n, f"{q['id']}: expected numbers come from facts"
            assert not any(k in n for k in ("value", "number")), q["id"]
    text = QUESTIONS.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"\d{1,3}(,\d{3})+|\d{5,}", code), "no project-sized number in the YAML"


def test_every_fact_and_binding_used_exists():
    spec = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    used = set(re.findall(r"fact: ([a-z][a-z_.]+)", QUESTIONS.read_text(encoding="utf-8")))
    assert used and used <= set(gen.FACTS), sorted(used - set(gen.FACTS))
    for q in spec["questions"]:
        bound = set(q.get("bind") or {})
        for name in re.findall(r"\{(\w+)(?:\[\w+\])?\}", " ".join([q["ask"], *q.get("setup", [])])):
            assert name in bound, f"{q['id']}: {{{name}}} is not bound"


# ------------------------------------------------------------------ generated set


def test_expected_numbers_come_from_the_database(built, conn):
    q = by_id(built)
    assert q["cost-total"]["expect"]["numbers"][0]["value"] == syn.GRAND_TOTAL
    assert q["cost-total"]["expect"]["status"] == {"value": "under_target", "subject": None}
    assert q["cost-target"]["expect"]["numbers"][0]["value"] == syn.TARGET
    snap = queries.resolve_snapshot(conn, None)
    shell = next(r for r in queries.cost_summary(conn, snap)["rows"] if r["cluster"] == "Shell")
    expect = q["cost-cluster-status"]["expect"]
    assert q["cost-cluster-status"]["ask"].startswith("How does the Shell cluster")
    assert [n["value"] for n in expect["numbers"]] == [shell["estimate"], shell["target"]]
    assert expect["status"]["value"] == shell["status"] and expect["status"]["subject"] == "Shell"


def test_the_what_if_numbers_are_the_servers(built, conn):
    q = by_id(built)["cost-whatif-plus-10"]
    expected = q["expect"]["numbers"][0]["value"]
    assert expected == pytest.approx(syn.GRAND_TOTAL + 3300.0)
    assert q["expect"]["scenario_label"] is True and "B30" in q["ask"]


def test_the_cluster_over_target_question_is_a_real_flip(built, conn):
    q = by_id(built)["cost-whatif-cluster-over-target"]
    cluster = q["expect"]["status"]["subject"]
    assert q["expect"]["status"]["value"] == "over_target" and cluster in q["ask"]
    cluster_after = q["expect"]["numbers"][0]["value"]
    snap = queries.resolve_snapshot(conn, None)
    target = next(r["target"] for r in queries.cost_summary(conn, snap)["rows"]
                  if r["cluster"] == cluster)
    assert cluster_after > target, "the cluster really ends above its own target"


def test_follow_ups_carry_their_setup_message(built):
    q = by_id(built)["qty-followup-level"]
    assert q["setup"] == ["How many Walls are there on L1?"] and q["ask"] == "And on L2?"
    assert q["expect"]["numbers"][0]["exact"] is True


def test_tier2_and_unavailable_data_are_skipped_with_a_reason(built):
    q = by_id(built)
    assert q["schedule-day"]["skip"] == "tier2" and q["schedule-deliveries"]["skip"] == "tier2"
    assert q["carbon-use-phase"]["skip"].startswith("data: use phase not modeled")
    assert q["general-compare"]["skip"].startswith("data: requirement not met")
    assert "skip" not in q["cost-total"]
    assert all("skip" in x or x["ask"] for x in built["questions"])


def test_unknown_names_questions_list_valid_names(built):
    q = by_id(built)
    assert set(q["cost-unknown-cluster"]["expect"]["names_any"]) == set(syn.LINE_ITEMS)
    assert "L1" in q["qty-unknown-level"]["expect"]["names_any"]
    assert q["oos-weather"]["expect"]["no_tools"] and q["oos-weather"]["category"] == "OTHER"
    # a greeting is small talk (OTHER) or "what can you do" (GENERAL); an unknown level is an
    # unknown_level error of /elements/count (no_match for /quantities)
    assert q["oos-greeting"]["category"] == ["GENERAL", "OTHER"]
    assert {"unknown_level", "no_match"} <= set(
        q["qty-unknown-level"]["expect"]["tool_errors_allowed"])


def test_the_set_is_valid_json_and_names_the_snapshot(built):
    json.dumps(built)
    assert built["snapshot"]["id"] and built["snapshot"]["timestamp"]


def test_cli_writes_the_set(tmp_path, conn, capsys):
    repo = syn.make_repo(tmp_path / "team")
    out = tmp_path / "set.json"
    assert gen.main(["--repo", str(repo), "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert any(q["id"] == "cost-total" for q in data["questions"])
    assert "skip schedule-day: tier2" in capsys.readouterr().out
    assert out.resolve().is_relative_to(tmp_path)


def test_generated_files_are_git_ignored():
    ignored = (Path(gen.REPO_ROOT) / ".gitignore").read_text(encoding="utf-8")
    assert "tests/agent_eval/generated/" in ignored
    assert str(gen.DEFAULT_OUT).endswith("tests/agent_eval/generated/eval_set.json")
