"""P6.4: conversation memory in Postgres (offline checks of the workflow and the SQL files).

The subagents use the n8n Postgres Chat Memory node (read and write); the router only reads the
same table through a query ("Load history"), because a memory node would also store the
router's JSON output. What needs a running n8n is listed in ``docs/agent.md``. The optional
database test runs against a real Postgres when ``CONCHO_TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import agent_helpers as h
import pytest

SUBAGENTS = ["Cost", "Carbon", "Quantity", "General", "Fallback"]
SQL_DIR = h.AGENT / "sql"
TABLE = "concho_chat_history"
WINDOW_MESSAGES = 6  # N, roadmap P6.4
RETENTION_DAYS = 30


@pytest.fixture(scope="module")
def wf():
    return h.load("concho.json")


def test_every_subagent_has_one_postgres_memory_on_the_shared_session(wf):
    nodes = h.by_name(wf)
    for agent in SUBAGENTS:
        memories = [s for s, d, k, _ in h.edges(wf) if d == f"{agent} Agent" and k == "ai_memory"]
        assert memories == [f"{agent} Memory"], agent
        mem = nodes[f"{agent} Memory"]
        p = mem["parameters"]
        assert mem["type"] == "@n8n/n8n-nodes-langchain.memoryPostgresChat"
        assert p["tableName"] == TABLE
        assert p["sessionIdType"] == "customKey"
        # the same key for every agent and for the router's history query
        assert p["sessionKey"] == "={{ $json.session_id }}"
        # the node counts question/answer pairs: 3 pairs = the last 6 messages
        assert p["contextWindowLength"] * 2 == WINDOW_MESSAGES
        assert mem["credentials"]["postgres"]["id"] == "concho-postgres"


def test_router_has_no_memory_node_but_reads_the_history_first(wf):
    nodes = h.by_name(wf)
    assert not [1 for s, d, k, _ in h.edges(wf) if d == "Router" and k == "ai_memory"]
    q = nodes["Load history"]["parameters"]["query"]
    assert nodes["Load history"]["parameters"]["operation"] == "executeQuery"
    assert f"FROM {TABLE}" in q and "session_id = $1" in q
    assert f"LIMIT {WINDOW_MESSAGES}" in q
    assert f"interval '{RETENTION_DAYS} days'" in q
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b", q, re.IGNORECASE)
    assert nodes["Load history"]["parameters"]["options"]["queryReplacement"] == \
        "={{ $json.session_id }}"
    # a database problem must not stop the answer
    assert nodes["Load history"]["onError"] == "continueRegularOutput"
    assert nodes["Load history"]["alwaysOutputData"] is True
    edges = set(h.edges(wf))
    assert ("Normalize input", "Load history", "main", 0) in edges
    assert ("Load history", "Router input", "main", 0) in edges
    assert ("Router input", "Router", "main", 0) in edges
    text = nodes["Router"]["parameters"]["text"]
    assert "$json.history" in text and "$json.message" in text


def test_session_is_per_user_and_channel_and_thread_wins(wf):
    norm = h.by_name(wf)["Normalize input"]["parameters"]["assignments"]["assignments"]
    value = next(a for a in norm if a["name"] == "session_id")["value"]
    assert value.index("author_id") < value.index("thread_id") < value.index("channel_id")
    assert "':'" in value
    # nobody identified: no shared "anonymous" memory between unrelated callers
    assert "$execution.id" in value
    classified = h.by_name(wf)["Classified"]["parameters"]["assignments"]["assignments"]
    assert any(a["name"] == "session_id" for a in classified)


def test_postgres_nodes_use_only_the_concho_credential(wf):
    for n in wf["nodes"]:
        if "postgres" in n["type"].lower():
            assert n["credentials"] == {"postgres": {"id": "concho-postgres",
                                                     "name": "Concho Postgres"}}


def test_sql_files_define_the_table_the_workflow_uses():
    ddl = (SQL_DIR / "memory.sql").read_text(encoding="utf-8")
    assert f"CREATE TABLE IF NOT EXISTS {TABLE}" in ddl
    for col in ("id ", "session_id", "message ", "created_at"):
        assert col in ddl
    assert "JSONB" in ddl and "DEFAULT now()" in ddl
    assert "CREATE INDEX IF NOT EXISTS" in ddl
    assert not re.search(r"\bDROP\b", ddl, re.IGNORECASE)  # runs on every start
    purge = (SQL_DIR / "memory_purge.sql").read_text(encoding="utf-8")
    assert f"DELETE FROM {TABLE}" in purge and ":retention_days" in purge
    assert "created_at <" in purge


# --- against a real Postgres (CONCHO_TEST_DATABASE_URL), skipped otherwise ----------------

DSN = os.environ.get("CONCHO_TEST_DATABASE_URL")


def _psql(*args, input=None):
    proc = subprocess.run(["psql", DSN, "-v", "ON_ERROR_STOP=1", "-q", "-At", *args],
                          input=input, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.mark.skipif(not (DSN and shutil.which("psql")),
                    reason="set CONCHO_TEST_DATABASE_URL (and have psql) to run against Postgres")
def test_history_query_window_retention_and_isolation(wf):
    query = h.by_name(wf)["Load history"]["parameters"]["query"]
    _psql("-f", str(SQL_DIR / "memory.sql"))
    _psql("-f", str(SQL_DIR / "memory.sql"))  # idempotent
    _psql("-c", f"DELETE FROM {TABLE} WHERE session_id LIKE 'pytest:%'")
    rows = [("pytest:a", "human", "ancient question", 40)]
    rows += [("pytest:a", "human" if i % 2 == 0 else "ai", f"m{i}", 0) for i in range(8)]
    rows += [("pytest:b", "human", "someone else", 0)]
    for sid, kind, text, age in rows:
        _psql("-c", f"INSERT INTO {TABLE}(session_id, message, created_at) VALUES "
                    f"('{sid}', '{{\"type\": \"{kind}\", \"data\": {{\"content\": \"{text}\"}}}}', "
                    f"now() - interval '{age} days')")
    prepared = "PREPARE hist(text) AS " + query + "; EXECUTE hist('pytest:a');"
    out = _psql("-c", prepared)
    lines = out.splitlines()
    assert lines == ["User: m2", "Concho: m3", "User: m4", "Concho: m5", "User: m6",
                     "Concho: m7"]
    assert "ancient" not in out and "someone else" not in out
    assert _psql("-c", f"PREPARE h2(text) AS {query}; EXECUTE h2('pytest:none');") == ""
    _psql("-v", f"retention_days={RETENTION_DAYS}", "-f", str(SQL_DIR / "memory_purge.sql"))
    assert _psql("-c", f"SELECT count(*) FROM {TABLE} WHERE session_id = 'pytest:a' "
                       f"AND message->'data'->>'content' = 'ancient question'") == "0"
    assert _psql("-c", f"SELECT count(*) FROM {TABLE} WHERE session_id = 'pytest:a'") == "8"
    _psql("-c", f"DELETE FROM {TABLE} WHERE session_id LIKE 'pytest:%'")
