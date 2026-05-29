-- ============================================================
-- Migration 009: Provider Dashboard Schema
-- ============================================================
-- Adds provider ownership model, analytics materialized views,
-- per-client tracking, and RLS policies for the Provider
-- Analytics Dashboard alpha.
--
-- Depends on: 001_initial.sql, 005_provider_ownership_and_read_api.sql,
--             007_entity_lifecycle_and_freshness.sql, 008_operational_stats.sql
-- ============================================================

-- ============================================================
-- Section A: Ownership Model
-- ============================================================

-- 1. Providers table
-- ============================================================

CREATE TABLE IF NOT EXISTS providers (
    id            UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id       UUID         NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name  TEXT,
    org_name      TEXT,
    contact_email TEXT,
    plan          TEXT         DEFAULT 'free'
                               CHECK (plan IN ('free', 'pro', 'enterprise')),
    created_at    TIMESTAMPTZ  DEFAULT now(),
    updated_at    TIMESTAMPTZ  DEFAULT now(),

    UNIQUE (user_id)  -- 1 provider per user (alpha)
);

-- Reuse existing update_updated_at() trigger function from migration 001
CREATE TRIGGER set_providers_updated_at
    BEFORE UPDATE ON providers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- 2. Provider → Server ownership columns
-- ============================================================

ALTER TABLE mcp_servers
    ADD COLUMN IF NOT EXISTS provider_id UUID REFERENCES providers(id),
    ADD COLUMN IF NOT EXISTS is_published BOOLEAN DEFAULT true,
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_mcp_servers_provider_id
    ON mcp_servers (provider_id);

-- 2b. Backfill provider_id from existing owner_user_id (one-time)
-- ============================================================
-- Creates a providers row for each distinct owner_user_id and links servers.
-- Safe to re-run (ON CONFLICT DO NOTHING + WHERE provider_id IS NULL).

INSERT INTO providers (user_id)
SELECT DISTINCT owner_user_id
FROM mcp_servers
WHERE owner_user_id IS NOT NULL
ON CONFLICT (user_id) DO NOTHING;

-- Batched backfill to avoid holding a table-wide lock on large tables.
DO $$
DECLARE
    rows_updated INT;
BEGIN
    LOOP
        UPDATE mcp_servers
        SET provider_id = (SELECT id FROM providers WHERE user_id = mcp_servers.owner_user_id)
        WHERE ctid = ANY (
            SELECT ctid FROM mcp_servers
            WHERE owner_user_id IS NOT NULL AND provider_id IS NULL
            LIMIT 1000
        );
        GET DIAGNOSTICS rows_updated = ROW_COUNT;
        EXIT WHEN rows_updated = 0;
        PERFORM pg_sleep(0.1);  -- brief pause between batches
    END LOOP;
END $$;

-- ============================================================
-- Section B: Analytics Materialized Views
-- ============================================================

-- 3. Tool selection stats (from query_logs)
-- ============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS tool_selection_stats AS
SELECT
    ql.selected_tool_id                                AS tool_id,
    COUNT(*)                                           AS times_selected,
    COUNT(DISTINCT ql.query)                           AS unique_queries_selected,
    ROUND(AVG(ql.confidence)::numeric, 4)              AS avg_confidence,
    MAX(ql.created_at)                                 AS last_selected_at
FROM query_logs ql
WHERE ql.selected_tool_id IS NOT NULL
GROUP BY ql.selected_tool_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_selection_stats_tool_id
    ON tool_selection_stats (tool_id);

-- 4. Tool exposure stats (appeared in alternatives)
-- ============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS tool_exposure_stats AS
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

CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_exposure_stats_tool_id
    ON tool_exposure_stats (tool_id);

-- 5. Tool exposure stats — 7-day window for trends
-- ============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS tool_exposure_stats_7d AS
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

CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_exposure_stats_7d_tool_id
    ON tool_exposure_stats_7d (tool_id);

-- ============================================================
-- Section C: Per-Client Analytics
-- ============================================================

-- 6. Client ID columns on log tables
-- ============================================================

ALTER TABLE execution_logs
    ADD COLUMN IF NOT EXISTS client_id TEXT;  -- vendor: 'claude', 'gpt', 'gemini', etc.

ALTER TABLE query_logs
    ADD COLUMN IF NOT EXISTS client_id TEXT;

