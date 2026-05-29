"""Schema assertions for migration 025 delegated OAuth broker tables."""

from pathlib import Path

import pytest

MIGRATION_PATH = Path("service/supabase/migrations/025_provider_oauth_broker.sql")


@pytest.fixture
def migration_sql() -> str:
    return MIGRATION_PATH.read_text()


def test_migration_025_creates_user_provider_connections(migration_sql: str) -> None:
    assert "CREATE TABLE IF NOT EXISTS user_provider_connections" in migration_sql
    assert "REFERENCES auth.users(id)" in migration_sql
    assert "granted_scopes      JSONB NOT NULL DEFAULT '[]'::jsonb" in migration_sql
    assert "scope_fingerprint" in migration_sql
    assert "UNIQUE (user_id, provider_key, scope_fingerprint)" in migration_sql
    assert "ALTER TABLE user_provider_connections ENABLE ROW LEVEL SECURITY" in migration_sql
    assert '"Users_manage_own_provider_connections"' in migration_sql
    assert "auth.uid() = user_id" in migration_sql


def test_migration_025_creates_service_role_only_user_provider_tokens(migration_sql: str) -> None:
    assert "CREATE TABLE IF NOT EXISTS user_provider_tokens" in migration_sql
    assert "connection_id      UUID PRIMARY KEY" in migration_sql
    assert "secret_backend     TEXT NOT NULL DEFAULT 'aws_secrets_manager'" in migration_sql
    assert "ALTER TABLE user_provider_tokens ENABLE ROW LEVEL SECURITY" in migration_sql
    assert '"service_role_all_user_provider_tokens"' in migration_sql
    assert "ON user_provider_tokens FOR ALL" in migration_sql
    assert "TO service_role" in migration_sql


def test_migration_025_creates_mcp_auth_requirements(migration_sql: str) -> None:
    assert "CREATE TABLE IF NOT EXISTS mcp_auth_requirements" in migration_sql
    assert "REFERENCES mcp_servers(server_id)" in migration_sql
    assert "REFERENCES mcp_tools(tool_id)" in migration_sql
    assert "REFERENCES oauth_provider_registry(provider_key)" in migration_sql
    assert "auth_kind         TEXT NOT NULL DEFAULT 'oauth'" in migration_sql
    assert "required_scopes   JSONB NOT NULL DEFAULT '[]'::jsonb" in migration_sql
    assert "scope_mode        TEXT NOT NULL DEFAULT 'default'" in migration_sql


def test_migration_025_creates_oauth_provider_registry(migration_sql: str) -> None:
    assert "CREATE TABLE IF NOT EXISTS oauth_provider_registry" in migration_sql
    assert "default_scopes          JSONB NOT NULL DEFAULT '[]'::jsonb" in migration_sql
    assert "scope_aliases           JSONB NOT NULL DEFAULT '{}'::jsonb" in migration_sql
    assert "pkce_required           BOOLEAN NOT NULL DEFAULT TRUE" in migration_sql


def test_migration_025_creates_pending_executions(migration_sql: str) -> None:
    assert "CREATE TABLE IF NOT EXISTS pending_executions" in migration_sql
    assert "params_json      JSONB NOT NULL DEFAULT '{}'::jsonb" in migration_sql
    assert "required_scopes  JSONB NOT NULL DEFAULT '[]'::jsonb" in migration_sql
    assert "retry_token      TEXT NOT NULL UNIQUE" in migration_sql
    assert "connection_id    UUID" in migration_sql
    assert "result_json      JSONB" in migration_sql
    assert "error_message    TEXT" in migration_sql
    for status in (
        "waiting_for_connect",
        "ready_to_resume",
        "resuming",
        "resumed",
        "failed",
        "expired",
    ):
        assert f"'{status}'" in migration_sql
    assert "ALTER TABLE pending_executions ENABLE ROW LEVEL SECURITY" in migration_sql


def test_migration_025_creates_service_role_pending_execution_policy(migration_sql: str) -> None:
    assert '"service_role_all_pending_executions"' in migration_sql
    assert "ON pending_executions FOR ALL" in migration_sql
    assert "TO service_role" in migration_sql


def test_migration_027_hardens_delegated_oauth_schema() -> None:
    hardening_sql = Path(
        "service/supabase/migrations/027_delegated_oauth_schema_hardening.sql"
    ).read_text()

    assert '"service_role_all_oauth_provider_registry"' in hardening_sql
    assert '"service_role_all_mcp_auth_requirements"' in hardening_sql
    assert "USING ((select auth.uid()) = user_id)" in hardening_sql
    for index_name in (
        "idx_mcp_auth_requirements_server_id",
        "idx_mcp_auth_requirements_tool_id",
        "idx_mcp_auth_requirements_provider_key",
        "idx_user_provider_connections_provider_key",
        "idx_pending_executions_user_id",
        "idx_pending_executions_tool_id",
        "idx_pending_executions_provider_key",
        "idx_pending_executions_connection_id",
        "idx_pending_executions_user_status_expires",
    ):
        assert index_name in hardening_sql


def test_migration_028_splits_user_provider_connection_write_policies() -> None:
    policy_sql = Path(
        "service/supabase/migrations/028_user_provider_connection_policy_split.sql"
    ).read_text()

    assert 'DROP POLICY IF EXISTS "Users_manage_own_provider_connections"' in policy_sql
    assert "FOR INSERT" in policy_sql
    assert "FOR UPDATE" in policy_sql
    assert "FOR DELETE" in policy_sql
    executable_sql = "\n".join(
        line for line in policy_sql.splitlines() if not line.strip().startswith("--")
    )
    assert "FOR ALL" not in executable_sql
    assert "WITH CHECK ((select auth.uid()) = user_id)" in policy_sql
