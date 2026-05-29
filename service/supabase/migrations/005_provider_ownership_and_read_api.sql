-- ============================================================
-- MCP Discovery Platform — Provider Ownership And Read API
-- ============================================================
-- Adds provider ownership to servers so dashboard reads can be
-- scoped to the authenticated provider through backend APIs.
-- ============================================================

ALTER TABLE mcp_servers
ADD COLUMN IF NOT EXISTS owner_user_id UUID;

CREATE INDEX IF NOT EXISTS idx_mcp_servers_owner_user_id
ON mcp_servers (owner_user_id);

