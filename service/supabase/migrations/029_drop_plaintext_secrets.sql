-- ============================================================
-- Migration 029: Drop plaintext secret columns
-- ============================================================
-- DESTRUCTIVE — operator approval required before applying.
-- Prod is E2E-only per session context.
--
-- Migrations 018 and 010/014 added _ref columns alongside the
-- original plaintext columns. The intent (documented in 018)
-- was to drop plaintext columns after all existing secrets are
-- migrated to AWS Secrets Manager. This migration executes
-- that drop.
--
-- Pre-flight safety check: raises an exception if any row in
-- mcp_server_auth has a non-NULL bearer_token or api_key
-- WITHOUT a corresponding _ref. Similarly for mcp_oauth_sessions
-- client_secret / refresh_token vs _ref. The migration ABORTS
-- rather than silently delete un-migrated secrets.
--
-- Run ONLY after verifying that all production secrets have been
-- migrated to AWS Secrets Manager and their _ref columns are
-- populated. Use 030_reseed_e2e_fixtures.sql afterward to
-- clean up E2E test rows that have no _ref counterpart.
--
-- Rollback: see service/supabase/rollback/029_rollback_restore_plaintext.sql
--
-- Depends on: 008_execution_auth_metadata.sql (mcp_server_auth),
--             014_oauth_gateway_tables.sql (mcp_oauth_sessions),
--             018_server_auth_secret_refs.sql (_ref columns)
-- ============================================================

BEGIN;

-- ============================================================
-- Pre-flight: refuse to proceed if un-migrated plaintext exists
-- ============================================================

DO $$
DECLARE
    unmigrated_auth   INT;
    unmigrated_oauth  INT;
BEGIN
    -- mcp_server_auth: any row with a plaintext secret but no ref
    SELECT count(*) INTO unmigrated_auth
    FROM mcp_server_auth
    WHERE (bearer_token IS NOT NULL AND bearer_token_ref IS NULL)
       OR (api_key      IS NOT NULL AND api_key_ref      IS NULL);

    IF unmigrated_auth > 0 THEN
        RAISE EXCEPTION
            'ABORT: % mcp_server_auth row(s) have plaintext bearer_token or '
            'api_key without a corresponding _ref. Migrate these secrets to '
            'AWS Secrets Manager and populate the _ref columns before '
            'running this migration.',
            unmigrated_auth;
    END IF;

    -- mcp_oauth_sessions: any row with a plaintext secret but no ref
    SELECT count(*) INTO unmigrated_oauth
    FROM mcp_oauth_sessions
    WHERE (client_secret  IS NOT NULL AND client_secret_ref  IS NULL)
       OR (refresh_token  IS NOT NULL AND refresh_token_ref  IS NULL);

    IF unmigrated_oauth > 0 THEN
        RAISE EXCEPTION
            'ABORT: % mcp_oauth_sessions row(s) have plaintext client_secret '
            'or refresh_token without a corresponding _ref. Migrate these '
            'secrets to AWS Secrets Manager and populate the _ref columns '
            'before running this migration.',
            unmigrated_oauth;
    END IF;
END $$;

-- ============================================================
-- Drop plaintext secret columns from mcp_server_auth
-- ============================================================

ALTER TABLE mcp_server_auth
    DROP COLUMN IF EXISTS bearer_token,
    DROP COLUMN IF EXISTS api_key;

COMMENT ON TABLE mcp_server_auth IS
    'Provider MCP upstream auth metadata; service_role-only. '
    'Plaintext bearer_token and api_key columns removed in migration 029 — '
    'use bearer_token_ref and api_key_ref (AWS Secrets Manager ARN/name).';

-- ============================================================
-- Drop plaintext secret columns from mcp_oauth_sessions
-- ============================================================

ALTER TABLE mcp_oauth_sessions
    DROP COLUMN IF EXISTS client_secret,
    DROP COLUMN IF EXISTS access_token,
    DROP COLUMN IF EXISTS refresh_token;

COMMENT ON TABLE mcp_oauth_sessions IS
    'Provider upstream OAuth token state; service_role-only. '
    'Plaintext client_secret, access_token, and refresh_token columns '
    'removed in migration 029 — use client_secret_ref and refresh_token_ref '
    '(AWS Secrets Manager ARN/name). access_token was never ref-backed; '
    'callers must obtain a fresh token via the token_endpoint.';

COMMIT;
