-- ============================================================
-- Migration 020: HTTP MCP metadata override/reference fields
-- ============================================================
-- Adds upstream/reference metadata fields so mcp_tools.description
-- can remain the effective published metadata while preserving
-- upstream snapshots and provider-authored helper metadata.
--
-- Depends on: 001_initial.sql (mcp_tools table),
--             017_schema_audit_fixes.sql (mcp_tools.updated_at)
-- ============================================================

ALTER TABLE mcp_tools
    ADD COLUMN IF NOT EXISTS upstream_description TEXT,
    ADD COLUMN IF NOT EXISTS metadata_last_fetched_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS parameter_notes TEXT,
    ADD COLUMN IF NOT EXISTS usage_examples JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS usage_hints JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS metadata_origin TEXT NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS override_updated_at TIMESTAMPTZ;

ALTER TABLE mcp_tools
    DROP CONSTRAINT IF EXISTS mcp_tools_metadata_origin_check;

ALTER TABLE mcp_tools
    ADD CONSTRAINT mcp_tools_metadata_origin_check
    CHECK (metadata_origin IN ('manual', 'discovered', 'mixed')) NOT VALID;

ALTER TABLE mcp_tools
    VALIDATE CONSTRAINT mcp_tools_metadata_origin_check;

COMMENT ON COLUMN mcp_tools.upstream_description IS 'Latest upstream tool description snapshot kept as reference metadata';
COMMENT ON COLUMN mcp_tools.metadata_last_fetched_at IS 'Timestamp of the latest upstream metadata fetch for this tool';
COMMENT ON COLUMN mcp_tools.parameter_notes IS 'Provider-authored usage notes that supplement the effective tool description';
COMMENT ON COLUMN mcp_tools.usage_examples IS 'Provider-authored example inputs or invocation snippets for the tool';
COMMENT ON COLUMN mcp_tools.usage_hints IS 'Provider-authored short hints shown alongside the published tool metadata';
COMMENT ON COLUMN mcp_tools.metadata_origin IS 'How the current metadata set was assembled: manual, discovered, or mixed';
COMMENT ON COLUMN mcp_tools.override_updated_at IS 'Timestamp of the latest explicit provider metadata override update';
