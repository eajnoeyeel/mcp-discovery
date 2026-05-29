-- ============================================================
-- MCP Discovery Platform — Execution Auth Metadata
-- ============================================================
-- Stores provider MCP upstream authentication metadata separately
-- from public mcp_servers rows. This table is service_role-only.
-- ============================================================

CREATE TABLE IF NOT EXISTS mcp_server_auth (
    server_id             TEXT PRIMARY KEY
                          REFERENCES mcp_servers(server_id)
                          ON DELETE CASCADE,
    auth_type             TEXT NOT NULL DEFAULT 'none'
                          CHECK (auth_type IN ('none', 'bearer', 'api_key_header', 'custom_headers')),
    bearer_token          TEXT,
    api_key_header_name   TEXT,
    api_key               TEXT,
    headers               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ DEFAULT now(),
    updated_at            TIMESTAMPTZ DEFAULT now()
);

CREATE TRIGGER set_mcp_server_auth_updated_at
    BEFORE UPDATE ON mcp_server_auth
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

ALTER TABLE mcp_server_auth ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_mcp_server_auth"
    ON mcp_server_auth FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON TABLE mcp_server_auth IS 'Provider MCP upstream auth metadata; service_role-only, never exposed through public catalog reads.';
