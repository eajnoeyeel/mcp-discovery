-- Migration 007: Entity lifecycle, content hash, and freshness tracking
-- Forward-only migration. Rollback: manually drop added columns and restore CHECK constraint.
-- Rollback is intentionally not scripted — column drops require data preservation decisions.

-- 1. Entity lifecycle state machine
ALTER TABLE mcp_tools
  DROP CONSTRAINT IF EXISTS mcp_tools_index_status_check;

ALTER TABLE mcp_tools
  ADD CONSTRAINT mcp_tools_index_status_check
  CHECK (index_status IN ('pending', 'indexing', 'indexed', 'failed', 'deprecated', 'unreachable', 'quarantined'));

-- 2. Content hash for idempotent indexing
ALTER TABLE mcp_tools
  ADD COLUMN IF NOT EXISTS content_hash TEXT;

-- 3. Freshness tracking (3-tier)
ALTER TABLE mcp_tools
  ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_health_check_at TIMESTAMPTZ;

ALTER TABLE mcp_servers
  ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_health_check_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS entity_status TEXT DEFAULT 'active'
    CHECK (entity_status IN ('active', 'deprecated', 'unreachable', 'superseded', 'quarantined'));

-- 4. Index on content_hash
CREATE INDEX IF NOT EXISTS idx_mcp_tools_content_hash ON mcp_tools(content_hash);

COMMENT ON COLUMN mcp_tools.content_hash IS 'SHA-256 of tool_name:description — skip re-embedding if unchanged';
COMMENT ON COLUMN mcp_tools.source_updated_at IS 'When the upstream registry last changed this tool';
COMMENT ON COLUMN mcp_tools.indexed_at IS 'When this tool was last embedded and upserted to Qdrant';
COMMENT ON COLUMN mcp_tools.last_health_check_at IS 'When the tool last passed a health/reachability check';
COMMENT ON COLUMN mcp_servers.entity_status IS 'Lifecycle state: active→deprecated→unreachable→superseded→quarantined';
