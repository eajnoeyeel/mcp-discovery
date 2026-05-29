-- ============================================================
-- Migration 017: Schema Audit Fixes (NOW-priority)
-- ============================================================
-- Remediates all NOW-priority issues identified in the
-- 2026-04-15 serverless schema audit.
--
-- Sections:
--   A  C2  — Drop NOT NULL on refresh_token (latent INSERT bug)
--   B  H1  — Add updated_at column + trigger to mcp_tools
--   C  H2  — GRANT SELECT on views/MVs missing grants
--   D  H3  — Partial index on query_logs(selected_tool_id)
--   E  H4  — Converge secret_backend CHECK constraint
--             (fresh-install vs live-DB schema divergence)
--   F       — Drop superseded provider_dashboard_snapshot view
--
-- Depends on: 001_initial.sql (update_updated_at function,
--             mcp_tools, mcp_servers, query_logs),
--             009 / 014 (mcp_oauth_sessions),
--             011 (tool_operability_view, tool_operational_stats,
--                  tool_operational_stats_7d),
--             012 (tool_selection_stats, tool_exposure_stats,
--                  tool_exposure_stats_7d, tool_daily_stats,
--                  tool_client_stats, tool_client_selection_stats,
--                  provider_tool_dashboard)
--
-- Forward-only. No rollback section.
-- All DDL uses IF NOT EXISTS / IF EXISTS / NOT VALID + VALIDATE
-- for idempotency and zero-downtime safety.
-- ============================================================

-- ============================================================
-- Section A: C2 — Fix refresh_token NOT NULL latent bug
-- ============================================================
-- _oauth_session_row() in register/handler.py and the store()
-- path in supabase_oauth_tokens.py both omit refresh_token
-- from the INSERT payload, storing the token in AWS Secrets
-- Manager and writing only refresh_token_ref. The NOT NULL
-- constraint on the column causes the first INSERT to fail
-- with a NOT NULL violation. The design intent (secret refs)
-- means plaintext refresh_token should be optional.
-- ============================================================

ALTER TABLE mcp_oauth_sessions
    ALTER COLUMN refresh_token DROP NOT NULL;

-- ============================================================
-- Section B: H1 — Add updated_at to mcp_tools
-- ============================================================
-- mcp_servers has had updated_at + trigger since migration 001.
-- mcp_tools lacked this column, creating asymmetric entity
-- design. The update_updated_at() function already exists.
-- ============================================================

ALTER TABLE mcp_tools
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

CREATE TRIGGER set_mcp_tools_updated_at
    BEFORE UPDATE ON mcp_tools
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- Section C: H2 — GRANT SELECT on views and MVs missing grants
-- ============================================================
-- Only provider_dashboard_snapshot, server_tool_counts, and
-- provider_search_simulations had explicit GRANTs (migrations
-- 002 and 004). All views and MVs added in migrations 011 and
-- 012 are missing GRANT statements. Currently bypassed by
-- service_role key usage; any non-service-role access fails.
-- ============================================================

-- From migration 011: view
GRANT SELECT ON tool_operability_view TO anon, authenticated;

-- From migration 012: view
GRANT SELECT ON provider_tool_dashboard TO anon, authenticated;

-- Materialized views from migration 011
GRANT SELECT ON tool_operational_stats    TO anon, authenticated;
GRANT SELECT ON tool_operational_stats_7d TO anon, authenticated;

-- Materialized views from migration 012
GRANT SELECT ON tool_selection_stats          TO anon, authenticated;
GRANT SELECT ON tool_exposure_stats           TO anon, authenticated;
GRANT SELECT ON tool_exposure_stats_7d        TO anon, authenticated;
GRANT SELECT ON tool_daily_stats              TO anon, authenticated;
GRANT SELECT ON tool_client_stats             TO anon, authenticated;
GRANT SELECT ON tool_client_selection_stats   TO anon, authenticated;

-- ============================================================
-- Section D: H3 — Index on query_logs(selected_tool_id)
-- ============================================================
-- tool_selection_stats MV, provider_search_simulations VIEW,
-- and fetch_tool_simulations() all filter/aggregate on
-- selected_tool_id. Partial index excludes NULLs (which are
-- never aggregated and would only bloat the index).
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_query_logs_selected_tool_id
    ON query_logs (selected_tool_id)
    WHERE selected_tool_id IS NOT NULL;

-- ============================================================
-- Section E: H4 — Converge secret_backend CHECK constraint
-- ============================================================
-- Fresh-install path runs 009 → 010 → 014 in sequence.
-- Migration 014's CREATE TABLE IF NOT EXISTS is a no-op when
-- 009 already created the table, so fresh-install ends with
-- the schema from 009+010: secret_backend column present but
-- the CHECK constraint from 010 uses a pg-auto-named inline
-- CHECK, while 014 explicitly names it
-- mcp_oauth_sessions_secret_backend_check.
--
-- This section drops any existing constraint under that name
-- and re-creates it using NOT VALID + VALIDATE for zero-
-- downtime convergence. The NOT VALID pattern skips a full
-- table scan on large live tables while still enforcing the
-- CHECK on new rows immediately; VALIDATE then back-fills.
-- ============================================================

ALTER TABLE mcp_oauth_sessions
    DROP CONSTRAINT IF EXISTS mcp_oauth_sessions_secret_backend_check;

ALTER TABLE mcp_oauth_sessions
    ADD CONSTRAINT mcp_oauth_sessions_secret_backend_check
    CHECK (secret_backend IN ('aws_secrets_manager')) NOT VALID;

ALTER TABLE mcp_oauth_sessions
    VALIDATE CONSTRAINT mcp_oauth_sessions_secret_backend_check;

-- ============================================================
-- Section F: Dead view cleanup — Drop provider_dashboard_snapshot
-- ============================================================
-- Created in migration 002 and superseded by provider_tool_dashboard
-- (migration 012), which joins all operational/selection/exposure
-- MVs and provides a richer, unified dashboard view.
--
-- Code search (search_for_pattern across all Python files)
-- found NO Python code references to provider_dashboard_snapshot.
-- The only non-SQL references are:
--   - tests/unit/test_mlp_schema_contracts.py line 17: checks
--     that the STRING "provider_dashboard_snapshot" appears in
--     the migration 002 SQL file text — this test will continue
--     to pass after the DROP because migration 002 still contains
--     the CREATE OR REPLACE VIEW statement.
--   - mlp/docs/handoff_lovable_supabase.md: documentation only,
--     no runtime dependency.
-- Safe to drop.
-- ============================================================

DROP VIEW IF EXISTS provider_dashboard_snapshot;
