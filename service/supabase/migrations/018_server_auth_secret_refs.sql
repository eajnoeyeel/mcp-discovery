-- ============================================================
-- MCP Discovery Platform — Server Auth Secret References
-- ============================================================
-- Adds secret reference columns to mcp_server_auth, mirroring
-- the OAuth indirection pattern from migration 010_oauth_secret_refs.
-- Plaintext columns are retained for backward compatibility during
-- the migration window; they will be dropped in a future migration
-- after all existing secrets are migrated to AWS Secrets Manager.
-- ============================================================

ALTER TABLE mcp_server_auth
    ADD COLUMN IF NOT EXISTS bearer_token_ref TEXT,
    ADD COLUMN IF NOT EXISTS api_key_ref TEXT,
    ADD COLUMN IF NOT EXISTS secret_backend TEXT NOT NULL DEFAULT 'aws_secrets_manager'
    CHECK (secret_backend IN ('aws_secrets_manager'));

COMMENT ON COLUMN mcp_server_auth.bearer_token_ref IS 'AWS Secrets Manager ARN/name for bearer token; takes precedence over plaintext bearer_token column';
COMMENT ON COLUMN mcp_server_auth.api_key_ref IS 'AWS Secrets Manager ARN/name for API key; takes precedence over plaintext api_key column';
COMMENT ON COLUMN mcp_server_auth.secret_backend IS 'Secret storage backend; currently only aws_secrets_manager is supported';
