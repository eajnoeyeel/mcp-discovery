-- ============================================================
-- Migration 022: Metric Semantic Redesign
-- ============================================================
-- Combines:
--   - Rename query_logs.selected_tool_id → recommended_tool_id
--     (semantic correctness: the column records the rank-1
--     recommendation from search, not a user-confirmed selection)
--   - Add execution_logs.query_log_id FK to query_logs(id)
--     (enables recommendation → execution funnel analysis)
--   - Recreate all 021 analytics views with new column name
--   - Recreate provider_search_simulations (004) and
--     provider_tool_dashboard with new column name
--   - Add tool_exposure_facts view (unnest alternatives JSONB)
--   - Add tool_conversion_funnel view (query_logs ⇔ execution_logs)
--
-- Four-fact separation:
--   recommendation: query_logs.recommended_tool_id (rank-1)
--   exposure:      tool_exposure_facts (any rank in alternatives)
--   execution:     execution_logs rows
--   conversion:    tool_conversion_funnel (exec/rec via query_log_id)
--
-- Principle 1 (live ranking untouched) is preserved:
--   - compute_operability_float() is NOT modified
--   - FlatStrategy / operability merge / confidence branching
--     are NOT modified
--   - `conversion_rate` is a dashboard metric only in this scope;
--     ranking integration is deferred to Phase B (separate ADR).
--
-- Depends on: 021_analytics_views_fix.sql
-- ============================================================

BEGIN;

SET lock_timeout = '5s';

-- ============================================================
-- 1. Rename query_logs.selected_tool_id → recommended_tool_id
-- ============================================================

ALTER TABLE query_logs RENAME COLUMN selected_tool_id TO recommended_tool_id;

COMMENT ON COLUMN query_logs.recommended_tool_id IS
    'Top-ranked tool_id from the search pipeline (rank-1 recommendation). '
    'Not a confirmed user/LLM selection — for that, join execution_logs '
    'via query_log_id FK.';

-- ============================================================
-- 2. Drop dependent views that reference selected_tool_id
-- ============================================================
-- Views from migrations 004 and 021 reference the renamed column.
-- Postgres does NOT automatically rewrite view bodies on column
-- rename, so we drop and recreate.

DROP VIEW IF EXISTS provider_tool_dashboard CASCADE;
DROP VIEW IF EXISTS provider_search_simulations CASCADE;
DROP VIEW IF EXISTS tool_client_selection_stats CASCADE;
DROP VIEW IF EXISTS tool_client_stats CASCADE;
DROP VIEW IF EXISTS tool_daily_stats CASCADE;
DROP VIEW IF EXISTS tool_exposure_stats_7d CASCADE;
DROP VIEW IF EXISTS tool_exposure_stats CASCADE;
DROP VIEW IF EXISTS tool_selection_stats CASCADE;

-- ============================================================
-- 3. Swap the partial index to the new column name
-- ============================================================

DROP INDEX IF EXISTS idx_query_logs_selected_tool_id;
CREATE INDEX idx_query_logs_recommended_tool_id
    ON query_logs (recommended_tool_id)
    WHERE recommended_tool_id IS NOT NULL;

-- ============================================================
-- 4. Add query_log_id FK to execution_logs
-- ============================================================
-- ON DELETE SET NULL: preserves historical execution rows even
-- if the originating query_log row is purged. NULL means "direct
-- execution" (no prior find_best_tool search in this context).

ALTER TABLE execution_logs
    ADD COLUMN query_log_id BIGINT REFERENCES query_logs(id) ON DELETE SET NULL;

COMMENT ON COLUMN execution_logs.query_log_id IS
    'FK to query_logs.id — correlates an execution back to the search '
    'that recommended it. NULL means direct execution without a prior '
    'find_best_tool call.';

CREATE INDEX idx_execution_logs_query_log_id
    ON execution_logs (query_log_id)
    WHERE query_log_id IS NOT NULL;

-- ============================================================
-- 5. Recreate 6 analytics views from 021 with recommended_tool_id
-- ============================================================

-- 5a. tool_selection_stats (kept name for dashboard compat, but
--     semantically now "tool_recommendation_stats")
CREATE OR REPLACE VIEW tool_selection_stats AS
SELECT
    ql.recommended_tool_id                             AS tool_id,
    COUNT(*)                                           AS times_selected,
    COUNT(DISTINCT ql.query)                           AS unique_queries_selected,
    ROUND(AVG(ql.confidence)::numeric, 4)              AS avg_confidence,
    MAX(ql.created_at)                                 AS last_selected_at
