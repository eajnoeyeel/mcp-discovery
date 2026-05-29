-- ============================================================
-- Migration 025a: Schema Housekeeping (2026-04-19 audit)
-- ============================================================
-- Idempotent. Addresses audit findings M2, M3, L3, L4, M5.
--
-- M2: tool_enrichment_cache missing RLS, updated_at, trigger
-- M3: mcp_servers.index_status CHECK missing 'event_failed'
-- L3: search_tools_fts signature consolidation
-- L4: provider_search_simulations filter on event_type='recommendation'
-- M5: COMMENT ON COLUMN for mcp_tools timestamp columns
--
-- M1 (server_github_metadata updated_at trigger) was dropped —
-- the feature was retired; the table and mcp_servers.repository_url
-- column were removed in migration retire_github_metadata_feature.
--
-- Depends on: 001_initial.sql (update_updated_at),
--             024_enrichment_cache.sql,
--             015_servers_index_status_expand.sql,
--             006_fts_nullable_status.sql,
--             022_metric_semantic_redesign.sql (provider_search_simulations)
-- ============================================================

BEGIN;

-- ============================================================
-- M2: tool_enrichment_cache — RLS, updated_at, trigger
-- ============================================================
-- Migration 024 created the table without RLS or updated_at.

ALTER TABLE tool_enrichment_cache
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

DROP TRIGGER IF EXISTS set_tool_enrichment_cache_updated_at ON tool_enrichment_cache;

CREATE TRIGGER set_tool_enrichment_cache_updated_at
    BEFORE UPDATE ON tool_enrichment_cache
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

ALTER TABLE tool_enrichment_cache ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_tool_enrichment_cache" ON tool_enrichment_cache;

CREATE POLICY "service_role_all_tool_enrichment_cache"
    ON tool_enrichment_cache FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================
-- M3: mcp_servers.index_status CHECK — add 'event_failed'
-- ============================================================
-- Migration 023 added event_failed to mcp_tools but not to
-- mcp_servers. Close the asymmetry using NOT VALID + VALIDATE
-- for zero-downtime safety on live tables.

ALTER TABLE mcp_servers
    DROP CONSTRAINT IF EXISTS mcp_servers_index_status_check;

ALTER TABLE mcp_servers
    ADD CONSTRAINT mcp_servers_index_status_check
    CHECK (index_status IN (
        'pending',
        'indexing',
        'indexed',
        'failed',
        'event_failed',
        'deprecated',
        'unreachable',
        'quarantined'
    )) NOT VALID;

ALTER TABLE mcp_servers
    VALIDATE CONSTRAINT mcp_servers_index_status_check;

-- ============================================================
-- L3: search_tools_fts — consolidate signature
-- ============================================================
-- Migrations 001 and 006 produced two different signatures.
-- Migration 006 (status_filter DEFAULT NULL) is the correct
-- live version. Consolidate to a single authoritative definition.

CREATE OR REPLACE FUNCTION search_tools_fts(
    search_query   TEXT,
    result_limit   INT  DEFAULT 5,
    status_filter  TEXT DEFAULT NULL
)
RETURNS SETOF mcp_tools
LANGUAGE sql STABLE
AS $$
    SELECT * FROM mcp_tools
    WHERE (status_filter IS NULL OR index_status = status_filter)
      AND fts @@ plainto_tsquery('english', search_query)
    ORDER BY ts_rank(fts, plainto_tsquery('english', search_query)) DESC
    LIMIT result_limit;
$$;

COMMENT ON FUNCTION search_tools_fts(TEXT, INT, TEXT) IS
    'Lexical fallback FTS. status_filter=NULL means search all index statuses '
    '(degraded-mode behaviour). Pass status_filter=''indexed'' for normal path.';

-- ============================================================
-- L4: provider_search_simulations — restrict to recommendation events
-- ============================================================
-- query_logs.event_type was added in 021_analytics_views_fix.
-- The view was recreated in 022 without the event_type filter,
-- meaning non-recommendation log rows pollute the aggregation.

CREATE OR REPLACE VIEW provider_search_simulations AS
SELECT
    q.recommended_tool_id,
    t.server_id,
    count(*)                                          AS query_count,
    avg(q.confidence)                                 AS avg_confidence,
    avg(q.latency_ms)                                 AS avg_latency_ms,
    count(*) FILTER (WHERE q.confidence >= 0.8)       AS high_confidence_count
FROM query_logs q
JOIN mcp_tools t ON q.recommended_tool_id = t.tool_id
WHERE q.recommended_tool_id IS NOT NULL
  AND q.event_type = 'recommendation'
GROUP BY q.recommended_tool_id, t.server_id;

GRANT SELECT ON provider_search_simulations TO anon, authenticated;

-- ============================================================
-- M5: COMMENT ON COLUMN for mcp_tools timestamp columns
-- ============================================================

COMMENT ON COLUMN mcp_tools.created_at IS
    'Timestamp when this tool row was first inserted into the database.';

COMMENT ON COLUMN mcp_tools.updated_at IS
    'Timestamp of the most recent UPDATE to any column on this tool row; '
    'maintained automatically by the set_mcp_tools_updated_at trigger.';

COMMENT ON COLUMN mcp_tools.source_updated_at IS
    'Timestamp when the upstream registry last reported a change to this tool '
    '(e.g. description, schema). Used to gate re-embedding decisions.';

COMMENT ON COLUMN mcp_tools.indexed_at IS
    'Timestamp when this tool was last embedded and upserted into Qdrant. '
    'NULL means not yet indexed. Used by the index staleness detector.';

COMMENT ON COLUMN mcp_tools.last_health_check_at IS
    'Timestamp of the most recent health / reachability probe for this tool. '
    'NULL means never probed. Updated by the health-check Lambda.';

COMMENT ON COLUMN mcp_tools.metadata_last_fetched_at IS
    'Timestamp of the most recent upstream metadata fetch (description, '
    'parameter notes). Distinct from indexed_at — fetch can succeed without '
    're-indexing if the content hash is unchanged.';

COMMENT ON COLUMN mcp_tools.override_updated_at IS
    'Timestamp of the most recent explicit provider metadata override. '
    'NULL means the tool has never had a provider-authored override applied.';

COMMIT;
