-- ============================================================
-- Migration 021: Analytics Views Fix
-- ============================================================
-- Converts 6 stale analytics materialized views to regular views.
-- Migration 012 created these MVs; migration 020 no-opped the
-- refresh function, leaving them frozen. This migration makes
-- analytics always-fresh by converting to live views.
--
-- Also adds event_type column to query_logs for future
-- extensibility (recommendation vs execution linking).
--
-- Depends on: 012_provider_dashboard.sql, 020_mv_to_view.sql
-- ============================================================

BEGIN;

-- ============================================================
-- 1. Add event_type column to query_logs
-- ============================================================

ALTER TABLE query_logs
    ADD COLUMN IF NOT EXISTS event_type TEXT NOT NULL DEFAULT 'recommendation';

COMMENT ON COLUMN query_logs.event_type IS
    'Discriminator for log entry type: recommendation (default), execution, user_selection (future)';

-- ============================================================
-- 2. Drop stale materialized views
-- ============================================================
-- CASCADE will also drop provider_tool_dashboard (depends on
-- tool_selection_stats, tool_exposure_stats, tool_exposure_stats_7d)
-- and the UNIQUE INDEXes on each MV.

DROP MATERIALIZED VIEW IF EXISTS tool_client_selection_stats CASCADE;
DROP MATERIALIZED VIEW IF EXISTS tool_client_stats CASCADE;
DROP MATERIALIZED VIEW IF EXISTS tool_daily_stats CASCADE;
DROP MATERIALIZED VIEW IF EXISTS tool_exposure_stats_7d CASCADE;
DROP MATERIALIZED VIEW IF EXISTS tool_exposure_stats CASCADE;
DROP MATERIALIZED VIEW IF EXISTS tool_selection_stats CASCADE;

-- ============================================================
-- 3. Recreate as regular views (same logic, always fresh)
-- ============================================================
-- NOTE: Regular views do NOT support indexes. The UNIQUE INDEX
-- statements from migration 012 are intentionally omitted.

-- 3a. tool_selection_stats
CREATE OR REPLACE VIEW tool_selection_stats AS
SELECT
    ql.selected_tool_id                                AS tool_id,
    COUNT(*)                                           AS times_selected,
    COUNT(DISTINCT ql.query)                           AS unique_queries_selected,
    ROUND(AVG(ql.confidence)::numeric, 4)              AS avg_confidence,
    MAX(ql.created_at)                                 AS last_selected_at
FROM query_logs ql
WHERE ql.selected_tool_id IS NOT NULL
GROUP BY ql.selected_tool_id;

-- 3b. tool_exposure_stats
CREATE OR REPLACE VIEW tool_exposure_stats AS
WITH expanded AS (
    SELECT
        ql.id AS query_log_id,
        ql.selected_tool_id,
        ql.created_at,
        (alt->>'tool_id')::text AS exposed_tool_id,
        (alt->>'score')::float  AS exposed_score
    FROM query_logs ql,
         jsonb_array_elements(ql.alternatives) AS alt
    WHERE ql.alternatives IS NOT NULL
      AND jsonb_typeof(ql.alternatives) = 'array'
)
SELECT
    exposed_tool_id                                    AS tool_id,
    COUNT(*)                                           AS times_exposed,
    COUNT(*) FILTER (
        WHERE exposed_tool_id = selected_tool_id
    )                                                  AS times_selected_from_exposure,
    ROUND(
        COUNT(*) FILTER (WHERE exposed_tool_id = selected_tool_id)::numeric
        / NULLIF(COUNT(*), 0), 4
    )                                                  AS selection_rate,
    ROUND(AVG(exposed_score)::numeric, 4)              AS avg_score_when_exposed,
    MAX(created_at)                                    AS last_exposed_at
FROM expanded
GROUP BY exposed_tool_id;

-- 3c. tool_exposure_stats_7d
CREATE OR REPLACE VIEW tool_exposure_stats_7d AS
WITH expanded AS (
    SELECT
        ql.id AS query_log_id,
        ql.selected_tool_id,
        ql.created_at,
        (alt->>'tool_id')::text AS exposed_tool_id,
        (alt->>'score')::float  AS exposed_score
    FROM query_logs ql,
         jsonb_array_elements(ql.alternatives) AS alt
    WHERE ql.alternatives IS NOT NULL
      AND jsonb_typeof(ql.alternatives) = 'array'
      AND ql.created_at > now() - interval '7 days'
)
SELECT
    exposed_tool_id                                    AS tool_id,
    COUNT(*)                                           AS times_exposed_7d,
    ROUND(
        COUNT(*) FILTER (WHERE exposed_tool_id = selected_tool_id)::numeric
        / NULLIF(COUNT(*), 0), 4
    )                                                  AS selection_rate_7d,
    ROUND(AVG(exposed_score)::numeric, 4)              AS avg_score_7d
