-- mlp/supabase/migrations/020_mv_to_view.sql
-- Replace materialized views with regular views for real-time stats.
-- Removes pg_cron dependency — stats are always fresh on read.
-- At current scale (< 10K rows) the aggregation cost is negligible.

-- ============================================================
-- 1. Remove pg_cron schedule
-- ============================================================

DO $$
BEGIN
    PERFORM cron.unschedule('refresh-ops-stats');
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'cron job refresh-ops-stats not found, skipping';
END $$;

-- ============================================================
-- 2. Drop materialized views and their indexes
-- ============================================================

DROP MATERIALIZED VIEW IF EXISTS tool_operational_stats_7d CASCADE;
DROP MATERIALIZED VIEW IF EXISTS tool_operational_stats CASCADE;

-- ============================================================
-- 3. Recreate as regular views (same SQL, always fresh)
-- ============================================================

CREATE OR REPLACE VIEW tool_operational_stats AS
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

CREATE OR REPLACE VIEW tool_operational_stats_7d AS
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

-- ============================================================
-- 4. Recreate tool_operability_view (dropped by CASCADE)
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

GRANT SELECT ON tool_operability_view TO anon, authenticated;
GRANT SELECT ON tool_operational_stats TO anon, authenticated;
GRANT SELECT ON tool_operational_stats_7d TO anon, authenticated;

-- ============================================================
-- 5. refresh_operational_stats() is now a no-op (kept for backward compat)
CREATE OR REPLACE FUNCTION refresh_operational_stats()
RETURNS void AS $$
BEGIN
    -- No-op: views are always fresh. Retained so callers don't break.
    NULL;
END;
$$ LANGUAGE plpgsql;
