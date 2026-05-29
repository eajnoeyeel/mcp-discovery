-- ============================================================
-- MCP Discovery Platform — OAuth Secret References
-- ============================================================
-- Replaces raw OAuth client_secret / refresh_token storage with
-- indirection through AWS Secrets Manager references.
-- ============================================================

ALTER TABLE mcp_oauth_sessions
ADD COLUMN IF NOT EXISTS client_secret_ref TEXT,
ADD COLUMN IF NOT EXISTS refresh_token_ref TEXT;

ALTER TABLE mcp_oauth_sessions
ADD COLUMN IF NOT EXISTS secret_backend TEXT NOT NULL DEFAULT 'aws_secrets_manager'
CHECK (secret_backend IN ('aws_secrets_manager'));
