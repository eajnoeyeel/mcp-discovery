"""Tests verifying the schema audit fixes applied in migrations 017 and 018.

Covers:
  - Migration 017 SQL contract tests (Sections A-F)
  - Migration 018 SQL contract tests (server auth secret ref columns)
  - C3: phantom fetch_tool_analytics removal from SupabaseClient
  - C1: register handler _auth_row output shape (ref columns present)
  - C1: execute handler _fetch_server_auth ref-column resolution path
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Migration file paths
# ---------------------------------------------------------------------------
MIGRATION_017 = Path("service/supabase/migrations/017_schema_audit_fixes.sql")
MIGRATION_018 = Path("service/supabase/migrations/018_server_auth_secret_refs.sql")

# ---------------------------------------------------------------------------
# Migration 017 — file existence
# ---------------------------------------------------------------------------


def test_migration_017_file_exists() -> None:
    assert MIGRATION_017.exists(), "017_schema_audit_fixes.sql not found"


def test_migration_018_file_exists() -> None:
    assert MIGRATION_018.exists(), "018_server_auth_secret_refs.sql not found"


# ---------------------------------------------------------------------------
# Section A — C2: refresh_token DROP NOT NULL
# ---------------------------------------------------------------------------


def test_migration_017_section_a_drops_refresh_token_not_null() -> None:
    sql = MIGRATION_017.read_text()
    assert "ALTER COLUMN refresh_token DROP NOT NULL" in sql, (
        "Section A: expected 'ALTER COLUMN refresh_token DROP NOT NULL' in migration 017"
    )


def test_migration_017_section_a_targets_mcp_oauth_sessions() -> None:
    sql = MIGRATION_017.read_text()
    # The DROP NOT NULL must target mcp_oauth_sessions, not some other table
    idx_table = sql.index("mcp_oauth_sessions")
    idx_alter = sql.index("ALTER COLUMN refresh_token DROP NOT NULL")
    assert idx_table < idx_alter, (
        "Section A: mcp_oauth_sessions ALTER TABLE should precede DROP NOT NULL"
    )


# ---------------------------------------------------------------------------
# Section B — H1: updated_at column + trigger on mcp_tools
# ---------------------------------------------------------------------------


def test_migration_017_section_b_adds_updated_at_column_to_mcp_tools() -> None:
    sql = MIGRATION_017.read_text()
    assert "updated_at" in sql, "Section B: expected 'updated_at' column addition in migration 017"
    # The column must be added to mcp_tools specifically
    assert "ALTER TABLE mcp_tools" in sql, (
        "Section B: expected 'ALTER TABLE mcp_tools' in migration 017"
    )


def test_migration_017_section_b_creates_set_mcp_tools_updated_at_trigger() -> None:
    sql = MIGRATION_017.read_text()
    assert "set_mcp_tools_updated_at" in sql, (
        "Section B: expected trigger 'set_mcp_tools_updated_at' in migration 017"
    )


def test_migration_017_section_b_trigger_calls_update_updated_at_function() -> None:
    sql = MIGRATION_017.read_text()
    assert "EXECUTE FUNCTION update_updated_at()" in sql, (
        "Section B: trigger must call the shared update_updated_at() function"
    )


# ---------------------------------------------------------------------------
# Section C — H2: GRANT SELECT on 10 views / MVs
# ---------------------------------------------------------------------------

_GRANT_TARGETS = [
    "tool_operability_view",
    "provider_tool_dashboard",
    "tool_operational_stats",
    "tool_operational_stats_7d",
    "tool_selection_stats",
    "tool_exposure_stats",
    "tool_exposure_stats_7d",
    "tool_daily_stats",
    "tool_client_stats",
    "tool_client_selection_stats",
]


@pytest.mark.parametrize("target", _GRANT_TARGETS)
def test_migration_017_section_c_grants_select_on_view(target: str) -> None:
    sql = MIGRATION_017.read_text()
    assert f"GRANT SELECT ON {target}" in sql, (
        f"Section C: missing 'GRANT SELECT ON {target}' in migration 017"
    )


def test_migration_017_section_c_grants_to_anon_and_authenticated() -> None:
    sql = MIGRATION_017.read_text()
    # Each grant should cover both roles; verify the pattern appears at least once
    assert "TO anon, authenticated" in sql, (
        "Section C: grants must target both 'anon' and 'authenticated' roles"
    )


# ---------------------------------------------------------------------------
# Section D — H3: partial index on query_logs(selected_tool_id) [017]
#              and rename to idx_query_logs_recommended_tool_id [022]
# ---------------------------------------------------------------------------

MIGRATION_022 = Path("service/supabase/migrations/022_metric_semantic_redesign.sql")


def test_migration_017_section_d_creates_partial_index_on_query_logs() -> None:
    sql = MIGRATION_017.read_text()
    assert "idx_query_logs_selected_tool_id" in sql, (
        "Section D: expected index 'idx_query_logs_selected_tool_id' in migration 017"
    )


def test_migration_017_section_d_index_is_partial_excluding_nulls() -> None:
    sql = MIGRATION_017.read_text()
    assert "WHERE selected_tool_id IS NOT NULL" in sql, (
        "Section D: partial index must exclude NULLs with WHERE clause"
    )


def test_migration_017_section_d_index_uses_if_not_exists() -> None:
    sql = MIGRATION_017.read_text()
    # Idempotency requirement
    idx = sql.index("idx_query_logs_selected_tool_id")
    preceding = sql[:idx]
    assert "CREATE INDEX IF NOT EXISTS" in preceding, (
        "Section D: index creation must use IF NOT EXISTS for idempotency"
    )


def test_migration_022_renames_index_to_recommended_tool_id() -> None:
    """Migration 022 must drop old index and create idx_query_logs_recommended_tool_id."""
    sql = MIGRATION_022.read_text()
    assert "DROP INDEX IF EXISTS idx_query_logs_selected_tool_id" in sql, (
        "Migration 022: must drop idx_query_logs_selected_tool_id"
    )
    assert "idx_query_logs_recommended_tool_id" in sql, (
        "Migration 022: must create idx_query_logs_recommended_tool_id"
    )


# ---------------------------------------------------------------------------
# Section E — H4: secret_backend CHECK constraint convergence
# ---------------------------------------------------------------------------


def test_migration_017_section_e_drops_existing_secret_backend_constraint() -> None:
    sql = MIGRATION_017.read_text()
    assert "DROP CONSTRAINT IF EXISTS mcp_oauth_sessions_secret_backend_check" in sql, (
        "Section E: must drop old constraint before re-creating"
    )


def test_migration_017_section_e_adds_named_secret_backend_check_constraint() -> None:
    sql = MIGRATION_017.read_text()
    assert "ADD CONSTRAINT mcp_oauth_sessions_secret_backend_check" in sql, (
        "Section E: must add named constraint 'mcp_oauth_sessions_secret_backend_check'"
    )


def test_migration_017_section_e_constraint_uses_not_valid_for_zero_downtime() -> None:
    sql = MIGRATION_017.read_text()
    assert "NOT VALID" in sql, (
        "Section E: constraint must use NOT VALID for zero-downtime large-table safety"
    )


def test_migration_017_section_e_constraint_is_subsequently_validated() -> None:
    sql = MIGRATION_017.read_text()
    assert "VALIDATE CONSTRAINT mcp_oauth_sessions_secret_backend_check" in sql, (
        "Section E: constraint must be validated after creation"
    )


# ---------------------------------------------------------------------------
# Section F — Dead view cleanup
# ---------------------------------------------------------------------------


def test_migration_017_section_f_drops_provider_dashboard_snapshot() -> None:
    sql = MIGRATION_017.read_text()
    assert "DROP VIEW IF EXISTS provider_dashboard_snapshot" in sql, (
        "Section F: must drop dead view 'provider_dashboard_snapshot'"
    )


# ---------------------------------------------------------------------------
# Migration 018 — C1: bearer_token_ref / api_key_ref / secret_backend columns
# ---------------------------------------------------------------------------


def test_migration_018_adds_bearer_token_ref_column_to_mcp_server_auth() -> None:
    sql = MIGRATION_018.read_text()
    assert "bearer_token_ref" in sql, (
        "Migration 018: expected 'bearer_token_ref' column in migration 018"
    )


def test_migration_018_adds_api_key_ref_column_to_mcp_server_auth() -> None:
    sql = MIGRATION_018.read_text()
    assert "api_key_ref" in sql, "Migration 018: expected 'api_key_ref' column in migration 018"


def test_migration_018_adds_secret_backend_column_to_mcp_server_auth() -> None:
    sql = MIGRATION_018.read_text()
    assert "secret_backend" in sql, (
        "Migration 018: expected 'secret_backend' column in migration 018"
    )


def test_migration_018_secret_backend_has_check_constraint() -> None:
    sql = MIGRATION_018.read_text()
    assert "CHECK (secret_backend IN ('aws_secrets_manager'))" in sql, (
        "Migration 018: secret_backend must have a CHECK constraint restricting allowed values"
    )


def test_migration_018_targets_mcp_server_auth_table() -> None:
    sql = MIGRATION_018.read_text()
    assert "ALTER TABLE mcp_server_auth" in sql, (
        "Migration 018: must operate on 'mcp_server_auth' table"
    )


def test_migration_018_uses_if_not_exists_for_idempotency() -> None:
    sql = MIGRATION_018.read_text()
    assert "ADD COLUMN IF NOT EXISTS" in sql, (
        "Migration 018: column additions must use IF NOT EXISTS for idempotency"
    )


# ---------------------------------------------------------------------------
# C3 — Phantom fetch_tool_analytics removal from SupabaseClient
# ---------------------------------------------------------------------------


def test_supabase_client_does_not_have_fetch_tool_analytics_method() -> None:
    from service.adapters.supabase_client import SupabaseClient

    assert not hasattr(SupabaseClient, "fetch_tool_analytics"), (
        "C3: phantom method 'fetch_tool_analytics' must not exist on SupabaseClient"
    )


# ---------------------------------------------------------------------------
# Helpers shared by handler tests
# ---------------------------------------------------------------------------


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.aws_request_id = "req-test"
    ctx.get_remaining_time_in_millis.return_value = 14000
    return ctx


# ---------------------------------------------------------------------------
# C1 — Register service → adapter: server auth row output shape (ADR-0015)
# Post-ADR-0015, the handler `_auth_row` helper is deleted and the row shape
# contract lives in `SupabaseClient.upsert_server_auth`, with fault tolerance
# for secret provisioning in `RegisterService.register`. Tests migrated to
# assert the same schema-audit F1 contract at the new boundaries.
# ---------------------------------------------------------------------------


class TestAuthRowOutputShape:
    """upsert_server_auth row shape must include bearer_token_ref + api_key_ref (migrations 017/018)."""  # noqa: E501

    def _make_payload(self, **overrides: Any) -> dict:
        base = {
            "server_id": "srv",
            "name": "Demo",
            "description": "A helpful MCP server",
            "url": "https://demo.example",
            "tags": [],
            "tools": [{"tool_name": "lookup", "description": "Search indexed data"}],
        }
        base.update(overrides)
        return base

    async def test_auth_row_contains_bearer_token_ref_key(self) -> None:
        from service.services.register_service import RegisterService

        db = AsyncMock()
        events = AsyncMock()
        secret_store = AsyncMock()
        secret_store.provision_server_auth_secret_refs = AsyncMock(
            return_value=MagicMock(bearer_token_ref="mlp/srv/bearer", api_key_ref=None)
        )
        service = RegisterService(db=db, events=events, oauth_secret_store=secret_store)

        await service.register(
            self._make_payload(execution_auth={"auth_type": "bearer", "bearer_token": "tok"}),
            provider_id="p-1",
        )

        db.upsert_server_auth.assert_awaited_once()
        forwarded_refs = db.upsert_server_auth.await_args.kwargs.get("secret_refs")
        assert forwarded_refs is not None, "secret_refs must be forwarded to adapter"
        assert hasattr(forwarded_refs, "bearer_token_ref")

    async def test_auth_row_contains_api_key_ref_key(self) -> None:
        from service.services.register_service import RegisterService

        db = AsyncMock()
        events = AsyncMock()
        secret_store = AsyncMock()
        secret_store.provision_server_auth_secret_refs = AsyncMock(
            return_value=MagicMock(bearer_token_ref=None, api_key_ref="mlp/srv/api_key")
        )
        service = RegisterService(db=db, events=events, oauth_secret_store=secret_store)

        await service.register(
            self._make_payload(
                execution_auth={
                    "auth_type": "api_key_header",
                    "api_key_header_name": "X-Key",
                    "api_key": "secret",
                }
            ),
            provider_id="p-1",
        )

        db.upsert_server_auth.assert_awaited_once()
        forwarded_refs = db.upsert_server_auth.await_args.kwargs.get("secret_refs")
        assert forwarded_refs is not None
        assert hasattr(forwarded_refs, "api_key_ref")

    async def test_auth_row_populates_ref_values_from_secret_store(self) -> None:
        from service.services.register_service import RegisterService

        db = AsyncMock()
        events = AsyncMock()
        expected_refs = MagicMock(bearer_token_ref="mlp/srv/bearer_token", api_key_ref=None)
        secret_store = AsyncMock()
        secret_store.provision_server_auth_secret_refs = AsyncMock(return_value=expected_refs)
        service = RegisterService(db=db, events=events, oauth_secret_store=secret_store)

        await service.register(
            self._make_payload(execution_auth={"auth_type": "bearer", "bearer_token": "tok"}),
            provider_id="p-1",
        )

        db.upsert_server_auth.assert_awaited_once()
        forwarded_refs = db.upsert_server_auth.await_args.kwargs.get("secret_refs")
        assert forwarded_refs is expected_refs

    async def test_auth_row_ref_columns_are_none_when_secrets_manager_unavailable(
        self,
    ) -> None:
        """Fallback: Secrets Manager raises → secret_refs forwarded as None (graceful degradation)."""  # noqa: E501
        from service.services.register_service import RegisterService

        db = AsyncMock()
        events = AsyncMock()
        secret_store = AsyncMock()
        secret_store.provision_server_auth_secret_refs = AsyncMock(
            side_effect=Exception("No AWS credentials")
        )
        service = RegisterService(db=db, events=events, oauth_secret_store=secret_store)

        # Must not raise — service should log and fall back to plaintext-only storage
        await service.register(
            self._make_payload(execution_auth={"auth_type": "bearer", "bearer_token": "tok"}),
            provider_id="p-1",
        )

        db.upsert_server_auth.assert_awaited_once()
        forwarded_refs = db.upsert_server_auth.await_args.kwargs.get("secret_refs")
        assert forwarded_refs is None, (
            "secret_refs must be None when Secrets Manager is unavailable"
        )

    async def test_auth_row_ref_columns_are_none_when_no_credentials_present(self) -> None:
        """When auth_type is 'none', upsert_server_auth must not be called (no row to write)."""
        from service.services.register_service import RegisterService

        db = AsyncMock()
        events = AsyncMock()
        secret_store = AsyncMock()
        secret_store.provision_server_auth_secret_refs = AsyncMock()
        service = RegisterService(db=db, events=events, oauth_secret_store=secret_store)

        await service.register(
            self._make_payload(execution_auth={"auth_type": "none"}),
            provider_id="p-1",
        )

        db.upsert_server_auth.assert_not_awaited()
        secret_store.provision_server_auth_secret_refs.assert_not_awaited()


# ---------------------------------------------------------------------------
# C1 — Execute handler: _fetch_server_auth ref-column resolution
# ---------------------------------------------------------------------------


class TestFetchServerAuthRefColumns:
    """_fetch_server_auth must resolve secrets from Secrets Manager when _ref columns present."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        fake_settings = MagicMock()
        fake_settings.openai_api_key = "fake"
        ps = [patch("mcp_discovery.config.Settings", return_value=fake_settings)]
        for p in ps:
            p.start()

        fake_execute_service = AsyncMock()
        with patch(
            "service.services.execute_service.ExecuteService",
            return_value=fake_execute_service,
        ):
            sys.modules.pop("service.lambdas.execute.handler", None)
            sys.modules.pop("service.adapters.execution", None)
            import service.adapters.execution as adapters_mod
            import service.lambdas.execute.handler as handler_mod  # noqa: F401

        self.m = adapters_mod
        adapters_mod._SUPABASE_URL = "http://fake"
        adapters_mod._SUPABASE_KEY = "k"

        yield

        for p in ps:
            p.stop()
        sys.modules.pop("service.lambdas.execute.handler", None)
        sys.modules.pop("service.adapters.execution", None)

    def _make_fake_http_client(self, row: dict):
        """Build a fake httpx.AsyncClient that returns a single-row Supabase response."""
        import httpx

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def get(self, url, headers):
                request = httpx.Request("GET", url, headers=headers)
                return httpx.Response(200, request=request, json=[row])

        return _FakeClient

    async def test_fetch_server_auth_calls_resolver_when_ref_columns_present(self) -> None:
        """When the row has bearer_token_ref, the Secrets Manager resolver is invoked."""
        row = {
            "auth_type": "bearer",
            "bearer_token": None,
            "api_key_header_name": None,
            "api_key": None,
            "headers": {},
            "bearer_token_ref": "mlp/srv/bearer_token",
            "api_key_ref": None,
        }

        fake_client_cls = self._make_fake_http_client(row)
        mock_secret_store = AsyncMock()
        mock_secret_store.resolve_server_auth_secrets = AsyncMock(
            return_value=("resolved-bearer-token", None)
        )

        # AWSSecretsManagerOAuthStore is a local import inside _fetch_server_auth;
        # patch at the source module so the local import receives the mock.
        with (
            patch("service.adapters.execution.httpx.AsyncClient", fake_client_cls),
            patch(
                "service.adapters.aws_secrets_manager.AWSSecretsManagerOAuthStore",
                return_value=mock_secret_store,
            ),
        ):
            auth = await self.m._fetch_server_auth("srv")

        mock_secret_store.resolve_server_auth_secrets.assert_awaited_once()
        assert auth.bearer_token == "resolved-bearer-token"

    async def test_fetch_server_auth_returns_empty_config_when_no_rows(self) -> None:
        """When Supabase returns an empty list, auth defaults to auth_type='none'."""
        import httpx

        class _EmptyClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def get(self, url, headers):
                request = httpx.Request("GET", url, headers=headers)
                return httpx.Response(200, request=request, json=[])

        with patch("service.adapters.execution.httpx.AsyncClient", _EmptyClient):
            auth = await self.m._fetch_server_auth("srv")

        assert auth.auth_type == "none"
        assert auth.bearer_token is None
