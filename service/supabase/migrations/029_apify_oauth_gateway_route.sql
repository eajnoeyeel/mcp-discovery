-- ============================================================
-- Migration 029: Route Apify OAuth MCP Through Gateway
-- ============================================================
-- Apify MCP uses streamable HTTP sessions and rejects stateless tools/call
-- requests without a valid initialized session id. Route it through the
-- long-running gateway session pool.
-- ============================================================

UPDATE mcp_servers
SET
    requires_gateway = true,
    transport_type = 'streamable_http'
WHERE server_id = 'apify-oauth';

INSERT INTO mcp_gateway_routes (server_id, gateway_url)
VALUES ('apify-oauth', 'http://gateway:8000')
ON CONFLICT (server_id)
DO UPDATE SET gateway_url = excluded.gateway_url;
