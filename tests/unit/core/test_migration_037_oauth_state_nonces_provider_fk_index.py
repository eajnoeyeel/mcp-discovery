from pathlib import Path

MIGRATION_PATH = Path("service/supabase/migrations/037_oauth_state_nonces_provider_fk_index.sql")


def test_migration_037_adds_provider_key_fk_index() -> None:
    sql = MIGRATION_PATH.read_text()
    assert "CREATE INDEX IF NOT EXISTS idx_oauth_state_nonces_provider_key" in sql
    assert "ON oauth_state_nonces(provider_key)" in sql
