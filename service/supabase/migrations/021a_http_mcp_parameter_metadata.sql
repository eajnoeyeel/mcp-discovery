-- ============================================================
-- Migration 021: HTTP MCP parameter metadata snapshots
-- ============================================================
-- Adds separate upstream/published parameter metadata fields so
-- input_schema remains upstream execution truth while provider-
-- authored parameter description overrides persist independently.
--
-- Depends on: 001_initial.sql (mcp_tools table),
--             020_http_mcp_metadata_overrides.sql
-- ============================================================

ALTER TABLE mcp_tools
    ADD COLUMN IF NOT EXISTS upstream_parameter_metadata JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS published_parameter_metadata JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN mcp_tools.upstream_parameter_metadata IS 'Latest normalized upstream parameter metadata snapshot derived from the tool input schema';
COMMENT ON COLUMN mcp_tools.published_parameter_metadata IS 'Provider-authored parameter description overrides applied on read paths to build the effective input schema';