FROM query_logs ql
WHERE ql.recommended_tool_id IS NOT NULL
GROUP BY ql.recommended_tool_id;

-- 5b. tool_exposure_stats
CREATE OR REPLACE VIEW tool_exposure_stats AS
WITH expanded AS (
    SELECT
        ql.id AS query_log_id,
        ql.recommended_tool_id,
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
        WHERE exposed_tool_id = recommended_tool_id
    )                                                  AS times_selected_from_exposure,
    ROUND(
        COUNT(*) FILTER (WHERE exposed_tool_id = recommended_tool_id)::numeric
        / NULLIF(COUNT(*), 0), 4
    )                                                  AS selection_rate,
    ROUND(AVG(exposed_score)::numeric, 4)              AS avg_score_when_exposed,
    MAX(created_at)                                    AS last_exposed_at
FROM expanded
GROUP BY exposed_tool_id;

-- 5c. tool_exposure_stats_7d
CREATE OR REPLACE VIEW tool_exposure_stats_7d AS
WITH expanded AS (
    SELECT
        ql.id AS query_log_id,
        ql.recommended_tool_id,
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
        COUNT(*) FILTER (WHERE exposed_tool_id = recommended_tool_id)::numeric
        / NULLIF(COUNT(*), 0), 4
    )                                                  AS selection_rate_7d,
    ROUND(AVG(exposed_score)::numeric, 4)              AS avg_score_7d
FROM expanded
GROUP BY exposed_tool_id;

-- 5d. tool_daily_stats (no rename needed — execution_logs only)
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

-- 5e. tool_client_stats (no rename needed — execution_logs only)
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

-- 5f. tool_client_selection_stats
CREATE OR REPLACE VIEW tool_client_selection_stats AS
SELECT
    recommended_tool_id                               AS tool_id,
    client_id,
    COUNT(*)                                          AS times_selected,
    ROUND(AVG(confidence)::numeric, 4)                AS avg_confidence
FROM query_logs
WHERE recommended_tool_id IS NOT NULL
  AND client_id IS NOT NULL
GROUP BY recommended_tool_id, client_id;

-- ============================================================
-- 6. Recreate provider_search_simulations (migration 004)
-- ============================================================

CREATE OR REPLACE VIEW provider_search_simulations AS
SELECT
    q.recommended_tool_id,
    t.server_id,
    count(*)                AS query_count,
    avg(q.confidence)       AS avg_confidence,
    avg(q.latency_ms)       AS avg_latency_ms,
    count(*) FILTER (WHERE q.confidence >= 0.8) AS high_confidence_count
FROM query_logs q
JOIN mcp_tools t ON q.recommended_tool_id = t.tool_id
WHERE q.recommended_tool_id IS NOT NULL
GROUP BY q.recommended_tool_id, t.server_id;

-- ============================================================
-- 7. Recreate provider_tool_dashboard (dropped above)
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
-- 8. NEW: tool_exposure_facts view (unnest alternatives)
-- ============================================================
-- Per-row exposure facts — one row per (query_log, tool) pair where
-- the tool appeared in the top-K alternatives of that query. Callers
-- can aggregate this however they like (by tool, by client, by day).

CREATE OR REPLACE VIEW tool_exposure_facts AS
SELECT
    ql.id                                               AS query_log_id,
    ql.query                                            AS query_text,
    ql.client_id,
    ql.recommended_tool_id,
    ql.event_type,
    ql.created_at                                       AS exposed_at,
    (alt->>'tool_id')::text                             AS exposed_tool_id,
    (alt->>'score')::float                              AS exposed_score,
    -- Ordinal position in the alternatives array (0-indexed) — useful
    -- for rank analysis. Requires WITH ORDINALITY.
    alt_ord.ordinality - 1                              AS exposed_rank,
    (alt->>'tool_id')::text = ql.recommended_tool_id    AS is_top_ranked
FROM query_logs ql
CROSS JOIN LATERAL jsonb_array_elements(ql.alternatives) WITH ORDINALITY AS alt_ord(alt, ordinality)
WHERE ql.alternatives IS NOT NULL
  AND jsonb_typeof(ql.alternatives) = 'array';

COMMENT ON VIEW tool_exposure_facts IS
    'Per-query, per-tool exposure facts. One row per tool that appeared '
    'in the alternatives array of a query_log. Includes rank ordinal '
    'and is_top_ranked flag. Use for exposure/recommendation/rank analysis.';

