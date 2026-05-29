-- Fix search_tools_fts: NULL status_filter means "search all tools" for degraded mode.

CREATE OR REPLACE FUNCTION search_tools_fts(
    search_query TEXT,
    result_limit INT DEFAULT 5,
    status_filter TEXT DEFAULT NULL
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
