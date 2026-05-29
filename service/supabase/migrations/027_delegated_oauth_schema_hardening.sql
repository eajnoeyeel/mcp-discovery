-- ============================================================
-- Migration 027: Delegated OAuth Schema Hardening
-- ============================================================
-- Documents service-role-only intent for registry/requirement tables,
-- optimizes RLS helper calls, and adds FK/query indexes flagged by
-- Supabase advisors after migrations 025/026 were applied.
-- ============================================================

DROP POLICY IF EXISTS "service_role_all_oauth_provider_registry" ON oauth_provider_registry;
CREATE POLICY "service_role_all_oauth_provider_registry"
    ON oauth_provider_registry FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_mcp_auth_requirements" ON mcp_auth_requirements;
CREATE POLICY "service_role_all_mcp_auth_requirements"
    ON mcp_auth_requirements FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Users_read_own_provider_connections" ON user_provider_connections;
CREATE POLICY "Users_read_own_provider_connections"
    ON user_provider_connections FOR SELECT
    TO authenticated
    USING ((select auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users_manage_own_provider_connections" ON user_provider_connections;
CREATE POLICY "Users_manage_own_provider_connections"
    ON user_provider_connections FOR ALL
    TO authenticated
    USING ((select auth.uid()) = user_id)
    WITH CHECK ((select auth.uid()) = user_id);

CREATE INDEX IF NOT EXISTS idx_mcp_auth_requirements_server_id
    ON mcp_auth_requirements(server_id);

CREATE INDEX IF NOT EXISTS idx_mcp_auth_requirements_tool_id
    ON mcp_auth_requirements(tool_id)
    WHERE tool_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_auth_requirements_provider_key
    ON mcp_auth_requirements(provider_key);

CREATE INDEX IF NOT EXISTS idx_user_provider_connections_provider_key
    ON user_provider_connections(provider_key);

CREATE INDEX IF NOT EXISTS idx_pending_executions_user_id
    ON pending_executions(user_id);

CREATE INDEX IF NOT EXISTS idx_pending_executions_tool_id
    ON pending_executions(tool_id);

CREATE INDEX IF NOT EXISTS idx_pending_executions_provider_key
    ON pending_executions(provider_key);

CREATE INDEX IF NOT EXISTS idx_pending_executions_connection_id
    ON pending_executions(connection_id)
    WHERE connection_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pending_executions_user_status_expires
    ON pending_executions(user_id, status, expires_at);