-- ============================================================
-- 9. NEW: tool_conversion_funnel view (query ⇔ execution join)
-- ============================================================
-- Joins query_logs.id ⇔ execution_logs.query_log_id to expose the
-- "LLM saw this recommendation and chose to execute it" funnel.
-- LEFT JOIN so queries without executions still appear (conversion
-- denominator). Executions with NULL query_log_id are direct calls
-- and appear separately via execution_logs_direct below.

CREATE OR REPLACE VIEW tool_conversion_funnel AS
SELECT
    ql.id                                           AS query_log_id,
    ql.query,
    ql.client_id,
    ql.recommended_tool_id,
    ql.confidence                                   AS recommendation_confidence,
    ql.created_at                                   AS recommended_at,
    el.id                                           AS execution_log_id,
    el.tool_id                                      AS executed_tool_id,
    el.server_id                                    AS executed_server_id,
    el.success                                      AS execution_success,
    el.latency_ms                                   AS execution_latency_ms,
    el.created_at                                   AS executed_at,
    -- Classification:
    --   'converted'          : execution happened AND executed_tool_id == recommended_tool_id
    --   'diverged'           : execution happened but LLM picked a different tool
    --   'no_execution'       : recommendation given, no execution recorded yet
    CASE
        WHEN el.id IS NULL THEN 'no_execution'
        WHEN el.tool_id = ql.recommended_tool_id THEN 'converted'
        ELSE 'diverged'
    END                                             AS funnel_outcome
FROM query_logs ql
LEFT JOIN execution_logs el ON el.query_log_id = ql.id
WHERE ql.recommended_tool_id IS NOT NULL;

COMMENT ON VIEW tool_conversion_funnel IS
    'Recommendation → execution funnel. One row per query_log, with '
    'a LEFT JOIN to execution_logs via query_log_id FK. funnel_outcome '
    'classifies as converted | diverged | no_execution. Executions '
    'with NULL query_log_id (direct calls without prior search) are '
    'excluded — query those via execution_logs directly.';

-- ============================================================
-- 10. Re-grant SELECT permissions
-- ============================================================

GRANT SELECT ON tool_selection_stats          TO anon, authenticated;
GRANT SELECT ON tool_exposure_stats           TO anon, authenticated;
GRANT SELECT ON tool_exposure_stats_7d        TO anon, authenticated;
GRANT SELECT ON tool_daily_stats              TO anon, authenticated;
GRANT SELECT ON tool_client_stats             TO anon, authenticated;
GRANT SELECT ON tool_client_selection_stats   TO anon, authenticated;
GRANT SELECT ON provider_tool_dashboard       TO anon, authenticated;
GRANT SELECT ON provider_search_simulations   TO anon, authenticated;
GRANT SELECT ON tool_exposure_facts           TO anon, authenticated;
GRANT SELECT ON tool_conversion_funnel        TO anon, authenticated;

COMMIT;

-- ============================================================
-- ROLLBACK DDL (for manual use only — not executed by migration runner)
-- ============================================================
-- BEGIN;
-- SET lock_timeout = '5s';
--
-- DROP VIEW IF EXISTS tool_conversion_funnel CASCADE;
-- DROP VIEW IF EXISTS tool_exposure_facts CASCADE;
-- DROP VIEW IF EXISTS provider_tool_dashboard CASCADE;
-- DROP VIEW IF EXISTS provider_search_simulations CASCADE;
-- DROP VIEW IF EXISTS tool_client_selection_stats CASCADE;
-- DROP VIEW IF EXISTS tool_client_stats CASCADE;
-- DROP VIEW IF EXISTS tool_daily_stats CASCADE;
-- DROP VIEW IF EXISTS tool_exposure_stats_7d CASCADE;
-- DROP VIEW IF EXISTS tool_exposure_stats CASCADE;
-- DROP VIEW IF EXISTS tool_selection_stats CASCADE;
--
-- DROP INDEX IF EXISTS idx_execution_logs_query_log_id;
-- ALTER TABLE execution_logs DROP COLUMN IF EXISTS query_log_id;
--
-- DROP INDEX IF EXISTS idx_query_logs_recommended_tool_id;
-- ALTER TABLE query_logs RENAME COLUMN recommended_tool_id TO selected_tool_id;
-- CREATE INDEX idx_query_logs_selected_tool_id
--     ON query_logs (selected_tool_id)
--     WHERE selected_tool_id IS NOT NULL;
--
-- -- Then re-run migration 021 to restore the 021-era views.
--
-- COMMIT;