CREATE INDEX IF NOT EXISTS idx_execution_logs_client_id
    ON execution_logs (client_id) WHERE client_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_query_logs_client_id
    ON query_logs (client_id) WHERE client_id IS NOT NULL;

-- 7. Daily bucket MV (time-series charts, 30d window)
-- ============================================================
-- Uses COALESCE(client_id, '__unknown__') to ensure UNIQUE INDEX has no NULLs,
-- which is required for REFRESH MATERIALIZED VIEW CONCURRENTLY.

CREATE MATERIALIZED VIEW IF NOT EXISTS tool_daily_stats AS
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

CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_daily_stats_pk
    ON tool_daily_stats (tool_id, day, client_id);

-- 8. Per-client aggregation MVs
-- ============================================================
-- These filter WHERE client_id IS NOT NULL, so UNIQUE INDEX is safe.

CREATE MATERIALIZED VIEW IF NOT EXISTS tool_client_stats AS
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

CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_client_stats_pk
    ON tool_client_stats (tool_id, client_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS tool_client_selection_stats AS
SELECT
    selected_tool_id                                  AS tool_id,
    client_id,
    COUNT(*)                                          AS times_selected,
    ROUND(AVG(confidence)::numeric, 4)                AS avg_confidence
FROM query_logs
WHERE selected_tool_id IS NOT NULL
  AND client_id IS NOT NULL
GROUP BY selected_tool_id, client_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_client_sel_stats_pk
    ON tool_client_selection_stats (tool_id, client_id);

-- ============================================================
-- Section D: Combined View + Refresh
-- ============================================================

-- 9. Combined provider dashboard view
-- ============================================================
-- Denormalization layer joining tools + servers + all MVs.
-- Provider scoping is done at the SERVICE layer (WHERE provider_id = $1),
-- NOT via this VIEW (which exposes all tools for flexibility).

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
    -- Operational stats (from migration 008)
    COALESCE(os.call_count, 0)              AS call_count,
    os.success_rate,
    os.avg_latency_ms,
    os.p95_latency_ms,
    os.timeout_rate,
    COALESCE(os7.call_count_7d, 0)          AS call_count_7d,
    os7.success_rate_7d,
    os7.avg_latency_ms_7d,
    -- Selection/exposure stats (new)
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

-- 10. Refresh function update (replaces migration 008 version)
-- ============================================================
-- Per-MV error handling: a failure in one MV does not block the rest.

CREATE OR REPLACE FUNCTION refresh_operational_stats()
RETURNS void AS $$
DECLARE
    mv_name TEXT;
    mv_names TEXT[] := ARRAY[
        'tool_operational_stats',
        'tool_operational_stats_7d',
        'tool_selection_stats',
        'tool_exposure_stats',
        'tool_exposure_stats_7d',
        'tool_daily_stats',
        'tool_client_stats',
        'tool_client_selection_stats'
    ];
BEGIN
    FOREACH mv_name IN ARRAY mv_names LOOP
        BEGIN
            EXECUTE format('REFRESH MATERIALIZED VIEW CONCURRENTLY %I', mv_name);
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'Failed to refresh %: %', mv_name, SQLERRM;
        END;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Section E: RLS Policies
-- ============================================================

-- Providers table: user can only see/edit own provider record
ALTER TABLE providers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "providers_own_read"
    ON providers FOR SELECT
    TO authenticated
    USING (user_id = auth.uid());

CREATE POLICY "providers_own_write"
    ON providers FOR ALL
    TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

CREATE POLICY "service_role_all_providers"
    ON providers FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- NOTE: No new SELECT policy on mcp_servers.
-- Existing `authenticated_read_servers USING(true)` from migration 001 would
-- OR with any new SELECT policy, making provider-scoping ineffective.
-- Provider read scoping is enforced at the VIEW/service layer instead.

-- Provider can update own servers (visibility toggle, metadata) — UPDATE-only
CREATE POLICY "provider_update_own_servers"
    ON mcp_servers FOR UPDATE
    TO authenticated
    USING (
        provider_id IN (
            SELECT id FROM providers WHERE user_id = auth.uid()
        )
    )
    WITH CHECK (
        provider_id IN (
            SELECT id FROM providers WHERE user_id = auth.uid()
        )
    );
