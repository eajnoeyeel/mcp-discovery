"""Unit tests for service.adapters.supabase_client.SupabaseClient — uncovered methods."""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock

import httpx
import pytest

from service.shared.content_hash import compute_content_hash

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_client(url: str = "http://fake", key: str = "key"):
    from service.adapters.supabase_client import SupabaseClient

    client = SupabaseClient(url=url, service_key=key)
    return client


def _mock_http(response_data, *, status_code: int = 200, raise_for_status=None):
    """Return a mock httpx.AsyncClient that responds with response_data."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    if raise_for_status is not None:
        mock_resp.raise_for_status = MagicMock(side_effect=raise_for_status)
    else:
        mock_resp.raise_for_status = MagicMock()
    mock_http = MagicMock()
    mock_http.request = AsyncMock(return_value=mock_resp)
    return mock_http


# ---------------------------------------------------------------------------
# Constructor / _get_client
# ---------------------------------------------------------------------------


class TestSupabaseClientInit:
    def test_strips_trailing_slash_from_url(self):
        from service.adapters.supabase_client import SupabaseClient

        client = SupabaseClient(url="http://fake/", service_key="k")
        assert client._url == "http://fake"

    def test_sets_authorization_header(self):
        from service.adapters.supabase_client import SupabaseClient

        client = SupabaseClient(url="http://fake", service_key="my-key")
        assert client._headers["Authorization"] == "Bearer my-key"
        assert client._headers["apikey"] == "my-key"

    def test_get_client_creates_async_client_on_first_call(self):
        from service.adapters.supabase_client import SupabaseClient

        client = SupabaseClient(url="http://fake", service_key="k")
        assert client._client is None
        http = client._get_client()
        assert http is not None
        assert client._client is http

    def test_get_client_returns_same_instance_on_subsequent_calls(self):
        from service.adapters.supabase_client import SupabaseClient

        client = SupabaseClient(url="http://fake", service_key="k")
        first = client._get_client()
        second = client._get_client()
        assert first is second


# ---------------------------------------------------------------------------
# fetch_provider_by_user_id
# ---------------------------------------------------------------------------


class TestFetchProviderByUserId:
    async def test_returns_first_row_when_found(self):
        client = _make_client()
        client._client = _mock_http([{"user_id": "u1", "display_name": "Alice"}])

        result = await client.fetch_provider_by_user_id("u1")

        assert result == {"user_id": "u1", "display_name": "Alice"}

    async def test_returns_none_when_no_rows(self):
        client = _make_client()
        client._client = _mock_http([])

        result = await client.fetch_provider_by_user_id("u-missing")

        assert result is None

    async def test_returns_none_on_http_error(self):
        client = _make_client()
        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=Exception("network error"))
        client._client = mock_http

        result = await client.fetch_provider_by_user_id("u1")

        assert result is None

    async def test_sends_eq_filter_param(self):
        client = _make_client()
        mock_http = _mock_http([{"user_id": "u1"}])
        client._client = mock_http

        await client.fetch_provider_by_user_id("u1")

        params = mock_http.request.call_args.kwargs["params"]
        assert params["user_id"] == "eq.u1"
        assert params["limit"] == 1


# ---------------------------------------------------------------------------
# create_provider
# ---------------------------------------------------------------------------


class TestCreateProvider:
    async def test_returns_created_provider_row(self):
        client = _make_client()
        created = {"user_id": "u2", "display_name": "Bob"}
        client._client = _mock_http([created])

        result = await client.create_provider("u2", display_name="Bob")

        assert result == created

    async def test_returns_single_dict_when_response_is_dict(self):
        client = _make_client()
        created = {"user_id": "u3", "display_name": None}
        client._client = _mock_http(created)  # non-list response

        result = await client.create_provider("u3")

        assert result == created

    async def test_posts_to_providers_endpoint(self):
        client = _make_client()
        mock_http = _mock_http([{"user_id": "u4"}])
        client._client = mock_http

        await client.create_provider("u4")

        url = mock_http.request.call_args.args[1]
        assert "providers" in url

    async def test_sends_prefer_return_representation_header(self):
        client = _make_client()
        mock_http = _mock_http([{"user_id": "u5"}])
        client._client = mock_http

        await client.create_provider("u5")

        headers = mock_http.request.call_args.kwargs["headers"]
        assert "return=representation" in headers.get("Prefer", "")


# ---------------------------------------------------------------------------
# update_provider
# ---------------------------------------------------------------------------


class TestUpdateProvider:
    async def test_returns_updated_row_on_success(self):
        client = _make_client()
        client._client = _mock_http([{"id": "p1", "display_name": "Updated"}])

        result = await client.update_provider("p1", {"display_name": "Updated"})

        assert result == {"id": "p1", "display_name": "Updated"}

    async def test_returns_none_on_http_error(self):
        client = _make_client()
        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=Exception("patch failed"))
        client._client = mock_http

        result = await client.update_provider("p1", {"display_name": "X"})

        assert result is None

    async def test_returns_none_when_no_rows_returned(self):
        client = _make_client()
        client._client = _mock_http([])

        result = await client.update_provider("p1", {"display_name": "X"})

        assert result is None

    async def test_sends_id_filter_param(self):
        client = _make_client()
        mock_http = _mock_http([{"id": "p1"}])
        client._client = mock_http

        await client.update_provider("p1", {"display_name": "Y"})

        params = mock_http.request.call_args.kwargs["params"]
        assert params["id"] == "eq.p1"


# ---------------------------------------------------------------------------
# fetch_provider_dashboard_tools
# ---------------------------------------------------------------------------


class TestFetchProviderDashboardTools:
    async def test_returns_tool_rows_on_success(self):
        client = _make_client()
        tools = [{"tool_id": "srv::t1", "tool_name": "t1"}]
        client._client = _mock_http(tools)

        result = await client.fetch_provider_dashboard_tools("p1", "u1")

        assert result == tools

    async def test_returns_empty_list_on_exception(self):
        client = _make_client()
        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=Exception("view missing"))
        client._client = mock_http

        result = await client.fetch_provider_dashboard_tools("p1", "u1")

        assert result == []

    async def test_filters_by_owner_user_id(self):
        client = _make_client()
        mock_http = _mock_http([])
        client._client = mock_http

        await client.fetch_provider_dashboard_tools("p1", "user-xyz")

        params = mock_http.request.call_args.kwargs["params"]
        assert params["owner_user_id"] == "eq.user-xyz"


# ---------------------------------------------------------------------------
# fetch_tool_daily_stats
# ---------------------------------------------------------------------------


class TestFetchToolDailyStats:
    async def test_returns_daily_stats_rows(self):
        client = _make_client()
        rows = [{"day": "2024-01-01", "call_count": 5}]
        client._client = _mock_http(rows)

        result = await client.fetch_tool_daily_stats("srv::tool")

        assert result == rows

    async def test_returns_empty_list_on_exception(self):
        client = _make_client()
        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=Exception("table missing"))
        client._client = mock_http

        result = await client.fetch_tool_daily_stats("srv::tool")

        assert result == []

    async def test_requests_ordered_by_day_desc(self):
        client = _make_client()
        mock_http = _mock_http([])
        client._client = mock_http

        await client.fetch_tool_daily_stats("srv::tool")

        params = mock_http.request.call_args.kwargs["params"]
        assert params["order"] == "day.desc"
        assert params["limit"] == 30


# ---------------------------------------------------------------------------
# fetch_tool_client_stats
# ---------------------------------------------------------------------------


class TestFetchToolClientStats:
    async def test_returns_client_stats(self):
        client = _make_client()
        rows = [{"client_id": "c1", "call_count": 10}]
        client._client = _mock_http(rows)

        result = await client.fetch_tool_client_stats("srv::tool")

        assert result == rows

    async def test_returns_empty_list_on_exception(self):
        client = _make_client()
        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=Exception("error"))
        client._client = mock_http

        result = await client.fetch_tool_client_stats("srv::tool")

        assert result == []

    async def test_filters_by_tool_id(self):
        client = _make_client()
        mock_http = _mock_http([])
        client._client = mock_http

        await client.fetch_tool_client_stats("srv::my-tool")

        params = mock_http.request.call_args.kwargs["params"]
        assert params["tool_id"] == "eq.srv::my-tool"


# ---------------------------------------------------------------------------
# fetch_tool_client_selection_stats
# ---------------------------------------------------------------------------


class TestFetchToolClientSelectionStats:
    async def test_returns_selection_stats(self):
        client = _make_client()
        rows = [{"client_id": "c1", "times_selected": 3}]
        client._client = _mock_http(rows)

        result = await client.fetch_tool_client_selection_stats("srv::tool")

        assert result == rows

    async def test_returns_empty_list_on_exception(self):
        client = _make_client()
        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=Exception("error"))
        client._client = mock_http

        result = await client.fetch_tool_client_selection_stats("srv::tool")

        assert result == []


# ---------------------------------------------------------------------------
# fetch_platform_stats
# ---------------------------------------------------------------------------


class TestFetchPlatformStats:
    async def test_returns_stats_dict_from_rpc(self):
        client = _make_client()
        client._client = _mock_http({"servers": 5, "tools": 20})

        result = await client.fetch_platform_stats()

        assert result == {"servers": 5, "tools": 20}

    async def test_returns_first_element_when_response_is_list(self):
        client = _make_client()
        client._client = _mock_http([{"servers": 3, "tools": 10}])

        result = await client.fetch_platform_stats()

        assert result == {"servers": 3, "tools": 10}

    async def test_returns_empty_dict_when_list_is_empty(self):
        client = _make_client()
        client._client = _mock_http([])

        result = await client.fetch_platform_stats()

        assert result == {}

    async def test_posts_to_rpc_endpoint(self):
        client = _make_client()
        mock_http = _mock_http({"servers": 1})
        client._client = mock_http

        await client.fetch_platform_stats()

        url = mock_http.request.call_args.args[1]
        assert "rpc/get_platform_stats" in url


# ---------------------------------------------------------------------------
# fetch_server_tool_counts
# ---------------------------------------------------------------------------


class TestFetchServerToolCounts:
    async def test_returns_server_id_to_count_mapping(self):
        client = _make_client()
        rows = [
            {"server_id": "srv-1", "tool_count": 5},
            {"server_id": "srv-2", "tool_count": 3},
        ]
        client._client = _mock_http(rows)

        result = await client.fetch_server_tool_counts()

        assert result == {"srv-1": 5, "srv-2": 3}

    async def test_returns_empty_dict_when_no_rows(self):
        client = _make_client()
        client._client = _mock_http([])

        result = await client.fetch_server_tool_counts()

        assert result == {}


# ---------------------------------------------------------------------------
# fetch_servers
# ---------------------------------------------------------------------------


class TestFetchServers:
    async def test_returns_servers_with_tool_counts_merged(self):
        client = _make_client()

        server_rows = [{"server_id": "srv-1", "name": "Alpha", "tags": []}]
        counts = [{"server_id": "srv-1", "tool_count": 7}]

        call_count = 0

        async def mock_request(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            if "server_tool_counts" in url:
                mock_resp.json.return_value = counts
            else:
                mock_resp.json.return_value = server_rows
            return mock_resp

        mock_http = MagicMock()
        mock_http.request = mock_request
        client._client = mock_http

        result = await client.fetch_servers(limit=10, offset=0)

        assert len(result) == 1
        assert result[0]["server_id"] == "srv-1"
        assert result[0]["tool_count"] == 7

    async def test_strips_internal_owner_tags_from_server_rows(self):
        client = _make_client()

        server_rows = [
            {"server_id": "srv-1", "name": "Alpha", "tags": ["__owner_user_id:u1", "public"]}
        ]
        counts = [{"server_id": "srv-1", "tool_count": 0}]

        async def mock_request(method, url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            if "server_tool_counts" in url:
                mock_resp.json.return_value = counts
            else:
                mock_resp.json.return_value = server_rows
            return mock_resp

        client._client = MagicMock()
        client._client.request = mock_request

        result = await client.fetch_servers()

        assert "__owner_user_id:u1" not in result[0]["tags"]
        assert "public" in result[0]["tags"]

    async def test_tool_count_defaults_to_zero_for_missing_server(self):
        client = _make_client()

        server_rows = [{"server_id": "srv-no-count", "name": "NoCount", "tags": []}]
        counts: list = []

        async def mock_request(method, url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            if "server_tool_counts" in url:
                mock_resp.json.return_value = counts
            else:
                mock_resp.json.return_value = server_rows
            return mock_resp

        client._client = MagicMock()
        client._client.request = mock_request

        result = await client.fetch_servers()

        assert result[0]["tool_count"] == 0


# ---------------------------------------------------------------------------
# fetch_server
# ---------------------------------------------------------------------------


class TestFetchServer:
    async def test_returns_server_row_when_found(self):
        client = _make_client()
        client._client = _mock_http([{"server_id": "srv-1", "name": "Alpha", "tags": []}])

        result = await client.fetch_server("srv-1")

        assert result is not None
        assert result["server_id"] == "srv-1"

    async def test_returns_none_when_not_found(self):
        client = _make_client()
        client._client = _mock_http([])

        result = await client.fetch_server("srv-missing")

        assert result is None

    async def test_normalizes_owner_user_id_from_tags(self):
        client = _make_client()
        client._client = _mock_http(
            [{"server_id": "srv-1", "name": "Alpha", "tags": ["__owner_user_id:u1"]}]
        )

        result = await client.fetch_server("srv-1")

        assert result is not None
        assert result["owner_user_id"] == "u1"
        assert "__owner_user_id:u1" not in result["tags"]


# ---------------------------------------------------------------------------
# fetch_server_tools
# ---------------------------------------------------------------------------


class TestFetchServerTools:
    async def test_returns_tools_for_server(self):
        client = _make_client()
        tools = [{"tool_id": "srv::t1", "tool_name": "t1"}]
        client._client = _mock_http(tools)

        result = await client.fetch_server_tools("srv")

        assert result == tools

    async def test_filters_by_server_id(self):
        client = _make_client()
        mock_http = _mock_http([])
        client._client = mock_http

        await client.fetch_server_tools("my-server")

        params = mock_http.request.call_args.kwargs["params"]
        assert params["server_id"] == "eq.my-server"

    async def test_selects_upstream_metadata_fields(self):
        client = _make_client()
        mock_http = _mock_http([])
        client._client = mock_http

        await client.fetch_server_tools("srv")

        select_columns = mock_http.request.call_args.kwargs["params"]["select"]
        assert "upstream_description" in select_columns
        assert "parameter_notes" in select_columns
        assert "usage_examples" in select_columns
        assert "usage_hints" in select_columns
        assert "metadata_origin" in select_columns
        assert "metadata_last_fetched_at" in select_columns
        assert "override_updated_at" in select_columns

    async def test_retries_without_metadata_override_columns_when_column_missing(self):
        client = _make_client()
        first = httpx.HTTPStatusError(
            "error",
            request=MagicMock(),
            response=MagicMock(
                spec=httpx.Response,
                json=MagicMock(
                    return_value={
                        "code": "PGRST204",
                        "message": (
                            "Could not find the 'upstream_description' column of 'mcp_tools' "
                            "in the schema cache"
                        ),
                    }
                ),
            ),
        )
        fallback_rows = [{"tool_id": "srv::t1", "tool_name": "t1"}]
        fallback_response = MagicMock()
        fallback_response.json.return_value = fallback_rows
        fallback_response.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.request = AsyncMock(side_effect=[first, fallback_response])

        result = await client.fetch_server_tools("srv")

        assert result == fallback_rows
        first_select = client._client.request.await_args_list[0].kwargs["params"]["select"]
        second_select = client._client.request.await_args_list[1].kwargs["params"]["select"]
        assert "upstream_description" in first_select
        assert "upstream_description" not in second_select
        assert "tool_id" in second_select
        assert "description" in second_select


# ---------------------------------------------------------------------------
# fetch_tool
# ---------------------------------------------------------------------------


class TestFetchTool:
    async def test_returns_tool_when_found(self):
        client = _make_client()
        tool = {"tool_id": "srv::t1", "tool_name": "t1"}
        client._client = _mock_http([tool])

        result = await client.fetch_tool("srv::t1")

        assert result == tool

    async def test_returns_override_and_upstream_metadata(self):
        client = _make_client()
        tool = {
            "tool_id": "srv::lookup",
            "server_id": "srv",
            "tool_name": "lookup",
            "description": "Published copy",
            "upstream_description": "Upstream copy",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
            "parameter_notes": "Use q for exact lookup",
            "usage_examples": ['{"q": "docs"}'],
            "usage_hints": ["Best for exact identifiers"],
            "metadata_origin": "discovered",
            "metadata_last_fetched_at": "2026-04-15T00:00:00Z",
            "override_updated_at": "2026-04-15T01:00:00Z",
        }
        client._client = _mock_http([tool])

        result = await client.fetch_tool("srv::lookup")

        assert result is not None
        assert result["description"] == "Published copy"
        assert result["upstream_description"] == "Upstream copy"
        assert result["parameter_notes"] == "Use q for exact lookup"
        assert result["usage_examples"] == ['{"q": "docs"}']
        assert result["usage_hints"] == ["Best for exact identifiers"]
        assert result["metadata_origin"] == "discovered"
        assert result["metadata_last_fetched_at"] == "2026-04-15T00:00:00Z"
        assert result["override_updated_at"] == "2026-04-15T01:00:00Z"

    async def test_fetch_tool_returns_parameter_metadata_fields(self):
        client = _make_client()
        tool = {
            "tool_id": "srv::lookup",
            "server_id": "srv",
            "tool_name": "lookup",
            "upstream_parameter_metadata": [
                {"path": "query", "description": "Upstream query"},
            ],
            "published_parameter_metadata": [
                {"path": "query", "description": "Published query"},
            ],
        }
        client._client = _mock_http([tool])

        result = await client.fetch_tool("srv::lookup")

        assert result is not None
        assert result["upstream_parameter_metadata"] == [
            {"path": "query", "description": "Upstream query"},
        ]
        assert result["published_parameter_metadata"] == [
            {"path": "query", "description": "Published query"},
        ]

    async def test_returns_none_when_not_found(self):
        client = _make_client()
        client._client = _mock_http([])

        result = await client.fetch_tool("srv::missing")

        assert result is None

    async def test_filters_by_tool_id(self):
        client = _make_client()
        mock_http = _mock_http([])
        client._client = mock_http

        await client.fetch_tool("srv::lookup")

        params = mock_http.request.call_args.kwargs["params"]
        assert params["tool_id"] == "eq.srv::lookup"

    async def test_selects_upstream_metadata_fields(self):
        client = _make_client()
        mock_http = _mock_http([])
        client._client = mock_http

        await client.fetch_tool("srv::lookup")

        select_columns = mock_http.request.call_args.kwargs["params"]["select"]
        assert "upstream_description" in select_columns
        assert "parameter_notes" in select_columns
        assert "usage_examples" in select_columns
        assert "usage_hints" in select_columns
        assert "metadata_origin" in select_columns
        assert "metadata_last_fetched_at" in select_columns
        assert "override_updated_at" in select_columns

    async def test_fetch_tool_selects_parameter_metadata_fields(self):
        client = _make_client()
        mock_http = _mock_http([])
        client._client = mock_http

        await client.fetch_tool("srv::lookup")

        select_columns = mock_http.request.call_args.kwargs["params"]["select"]
        assert "upstream_parameter_metadata" in select_columns
        assert "published_parameter_metadata" in select_columns

    async def test_retries_without_metadata_override_columns_when_column_missing(self):
        client = _make_client()
        first = httpx.HTTPStatusError(
            "error",
            request=MagicMock(),
            response=MagicMock(
                spec=httpx.Response,
                json=MagicMock(
                    return_value={
                        "code": "PGRST204",
                        "message": (
                            "Could not find the 'upstream_description' column of 'mcp_tools' "
                            "in the schema cache"
                        ),
                    }
                ),
            ),
        )
        fallback_rows = [{"tool_id": "srv::lookup", "tool_name": "lookup"}]
        fallback_response = MagicMock()
        fallback_response.json.return_value = fallback_rows
        fallback_response.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.request = AsyncMock(side_effect=[first, fallback_response])

        result = await client.fetch_tool("srv::lookup")

        assert result == fallback_rows[0]
        first_select = client._client.request.await_args_list[0].kwargs["params"]["select"]
        second_select = client._client.request.await_args_list[1].kwargs["params"]["select"]
        assert "upstream_description" in first_select
        assert "upstream_description" not in second_select
        assert "tool_id" in second_select
        assert "description" in second_select


# ---------------------------------------------------------------------------
# insert_tools
# ---------------------------------------------------------------------------


class TestMarkToolsEventFailed:
    """US-C4.5 adapter method: flip pending tools for a server to event_failed."""

    async def test_patches_mcp_tools_with_event_failed_status(self):
        client = _make_client()
        mock_http = _mock_http([{}])
        client._client = mock_http

        await client.mark_tools_event_failed("srv-1")

        method = mock_http.request.call_args.args[0]
        url = mock_http.request.call_args.args[1]
        payload = mock_http.request.call_args.kwargs["json"]
        params = mock_http.request.call_args.kwargs["params"]

        assert method == "PATCH"
        assert "/rest/v1/mcp_tools" in url
        assert payload == {"index_status": "event_failed"}
        assert params["server_id"] == "eq.srv-1"
        assert params["index_status"] == "eq.pending"


class TestInsertToolsUpsertSemantics:
    """US-C2: merge-duplicates Prefer header for idempotent re-registration."""

    async def test_insert_tools_uses_merge_duplicates_prefer_header(self):
        client = _make_client()
        mock_http = _mock_http([{}])
        client._client = mock_http

        await client.insert_tools(
            "srv",
            [{"tool_name": "lookup", "description": "docs"}],
        )

        headers = mock_http.request.call_args.kwargs["headers"]
        prefer = headers.get("Prefer", "")
        assert "resolution=merge-duplicates" in prefer, (
            f"Expected merge-duplicates in Prefer header, got: {prefer!r}"
        )
        assert "return=representation" in prefer

    async def test_insert_tools_computes_content_hash_from_raw_input(self):
        """Adapter's build_tool_insert_rows is single authority for content_hash."""
        client = _make_client()
        mock_http = _mock_http([{}])
        client._client = mock_http

        await client.insert_tools(
            "srv",
            [{"tool_name": "lookup", "description": "Search docs"}],
        )

        posted = mock_http.request.call_args.kwargs["json"]
        assert len(posted) == 1
        assert "content_hash" in posted[0]
        assert posted[0]["content_hash"] == compute_content_hash("lookup", "Search docs")

    async def test_insert_tools_composes_tool_id_from_server_id_and_name(self):
        client = _make_client()
        mock_http = _mock_http([{}])
        client._client = mock_http

        await client.insert_tools(
            "my-srv",
            [{"tool_name": "my-tool", "description": "d"}],
        )

        posted = mock_http.request.call_args.kwargs["json"]
        assert posted[0]["tool_id"] == "my-srv::my-tool"


