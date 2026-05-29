-- ============================================================
-- Migration 028: Scoped provider dashboard view
-- ============================================================
-- provider_tool_dashboard exposes ALL tools to any authenticated
-- user, relying on the service layer to apply provider_id
-- filtering. This creates a risk of accidental cross-provider
-- data leakage if a caller omits the WHERE clause.
--
-- This migration adds provider_tool_dashboard_self: a
-- security_invoker view that automatically scopes rows to the
-- calling user's provider. The original provider_tool_dashboard
-- is retained for service_role internal use (Lambda callers)
-- but its SELECT grant for anon/authenticated is revoked.
--
-- security_invoker=true means row visibility is evaluated using
-- the calling user's session (auth.uid()), not the definer's
-- privileges. This is the correct pattern for Supabase RLS-
-- compatible views.
--
-- Depends on: 022_metric_semantic_redesign.sql
--             (provider_tool_dashboard, providers table)
-- ============================================================

BEGIN;

-- Scoped view — RLS-equivalent via security_invoker
CREATE OR REPLACE VIEW provider_tool_dashboard_self
    WITH (security_invoker = true)
AS
SELECT *
FROM provider_tool_dashboard
WHERE provider_id IN (
    SELECT id FROM providers WHERE user_id = auth.uid()
);

COMMENT ON VIEW provider_tool_dashboard_self IS
    'Security-invoker view of provider_tool_dashboard scoped to the '
    'calling user''s own provider. Use this from client-facing API paths. '
    'provider_tool_dashboard remains available to service_role for internal '
    'Lambda queries that perform explicit provider_id filtering.';

GRANT SELECT ON provider_tool_dashboard_self TO authenticated;

-- Revoke broad access on the base view; service_role retains its
-- default superuser access (not governed by GRANT/REVOKE for views).
REVOKE SELECT ON provider_tool_dashboard FROM anon, authenticated;

COMMIT;
