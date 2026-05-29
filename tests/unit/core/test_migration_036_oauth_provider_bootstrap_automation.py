from pathlib import Path

MIGRATION_PATH = Path("service/supabase/migrations/036_oauth_provider_bootstrap_automation.sql")


def test_migration_036_extends_provider_registry_for_bootstrap() -> None:
    sql = MIGRATION_PATH.read_text()
    for column in (
        "issuer",
        "metadata_url",
        "protected_resource_metadata_url",
        "registration_endpoint",
        "client_secret_ref",
        "token_endpoint_auth_method",
        "bootstrap_mode",
        "bootstrap_status",
    ):
        assert column in sql
    assert "client_secret_post" in sql
    assert "client_secret_basic" in sql
    assert "enabled IS FALSE OR bootstrap_status = 'enabled'" in sql


def test_migration_036_adds_draft_table_and_promotion_rpc() -> None:
    sql = MIGRATION_PATH.read_text()
    assert "CREATE TABLE IF NOT EXISTS oauth_provider_bootstrap_drafts" in sql
    assert "UNIQUE (owner_user_id, idempotency_key)" in sql
    assert "CREATE OR REPLACE FUNCTION public.promote_oauth_provider_bootstrap_draft" in sql
    assert "GRANT EXECUTE ON FUNCTION public.promote_oauth_provider_bootstrap_draft" in sql


def test_migration_036_adds_oauth_state_nonce_replay_protection() -> None:
    sql = MIGRATION_PATH.read_text()
    assert "CREATE TABLE IF NOT EXISTS oauth_state_nonces" in sql
    assert "nonce_hash       TEXT PRIMARY KEY" in sql
    assert "code_verifier    TEXT" in sql
    assert "required_scopes  JSONB NOT NULL DEFAULT '[]'::jsonb" in sql
    assert "consumed_at" in sql
    assert "CREATE OR REPLACE FUNCTION public.consume_oauth_state_nonce" in sql
    assert "FOR UPDATE" in sql
