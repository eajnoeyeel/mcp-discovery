-- ============================================================
-- Migration 025: Delegated OAuth Broker Schema
-- ============================================================
-- Adds provider registry, per-tool auth requirements, user-owned
-- provider connections, service-role token storage, and resumable
-- execution records for delegated OAuth flows.
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS oauth_provider_registry (
    provider_key            TEXT PRIMARY KEY,
    display_name            TEXT NOT NULL,
    authorize_url           TEXT NOT NULL,
    token_url               TEXT NOT NULL,
    client_id               TEXT NOT NULL,
    redirect_uri            TEXT NOT NULL,
    default_scopes          JSONB NOT NULL DEFAULT '[]'::jsonb,
    scope_aliases           JSONB NOT NULL DEFAULT '{}'::jsonb,
    supports_refresh_token  BOOLEAN NOT NULL DEFAULT FALSE,
    pkce_required           BOOLEAN NOT NULL DEFAULT TRUE,
    enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS set_oauth_provider_registry_updated_at ON oauth_provider_registry;
CREATE TRIGGER set_oauth_provider_registry_updated_at
    BEFORE UPDATE ON oauth_provider_registry
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TABLE IF NOT EXISTS mcp_auth_requirements (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id         TEXT NOT NULL
                      REFERENCES mcp_servers(server_id)
                      ON DELETE CASCADE,
    tool_id           TEXT
                      REFERENCES mcp_tools(tool_id)
                      ON DELETE CASCADE,
    provider_key      TEXT NOT NULL
                      REFERENCES oauth_provider_registry(provider_key)
                      ON DELETE CASCADE,
    auth_kind         TEXT NOT NULL DEFAULT 'oauth'
                      CHECK (auth_kind IN ('oauth')),
    required_scopes   JSONB NOT NULL DEFAULT '[]'::jsonb,
    scope_mode        TEXT NOT NULL DEFAULT 'default'
                      CHECK (scope_mode IN ('default', 'override')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS set_mcp_auth_requirements_updated_at ON mcp_auth_requirements;
CREATE TRIGGER set_mcp_auth_requirements_updated_at
    BEFORE UPDATE ON mcp_auth_requirements
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TABLE IF NOT EXISTS user_provider_connections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL
                        REFERENCES auth.users(id)
                        ON DELETE CASCADE,
    provider_key        TEXT NOT NULL
                        REFERENCES oauth_provider_registry(provider_key)
                        ON DELETE CASCADE,
    provider_account_id TEXT,
    granted_scopes      JSONB NOT NULL DEFAULT '[]'::jsonb,
    scope_fingerprint   TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'expired', 'revoked')),
    token_storage_mode  TEXT NOT NULL DEFAULT 'refreshable'
                        CHECK (token_storage_mode IN ('refreshable', 'session_only')),
    last_used_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider_key, scope_fingerprint)
);

DROP TRIGGER IF EXISTS set_user_provider_connections_updated_at ON user_provider_connections;
CREATE TRIGGER set_user_provider_connections_updated_at
    BEFORE UPDATE ON user_provider_connections
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TABLE IF NOT EXISTS user_provider_tokens (
    connection_id      UUID PRIMARY KEY
                       REFERENCES user_provider_connections(id)
                       ON DELETE CASCADE,
    access_token       TEXT,
    refresh_token      TEXT,
    expires_at         TIMESTAMPTZ,
    token_type         TEXT NOT NULL DEFAULT 'Bearer',
    access_token_ref   TEXT,
    refresh_token_ref  TEXT,
    secret_backend     TEXT NOT NULL DEFAULT 'aws_secrets_manager'
                       CHECK (secret_backend IN ('aws_secrets_manager')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS set_user_provider_tokens_updated_at ON user_provider_tokens;
CREATE TRIGGER set_user_provider_tokens_updated_at
    BEFORE UPDATE ON user_provider_tokens
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TABLE IF NOT EXISTS pending_executions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL
                     REFERENCES auth.users(id)
                     ON DELETE CASCADE,
    tool_id          TEXT NOT NULL
                     REFERENCES mcp_tools(tool_id)
                     ON DELETE CASCADE,
    params_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    provider_key     TEXT NOT NULL
                     REFERENCES oauth_provider_registry(provider_key)
                     ON DELETE CASCADE,
    required_scopes  JSONB NOT NULL DEFAULT '[]'::jsonb,
    retry_token      TEXT NOT NULL UNIQUE,
    connection_id    UUID
                     REFERENCES user_provider_connections(id)
                     ON DELETE SET NULL,
    result_json      JSONB,
    error_message    TEXT,
    status           TEXT NOT NULL DEFAULT 'waiting_for_connect'
                     CHECK (status IN ('waiting_for_connect', 'ready_to_resume', 'resuming',
                                       'resumed', 'failed', 'expired')),
    expires_at       TIMESTAMPTZ NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE user_provider_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_provider_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_executions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users_read_own_provider_connections" ON user_provider_connections;
CREATE POLICY "Users_read_own_provider_connections"
    ON user_provider_connections FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users_manage_own_provider_connections" ON user_provider_connections;
CREATE POLICY "Users_manage_own_provider_connections"
    ON user_provider_connections FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "service_role_all_user_provider_tokens" ON user_provider_tokens;
CREATE POLICY "service_role_all_user_provider_tokens"
    ON user_provider_tokens FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_pending_executions" ON pending_executions;
CREATE POLICY "service_role_all_pending_executions"
    ON pending_executions FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
