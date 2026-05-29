-- ============================================================
-- MCP Discovery Platform — Transport/OAuth Runtime Metadata
-- ============================================================
-- Adds execution transport metadata and service-role-only OAuth
-- session state for the long-running MCP gateway.
-- ============================================================

ALTER TABLE mcp_servers
ADD COLUMN IF NOT EXISTS transport_type TEXT NOT NULL DEFAULT 'stateless_http'
CHECK (transport_type IN ('stateless_http', 'streamable_http', 'sse', 'stdio'));

ALTER TABLE mcp_servers
ADD COLUMN IF NOT EXISTS requires_gateway BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS mcp_oauth_sessions (
    server_id             TEXT PRIMARY KEY
                          REFERENCES mcp_servers(server_id)
                          ON DELETE CASCADE,
    token_endpoint        TEXT NOT NULL,
    client_id             TEXT NOT NULL,
    client_secret         TEXT,
    access_token          TEXT,
    refresh_token         TEXT NOT NULL,
    scope                 TEXT,
    token_type            TEXT NOT NULL DEFAULT 'Bearer',
    expires_at            TIMESTAMPTZ,
    created_at            TIMESTAMPTZ DEFAULT now(),
    updated_at            TIMESTAMPTZ DEFAULT now()
);

CREATE TRIGGER set_mcp_oauth_sessions_updated_at
    BEFORE UPDATE ON mcp_oauth_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

ALTER TABLE mcp_oauth_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_mcp_oauth_sessions"
    ON mcp_oauth_sessions FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE TABLE IF NOT EXISTS mcp_gateway_routes (
    server_id             TEXT PRIMARY KEY
                          REFERENCES mcp_servers(server_id)
                          ON DELETE CASCADE,
    gateway_url           TEXT NOT NULL,
    health_status         TEXT NOT NULL DEFAULT 'unknown'
                          CHECK (health_status IN ('unknown', 'healthy', 'degraded', 'unhealthy')),
    last_health_check_at  TIMESTAMPTZ,
    created_at            TIMESTAMPTZ DEFAULT now(),
    updated_at            TIMESTAMPTZ DEFAULT now()
);

CREATE TRIGGER set_mcp_gateway_routes_updated_at
    BEFORE UPDATE ON mcp_gateway_routes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

ALTER TABLE mcp_gateway_routes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_mcp_gateway_routes"
    ON mcp_gateway_routes FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON TABLE mcp_oauth_sessions IS 'Provider upstream OAuth token state; service_role-only and never exposed through public catalog APIs.';
COMMENT ON TABLE mcp_gateway_routes IS 'Internal execution gateway routing metadata for pooled MCP transports.';
