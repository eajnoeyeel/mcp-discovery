-- ============================================================
-- Migration 028: User Provider Connection Policy Split
-- ============================================================
-- Avoid multiple permissive SELECT policies on user_provider_connections
-- by replacing the broad FOR ALL policy with action-specific write policies.
-- ============================================================

DROP POLICY IF EXISTS "Users_manage_own_provider_connections" ON user_provider_connections;
DROP POLICY IF EXISTS "Users_insert_own_provider_connections" ON user_provider_connections;
DROP POLICY IF EXISTS "Users_update_own_provider_connections" ON user_provider_connections;
DROP POLICY IF EXISTS "Users_delete_own_provider_connections" ON user_provider_connections;

CREATE POLICY "Users_insert_own_provider_connections"
    ON user_provider_connections FOR INSERT
    TO authenticated
    WITH CHECK ((select auth.uid()) = user_id);

CREATE POLICY "Users_update_own_provider_connections"
    ON user_provider_connections FOR UPDATE
    TO authenticated
    USING ((select auth.uid()) = user_id)
    WITH CHECK ((select auth.uid()) = user_id);

CREATE POLICY "Users_delete_own_provider_connections"
    ON user_provider_connections FOR DELETE
    TO authenticated
    USING ((select auth.uid()) = user_id);
