-- Concho conversation memory (roadmap P6.4). Idempotent: safe to run on every start.
--
-- Same layout as the table the n8n "Postgres Chat Memory" node creates itself
-- (id, session_id, message) plus created_at for the 30-day retention. The node only ever
-- inserts session_id and message, so created_at fills itself.
--
-- session_id = "<user_id>:<channel_id>" (Normalize input in agent/workflows/concho.json), so
-- memory is per user AND per channel (a Discord thread is its own channel).
-- message     = LangChain message JSON: {"type": "human" | "ai", "data": {"content": ...}}.
--
-- Window: the subagents read the last 6 messages (Postgres Chat Memory node, context window
-- 3 = 3 question/answer pairs); the router reads the last 6 through "Load history" below.
-- Retention: agent/sql/memory_purge.sql deletes rows older than 30 days; the compose service
-- "memory-purge" runs it daily. The router query also filters on age.

CREATE TABLE IF NOT EXISTS concho_chat_history (
    id         SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    message    JSONB        NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- If the n8n node created the table first (it has no created_at), add the column.
ALTER TABLE concho_chat_history
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS concho_chat_history_session_idx
    ON concho_chat_history (session_id, id);
CREATE INDEX IF NOT EXISTS concho_chat_history_created_idx
    ON concho_chat_history (created_at);
