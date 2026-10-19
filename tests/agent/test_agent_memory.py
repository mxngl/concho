"""P6.4: chat memory (Postgres). Static checks of the SQL file and the workflow wiring; the SQL
itself runs against a real Postgres when ``CONCHO_TEST_PSQL`` holds psql's connection options
(e.g. ``-h /tmp/pgsock -p 5499 -U postgres``): not available in CI, run by hand.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess

import agent_helpers as h
import pytest

SQL_FILE = h.AGENT / "memory.sql"
AGENTS = ["Router", "Cost Agent", "Carbon Agent", "Quantity Agent", "General Agent",
          "Fallback Agent"]


@pytest.fixture(scope="module")
def wf():
    return h.load("concho.json")


def pg_nodes(wf):
    return {n["name"]: n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.postgres"}


def test_sql_file_defines_the_table_the_window_index_and_retention():
    sql = SQL_FILE.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS concho_memory" in sql
    for column in ("user_id", "channel_id", "role", "content", "created_at", "category"):
        assert re.search(rf"\b{column}\b", sql)
    assert "BIGSERIAL" in sql and "CHECK (role IN ('user', 'assistant'))" in sql
    assert "ON concho_memory (user_id, channel_id, id DESC)" in sql   # the window query
    assert "ON concho_memory (created_at)" in sql                     # the retention delete
    assert "concho_memory_cleanup" in sql and "30" in sql
    # idempotent: safe to run again against an existing database
    assert all("IF NOT EXISTS" in line or "OR REPLACE" in line for line in sql.splitlines()
               if re.match(r"\s*CREATE ", line))


def test_two_postgres_nodes_load_before_and_save_after_the_answer(wf):
    nodes = pg_nodes(wf)
    assert set(nodes) == {"Load history", "Save turn"}
    for node in nodes.values():
        assert node["credentials"] == {"postgres": {"id": "concho-postgres",
                                                    "name": "Concho Postgres"}}
        # memory must never take the answer down
        assert node["onError"] == "continueRegularOutput"
    order = {(s, d) for s, d, k, _ in h.edges(wf) if k == "main"}
    assert ("Normalize input", "Load history") in order
    assert ("Load history", "With history") in order
    assert ("Normalize input", "With history") in order
    assert ("With history", "Router") in order and ("With history", "Router + context") in order
    assert ("Respond to caller", "Remember turn?") in order      # saved after the caller got it
    assert ("Remember turn?", "Save turn") in order
    assert nodes["Load history"]["alwaysOutputData"] is True


def test_queries_are_parameterized_and_match_their_parameter_lists(wf):
    nodes = pg_nodes(wf)
    for name, node in nodes.items():
        query = node["parameters"]["query"]
        replacement = node["parameters"]["options"]["queryReplacement"]
        used = {int(n) for n in re.findall(r"\$(\d+)", query)}
        listed = replacement.split("[", 1)[1].rsplit("]", 1)[0]
        count = len(re.findall(r",(?![^()]*\))", "[" + listed + "]")) + 1 if listed else 0
        assert used == set(range(1, max(used) + 1)), name
        assert count == max(used), f"{name}: {count} parameters for ${max(used)}"
        assert "{{" not in query and "$json" not in query, "no string-built SQL"
    load = nodes["Load history"]["parameters"]["query"]
    assert "WHERE user_id = $1 AND channel_id = $2" in load
    assert "make_interval(days => $4::int)" in load and "LIMIT $3::int" in load
    save = nodes["Save turn"]["parameters"]["query"]
    assert "DELETE FROM concho_memory WHERE created_at < now() - make_interval" in save
    assert save.count("INSERT INTO concho_memory") == 1


def test_window_and_retention_come_from_the_env_with_the_defaults(wf):
    text = " ".join(h.strings(pg_nodes(wf)))
    assert "$env.CONCHO_MEMORY_MESSAGES || 6" in text and "$env.CONCHO_MEMORY_DAYS || 30" in text
    assert {"CONCHO_MEMORY_MESSAGES", "CONCHO_MEMORY_DAYS"} <= h.env_vars_in_example()


def test_history_reaches_the_router_and_every_subagent(wf):
    nodes = h.by_name(wf)
    for agent in AGENTS:
        text = nodes[agent]["parameters"]["text"]
        assert "$json.history" in text, agent
        assert "$json.message" in text
    assignments = nodes["Classified"]["parameters"]["assignments"]["assignments"]
    classified = {a["name"] for a in assignments}
    assert "history" in classified, "the history travels with the item to the subagents"


def js(expression: str, item: dict):
    """Evaluate an n8n ``={{ ... }}`` expression with ``$json`` = ``item`` in node."""
    assert expression.startswith("={{") and expression.endswith("}}"), expression
    code = ("const $json = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
            f"process.stdout.write(JSON.stringify({expression[3:-2]}));")
    proc = subprocess.run(["node", "-e", code], input=json.dumps(item), capture_output=True,
                          text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def gate(wf, item: dict, evaluate=js) -> bool:
    """Does ``Remember turn?`` let this item through? (all conditions, combinator AND)"""
    for cond in h.by_name(wf)["Remember turn?"]["parameters"]["conditions"]["conditions"]:
        value = evaluate(cond["leftValue"], item)
        op = cond["operator"]
        if op["type"] == "boolean":
            ok = value is (op["operation"] == "true")
        else:
            assert op["operation"] == "notEmpty"
            ok = bool(value)
        if not ok:
            return False
    return True


def test_only_successful_turns_of_known_users_are_saved(wf):
    gate_nodes = h.by_name(wf)["Remember turn?"]["parameters"]["conditions"]
    assert gate_nodes["combinator"] == "and"
    left = {c["leftValue"] for c in gate_nodes["conditions"]}
    assert left == {"={{ $json.failed }}", "={{ $json.user_id }}", "={{ $json.reply }}",
                    "={{ $json.channel_id }}", "={{ ($json.tool_errors || []).length === 0 }}",
                    "={{ $json.data_unreachable }}"}
    assert next(c for c in gate_nodes["conditions"] if c["leftValue"] == "={{ $json.failed }}")[
        "operator"]["operation"] == "false"


GOOD_TURN = {"failed": False, "user_id": "u1", "channel_id": "c1", "reply": "Total is 16,081,484.",
             "tool_errors": [], "data_unreachable": False}


@needs_node
@pytest.mark.parametrize("change, saved", [
    ({}, True),
    ({"tool_errors": ["tool_failed"]}, False),         # data API stopped
    ({"tool_errors": ["too_many_results"]}, False),    # any tool error: not stored
    ({"tool_errors": ["unknown_cluster", "no_match"]}, False),
    ({"data_unreachable": True}, False),               # "data not reachable" fallback reply
    ({"failed": True}, False),
    ({"reply": ""}, False),
    ({"user_id": ""}, False),
    ({"channel_id": ""}, False),
])
def test_turns_with_a_tool_error_are_not_saved(wf, change, saved):
    """Max saw the "data not reachable" reply in concho_memory after stopping the data API:
    neither the user message nor the reply of such a turn may be stored."""
    assert gate(wf, {**GOOD_TURN, **change}) is saved


@needs_node
def test_a_tool_failure_and_an_unreachable_reply_are_detected_in_compose_reply(wf):
    assigns = {a["name"]: a["value"] for a in
               h.by_name(wf)["Compose reply"]["parameters"]["assignments"]["assignments"]}

    def step(observation):
        return {"action": {"tool": "get_cost_summary"}, "observation": observation}

    def errors(observation):
        return js(assigns["tool_errors"], {"intermediateSteps": [step(observation)]})

    # what the HTTP tool returns when the data API is stopped, in the wording of n8n
    assert errors("The service refused the connection - perhaps it is offline") == ["tool_failed"]
    assert errors("connect ECONNREFUSED 172.19.0.3:8000") == ["tool_failed"]
    assert errors("getaddrinfo ENOTFOUND data-api") == ["tool_failed"]
    assert errors('{"error": "unknown_cluster", "hint": "x"}') == ["unknown_cluster"]
    assert errors('{"snapshot": {"id": "S"}, "grand_total": 1}') == []
    assert js(assigns["tool_errors"], {"intermediateSteps": []}) == []

    def unreachable(reply):
        return js(assigns["data_unreachable"], {"output": reply})

    for reply in ("Sorry, the data is currently not reachable. Please try again later.",
                  "I could not retrieve the data right now.",
                  "I can't access the project data at the moment.",
                  "Die Daten sind nicht erreichbar.",
                  "Ich habe keine Verbindung zur Datenquelle.",
                  "No se pudo acceder a los datos.",
                  "No puedo acceder a los datos.",
                  "Brak dostępu do danych.",
                  "Nie udało się pobrać danych."):
        assert unreachable(reply) is True, reply
    for reply in ("The grand total is 16,081,484 and the target is 15,500,000.",
                  "Der Gesamtbetrag liegt unter dem Zielwert.", "", "Hi! I can help with cost."):
        assert unreachable(reply) is False, reply


def test_memory_sql_and_docs_say_tool_error_turns_are_not_stored():
    def flat(text: str) -> str:
        return re.sub(r"\s*--\s*|\s+", " ", text)

    sql = flat(SQL_FILE.read_text(encoding="utf-8"))
    docs = flat((h.REPO_ROOT / "docs" / "agent.md").read_text(encoding="utf-8"))
    for text in (sql, docs):
        assert "Failed turns are not stored" not in text
        assert "tool_errors not empty" in text or "tool_errors` not empty" in text
    assert "neither the question nor the reply is stored" in sql
    assert "**not stored**" in docs and "data_unreachable" in docs


def test_prompts_use_the_history_only_for_follow_ups():
    common = (h.PROMPTS / "common.md").read_text(encoding="utf-8")
    assert "Chat history" in common and "follow-up" in common
    assert "Numbers in the history are old" in common
    assert "chat history" in (h.PROMPTS / "router.md").read_text(encoding="utf-8")


@pytest.mark.skipif(not os.environ.get("CONCHO_TEST_PSQL"),
                    reason="set CONCHO_TEST_PSQL to psql options of a scratch Postgres")
def test_sql_on_a_real_postgres(wf):
    options = shlex.split(os.environ["CONCHO_TEST_PSQL"])

    def psql(script: str) -> str:
        proc = subprocess.run(["psql", *options, "-v", "ON_ERROR_STOP=1", "-At"], input=script,
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    nodes = pg_nodes(wf)
    sql = SQL_FILE.read_text(encoding="utf-8")
    script = ["DROP TABLE IF EXISTS concho_memory;", sql, sql,   # twice: idempotent
              f"PREPARE save AS {nodes['Save turn']['parameters']['query']};",
              f"PREPARE load AS {nodes['Load history']['parameters']['query']};"]
    for i in range(5):
        script.append(f"EXECUTE save('u1','c1','COST','question {i}','answer {i}',30);")
    script += ["EXECUTE save('u2','c1','COST','other user','x',30);",
               "INSERT INTO concho_memory(user_id, channel_id, role, content, created_at) "
               "VALUES ('u1','c1','user','ancient', now() - interval '40 days');",
               "EXECUTE load('u1','c1',6,30);",
               "SELECT 'ancient rows before the next save: ' || count(*) FROM concho_memory "
               "WHERE content = 'ancient';",
               "EXECUTE save('u1','c1','COST','again','a',30);",   # the purge rides on the save
               "SELECT 'ancient rows after the next save: ' || count(*) FROM concho_memory "
               "WHERE content = 'ancient';"]
    out = psql("\n".join(script))
    lines = [ln for ln in out.splitlines() if ln.startswith(("user:", "assistant:"))]
    assert lines == ["user: question 2", "assistant: answer 2", "user: question 3",
                     "assistant: answer 3", "user: question 4", "assistant: answer 4"]
    assert "other user" not in out and "ancient rows before the next save: 1" in out
    assert "ancient rows after the next save: 0" in out