class TestInsertToolsTask2:
    async def test_insert_tools_uses_normalized_upstream_parameter_metadata_only(self):
        client = _make_client()
        mock_http = _mock_http([{}])
        client._client = mock_http

        await client.insert_tools(
            "srv",
            [
                {
                    "tool_name": "lookup",
                    "description": "Lookup docs",
                    "upstream_parameter_metadata": [
                        {"path": "query", "name": "query", "type": "string"}
                    ],
                    "parameter_metadata": [
                        {"path": "unsanitized", "name": "unsanitized", "type": "string"}
                    ],
                }
            ],
        )

        posted_data = mock_http.request.call_args.kwargs["json"]
        assert posted_data[0]["upstream_parameter_metadata"] == [
            {"path": "query", "name": "query", "type": "string"}
        ]
        assert "parameter_metadata" not in posted_data[0]

    async def test_insert_tools_normalizes_frontend_first_submit_parameter_metadata(self):
        client = _make_client()
        mock_http = _mock_http([{}])
        client._client = mock_http

        await client.insert_tools(
            "srv",
            [
                {
                    "tool_name": "lookup",
                    "description": "Find the best matching document for a query.",
                    "upstream_description": "Lookup docs",
                    "input_schema": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                    "parameter_metadata": [
                        {
                            "path": "q",
                            "name": "q",
                            "type": "string",
                            "required": True,
                            "description": "Search query",
                            "enum_values": [],
                            "default_value": None,
                            "items_type": None,
                            "object_properties_count": None,
                        }
                    ],
                    "published_parameter_metadata": [
                        {
                            "path": "q",
                            "description": "Exact search string to send upstream.",
                        }
                    ],
                    "parameter_notes": "Use q for exact lookup requests.",
                    "usage_examples": ['{"q": "docs"}', '{"q": "api"}'],
                    "usage_hints": [
                        "Best for exact identifiers",
                        "Great for provider docs",
                    ],
                }
            ],
        )

        posted_data = mock_http.request.call_args.kwargs["json"]
        assert posted_data == [
            {
                "tool_id": "srv::lookup",
                "server_id": "srv",
                "tool_name": "lookup",
                "description": "Find the best matching document for a query.",
                "input_schema": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
                "upstream_description": "Lookup docs",
                "upstream_parameter_metadata": [
                    {
                        "path": "q",
                        "name": "q",
                        "type": "string",
                        "required": True,
                        "description": "Search query",
                        "enum_values": [],
                        "default_value": None,
                        "items_type": None,
                        "object_properties_count": None,
                    }
                ],
                "published_parameter_metadata": [
                    {
                        "path": "q",
                        "description": "Exact search string to send upstream.",
                    }
                ],
                "parameter_notes": "Use q for exact lookup requests.",
                "usage_examples": ['{"q": "docs"}', '{"q": "api"}'],
                "usage_hints": [
                    "Best for exact identifiers",
                    "Great for provider docs",
                ],
                "index_status": "pending",
                "content_hash": ANY,
            }
        ]
        assert "parameter_metadata" not in posted_data[0]

    async def test_insert_tools_preserves_registration_metadata_fields(self):
        client = _make_client()
        mock_http = _mock_http([{}])
        client._client = mock_http

        await client.insert_tools(
            "srv",
            [
                {
                    "tool_name": "lookup",
                    "description": "Published lookup copy",
                    "input_schema": {"type": "object"},
                    "upstream_description": "Original upstream lookup copy",
                    "upstream_parameter_metadata": [
                        {"path": "query", "name": "query", "type": "string"}
                    ],
                    "published_parameter_metadata": [
                        {"path": "query", "description": "Lookup query"}
                    ],
                    "parameter_notes": "Use exact IDs when possible.",
                    "usage_examples": ['{"query": "docs"}'],
                    "usage_hints": ["Supports prefix matches."],
                    "metadata_origin": "mixed",
                    "metadata_last_fetched_at": "2026-04-16T00:00:00Z",
                    "override_updated_at": "2026-04-16T01:00:00Z",
                }
            ],
        )

        assert mock_http.request.call_args.kwargs["json"] == [
            {
                "tool_id": "srv::lookup",
                "server_id": "srv",
                "tool_name": "lookup",
                "description": "Published lookup copy",
                "input_schema": {"type": "object"},
                "upstream_description": "Original upstream lookup copy",
                "upstream_parameter_metadata": [
                    {"path": "query", "name": "query", "type": "string"}
                ],
                "published_parameter_metadata": [{"path": "query", "description": "Lookup query"}],
                "parameter_notes": "Use exact IDs when possible.",
                "usage_examples": ['{"query": "docs"}'],
                "usage_hints": ["Supports prefix matches."],
                "metadata_origin": "mixed",
                "metadata_last_fetched_at": "2026-04-16T00:00:00Z",
                "override_updated_at": "2026-04-16T01:00:00Z",
                "index_status": "pending",
                "content_hash": compute_content_hash("lookup", "Published lookup copy"),
            }
        ]


