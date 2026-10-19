-- Concho chat memory (roadmap P6.4): the last N messages per user and channel.
--
-- Postgres. docker-compose mounts this file into /docker-entrypoint-initdb.d, so it runs once
-- when the database volume is created; it is idempotent, so it can also be applied by hand:
--   docker compose -f agent/docker-compose.yml exec -T postgres \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < agent/memory.sql
--
-- The workflow (agent/workflows/concho.json) uses it in two places:
--   "Load history"  reads the last CONCHO_MEMORY_MESSAGES (default 6) rows of one user_id +
--                   channel_id that are younger than CONCHO_MEMORY_DAYS (default 30), oldest
--                   first, as one text block that goes in front of the question. A Discord
--                   thread is a channel of its own, so every thread has its own memory.
--   "Save turn"     stores the user's message and Concho's reply after the answer was sent and
--                   deletes everything older than CONCHO_MEMORY_DAYS in the same statement
--                   (retention without a cron job). Failed turns are not stored.
--
-- Stored text: chat messages of the team's own Discord channel and the replies, for at most
-- 30 days. Nothing here is project data; the numbers in old replies are never reused, the
-- agents' prompts say so and fetch every number from the data API again.

CREATE TABLE IF NOT EXISTS concho_memory (
    id          BIGSERIAL PRIMARY KEY,                   -- order of messages (not the clock)
    user_id     TEXT        NOT NULL,                    -- Discord author id (or eval user)
    channel_id  TEXT        NOT NULL,                    -- channel or thread id
    role        TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    category    TEXT,                                    -- router category of the turn
    content     TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- the window query: newest rows of one user in one channel
CREATE INDEX IF NOT EXISTS concho_memory_window_idx
    ON concho_memory (user_id, channel_id, id DESC);
-- the retention delete
CREATE INDEX IF NOT EXISTS concho_memory_created_idx
    ON concho_memory (created_at);

-- Manual cleanup (also usable from pg_cron): SELECT concho_memory_cleanup(30);
CREATE OR REPLACE FUNCTION concho_memory_cleanup(retention_days integer DEFAULT 30)
RETURNS bigint LANGUAGE sql AS $$
    WITH gone AS (
        DELETE FROM concho_memory
        WHERE created_at < now() - make_interval(days => retention_days)
        RETURNING 1
    )
    SELECT count(*) FROM gone
$$;
