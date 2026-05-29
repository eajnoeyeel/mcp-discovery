"""Schema assertions for migration 034 mcp_auth_requirements uniqueness."""

from pathlib import Path


def test_migration_034_enforces_unique_tool_and_server_default_rows() -> None:
    migration_sql = Path(
        "service/supabase/migrations/034_mcp_auth_requirements_uniqueness.sql"
    ).read_text()

    assert "ranked_tool_rows" in migration_sql
    assert "ranked_server_defaults" in migration_sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_auth_requirements_tool_id" in migration_sql
    assert "WHERE tool_id IS NOT NULL" in migration_sql
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_auth_requirements_server_default" in migration_sql
    )
    assert "WHERE tool_id IS NULL" in migration_sql