# ---------------------------------------------------------------------------
# fetch_tool_public_stats
# ---------------------------------------------------------------------------


class TestFetchToolPublicStats:
    async def test_returns_allowlisted_fields_only(self):
        client = _make_client()
        client._client = _mock_http(
            [{"call_count": 100, "success_rate": 0.99, "avg_latency_ms": 42.0}]
        )

        result = await client.fetch_tool_public_stats("srv::tool")

        assert result == {"call_count": 100, "success_rate": 0.99, "avg_latency_ms": 42.0}

    async def test_returns_none_when_no_rows(self):
        client = _make_client()
        client._client = _mock_http([])

        result = await client.fetch_tool_public_stats("srv::tool")

        assert result is None

    async def test_returns_none_on_exception(self):
        client = _make_client()
        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=Exception("view missing"))
        client._client = mock_http

        result = await client.fetch_tool_public_stats("srv::tool")

        assert result is None

    async def test_returns_none_call_count_when_db_value_is_null(self):
        client = _make_client()
        client._client = _mock_http(
            [{"call_count": None, "success_rate": None, "avg_latency_ms": None}]
        )

        result = await client.fetch_tool_public_stats("srv::tool")

        # row.get("call_count", 0) returns None when key exists with value None;
        # the default only applies when the key is absent entirely.
        assert result["call_count"] is None
        assert result["success_rate"] is None
        assert result["avg_latency_ms"] is None


