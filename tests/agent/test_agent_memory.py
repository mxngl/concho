"""P6.4: chat memory (Postgres). Static checks of the SQL file and the workflow wiring; the SQL
itself runs against a real Postgres when ``CONCHO_TEST_PSQL`` holds psql's connection options
(e.g. ``-h /tmp/pgsock -p 5499 -U postgres``): not available in CI, run by hand.
"""

from __future__ import annotations

import os
import re
import shlex
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


def test_only_successful_turns_of_known_users_are_saved(wf):
    gate = h.by_name(wf)["Remember turn?"]["parameters"]["conditions"]["conditions"]
    left = {c["leftValue"] for c in gate}
    assert left == {"={{ $json.failed }}", "={{ $json.user_id }}", "={{ $json.reply }}",
                    "={{ $json.channel_id }}"}
    assert next(c for c in gate if c["leftValue"] == "={{ $json.failed }}")["operator"][
        "operation"] == "false"


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
