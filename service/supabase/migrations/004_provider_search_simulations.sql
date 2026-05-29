-- ============================================================
-- MCP Discovery Platform — Provider Search Simulations View
-- ============================================================
-- Aggregates query_logs by selected tool, joined to server.
-- Consumed by the provider dashboard to show search performance.
-- Depends on: 001_initial.sql (query_logs, mcp_tools)
-- ============================================================

-- 1. Provider search simulations view
CREATE OR REPLACE VIEW provider_search_simulations AS
SELECT
    q.selected_tool_id,
    t.server_id,
    count(*)                AS query_count,
    avg(q.confidence)       AS avg_confidence,
    avg(q.latency_ms)       AS avg_latency_ms,
    count(*) FILTER (WHERE q.confidence >= 0.8) AS high_confidence_count
FROM query_logs q
JOIN mcp_tools t ON q.selected_tool_id = t.tool_id
WHERE q.selected_tool_id IS NOT NULL
GROUP BY q.selected_tool_id, t.server_id;

-- 2. Read access
GRANT SELECT ON provider_search_simulations TO anon, authenticated;
