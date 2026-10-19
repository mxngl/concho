-- Retention for concho_chat_history (roadmap P6.4): drop messages older than the retention.
-- Run with psql -v retention_days=30 -f memory_purge.sql (the compose service "memory-purge"
-- does this daily; CONCHO_MEMORY_RETENTION_DAYS, default 30).

DELETE FROM concho_chat_history
 WHERE created_at < now() - make_interval(days => :retention_days);