# ---------------------------------------------------------------------------
# fetch_tool_simulations
# ---------------------------------------------------------------------------


class TestFetchToolSimulations:
    async def test_returns_simulation_rows(self):
        client = _make_client()
        rows = [{"recommended_tool_id": "srv::tool", "query": "search"}]
        client._client = _mock_http(rows)

        result = await client.fetch_tool_simulations("srv::tool")

        assert result == rows

    async def test_returns_empty_list_on_exception(self):
        client = _make_client()
        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=Exception("table missing"))
        client._client = mock_http

        result = await client.fetch_tool_simulations("srv::tool")

        assert result == []

    async def test_filters_by_recommended_tool_id(self):
        client = _make_client()
        mock_http = _mock_http([])
        client._client = mock_http

        await client.fetch_tool_simulations("srv::my-tool")

        params = mock_http.request.call_args.kwargs["params"]
        assert params["recommended_tool_id"] == "eq.srv::my-tool"
        assert "selected_tool_id" not in params


# ---------------------------------------------------------------------------
# fetch_owned_servers
# ---------------------------------------------------------------------------


class TestFetchOwnedServers:
    async def test_returns_servers_for_owner(self):
        client = _make_client()
        rows = [{"server_id": "srv-1", "name": "Alpha", "tags": [], "owner_user_id": "u1"}]
        client._client = _mock_http(rows)

        result = await client.fetch_owned_servers("u1")

        assert len(result) == 1
        assert result[0]["server_id"] == "srv-1"

    async def test_normalizes_owner_user_id_in_returned_rows(self):
        client = _make_client()
        rows = [{"server_id": "srv-1", "name": "Alpha", "tags": ["__owner_user_id:u1"]}]
        client._client = _mock_http(rows)

        result = await client.fetch_owned_servers("u1")

        assert result[0]["owner_user_id"] == "u1"
        assert "__owner_user_id:u1" not in result[0]["tags"]


