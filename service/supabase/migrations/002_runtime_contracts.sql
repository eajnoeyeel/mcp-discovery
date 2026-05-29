-- ============================================================
-- MCP Discovery Platform — Runtime Contracts Migration
-- ============================================================
-- Dashboard views, FTS default fix, platform stats RPC.
-- Depends on: 001_initial.sql
-- ============================================================

-- 1. Fix search_tools_fts: default status_filter → 'indexed' (was 'pending')
CREATE OR REPLACE FUNCTION search_tools_fts(
    search_query TEXT,
    result_limit INT DEFAULT 5,
    status_filter TEXT DEFAULT 'indexed'
)
RETURNS SETOF mcp_tools
LANGUAGE sql STABLE
AS $$
    SELECT * FROM mcp_tools
    WHERE index_status = status_filter
      AND fts @@ plainto_tsquery('english', search_query)
    ORDER BY ts_rank(fts, plainto_tsquery('english', search_query)) DESC
    LIMIT result_limit;
$$;

-- 2. Provider dashboard snapshot (server-level GEO aggregates)
CREATE OR REPLACE VIEW provider_dashboard_snapshot AS
SELECT
    s.server_id,
    s.name AS server_name,
    s.description AS server_description,
    count(t.tool_id) AS tool_count,
    avg((t.geo_score->>'total')::float) AS avg_geo_score,
    min((t.geo_score->>'total')::float) AS min_geo_score,
    max((t.geo_score->>'total')::float) AS max_geo_score,
    count(*) FILTER (WHERE (t.geo_score->>'total')::float < 0.5) AS low_score_count,
    count(*) FILTER (WHERE t.index_status = 'indexed') AS indexed_count
FROM mcp_servers s
LEFT JOIN mcp_tools t ON t.server_id = s.server_id
GROUP BY s.server_id, s.name, s.description;

-- 3. Server tool counts (for /servers listing)
CREATE OR REPLACE VIEW server_tool_counts AS
SELECT server_id, count(*) AS tool_count
FROM mcp_tools
GROUP BY server_id;

-- 4. Platform stats RPC (landing page)
CREATE OR REPLACE FUNCTION get_platform_stats()
RETURNS json
LANGUAGE sql STABLE
AS $$
    SELECT json_build_object(
        'server_count', (SELECT count(*) FROM mcp_servers),
        'tool_count', (SELECT count(*) FROM mcp_tools),
        'indexed_count', (SELECT count(*) FROM mcp_tools WHERE index_status = 'indexed'),
        'avg_geo_score', (SELECT round(avg((geo_score->>'total')::float)::numeric, 3) FROM mcp_tools WHERE geo_score IS NOT NULL)
    );
$$;

-- 5. Read access for views
GRANT SELECT ON provider_dashboard_snapshot TO anon, authenticated;
GRANT SELECT ON server_tool_counts TO anon, authenticated;
