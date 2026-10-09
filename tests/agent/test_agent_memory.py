"""P6.4: chat memory in the workflow (Postgres Chat Memory nodes) and its SQL file.

Offline: the JSON wiring and ``agent/memory.sql`` are checked statically. That n8n loads the
last 6 messages from this table and the follow-up works is for Max to see in n8n; the SQL itself
was also run once by hand against PostgreSQL 16 (see ``docs/agent.md``).
"""

from __future__ import annotations

import re

import agent_helpers as h
import pytest

MEMORY_SQL = h.AGENT / "memory.sql"
MESSAGES = 6  # roadmap P6.4: the last N=6 messages per user and channel
RETENTION_DAYS = 30
AGENTS = ["Router", "Cost Agent", "Carbon Agent", "Quantity Agent", "General Agent",
          "Fallback Agent"]


@pytest.fixture(scope="module")
def wf():
    return h.load("concho.json")


def memory_nodes(wf):
    return [n for n in wf["nodes"] if n["type"].endswith(".memoryPostgresChat")]


def test_every_agent_has_exactly_one_postgres_memory(wf):
    nodes = {n["name"]: n for n in memory_nodes(wf)}
    attached: dict[str, list[str]] = {}
    for src, dst, kind, _ in h.edges(wf):
        if kind == "ai_memory":
            assert src in nodes, f"{src} is not a Postgres chat memory node"
            attached.setdefault(dst, []).append(src)
    assert sorted(attached) == sorted(AGENTS)
    assert all(len(v) == 1 for v in attached.values())
    assert len(nodes) == len(AGENTS)


def test_window_is_six_messages_and_session_is_user_and_channel(wf):
    for node in memory_nodes(wf):
        p = node["parameters"]
        # n8n's window counts question/answer pairs: 3 pairs = 6 messages
        assert p["contextWindowLength"] * 2 == MESSAGES
        assert p["sessionIdType"] == "customKey"
        assert "$json.session_id" in p["sessionKey"]
        assert p["tableName"] == "concho_chat_history"


def test_router_has_its_own_session_subagents_share_one(wf):
    keys = {n["name"]: n["parameters"]["sessionKey"] for n in memory_nodes(wf)}
    assert keys["Router Memory"].endswith(":router' }}")
    sub = {k: v for k, v in keys.items() if k != "Router Memory"}
    assert set(sub.values()) == {"={{ $json.session_id }}"}


def test_session_id_is_built_from_channel_thread_and_user(wf):
    norm = h.by_name(wf)["Normalize input"]
    expr = next(a["value"] for a in norm["parameters"]["assignments"]["assignments"]
                if a["name"] == "session_id")
    assert "thread_id ?? $json.body.channel_id" in expr  # a thread is its own conversation
    assert "author_id ?? $json.body.user_id" in expr
    # no channel or no user: no shared bucket, a one-off session per execution
    assert "nomemory:' + $execution.id" in expr


def test_postgres_credential_matches_the_import_script(wf):
    import agent_credentials as ac

    env = {"OPENAI_API_KEY": "a", "DISCORD_BOT_TOKEN": "b", "CONCHO_WEBHOOK_TOKEN": "c",
           "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p"}
    created = {c["id"]: c for c in ac.build_credentials(env)}
    for node in memory_nodes(wf):
        cred = node["credentials"]["postgres"]
        assert created[cred["id"]]["name"] == cred["name"]
        assert created[cred["id"]]["type"] == "postgres"


def test_prompts_explain_the_history():
    common = (h.PROMPTS / "common.md").read_text(encoding="utf-8")
    assert "CHAT HISTORY" in common and "follow-up" in common
    assert "history" in (h.PROMPTS / "router.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ memory.sql


def sql() -> str:
    return MEMORY_SQL.read_text(encoding="utf-8")


def test_sql_creates_the_table_n8n_expects_and_is_idempotent():
    text = sql()
    m = re.search(r"CREATE TABLE IF NOT EXISTS concho_chat_history \((.*?)\);", text, re.S)
    assert m, "table must be created with IF NOT EXISTS"
    cols = m.group(1)
    # the three columns n8n's Postgres Chat Memory reads and writes ...
    assert re.search(r"\bid\s+SERIAL PRIMARY KEY", cols)
    assert re.search(r"\bsession_id\s+VARCHAR\(255\) NOT NULL", cols)
    assert re.search(r"\bmessage\s+JSONB\s+NOT NULL", cols)
    # ... and ours, filled by the default so n8n's two-column INSERT works
    assert re.search(r"\bcreated_at\s+TIMESTAMPTZ\s+NOT NULL DEFAULT now\(\)", cols)
    assert text.count("CREATE INDEX IF NOT EXISTS") == 2
    assert "CREATE OR REPLACE FUNCTION concho_purge_chat_history" in text


def test_retention_is_30_days_everywhere():
    assert f"retention_days integer DEFAULT {RETENTION_DAYS}" in sql()
    assert "created_at < now() - make_interval(days => retention_days)" in sql()
    env = (h.ENV_EXAMPLE).read_text(encoding="utf-8")
    assert f"CONCHO_MEMORY_RETENTION_DAYS={RETENTION_DAYS}" in env


def test_sql_has_no_destructive_statement_beyond_the_purge():
    text = re.sub(r"--.*", "", sql())
    assert not re.search(r"\bDROP\b|\bTRUNCATE\b", text, re.I)
    assert len(re.findall(r"\bDELETE\b", text, re.I)) == 1