# ---------------------------------------------------------------------------
# fetch_owned_tool_detail
# ---------------------------------------------------------------------------


class TestFetchOwnedToolDetail:
    async def test_returns_none_when_tool_not_found(self):
        client = _make_client()
        client.fetch_tool = AsyncMock(return_value=None)

        result = await client.fetch_owned_tool_detail("u1", "srv::missing")

        assert result is None

    async def test_returns_none_when_server_not_found(self):
        client = _make_client()
        client.fetch_tool = AsyncMock(return_value={"tool_id": "srv::t", "server_id": "srv"})
        client.fetch_server = AsyncMock(return_value=None)

        result = await client.fetch_owned_tool_detail("u1", "srv::t")

        assert result is None

    async def test_returns_none_when_server_owner_mismatch(self):
        client = _make_client()
        client.fetch_tool = AsyncMock(return_value={"tool_id": "srv::t", "server_id": "srv"})
        client.fetch_server = AsyncMock(
            return_value={"server_id": "srv", "name": "X", "owner_user_id": "other-user"}
        )

        result = await client.fetch_owned_tool_detail("u1", "srv::t")

        assert result is None

    async def test_returns_tool_with_server_fields_when_owner_matches(self):
        client = _make_client()
        client.fetch_tool = AsyncMock(
            return_value={"tool_id": "srv::t", "server_id": "srv", "tool_name": "t"}
        )
        client.fetch_server = AsyncMock(
            return_value={
                "server_id": "srv",
                "name": "MyServer",
                "url": "http://srv",
                "owner_user_id": "u1",
            }
        )

        result = await client.fetch_owned_tool_detail("u1", "srv::t")

        assert result is not None
        assert result["tool_id"] == "srv::t"
        assert result["server_name"] == "MyServer"
        assert result["server_url"] == "http://srv"


# ---------------------------------------------------------------------------
# fetch_owned_server_tools
# ---------------------------------------------------------------------------


class TestFetchOwnedServerTools:
    async def test_returns_empty_list_when_server_not_found(self):
        client = _make_client()
        client.fetch_server = AsyncMock(return_value=None)

        result = await client.fetch_owned_server_tools("u1", "srv-missing")

        assert result == []

    async def test_returns_empty_list_when_server_owner_mismatch(self):
        client = _make_client()
        client.fetch_server = AsyncMock(
            return_value={"server_id": "srv", "name": "X", "owner_user_id": "other"}
        )

        result = await client.fetch_owned_server_tools("u1", "srv")

        assert result == []

    async def test_returns_tools_with_server_name_attached(self):
        client = _make_client()
        client.fetch_server = AsyncMock(
            return_value={"server_id": "srv", "name": "MyServer", "owner_user_id": "u1"}
        )
        client.fetch_server_tools = AsyncMock(
            return_value=[{"tool_id": "srv::t1", "tool_name": "t1"}]
        )

        result = await client.fetch_owned_server_tools("u1", "srv")

        assert len(result) == 1
        assert result[0]["server_name"] == "MyServer"

    async def test_excludes_tool_when_exclude_tool_id_provided(self):
        client = _make_client()
        client.fetch_server = AsyncMock(
            return_value={"server_id": "srv", "name": "MyServer", "owner_user_id": "u1"}
        )
        client.fetch_server_tools = AsyncMock(
            return_value=[
                {"tool_id": "srv::t1", "tool_name": "t1"},
                {"tool_id": "srv::t2", "tool_name": "t2"},
            ]
        )

        result = await client.fetch_owned_server_tools("u1", "srv", exclude_tool_id="srv::t1")

        tool_ids = [t["tool_id"] for t in result]
        assert "srv::t1" not in tool_ids
        assert "srv::t2" in tool_ids


# ---------------------------------------------------------------------------
# _normalize_server_row (static method)
# ---------------------------------------------------------------------------


class TestNormalizeServerRow:
    def test_extracts_owner_user_id_from_column(self):
        from service.adapters.supabase_client import SupabaseClient

        row = {"server_id": "srv", "owner_user_id": "u1", "tags": []}
        result = SupabaseClient._normalize_server_row(row)

        assert result["owner_user_id"] == "u1"

    def test_extracts_owner_user_id_from_tags_when_column_missing(self):
        from service.adapters.supabase_client import SupabaseClient

        row = {"server_id": "srv", "tags": ["__owner_user_id:u2", "public"]}
        result = SupabaseClient._normalize_server_row(row)

        assert result["owner_user_id"] == "u2"

    def test_strips_internal_owner_tag_from_tags(self):
        from service.adapters.supabase_client import SupabaseClient

        row = {"server_id": "srv", "tags": ["__owner_user_id:u3", "public"]}
        result = SupabaseClient._normalize_server_row(row)

        assert "__owner_user_id:u3" not in result["tags"]
        assert "public" in result["tags"]

    def test_does_not_mutate_original_row(self):
        from service.adapters.supabase_client import SupabaseClient

        original_tags = ["public"]
        row = {"server_id": "srv", "tags": original_tags}
        SupabaseClient._normalize_server_row(row)

        assert row["tags"] is original_tags


# ---------------------------------------------------------------------------
# _is_missing_owner_column_error (static method)
# ---------------------------------------------------------------------------


class TestIsMissingOwnerColumnError:
    def _make_http_error(self, payload: dict) -> httpx.HTTPStatusError:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.json.return_value = payload
        return httpx.HTTPStatusError("error", request=MagicMock(), response=mock_resp)

    def test_returns_true_for_42703_code_with_owner_user_id_message(self):
        from service.adapters.supabase_client import SupabaseClient

        exc = self._make_http_error({"code": "42703", "message": "column owner_user_id missing"})
        assert SupabaseClient._is_missing_owner_column_error(exc) is True

    def test_returns_true_for_pgrst204_code(self):
        from service.adapters.supabase_client import SupabaseClient

        exc = self._make_http_error({"code": "PGRST204", "message": "owner_user_id not found"})
        assert SupabaseClient._is_missing_owner_column_error(exc) is True

    def test_returns_false_for_unrelated_error_code(self):
        from service.adapters.supabase_client import SupabaseClient

        exc = self._make_http_error({"code": "42P01", "message": "table not found"})
        assert SupabaseClient._is_missing_owner_column_error(exc) is False

    def test_returns_false_when_json_parse_fails(self):
        from service.adapters.supabase_client import SupabaseClient

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.json.side_effect = ValueError("not json")
        exc = httpx.HTTPStatusError("error", request=MagicMock(), response=mock_resp)

        assert SupabaseClient._is_missing_owner_column_error(exc) is False


# ---------------------------------------------------------------------------
# fetch_tool_exposure_count  (migration 022)
# ---------------------------------------------------------------------------


