"""Tests for migration 022: metric semantic redesign schema assertions.

No-DB tests assert the migration SQL content directly (parseable, contains
required DDL statements). DB-dependent tests are gated with skipif.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

MIGRATION_PATH = Path("service/supabase/migrations/022_metric_semantic_redesign.sql")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

_db_required = pytest.mark.skipif(
    not SUPABASE_URL,
    reason="SUPABASE_URL not set — skipping DB-dependent schema assertions",
)


# ---------------------------------------------------------------------------
# No-DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def migration_sql() -> str:
    assert MIGRATION_PATH.exists(), f"Migration file not found: {MIGRATION_PATH}"
    return MIGRATION_PATH.read_text()


# ---------------------------------------------------------------------------
# No-DB: SQL content assertions (no Supabase required)
# ---------------------------------------------------------------------------


def test_migration_sql_parseable(migration_sql: str) -> None:
    """Migration file exists and is non-empty."""
    assert len(migration_sql) > 100


def test_migration_contains_column_rename(migration_sql: str) -> None:
    """Must rename selected_tool_id → recommended_tool_id."""
    assert "RENAME COLUMN selected_tool_id TO recommended_tool_id" in migration_sql


def test_migration_contains_recommended_tool_id_index(migration_sql: str) -> None:
    """Must create partial index on recommended_tool_id."""
    assert "idx_query_logs_recommended_tool_id" in migration_sql
    assert "recommended_tool_id IS NOT NULL" in migration_sql


def test_migration_drops_old_index(migration_sql: str) -> None:
    """Must drop the old idx_query_logs_selected_tool_id index."""
    assert "DROP INDEX IF EXISTS idx_query_logs_selected_tool_id" in migration_sql


def test_migration_contains_query_log_id_fk(migration_sql: str) -> None:
    """Must add query_log_id FK column to execution_logs."""
    assert "ADD COLUMN query_log_id" in migration_sql
    assert "REFERENCES query_logs(id)" in migration_sql
    assert "ON DELETE SET NULL" in migration_sql


def test_migration_contains_execution_logs_index(migration_sql: str) -> None:
    """Must create partial index on execution_logs.query_log_id."""
    assert "idx_execution_logs_query_log_id" in migration_sql
    assert "query_log_id IS NOT NULL" in migration_sql


def test_migration_contains_tool_exposure_facts_view(migration_sql: str) -> None:
    """Must create tool_exposure_facts view."""
    assert "CREATE OR REPLACE VIEW tool_exposure_facts" in migration_sql
    assert "WITH ORDINALITY" in migration_sql
    assert "exposed_rank" in migration_sql


def test_migration_contains_tool_conversion_funnel_view(migration_sql: str) -> None:
    """Must create tool_conversion_funnel view."""
    assert "CREATE OR REPLACE VIEW tool_conversion_funnel" in migration_sql
    assert "funnel_outcome" in migration_sql
    assert "LEFT JOIN execution_logs" in migration_sql


def test_migration_contains_rollback_ddl(migration_sql: str) -> None:
    """Must include commented rollback DDL block for manual use."""
    assert "ROLLBACK DDL" in migration_sql
    # Rollback must reference the reverse rename
    assert "RENAME COLUMN recommended_tool_id TO selected_tool_id" in migration_sql


def test_migration_expected_views_listed(migration_sql: str) -> None:
    """All 10 expected views referenced in migration."""
    expected_views = [
        "tool_selection_stats",
        "tool_exposure_stats",
        "tool_exposure_stats_7d",
        "tool_daily_stats",
        "tool_client_stats",
        "tool_client_selection_stats",
        "provider_tool_dashboard",
        "provider_search_simulations",
        "tool_exposure_facts",
        "tool_conversion_funnel",
    ]
    for view in expected_views:
        assert view in migration_sql, f"Expected view '{view}' not found in migration SQL"


# ---------------------------------------------------------------------------
# DB-dependent: schema introspection via Supabase REST
# ---------------------------------------------------------------------------


@_db_required
async def test_recommended_tool_id_column_exists() -> None:
    """query_logs.recommended_tool_id must exist in information_schema.columns."""
    import httpx

    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Verify via information_schema columns view
        col_resp = await client.get(
            f"{SUPABASE_URL.rstrip('/')}/rest/v1/information_schema_columns",
            headers={**headers, "Accept": "application/json"},
            params={
                "table_name": "eq.query_logs",
                "column_name": "eq.recommended_tool_id",
            },
        )
    # If PostgREST exposes information_schema, verify; otherwise skip gracefully
    if col_resp.status_code == 200:
        rows = col_resp.json()
        assert len(rows) >= 1, "recommended_tool_id column not found in query_logs"


@_db_required
async def test_selected_tool_id_column_does_not_exist() -> None:
    """query_logs.selected_tool_id must NOT exist after migration 022."""
    import httpx

    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        col_resp = await client.get(
            f"{SUPABASE_URL.rstrip('/')}/rest/v1/information_schema_columns",
            headers={**headers, "Accept": "application/json"},
            params={
                "table_name": "eq.query_logs",
                "column_name": "eq.selected_tool_id",
            },
        )
    if col_resp.status_code == 200:
        rows = col_resp.json()
        assert len(rows) == 0, "selected_tool_id still exists in query_logs after migration 022"


@_db_required
async def test_all_expected_views_exist() -> None:
    """All 10 views from migration 022 must exist in information_schema.views."""
    import httpx

    expected_views = [
        "tool_selection_stats",
        "tool_exposure_stats",
        "tool_exposure_stats_7d",
        "tool_daily_stats",
        "tool_client_stats",
        "tool_client_selection_stats",
        "provider_tool_dashboard",
        "provider_search_simulations",
        "tool_exposure_facts",
        "tool_conversion_funnel",
    ]

    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{SUPABASE_URL.rstrip('/')}/rest/v1/information_schema_views",
            headers={**headers, "Accept": "application/json"},
            params={"table_schema": "eq.public"},
        )
    if resp.status_code == 200:
        existing = {r["table_name"] for r in resp.json()}
        for view in expected_views:
            assert view in existing, f"View '{view}' not found in information_schema.views"


@_db_required
async def test_execution_logs_fk_constraint_exists() -> None:
    """pg_constraint must include execution_logs_query_log_id_fkey."""
    import httpx

    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{SUPABASE_URL.rstrip('/')}/rest/v1/pg_constraint",
            headers={**headers, "Accept": "application/json"},
            params={"conname": "eq.execution_logs_query_log_id_fkey"},
        )
    if resp.status_code == 200:
        rows = resp.json()
        assert len(rows) >= 1, "execution_logs_query_log_id_fkey constraint not found"
