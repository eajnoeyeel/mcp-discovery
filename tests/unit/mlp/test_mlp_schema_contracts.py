"""Test that Supabase migration files contain required database objects."""

from pathlib import Path

MIGRATION_002 = Path("service/supabase/migrations/002_runtime_contracts.sql")
MIGRATION_006 = Path("service/supabase/migrations/006_fts_nullable_status.sql")


def test_migration_002_exists():
    assert MIGRATION_002.exists(), "002_runtime_contracts.sql not found"


def test_migration_002_contains_required_objects():
    sql = MIGRATION_002.read_text()
    required = [
        "search_tools_fts",
        "provider_dashboard_snapshot",
        "server_tool_counts",
        "get_platform_stats",
    ]
    for name in required:
        assert name in sql, f"Missing: {name}"


def test_migration_006_fixes_fts_nullable_status():
    sql = MIGRATION_006.read_text()
    assert "search_tools_fts" in sql
    assert "status_filter IS NULL" in sql