class TestFetchToolExposureCount:
    def _mock_http_with_content_range(self, total: int | None, rows: list | None = None):
        mock_resp = MagicMock()
        mock_resp.json.return_value = rows or []
        mock_resp.raise_for_status = MagicMock()
        if total is not None:
            mock_resp.headers = {"Content-Range": f"0-0/{total}"}
        else:
            mock_resp.headers = {}
        mock_http = MagicMock()
        mock_http.request = AsyncMock(return_value=mock_resp)
        return mock_http

    async def test_parses_content_range_total(self):
        client = _make_client()
        client._client = self._mock_http_with_content_range(total=42)

        result = await client.fetch_tool_exposure_count("srv::tool")

        assert result == 42

    async def test_falls_back_to_row_count_when_content_range_missing(self):
        client = _make_client()
        client._client = self._mock_http_with_content_range(total=None, rows=[{}, {}, {}])

        result = await client.fetch_tool_exposure_count("srv::tool")

        assert result == 3

    async def test_returns_zero_on_exception(self):
        client = _make_client()
        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=Exception("view missing"))
        client._client = mock_http

        result = await client.fetch_tool_exposure_count("srv::tool")

        assert result == 0

    async def test_sends_count_exact_headers(self):
        client = _make_client()
        mock_http = self._mock_http_with_content_range(total=0)
        client._client = mock_http

        await client.fetch_tool_exposure_count("srv::tool")

        headers = mock_http.request.call_args.kwargs["headers"]
        assert headers["Prefer"] == "count=exact"
        assert headers["Range"] == "0-0"


# ---------------------------------------------------------------------------
# fetch_tool_conversion_stats  (migration 022)
# ---------------------------------------------------------------------------


class TestFetchToolConversionStats:
    async def test_counts_converted_outcomes(self):
        """F7 audit fix: rows dedupe per query_log_id; converted wins over diverged."""
        client = _make_client()
        rows = [
            {"query_log_id": 1, "funnel_outcome": "converted"},
            {"query_log_id": 2, "funnel_outcome": "converted"},
            {"query_log_id": 3, "funnel_outcome": "diverged"},
            {"query_log_id": 4, "funnel_outcome": "no_execution"},
        ]
        client._client = _mock_http(rows)

        result = await client.fetch_tool_conversion_stats("srv::tool")

        assert result == {"recommendation_count": 4, "converted_count": 2}

    async def test_zero_recommendations_produces_zeros(self):
        client = _make_client()
        client._client = _mock_http([])

        result = await client.fetch_tool_conversion_stats("srv::tool")

        assert result == {"recommendation_count": 0, "converted_count": 0}

    async def test_returns_zeros_on_exception(self):
        client = _make_client()
        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=Exception("view missing"))
        client._client = mock_http

        result = await client.fetch_tool_conversion_stats("srv::tool")

        assert result == {"recommendation_count": 0, "converted_count": 0}

    async def test_filters_by_recommended_tool_id(self):
        client = _make_client()
        mock_http = _mock_http([])
        client._client = mock_http

        await client.fetch_tool_conversion_stats("srv::my-tool")

        params = mock_http.request.call_args.kwargs["params"]
        assert params["recommended_tool_id"] == "eq.srv::my-tool"


# ---------------------------------------------------------------------------
# upsert_server — schema-compat fallback (US-C1: owner_user_id)
# ---------------------------------------------------------------------------


def _pgrst_missing_column_error(column: str) -> httpx.HTTPStatusError:
    """Construct an HTTPStatusError matching PostgREST's missing-column shape."""
    return httpx.HTTPStatusError(
        "error",
        request=MagicMock(),
        response=MagicMock(
            spec=httpx.Response,
            json=MagicMock(
                return_value={
                    "code": "PGRST204",
                    "message": (
                        f"Could not find the '{column}' column of 'mcp_servers' in the schema cache"
                    ),
                }
            ),
        ),
    )


class TestUpsertServerSchemaCompat:
    async def test_success_path_no_fallback(self):
        client = _make_client()
        success_response = MagicMock()
        success_response.json.return_value = [{"server_id": "srv", "name": "Alpha"}]
        success_response.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=success_response)

        result = await client.upsert_server(
            {"server_id": "srv", "name": "Alpha", "owner_user_id": "u1"}
        )

        assert result == [{"server_id": "srv", "name": "Alpha"}]
        assert client._client.request.await_count == 1

    async def test_drops_owner_user_id_on_missing_column(self):
        client = _make_client()
        fallback_response = MagicMock()
        fallback_response.json.return_value = [{"server_id": "srv", "tags": ["__owner_user_id:u1"]}]
        fallback_response.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.request = AsyncMock(
            side_effect=[_pgrst_missing_column_error("owner_user_id"), fallback_response]
        )

        await client.upsert_server(
            {"server_id": "srv", "name": "Alpha", "owner_user_id": "u1", "tags": []}
        )

        assert client._client.request.await_count == 2
        retry_payload = client._client.request.await_args_list[1].kwargs["json"]
        assert "owner_user_id" not in retry_payload
        assert "__owner_user_id:u1" in retry_payload["tags"]

    async def test_logs_warning_on_fallback(self):
        from loguru import logger

        captured: list[str] = []
        sink_id = logger.add(captured.append, level="WARNING", format="{message}")
        try:
            client = _make_client()
            fallback_response = MagicMock()
            fallback_response.json.return_value = [{"server_id": "srv"}]
            fallback_response.raise_for_status = MagicMock()
            client._client = MagicMock()
            client._client.request = AsyncMock(
                side_effect=[_pgrst_missing_column_error("owner_user_id"), fallback_response]
            )

            await client.upsert_server(
                {"server_id": "srv", "name": "Alpha", "owner_user_id": "u1", "tags": []}
            )
        finally:
            logger.remove(sink_id)

        assert any("schema-compat fallback" in msg for msg in captured), (
            f"Expected schema-compat fallback warning, got: {captured}"
        )
        assert any("owner_user_id" in msg for msg in captured)

    async def test_propagates_unrelated_pgrst_errors(self):
        client = _make_client()
        unrelated_err = httpx.HTTPStatusError(
            "bad request",
            request=MagicMock(),
            response=MagicMock(
                spec=httpx.Response,
                json=MagicMock(return_value={"code": "42703", "message": "unrelated issue"}),
            ),
        )
        client._client = MagicMock()
        client._client.request = AsyncMock(side_effect=unrelated_err)

        import pytest

        with pytest.raises(httpx.HTTPStatusError):
            await client.upsert_server({"server_id": "srv", "name": "Alpha"})


# ---------------------------------------------------------------------------
# upsert_server_auth
# ---------------------------------------------------------------------------


