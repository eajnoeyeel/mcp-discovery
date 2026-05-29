-- ============================================================
-- Migration 032: Revoke analytics view public grants (F4 — 2026-04-20 audit)
-- ============================================================
-- Analytics views derived from query_logs / execution_logs were granted
-- SELECT to anon and authenticated in migrations 017 / 021 / 022 / 025a.
-- That exposed per-provider call patterns, recommendations, client
-- identifiers, and p95/latency percentiles to any logged-in user —
-- bypassing the provider boundary we document in ADR-0022 and
-- docs/design/serverless-architecture-principles.md.
--
-- Decision: DB contract enforces tenant isolation, not application
-- discipline. Runtime adapters use the service_role key (bypasses
-- REVOKE), so revoking public grants does not break internal paths.
-- Public / provider-scoped client reads should go through:
--   - server_tool_counts (public, non-sensitive)
--   - provider_tool_dashboard_self (security_invoker, auth.uid() scoped)
-- or explicit service-role-backed HTTP endpoints.
--
-- Rollback (emergency): re-run
--   GRANT SELECT ON <view> TO anon, authenticated;
-- for each view listed below.
--
-- Depends on: 017_schema_audit_fixes.sql, 020_mv_to_view.sql,
--             021_analytics_views_fix.sql, 022_metric_semantic_redesign.sql,
--             025a_schema_housekeeping.sql
-- ============================================================

REVOKE SELECT ON tool_operational_stats         FROM anon, authenticated;
REVOKE SELECT ON tool_operational_stats_7d      FROM anon, authenticated;
REVOKE SELECT ON tool_selection_stats           FROM anon, authenticated;
REVOKE SELECT ON tool_exposure_stats            FROM anon, authenticated;
REVOKE SELECT ON tool_exposure_stats_7d         FROM anon, authenticated;
REVOKE SELECT ON tool_daily_stats               FROM anon, authenticated;
REVOKE SELECT ON tool_client_stats              FROM anon, authenticated;
REVOKE SELECT ON tool_client_selection_stats    FROM anon, authenticated;
REVOKE SELECT ON tool_exposure_facts            FROM anon, authenticated;
REVOKE SELECT ON tool_conversion_funnel         FROM anon, authenticated;
REVOKE SELECT ON provider_search_simulations    FROM anon, authenticated;
REVOKE SELECT ON tool_operability_view          FROM anon, authenticated;

-- server_tool_counts is left public (non-sensitive tool counts).
-- provider_tool_dashboard stays REVOKEd as set in migration 028.
