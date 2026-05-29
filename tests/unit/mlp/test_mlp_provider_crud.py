"""Unit tests for SupabaseClient provider CRUD methods and register handler auth validation."""

from __future__ import annotations

import importlib
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from service.adapters.supabase_client import SupabaseClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, body: list | dict) -> httpx.Response:
    """Build a fake httpx.Response with the given status and JSON body."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = body
    response.raise_for_status = MagicMock()
    return response


def _make_client(response: httpx.Response) -> SupabaseClient:
    """Build a SupabaseClient whose internal httpx client returns the given response."""
    client = SupabaseClient(url="https://example.supabase.co", service_key="test-key")
    mock_httpx = AsyncMock()
    mock_httpx.request = AsyncMock(return_value=response)
    client._client = mock_httpx
    return client


# ---------------------------------------------------------------------------
# fetch_provider_by_user_id
# ---------------------------------------------------------------------------


class TestFetchProviderByUserId:
    async def test_returns_first_row_when_found(self) -> None:
        row = {"id": "prov-1", "user_id": "user-abc", "display_name": "Acme"}
        client = _make_client(_make_response(200, [row]))
        result = await client.fetch_provider_by_user_id("user-abc")
        assert result == row

    async def test_returns_none_when_empty(self) -> None:
        client = _make_client(_make_response(200, []))
        result = await client.fetch_provider_by_user_id("user-abc")
        assert result is None

    async def test_returns_none_on_exception(self) -> None:
        client = SupabaseClient(url="https://example.supabase.co", service_key="test-key")
        mock_httpx = AsyncMock()
        mock_httpx.request = AsyncMock(side_effect=Exception("network error"))
        client._client = mock_httpx
        result = await client.fetch_provider_by_user_id("user-abc")
        assert result is None


# ---------------------------------------------------------------------------
# create_provider
# ---------------------------------------------------------------------------


class TestCreateProvider:
    async def test_returns_created_row(self) -> None:
        row = {"id": "prov-new", "user_id": "user-xyz", "display_name": "Beta Corp"}
        client = _make_client(_make_response(201, [row]))
        result = await client.create_provider("user-xyz", display_name="Beta Corp")
        assert result == row

    async def test_returns_dict_directly_when_not_list(self) -> None:
        row = {"id": "prov-new", "user_id": "user-xyz", "display_name": None}
        client = _make_client(_make_response(201, row))
        result = await client.create_provider("user-xyz")
        assert result == row

    async def test_passes_display_name_in_payload(self) -> None:
        row = {"id": "prov-1", "user_id": "u1", "display_name": "My Co"}
        client = _make_client(_make_response(201, [row]))
        mock_httpx = client._client
        await client.create_provider("u1", display_name="My Co")
        call_kwargs = mock_httpx.request.call_args
        assert call_kwargs.kwargs["json"]["display_name"] == "My Co"
        assert call_kwargs.kwargs["json"]["user_id"] == "u1"


# ---------------------------------------------------------------------------
# update_provider
# ---------------------------------------------------------------------------


class TestUpdateProvider:
    async def test_returns_updated_row(self) -> None:
        row = {"id": "prov-1", "display_name": "Updated"}
        client = _make_client(_make_response(200, [row]))
        result = await client.update_provider("prov-1", {"display_name": "Updated"})
        assert result == row

    async def test_returns_none_when_empty_response(self) -> None:
        client = _make_client(_make_response(200, []))
        result = await client.update_provider("prov-1", {"display_name": "x"})
        assert result is None

    async def test_returns_none_on_exception(self) -> None:
        client = SupabaseClient(url="https://example.supabase.co", service_key="test-key")
        mock_httpx = AsyncMock()
        mock_httpx.request = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock(status_code=404)
            )
        )
        client._client = mock_httpx
        result = await client.update_provider("missing", {"display_name": "x"})
        assert result is None


# ---------------------------------------------------------------------------
# fetch_provider_dashboard_tools
# ---------------------------------------------------------------------------


class TestFetchProviderDashboardTools:
    async def test_returns_list_of_tool_rows(self) -> None:
        rows = [
            {"tool_id": "srv::t1", "tool_name": "t1", "server_id": "srv"},
            {"tool_id": "srv::t2", "tool_name": "t2", "server_id": "srv"},
        ]
        client = _make_client(_make_response(200, rows))
        result = await client.fetch_provider_dashboard_tools("prov-1", "user-abc")
        assert result == rows

    async def test_returns_empty_list_on_exception(self) -> None:
        client = SupabaseClient(url="https://example.supabase.co", service_key="test-key")
        mock_httpx = AsyncMock()
        mock_httpx.request = AsyncMock(side_effect=Exception("error"))
        client._client = mock_httpx
        result = await client.fetch_provider_dashboard_tools("prov-1", "user-abc")
        assert result == []


# ---------------------------------------------------------------------------
# fetch_tool_daily_stats
# ---------------------------------------------------------------------------


class TestFetchToolDailyStats:
    async def test_returns_stat_rows(self) -> None:
        rows = [{"day": "2026-04-14", "call_count": 10}, {"day": "2026-04-13", "call_count": 8}]
        client = _make_client(_make_response(200, rows))
        result = await client.fetch_tool_daily_stats("srv::tool")
        assert result == rows

    async def test_returns_empty_list_on_exception(self) -> None:
        client = SupabaseClient(url="https://example.supabase.co", service_key="test-key")
        mock_httpx = AsyncMock()
        mock_httpx.request = AsyncMock(side_effect=Exception("error"))
        client._client = mock_httpx
        result = await client.fetch_tool_daily_stats("srv::tool")
        assert result == []


# ---------------------------------------------------------------------------
# fetch_tool_client_stats
# ---------------------------------------------------------------------------


class TestFetchToolClientStats:
    async def test_returns_client_stat_rows(self) -> None:
        rows = [{"client_id": "claude", "call_count": 5}]
        client = _make_client(_make_response(200, rows))
        result = await client.fetch_tool_client_stats("srv::tool")
        assert result == rows

    async def test_returns_empty_list_on_exception(self) -> None:
        client = SupabaseClient(url="https://example.supabase.co", service_key="test-key")
        mock_httpx = AsyncMock()
        mock_httpx.request = AsyncMock(side_effect=Exception("error"))
        client._client = mock_httpx
        result = await client.fetch_tool_client_stats("srv::tool")
        assert result == []


# ---------------------------------------------------------------------------
# fetch_tool_client_selection_stats
# ---------------------------------------------------------------------------


class TestFetchToolClientSelectionStats:
    async def test_returns_selection_stat_rows(self) -> None:
        rows = [{"client_id": "claude", "selection_count": 3, "win_rate": 0.6}]
        client = _make_client(_make_response(200, rows))
        result = await client.fetch_tool_client_selection_stats("srv::tool")
        assert result == rows

    async def test_returns_empty_list_on_exception(self) -> None:
        client = SupabaseClient(url="https://example.supabase.co", service_key="test-key")
        mock_httpx = AsyncMock()
        mock_httpx.request = AsyncMock(side_effect=Exception("error"))
        client._client = mock_httpx
        result = await client.fetch_tool_client_selection_stats("srv::tool")
        assert result == []


# ---------------------------------------------------------------------------
# Register handler auth validation
# ---------------------------------------------------------------------------


def _build_register_event(
    body: dict,
    token: str | None = "valid-token",
) -> dict:
    headers: dict = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return {"body": json.dumps(body), "headers": headers}


def _minimal_body(**overrides: object) -> dict:
    base = {
        "server_id": "my-server",
        "name": "My Server",
        "url": "https://example.com/mcp",
        "tools": [{"tool_name": "do_thing", "description": "Does a thing"}],
    }
    base.update(overrides)
    return base


class TestRegisterHandlerAuthValidation:
    """Tests for owner_user_id mismatch rejection added to _async_handler."""

    def _fresh_handler(self):
        """Return _async_handler from a freshly (re)loaded module to avoid cross-test pollution."""
        mod_name = "service.lambdas.register.handler"
        sys.modules.pop(mod_name, None)
        mod = importlib.import_module(mod_name)
        return mod._async_handler, mod

    def _make_auth_client_mock(self, user_id: str) -> MagicMock:
        mock = MagicMock()
        mock.get_user = AsyncMock(return_value={"id": user_id})
        return mock

    async def test_matching_owner_user_id_is_accepted(self) -> None:
        """owner_user_id matching the token user proceeds past auth check."""
        body = _minimal_body(owner_user_id="user-123")
        event = _build_register_event(body, token="tok")
        handler, mod = self._fresh_handler()

        auth_mock = self._make_auth_client_mock("user-123")
        provider_service_mock = MagicMock()
        provider_service_mock.get_or_create_provider = AsyncMock(return_value={"id": "prov-1"})
        register_result = {
            "server_id": "srv",
            "tools_count": 1,
            "message": "Server registered. Indexing in progress.",
        }
        with (
            patch.object(mod, "SupabaseAuthClient", return_value=auth_mock),
            patch.object(mod, "ProviderService", return_value=provider_service_mock),
            patch.object(
                mod.RegisterService, "register", new=AsyncMock(return_value=register_result)
            ),
        ):
            response = await handler(event, None)

        # Should not be 403 — reaches server/tool logic (201 or 500 from mocked inserts)
        assert response["statusCode"] != 403

    async def test_mismatched_owner_user_id_returns_403(self) -> None:
        """owner_user_id that differs from token user is rejected with 403."""
        body = _minimal_body(owner_user_id="attacker-999")
        event = _build_register_event(body, token="tok")
        handler, mod = self._fresh_handler()
        auth_mock = self._make_auth_client_mock("real-user-123")

        with patch.object(mod, "SupabaseAuthClient", return_value=auth_mock):
            response = await handler(event, None)

        assert response["statusCode"] == 403
        assert "owner_user_id" in json.loads(response["body"])["error"]

    async def test_no_owner_user_id_in_payload_is_allowed(self) -> None:
        """Requests without owner_user_id in payload bypass the ownership check."""
        body = _minimal_body()  # no owner_user_id key
        event = _build_register_event(body, token="tok")
        handler, mod = self._fresh_handler()
        auth_mock = self._make_auth_client_mock("user-123")
        provider_service_mock = MagicMock()
        provider_service_mock.get_or_create_provider = AsyncMock(return_value={"id": "prov-1"})
        register_result = {
            "server_id": "srv",
            "tools_count": 1,
            "message": "Server registered. Indexing in progress.",
        }

        with (
            patch.object(mod, "SupabaseAuthClient", return_value=auth_mock),
            patch.object(mod, "ProviderService", return_value=provider_service_mock),
            patch.object(
                mod.RegisterService, "register", new=AsyncMock(return_value=register_result)
            ),
        ):
            response = await handler(event, None)

        assert response["statusCode"] != 403