class TestUpsertServerAuth:
    async def test_upsert_server_auth_bearer_writes_ref_only(self):
        """Post-029 schema: bearer_token column dropped, only bearer_token_ref written."""
        from service.services.contracts import UpstreamAuthConfig
        from service.services.secret_refs import ServerAuthSecretRefs

        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"server_id": "srv"}]
        mock_resp.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=mock_resp)

        auth = UpstreamAuthConfig(auth_type="bearer", bearer_token="tok-plain")
        refs = ServerAuthSecretRefs(bearer_token_ref="mlp/srv/auth/bearer_token")

        await client.upsert_server_auth("srv", auth, secret_refs=refs)

        payload = client._client.request.await_args.kwargs["json"]
        assert "bearer_token" not in payload, "plaintext bearer_token must not be written"
        assert payload["bearer_token_ref"] == "mlp/srv/auth/bearer_token"

    async def test_upsert_server_auth_api_key_writes_ref_only(self):
        """Post-029 schema: api_key column dropped, only api_key_ref written."""
        from service.services.contracts import UpstreamAuthConfig
        from service.services.secret_refs import ServerAuthSecretRefs

        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"server_id": "srv"}]
        mock_resp.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=mock_resp)

        auth = UpstreamAuthConfig(
            auth_type="api_key_header", api_key="k-plain", api_key_header_name="X-Api-Key"
        )
        refs = ServerAuthSecretRefs(api_key_ref="mlp/srv/auth/api_key")

        await client.upsert_server_auth("srv", auth, secret_refs=refs)

        payload = client._client.request.await_args.kwargs["json"]
        assert "api_key" not in payload, "plaintext api_key must not be written"
        assert payload["api_key_ref"] == "mlp/srv/auth/api_key"

    async def test_upsert_server_auth_no_secret_refs_writes_null_refs(self):
        """Post-029 schema: no plaintext anywhere; missing refs → NULL ref columns."""
        from service.services.contracts import UpstreamAuthConfig

        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"server_id": "srv"}]
        mock_resp.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=mock_resp)

        auth = UpstreamAuthConfig(auth_type="bearer", bearer_token="tok-plain")

        await client.upsert_server_auth("srv", auth, secret_refs=None)

        payload = client._client.request.await_args.kwargs["json"]
        assert "bearer_token" not in payload
        assert "api_key" not in payload
        assert payload["bearer_token_ref"] is None
        assert payload["api_key_ref"] is None

    async def test_upsert_server_auth_uses_merge_duplicates_and_on_conflict(self):
        from service.services.contracts import UpstreamAuthConfig

        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"server_id": "srv"}]
        mock_resp.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=mock_resp)

        auth = UpstreamAuthConfig(auth_type="none")

        await client.upsert_server_auth("srv", auth)

        call_kwargs = client._client.request.await_args.kwargs
        prefer_header = call_kwargs["headers"]["Prefer"]
        assert "merge-duplicates" in prefer_header
        params = call_kwargs["params"]
        assert params.get("on_conflict") == "server_id"


# ---------------------------------------------------------------------------
# upsert_oauth_session
# ---------------------------------------------------------------------------


class TestUpsertOAuthSession:
    async def test_upsert_oauth_session_writes_ref_columns_only(self):
        """Post-029 schema: client_secret/refresh_token/access_token columns dropped.
        Only *_ref columns written to mcp_oauth_sessions."""
        from service.services.contracts import UpstreamAuthConfig
        from service.services.secret_refs import OAuthSecretRefs

        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"server_id": "srv"}]
        mock_resp.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=mock_resp)

        auth = UpstreamAuthConfig(
            auth_type="oauth_session",
            oauth_client_id="cid",
            oauth_client_secret="csecret",
            oauth_refresh_token="rtok",
            oauth_token_endpoint="https://auth.example.com/token",
        )
        refs = OAuthSecretRefs(
            client_secret_ref="mlp/srv/oauth/client_secret",
            refresh_token_ref="mlp/srv/oauth/refresh_token",
        )

        await client.upsert_oauth_session("srv", auth, secret_refs=refs)

        payload = client._client.request.await_args.kwargs["json"]
        assert "client_secret" not in payload, "plaintext client_secret must not be written"
        assert "refresh_token" not in payload, "plaintext refresh_token must not be written"
        assert "access_token" not in payload, "plaintext access_token must not be written"
        assert payload["client_secret_ref"] == "mlp/srv/oauth/client_secret"
        assert payload["refresh_token_ref"] == "mlp/srv/oauth/refresh_token"

    async def test_upsert_oauth_session_uses_merge_duplicates_and_on_conflict(self):
        from service.services.contracts import UpstreamAuthConfig

        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"server_id": "srv"}]
        mock_resp.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.request = AsyncMock(return_value=mock_resp)

        auth = UpstreamAuthConfig(auth_type="oauth_session", oauth_client_id="cid")

        await client.upsert_oauth_session("srv", auth)

        call_kwargs = client._client.request.await_args.kwargs
        prefer_header = call_kwargs["headers"]["Prefer"]
        assert "merge-duplicates" in prefer_header
        params = call_kwargs["params"]
        assert params.get("on_conflict") == "server_id"


# ---------------------------------------------------------------------------
# mcp_auth_requirements persistence
# ---------------------------------------------------------------------------


class TestReplaceAuthRequirements:
    async def test_replace_auth_requirements_calls_atomic_rpc(self):
        client = _make_client()
        rpc_response = MagicMock()
        rpc_response.raise_for_status = MagicMock()
        rpc_response.json.return_value = [
            {
                "server_id": "srv",
                "tool_id": "srv::lookup",
                "provider_key": "github",
            }
        ]
        client._request = AsyncMock(return_value=rpc_response)

        result = await client.replace_auth_requirements(
            "srv",
            [
                {
                    "server_id": "srv",
                    "tool_id": "srv::lookup",
                    "provider_key": "github",
                    "auth_kind": "oauth",
                    "required_scopes": ["repo"],
                    "scope_mode": "default",
                }
            ],
        )

        assert result == [
            {
                "server_id": "srv",
                "tool_id": "srv::lookup",
                "provider_key": "github",
            }
        ]
        client._request.assert_awaited_once()
        assert client._request.await_args.args == (
            "POST",
            "/rest/v1/rpc/replace_mcp_auth_requirements",
        )
        assert client._request.await_args.kwargs["payload"] == {
            "p_server_id": "srv",
            "p_requirements": [
                {
                    "server_id": "srv",
                    "tool_id": "srv::lookup",
                    "provider_key": "github",
                    "auth_kind": "oauth",
                    "required_scopes": ["repo"],
                    "scope_mode": "default",
                }
            ],
        }

    async def test_replace_auth_requirements_calls_atomic_rpc_when_rows_empty(self):
        client = _make_client()
        rpc_response = MagicMock()
        rpc_response.raise_for_status = MagicMock()
        rpc_response.json.return_value = []
        client._request = AsyncMock(return_value=rpc_response)

        result = await client.replace_auth_requirements("srv", [])

        assert result == []
        client._request.assert_awaited_once_with(
            "POST",
            "/rest/v1/rpc/replace_mcp_auth_requirements",
            payload={"p_server_id": "srv", "p_requirements": []},
            headers={
                **client._headers,
                "Prefer": "return=representation",
            },
        )


# ---------------------------------------------------------------------------
# Delegated OAuth provider connections
# ---------------------------------------------------------------------------


