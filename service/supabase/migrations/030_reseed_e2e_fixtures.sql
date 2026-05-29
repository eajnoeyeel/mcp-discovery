-- ============================================================
-- Migration 030: Truncate E2E fixture rows with no secret refs
-- ============================================================
-- Only run after 029_drop_plaintext_secrets.sql has been applied.
--
-- After migration 029 drops the plaintext columns, E2E test rows
-- that were seeded with bearer_token/api_key but never given _ref
-- counterparts are left with no usable auth data. This migration
-- deletes those orphaned rows so E2E tests start from a clean
-- fixture state and can re-seed with ref-backed credentials.
--
-- Conservative scope: only deletes rows where BOTH ref columns
-- are NULL (i.e. the row carries no usable secret reference at
-- all). Rows with at least one populated _ref column are retained.
--
-- Depends on: 029_drop_plaintext_secrets.sql
-- ============================================================

BEGIN;

DELETE FROM mcp_server_auth
WHERE bearer_token_ref IS NULL
  AND api_key_ref       IS NULL;

DELETE FROM mcp_oauth_sessions
WHERE client_secret_ref IS NULL
  AND refresh_token_ref  IS NULL;

COMMIT;
