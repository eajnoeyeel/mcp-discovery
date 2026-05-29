-- ============================================================
-- Migration 014: OAuth Session & Gateway Tables
-- ============================================================
-- Consolidates content from 009_transport_oauth_runtime.sql and
-- 010_oauth_secret_refs.sql, which were never applied to the live
-- DB due to a migration numbering collision in the provider-dashboard
-- worktree (two 008_* and two 009_* files existed simultaneously).
--
-- The ALTER TABLE columns from 009 (transport_type, requires_gateway)
-- were applied manually to mcp_servers; only the CREATE TABLE
-- statements for mcp_oauth_sessions and mcp_gateway_routes were
-- missing.
--
-- Files 009 and 010 remain in the repo for fresh-install paths.
-- Depends on: 001_initial.sql (mcp_servers, update_updated_at)
-- ============================================================

-- Pre-flight: ensure trigger function exists (defensive re-create)
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 1. mcp_oauth_sessions (from 009 + 010)
-- ============================================================

CREATE TABLE IF NOT EXISTS mcp_oauth_sessions (
    server_id         TEXT PRIMARY KEY
                      REFERENCES mcp_servers(server_id)
                      ON DELETE CASCADE,
    token_endpoint    TEXT NOT NULL,
    client_id         TEXT NOT NULL,
    client_secret     TEXT,
    access_token      TEXT,
    refresh_token     TEXT NOT NULL,
    scope             TEXT,
    token_type        TEXT NOT NULL DEFAULT 'Bearer',
    expires_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now(),
    -- From 010_oauth_secret_refs:
    client_secret_ref  TEXT,
    refresh_token_ref  TEXT,
    secret_backend     TEXT NOT NULL DEFAULT 'aws_secrets_manager'
                       CHECK (secret_backend IN ('aws_secrets_manager'))
);

DROP TRIGGER IF EXISTS set_mcp_oauth_sessions_updated_at ON mcp_oauth_sessions;
CREATE TRIGGER set_mcp_oauth_sessions_updated_at
    BEFORE UPDATE ON mcp_oauth_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

ALTER TABLE mcp_oauth_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_mcp_oauth_sessions" ON mcp_oauth_sessions;
CREATE POLICY "service_role_all_mcp_oauth_sessions"
    ON mcp_oauth_sessions FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================
-- 2. mcp_gateway_routes (from 009)
-- ============================================================

CREATE TABLE IF NOT EXISTS mcp_gateway_routes (
    server_id            TEXT PRIMARY KEY
                         REFERENCES mcp_servers(server_id)
                         ON DELETE CASCADE,
    gateway_url          TEXT NOT NULL,
    health_status        TEXT NOT NULL DEFAULT 'unknown'
                         CHECK (health_status IN ('unknown', 'healthy', 'degraded', 'unhealthy')),
    last_health_check_at TIMESTAMPTZ,
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_at           TIMESTAMPTZ DEFAULT now()
);

DROP TRIGGER IF EXISTS set_mcp_gateway_routes_updated_at ON mcp_gateway_routes;
CREATE TRIGGER set_mcp_gateway_routes_updated_at
    BEFORE UPDATE ON mcp_gateway_routes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

ALTER TABLE mcp_gateway_routes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_mcp_gateway_routes" ON mcp_gateway_routes;
CREATE POLICY "service_role_all_mcp_gateway_routes"
    ON mcp_gateway_routes FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================
-- 3. Comments
-- ============================================================

COMMENT ON TABLE mcp_oauth_sessions IS 'Provider upstream OAuth token state; service_role-only, never exposed through public catalog APIs.';
COMMENT ON TABLE mcp_gateway_routes IS 'Internal execution gateway routing metadata for pooled MCP transports.';