FROM expanded
GROUP BY exposed_tool_id;

-- 3d. tool_daily_stats
CREATE OR REPLACE VIEW tool_daily_stats AS
SELECT
    tool_id,
    date_trunc('day', created_at)::date              AS day,
    COUNT(*)                                          AS call_count,
    COUNT(*) FILTER (WHERE success = true)            AS success_count,
    ROUND(AVG(latency_ms)::numeric, 1)                AS avg_latency_ms,
    COALESCE(client_id, '__unknown__')                AS client_id
FROM execution_logs
WHERE created_at > now() - interval '30 days'
GROUP BY tool_id, date_trunc('day', created_at)::date, COALESCE(client_id, '__unknown__');

-- 3e. tool_client_stats
CREATE OR REPLACE VIEW tool_client_stats AS
SELECT
    tool_id,
    client_id,
    COUNT(*)                                          AS call_count,
    COUNT(*) FILTER (WHERE success = true)            AS success_count,
    ROUND(
        COUNT(*) FILTER (WHERE success = true)::numeric
        / NULLIF(COUNT(*), 0), 4
    )                                                 AS success_rate,
    ROUND(AVG(latency_ms)::numeric, 1)                AS avg_latency_ms,
    MAX(created_at)                                   AS last_called_at
FROM execution_logs
WHERE client_id IS NOT NULL
GROUP BY tool_id, client_id;

-- 3f. tool_client_selection_stats
CREATE OR REPLACE VIEW tool_client_selection_stats AS
SELECT
    selected_tool_id                                  AS tool_id,
    client_id,
    COUNT(*)                                          AS times_selected,
    ROUND(AVG(confidence)::numeric, 4)                AS avg_confidence
FROM query_logs
WHERE selected_tool_id IS NOT NULL
  AND client_id IS NOT NULL
GROUP BY selected_tool_id, client_id;

-- ============================================================
-- 4. Recreate provider_tool_dashboard (dropped by CASCADE)
-- ============================================================

CREATE OR REPLACE VIEW provider_tool_dashboard AS
SELECT
    t.tool_id,
    t.tool_name,
    t.description,
    t.input_schema,
    t.geo_score,
    t.index_status,
    t.created_at                            AS tool_created_at,
    s.server_id,
    s.name                                  AS server_name,
    s.provider_id,
    s.owner_user_id,
    s.is_published,
    s.entity_status,
    -- Operational stats (from migration 020 views)
    COALESCE(os.call_count, 0)              AS call_count,
    os.success_rate,
    os.avg_latency_ms,
    os.p95_latency_ms,
    os.timeout_rate,
    COALESCE(os7.call_count_7d, 0)          AS call_count_7d,
    os7.success_rate_7d,
    os7.avg_latency_ms_7d,
    -- Selection/exposure stats (now live views)
    COALESCE(ss.times_selected, 0)          AS times_selected,
    ss.avg_confidence,
    COALESCE(es.times_exposed, 0)           AS times_exposed,
    es.selection_rate,
    es.avg_score_when_exposed,
    COALESCE(es7.times_exposed_7d, 0)       AS times_exposed_7d,
    es7.selection_rate_7d
FROM mcp_tools t
JOIN mcp_servers s ON s.server_id = t.server_id
LEFT JOIN tool_operational_stats os ON os.tool_id = t.tool_id
LEFT JOIN tool_operational_stats_7d os7 ON os7.tool_id = t.tool_id
LEFT JOIN tool_selection_stats ss ON ss.tool_id = t.tool_id
LEFT JOIN tool_exposure_stats es ON es.tool_id = t.tool_id
LEFT JOIN tool_exposure_stats_7d es7 ON es7.tool_id = t.tool_id;

-- ============================================================
-- 5. Re-grant SELECT permissions (from migration 017)
-- ============================================================

GRANT SELECT ON tool_selection_stats          TO anon, authenticated;
GRANT SELECT ON tool_exposure_stats           TO anon, authenticated;
GRANT SELECT ON tool_exposure_stats_7d        TO anon, authenticated;
GRANT SELECT ON tool_daily_stats              TO anon, authenticated;
GRANT SELECT ON tool_client_stats             TO anon, authenticated;
GRANT SELECT ON tool_client_selection_stats   TO anon, authenticated;
GRANT SELECT ON provider_tool_dashboard       TO anon, authenticated;

-- ============================================================
-- 6. refresh_operational_stats() remains a no-op (from migration 020)
-- No changes needed — views are always fresh.
-- ============================================================

COMMIT;
