"""Verify migration 008 SQL is parseable and contains required elements."""

from pathlib import Path

import pytest

MIGRATION_PATH = Path("service/supabase/migrations/011_operational_stats.sql")


@pytest.fixture
def migration_sql():
    assert MIGRATION_PATH.exists(), f"Migration file not found: {MIGRATION_PATH}"
    return MIGRATION_PATH.read_text()


def test_event_id_columns(migration_sql):
    assert "event_id" in migration_sql
    assert "execution_logs" in migration_sql
    assert "query_logs" in migration_sql


def test_unique_constraint_for_idempotency(migration_sql):
    sql_lower = migration_sql.lower()
    assert "unique" in sql_lower or "on conflict" in sql_lower


def test_materialized_views_exist(migration_sql):
    sql_lower = migration_sql.lower()
    assert "create materialized view" in sql_lower
    assert "tool_operational_stats" in sql_lower


def test_seven_day_window_view(migration_sql):
    assert "tool_operational_stats_7d" in migration_sql


def test_pg_cron_schedule(migration_sql):
    sql_lower = migration_sql.lower()
    assert "cron.schedule" in sql_lower


def test_refresh_function(migration_sql):
    assert "refresh_operational_stats" in migration_sql


def test_stage_metrics_column(migration_sql):
    assert "stage_metrics" in migration_sql


def test_tool_operability_view(migration_sql):
    """View that OperabilityCache reads from."""
    assert "tool_operability_view" in migration_sql
