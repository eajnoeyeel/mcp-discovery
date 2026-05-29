-- ============================================================
-- Rollback for Migration 029: Restore plaintext secret columns
-- ============================================================
-- EMERGENCY ROLLBACK ONLY — do not run in normal operations.
--
-- Restores the plaintext columns dropped by 029_drop_plaintext_secrets.sql.
-- After running this script, operators MUST also run a Secrets Manager
-- → plaintext backfill script to re-populate the restored columns from
-- AWS Secrets Manager before any application code can use them.
--
-- The columns are restored as nullable (no NOT NULL constraint) because
-- the pre-029 state allowed NULL for optional auth fields, and a rollback
-- should not introduce new constraint violations.
--
-- Steps after running this rollback:
--   1. Run the backfill script to populate plaintext values from Secrets Manager.
--   2. Verify application auth paths are functional.
--   3. Re-assess whether to re-attempt migration 029 with corrected data.
-- ============================================================

BEGIN;

-- ============================================================
-- Restore mcp_server_auth plaintext columns
-- ============================================================

ALTER TABLE mcp_server_auth
    ADD COLUMN IF NOT EXISTS bearer_token TEXT,
    ADD COLUMN IF NOT EXISTS api_key      TEXT;

COMMENT ON COLUMN mcp_server_auth.bearer_token IS
    'RESTORED BY ROLLBACK 029. Plaintext bearer token — populate via '
    'Secrets Manager backfill script before use. Superseded by bearer_token_ref.';

COMMENT ON COLUMN mcp_server_auth.api_key IS
    'RESTORED BY ROLLBACK 029. Plaintext API key — populate via '
    'Secrets Manager backfill script before use. Superseded by api_key_ref.';

-- ============================================================
-- Restore mcp_oauth_sessions plaintext columns
-- ============================================================

ALTER TABLE mcp_oauth_sessions
    ADD COLUMN IF NOT EXISTS client_secret  TEXT,
    ADD COLUMN IF NOT EXISTS access_token   TEXT,
    ADD COLUMN IF NOT EXISTS refresh_token  TEXT;

COMMENT ON COLUMN mcp_oauth_sessions.client_secret IS
    'RESTORED BY ROLLBACK 029. Plaintext OAuth client secret — populate via '
    'Secrets Manager backfill script before use. Superseded by client_secret_ref.';

COMMENT ON COLUMN mcp_oauth_sessions.access_token IS
    'RESTORED BY ROLLBACK 029. Plaintext OAuth access token — was never '
    'ref-backed; callers should obtain a fresh token via token_endpoint.';

COMMENT ON COLUMN mcp_oauth_sessions.refresh_token IS
    'RESTORED BY ROLLBACK 029. Plaintext OAuth refresh token — populate via '
    'Secrets Manager backfill script before use. Superseded by refresh_token_ref.';

COMMIT;
