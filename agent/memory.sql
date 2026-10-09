-- Concho chat memory (roadmap P6.4): the last messages per user and channel, kept in Postgres.
--
-- Used by the six "Postgres Chat Memory" nodes of agent/workflows/concho.json (table name
-- `concho_chat_history`, session key `concho:<channel or thread id>:<user id>`; the router uses
-- the same key plus `:router`). The node reads the newest messages of one session
-- (contextWindowLength 3 = 3 question/answer pairs = 6 messages) and appends to the table;
-- it knows nothing about age, so the 30-day retention is the purge below, run once a day by the
-- `memory-maintenance` service of agent/docker-compose.yml.
--
-- Idempotent: safe to run at every start. The column layout (id, session_id, message) is the one
-- n8n creates itself; `created_at` is ours and is filled by the default.

CREATE TABLE IF NOT EXISTS concho_chat_history (
    id         SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    message    JSONB        NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- a session's newest messages (what the node reads) and the retention purge
CREATE INDEX IF NOT EXISTS concho_chat_history_session_idx ON concho_chat_history (session_id, id DESC);
CREATE INDEX IF NOT EXISTS concho_chat_history_created_idx ON concho_chat_history (created_at);

-- Retention: delete messages older than `retention_days` (default 30); returns the row count.
CREATE OR REPLACE FUNCTION concho_purge_chat_history(retention_days integer DEFAULT 30)
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    deleted bigint;
BEGIN
    DELETE FROM concho_chat_history
     WHERE created_at < now() - make_interval(days => retention_days);
    GET DIAGNOSTICS deleted = ROW_COUNT;
    RETURN deleted;
END;
$$;
