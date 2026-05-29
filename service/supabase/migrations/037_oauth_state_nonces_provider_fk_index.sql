-- ============================================================
-- Migration 037: OAuth State Nonces Provider FK Index
-- ============================================================
-- Adds a covering index for the oauth_state_nonces.provider_key foreign key.
-- The composite user/provider index from migration 036 optimizes user-scoped
-- lookups but does not cover provider-key-only FK checks/deletes.
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_oauth_state_nonces_provider_key
    ON oauth_state_nonces(provider_key);
