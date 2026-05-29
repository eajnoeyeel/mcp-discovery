"""Static checks for atomic mcp_auth_requirements replacement RPC."""

from pathlib import Path

MIGRATION_PATH = Path("service/supabase/migrations/035_replace_mcp_auth_requirements_rpc.sql")


def test_migration_defines_atomic_replace_rpc() -> None:
    migration_sql = MIGRATION_PATH.read_text()

    assert "CREATE OR REPLACE FUNCTION public.replace_mcp_auth_requirements" in migration_sql
    assert "RETURNS JSONB" in migration_sql
    assert "SECURITY DEFINER" in migration_sql
    assert "SET search_path = public" in migration_sql
    assert "DELETE FROM public.mcp_auth_requirements" in migration_sql
    assert "INSERT INTO public.mcp_auth_requirements" in migration_sql
    assert "jsonb_array_elements(v_requirements)" in migration_sql
    assert "all auth requirement rows must match p_server_id" in migration_sql
    assert "GRANT EXECUTE ON FUNCTION public.replace_mcp_auth_requirements" in migration_sql