class TestDelegatedOAuthConnections:
    async def test_find_user_provider_connection_returns_scope_covering_row(self):
        client = _make_client()
        rows = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "provider_key": "github",
                "provider_account_id": "octo",
                "granted_scopes": ["repo", "issues:write"],
                "scope_fingerprint": "fp",
                "status": "active",
                "token_storage_mode": "refreshable",
            }
        ]
        client._get = AsyncMock(return_value=rows)

        result = await client.find_user_provider_connection(
            user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            provider_key="github",
            required_scopes=["repo"],
        )

        assert result is not None
        assert result.provider_key == "github"
        assert result.granted_scopes == ["repo", "issues:write"]
        client._get.assert_awaited_once()

    async def test_find_user_provider_connection_skips_insufficient_scope_rows(self):
        client = _make_client()
        client._get = AsyncMock(
            return_value=[
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "provider_key": "github",
                    "provider_account_id": "octo",
                    "granted_scopes": ["repo"],
                    "scope_fingerprint": "fp",
                    "status": "active",
                    "token_storage_mode": "refreshable",
                }
            ]
        )

        result = await client.find_user_provider_connection(
            user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            provider_key="github",
            required_scopes=["repo", "issues:write"],
        )

        assert result is None

    async def test_create_pending_execution_posts_expected_payload(self):
        client = _make_client()
        client._request = AsyncMock(
            return_value=MagicMock(json=MagicMock(return_value=[{"id": "pe_123"}]))
        )

        result = await client.create_pending_execution(
            user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            tool_id="github::create_issue",
            params_json={"title": "bug"},
            provider_key="github",
            required_scopes=["repo", "issues:write"],
            retry_token="rt_123",
            expires_at="2026-04-20T00:00:00Z",
        )

        assert result == [{"id": "pe_123"}]
        client._request.assert_awaited_once_with(
            "POST",
            "/rest/v1/pending_executions",
            payload={
                "user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "tool_id": "github::create_issue",
                "params_json": {"title": "bug"},
                "provider_key": "github",
                "required_scopes": ["repo", "issues:write"],
                "retry_token": "rt_123",
                "expires_at": "2026-04-20T00:00:00Z",
            },
            headers={
                **client._headers,
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
        )

    async def test_create_pending_execution_accepts_resume_token_alias(self):
        client = _make_client()
        client._request = AsyncMock(
            return_value=MagicMock(json=MagicMock(return_value=[{"id": "pe_123"}]))
        )

        await client.create_pending_execution(
            user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            tool_id="github::create_issue",
            params_json={"title": "bug"},
            provider_key="github",
            required_scopes=["repo", "issues:write"],
            resume_token="rt_alias",
            expires_at="2026-04-20T00:00:00Z",
        )

        payload = client._request.await_args.kwargs["payload"]
        assert payload["retry_token"] == "rt_alias"

    async def test_update_pending_execution_patches_expected_row(self):
        client = _make_client()
        client._request = AsyncMock(
            return_value=MagicMock(
                json=MagicMock(return_value=[{"id": "pe_123", "status": "ready_to_resume"}])
            )
        )

        result = await client.update_pending_execution(
            "pe_123",
            {"status": "ready_to_resume", "connection_id": "conn-123"},
        )

        assert result == [{"id": "pe_123", "status": "ready_to_resume"}]
        client._request.assert_awaited_once_with(
            "PATCH",
            "/rest/v1/pending_executions",
            payload={"status": "ready_to_resume", "connection_id": "conn-123"},
            params={"id": "eq.pe_123"},
            headers={
                **client._headers,
                "Prefer": "return=representation",
            },
        )

    async def test_fetch_pending_execution_by_resume_token_returns_first_row(self):
        client = _make_client()
        client._get = AsyncMock(return_value=[{"id": "pe_123", "retry_token": "rt_123"}])

        result = await client.fetch_pending_execution_by_resume_token("rt_123")

        assert result == {"id": "pe_123", "retry_token": "rt_123"}
        client._get.assert_awaited_once_with(
            "/rest/v1/pending_executions",
            params={"retry_token": "eq.rt_123", "limit": 1},
        )

    async def test_fetch_user_provider_token_returns_first_row(self):
        client = _make_client()
        client._get = AsyncMock(
            return_value=[
                {
                    "connection_id": "conn-123",
                    "access_token": "apify-user-token",
                    "refresh_token": "refresh-token",
                    "expires_at": "2026-04-20T00:00:00Z",
                    "token_type": "Bearer",
                    "user_provider_connections": {"provider_key": "github"},
                }
            ]
        )

        result = await client.fetch_user_provider_token("conn-123")

        assert result["access_token"] == "apify-user-token"
        assert result["provider_key"] == "github"
        client._get.assert_awaited_once_with(
            "/rest/v1/user_provider_tokens",
            params={
                "connection_id": "eq.conn-123",
                "select": (
                    "connection_id,access_token,refresh_token,expires_at,token_type,"
                    "user_provider_connections(provider_key)"
                ),
                "limit": 1,
            },
        )


# ---------------------------------------------------------------------------
# OAuthSecretStore protocol — provision_server_auth_secret_refs declaration
# ---------------------------------------------------------------------------


class TestOAuthSecretStoreProtocol:
    def test_oauth_secret_store_protocol_declares_server_auth_provisioning(self):
        from service.services.secret_refs import OAuthSecretStore

        assert getattr(OAuthSecretStore, "provision_server_auth_secret_refs", None) is not None


@pytest.mark.asyncio
async def test_create_oauth_provider_bootstrap_draft_uses_idempotency_conflict() -> None:
    from service.adapters.supabase_client import SupabaseClient

    client = SupabaseClient.__new__(SupabaseClient)
    client._headers = {"Authorization": "Bearer service-key"}
    seen = {}

    async def fake_request(method, path, *, payload=None, params=None, headers=None):
        seen.update(
            {
                "method": method,
                "path": path,
                "payload": payload,
                "params": params,
                "headers": headers,
            }
        )
        response = MagicMock()
        response.json.return_value = [{"id": "draft-1"}]
        return response

    client._request = fake_request

    result = await client.create_oauth_provider_bootstrap_draft(
        {
            "owner_user_id": "user-1",
            "provider_key": "github",
            "idempotency_key": "idem-1",
        }
    )

    assert result == [{"id": "draft-1"}]
    assert seen["method"] == "POST"
    assert seen["path"] == "/rest/v1/oauth_provider_bootstrap_drafts"
    assert seen["params"] == {"on_conflict": "owner_user_id,idempotency_key"}
    assert "return=representation" in seen["headers"]["Prefer"]


@pytest.mark.asyncio
async def test_fetch_oauth_provider_bootstrap_draft_filters_by_id_and_owner() -> None:
    from service.adapters.supabase_client import SupabaseClient

    client = SupabaseClient.__new__(SupabaseClient)
    client._headers = {}
    seen = {}

    async def fake_get(path, *, params=None):
        seen.update({"path": path, "params": params})
        return [{"id": "draft-1", "provider_key": "github"}]

    client._get = fake_get

    result = await client.fetch_oauth_provider_bootstrap_draft(
        draft_id="draft-1", owner_user_id="user-1"
    )

    assert result == {"id": "draft-1", "provider_key": "github"}
    assert seen == {
        "path": "/rest/v1/oauth_provider_bootstrap_drafts",
        "params": {
            "id": "eq.draft-1",
            "owner_user_id": "eq.user-1",
            "select": "id,provider_key,metadata,status",
            "limit": 1,
        },
    }


@pytest.mark.asyncio
async def test_promote_oauth_provider_bootstrap_draft_calls_rpc() -> None:
    from service.adapters.supabase_client import SupabaseClient

    client = SupabaseClient.__new__(SupabaseClient)
    client._headers = {}
    seen = {}

    async def fake_request(method, path, *, payload=None, params=None, headers=None):
        seen.update({"method": method, "path": path, "payload": payload})
        response = MagicMock()
        response.json.return_value = {"provider_key": "github"}
        return response

    client._request = fake_request

    result = await client.promote_oauth_provider_bootstrap_draft(
        draft_id="draft-1", owner_user_id="user-1"
    )

    assert result == {"provider_key": "github"}
    assert seen == {
        "method": "POST",
        "path": "/rest/v1/rpc/promote_oauth_provider_bootstrap_draft",
        "payload": {"p_draft_id": "draft-1", "p_owner_user_id": "user-1"},
    }


@pytest.mark.asyncio
async def test_oauth_state_nonce_rpc_methods() -> None:
    from service.adapters.supabase_client import SupabaseClient

    client = SupabaseClient.__new__(SupabaseClient)
    client._headers = {}
    calls = []

    async def fake_request(method, path, *, payload=None, params=None, headers=None):
        calls.append((method, path, payload))
        response = MagicMock()
        response.json.return_value = {"ok": True}
        return response

    client._request = fake_request

    await client.create_oauth_state_nonce({"nonce_hash": "hash", "provider_key": "github"})
    await client.consume_oauth_state_nonce(nonce_hash="hash", provider_key="github")

    assert calls == [
        ("POST", "/rest/v1/oauth_state_nonces", {"nonce_hash": "hash", "provider_key": "github"}),
        (
            "POST",
            "/rest/v1/rpc/consume_oauth_state_nonce",
            {"p_nonce_hash": "hash", "p_provider_key": "github"},
        ),
    ]
