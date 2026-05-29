-- mlp/supabase/migrations/008_operational_stats.sql
-- Operational stats infrastructure: event dedup, materialized views, pg_cron refresh.
-- Depends on: 001_initial.sql (execution_logs, query_logs tables)

-- ============================================================
-- 1. Event dedup columns (idempotency)
-- ============================================================

ALTER TABLE execution_logs
    ADD COLUMN IF NOT EXISTS event_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_execution_logs_event_id
    ON execution_logs (event_id) WHERE event_id IS NOT NULL;

ALTER TABLE query_logs
    ADD COLUMN IF NOT EXISTS event_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_query_logs_event_id
    ON query_logs (event_id) WHERE event_id IS NOT NULL;

-- Stage metrics for pipeline observability
ALTER TABLE query_logs
    ADD COLUMN IF NOT EXISTS stage_metrics JSONB;

-- ============================================================
-- 2. Materialized views — all-time + 7-day window
-- ============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS tool_operational_stats AS
SELECT
    tool_id,
    COUNT(*)                                                    AS call_count,
    COUNT(*) FILTER (WHERE success = true)                      AS success_count,
    ROUND(
        COUNT(*) FILTER (WHERE success = true)::numeric
        / NULLIF(COUNT(*), 0), 4
    )                                                           AS success_rate,
    ROUND(AVG(latency_ms)::numeric, 1)                          AS avg_latency_ms,
    ROUND(
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::numeric, 1
    )                                                           AS p95_latency_ms,
    ROUND(
        COUNT(*) FILTER (WHERE latency_ms > 10000)::numeric
        / NULLIF(COUNT(*), 0), 4
    )                                                           AS timeout_rate,
    MAX(created_at)                                             AS last_called_at,
    MIN(created_at)                                             AS first_called_at
FROM execution_logs
GROUP BY tool_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_ops_stats_tool_id
    ON tool_operational_stats (tool_id);

-- 7-day rolling window
CREATE MATERIALIZED VIEW IF NOT EXISTS tool_operational_stats_7d AS
SELECT
    tool_id,
    COUNT(*)                                                    AS call_count_7d,
    ROUND(
        COUNT(*) FILTER (WHERE success = true)::numeric
        / NULLIF(COUNT(*), 0), 4
    )                                                           AS success_rate_7d,
    ROUND(AVG(latency_ms)::numeric, 1)                          AS avg_latency_ms_7d,
    ROUND(
        COUNT(*) FILTER (WHERE latency_ms > 10000)::numeric
        / NULLIF(COUNT(*), 0), 4
    )                                                           AS timeout_rate_7d
FROM execution_logs
WHERE created_at > now() - interval '7 days'
GROUP BY tool_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_ops_stats_7d_tool_id
    ON tool_operational_stats_7d (tool_id);

-- ============================================================
-- 3. Combined operability view (OperabilityCache reads this)
-- ============================================================

CREATE OR REPLACE VIEW tool_operability_view AS
SELECT
    s.server_id,
    t.tool_id,
    COALESCE(os.call_count, 0)          AS call_count,
    COALESCE(os7.call_count_7d, 0)      AS call_count_7d,
    os.success_rate,
    os7.success_rate_7d,
    os.timeout_rate,
    os.avg_latency_ms,
    os.p95_latency_ms,
    os.last_called_at,
    os.first_called_at,
    t.created_at                        AS registered_at,
    t.source_updated_at,
    s.name                              AS server_name,
    COALESCE(t.index_status, 'pending') AS index_status
FROM mcp_tools t
JOIN mcp_servers s ON s.server_id = t.server_id
LEFT JOIN tool_operational_stats os ON os.tool_id = t.tool_id
LEFT JOIN tool_operational_stats_7d os7 ON os7.tool_id = t.tool_id;

-- ============================================================
-- 4. Refresh function + pg_cron schedule
-- ============================================================

CREATE OR REPLACE FUNCTION refresh_operational_stats()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY tool_operational_stats;
    REFRESH MATERIALIZED VIEW CONCURRENTLY tool_operational_stats_7d;
END;
$$ LANGUAGE plpgsql;

-- Enable pg_cron if not already enabled
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Schedule refresh every 5 minutes
SELECT cron.schedule(
    'refresh-ops-stats',
    '*/5 * * * *',
    'SELECT refresh_operational_stats()'
);
