"""Tests for SmitheryClient — HTTP client for Smithery Registry API."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_discovery.data.smithery_client import SmitheryClient
from mcp_discovery.models import TOOL_ID_SEPARATOR, MCPServer, MCPServerSummary

# --- Fixtures: raw API responses ---

SAMPLE_LIST_ITEM = {
    "qualifiedName": "@anthropic/claude-code",
    "displayName": "Claude Code",
    "description": "AI coding assistant",
    "useCount": 5000,
    "createdAt": "2025-01-01T00:00:00Z",
    "verified": True,
    "isDeployed": True,
}

SAMPLE_LIST_ITEM_MINIMAL = {
    "qualifiedName": "@test/minimal",
    "displayName": "Minimal Server",
}

SAMPLE_DETAIL_RESPONSE = {
    "qualifiedName": "@anthropic/claude-code",
    "displayName": "Claude Code",
    "description": "AI coding assistant",
    "homepage": "https://claude.ai",
    "tools": [
        {
            "name": "run_command",
            "description": "Run a shell command",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
            },
        },
        {
            "name": "edit_file",
            "description": "Edit a file",
            "inputSchema": None,
        },
    ],
}

SAMPLE_DETAIL_NO_TOOLS = {
    "qualifiedName": "@test/empty",
    "displayName": "Empty Server",
    "description": "No tools",
}


class TestParseServerSummary:
    def test_full_fields(self):
        result = SmitheryClient.parse_server_summary(SAMPLE_LIST_ITEM)
        assert isinstance(result, MCPServerSummary)
        assert result.qualified_name == "@anthropic/claude-code"
        assert result.display_name == "Claude Code"
        assert result.description == "AI coding assistant"
        assert result.use_count == 5000
        assert result.is_verified is True
        assert result.is_deployed is True

    def test_minimal_fields(self):
        result = SmitheryClient.parse_server_summary(SAMPLE_LIST_ITEM_MINIMAL)
        assert result.qualified_name == "@test/minimal"
        assert result.use_count == 0
        assert result.is_verified is False
        assert result.is_deployed is False


class TestParseServerDetail:
    def test_with_tools(self):
        result = SmitheryClient.parse_server_detail(SAMPLE_DETAIL_RESPONSE)
        assert isinstance(result, MCPServer)
        assert result.server_id == "@anthropic/claude-code"
        assert result.name == "Claude Code"
        assert result.homepage == "https://claude.ai"
        assert len(result.tools) == 2

        tool0 = result.tools[0]
        assert tool0.tool_id == f"@anthropic/claude-code{TOOL_ID_SEPARATOR}run_command"
        assert tool0.tool_name == "run_command"
        assert tool0.description == "Run a shell command"
        assert tool0.input_schema is not None

        tool1 = result.tools[1]
        assert tool1.tool_id == f"@anthropic/claude-code{TOOL_ID_SEPARATOR}edit_file"
        assert tool1.input_schema is None

    def test_no_tools(self):
        result = SmitheryClient.parse_server_detail(SAMPLE_DETAIL_NO_TOOLS)
        assert result.server_id == "@test/empty"
        assert result.tools == []

    def test_tool_id_uses_separator_constant(self):
        result = SmitheryClient.parse_server_detail(SAMPLE_DETAIL_RESPONSE)
        for tool in result.tools:
            assert TOOL_ID_SEPARATOR in tool.tool_id
            parts = tool.tool_id.split(TOOL_ID_SEPARATOR)
            assert len(parts) == 2
            assert parts[0] == "@anthropic/claude-code"


class TestSmitheryClientInit:
    def test_default_rate_limit(self):
        client = SmitheryClient(base_url="https://example.com")
        assert client.rate_limit_seconds == 0.5

    def test_custom_rate_limit(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=1.0)
        assert client.rate_limit_seconds == 1.0


class TestFetchAllSummaries:
    async def test_stops_on_empty_page(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)
        calls = 0

        async def mock_fetch(page, page_size=50):
            nonlocal calls
            calls += 1
            if page == 1:
                return [
                    SmitheryClient.parse_server_summary(SAMPLE_LIST_ITEM),
                    SmitheryClient.parse_server_summary(SAMPLE_LIST_ITEM_MINIMAL),
                ], {"currentPage": 1, "totalPages": 5}
            return [], {}

        client.fetch_server_list = mock_fetch
        result = await client.fetch_all_summaries(max_pages=10)
        assert len(result) == 2
        assert calls == 2

    async def test_stops_on_max_pages(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)

        async def mock_fetch(page, page_size=50):
            return [SmitheryClient.parse_server_summary(SAMPLE_LIST_ITEM)], {
                "currentPage": page,
                "totalPages": 100,
            }

        client.fetch_server_list = mock_fetch
        result = await client.fetch_all_summaries(max_pages=3)
        assert len(result) == 3

    async def test_stops_on_last_page(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)

        async def mock_fetch(page, page_size=50):
            return [SmitheryClient.parse_server_summary(SAMPLE_LIST_ITEM)], {
                "currentPage": 2,
                "totalPages": 2,
            }

        client.fetch_server_list = mock_fetch
        result = await client.fetch_all_summaries(max_pages=10)
        assert len(result) == 1


class TestAsyncContextManager:
    async def test_aenter_creates_http_client(self):
        client = SmitheryClient(base_url="https://example.com")
        assert client._http_client is None
        async with client as ctx:
            assert ctx is client
            assert ctx._http_client is not None
            assert isinstance(ctx._http_client, httpx.AsyncClient)
        assert client._http_client is None

    async def test_aexit_closes_and_clears_http_client(self):
        client = SmitheryClient(base_url="https://example.com")
        async with client:
            assert client._http_client is not None
        assert client._http_client is None

    async def test_aexit_handles_none_client_gracefully(self):
        client = SmitheryClient(base_url="https://example.com")
        # Manually call __aexit__ without __aenter__
        await client.__aexit__(None, None, None)
        assert client._http_client is None


class TestGetClient:
    def test_raises_runtime_error_when_not_in_context(self):
        client = SmitheryClient(base_url="https://example.com")
        with pytest.raises(RuntimeError, match="async context manager"):
            client._get_client()

    async def test_returns_client_when_in_context(self):
        client = SmitheryClient(base_url="https://example.com")
        async with client:
            http_client = client._get_client()
            assert isinstance(http_client, httpx.AsyncClient)


class TestRateLimit:
    async def test_rate_limit_does_not_sleep_on_first_call(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=1.0)
        client._last_request_time = 0.0
        # First call with _last_request_time=0.0 should effectively not block
        # because monotonic() will be far above 0.0
        await client._rate_limit()
        assert client._last_request_time > 0.0

    async def test_rate_limit_updates_last_request_time(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)
        await client._rate_limit()
        first_time = client._last_request_time
        await client._rate_limit()
        second_time = client._last_request_time
        assert second_time >= first_time


class TestRequestWithRetry:
    async def test_successful_request(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_http.request = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        result = await client._request_with_retry("GET", "https://example.com/api")
        assert result is mock_response
        mock_http.request.assert_called_once()

    async def test_retries_on_500(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 500
        error_request = MagicMock(spec=httpx.Request)

        success_response = MagicMock(spec=httpx.Response)
        success_response.status_code = 200
        success_response.raise_for_status = MagicMock()

        mock_http.request = AsyncMock(
            side_effect=[
                httpx.HTTPStatusError(
                    "Server Error", request=error_request, response=error_response
                ),
                success_response,
            ]
        )
        client._http_client = mock_http

        with patch("mcp_discovery.data.smithery_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request_with_retry(
                "GET", "https://example.com/api", max_retries=3
            )
        assert result is success_response
        assert mock_http.request.call_count == 2

    async def test_retries_on_429(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 429
        error_request = MagicMock(spec=httpx.Request)

        success_response = MagicMock(spec=httpx.Response)
        success_response.status_code = 200
        success_response.raise_for_status = MagicMock()

        mock_http.request = AsyncMock(
            side_effect=[
                httpx.HTTPStatusError(
                    "Too Many Requests", request=error_request, response=error_response
                ),
                success_response,
            ]
        )
        client._http_client = mock_http

        with patch("mcp_discovery.data.smithery_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request_with_retry(
                "GET", "https://example.com/api", max_retries=3
            )
        assert result is success_response

    async def test_raises_non_retryable_http_error(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 404
        error_request = MagicMock(spec=httpx.Request)

        mock_http.request = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found", request=error_request, response=error_response
            )
        )
        client._http_client = mock_http

        with pytest.raises(httpx.HTTPStatusError):
            await client._request_with_retry("GET", "https://example.com/api", max_retries=3)
        assert mock_http.request.call_count == 1

    async def test_retries_on_connect_error_then_succeeds(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        success_response = MagicMock(spec=httpx.Response)
        success_response.status_code = 200
        success_response.raise_for_status = MagicMock()

        mock_http.request = AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused"),
                success_response,
            ]
        )
        client._http_client = mock_http

        with patch("mcp_discovery.data.smithery_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request_with_retry(
                "GET", "https://example.com/api", max_retries=3
            )
        assert result is success_response

    async def test_retries_on_timeout_then_raises_after_exhaustion(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        mock_http.request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        client._http_client = mock_http

        with patch("mcp_discovery.data.smithery_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.TimeoutException):
                await client._request_with_retry("GET", "https://example.com/api", max_retries=2)
        assert mock_http.request.call_count == 2

    async def test_raises_after_all_retries_exhausted_http_error(self):
        client = SmitheryClient(base_url="https://example.com", rate_limit_seconds=0.0)
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 503
        error_request = MagicMock(spec=httpx.Request)

        mock_http.request = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Service Unavailable", request=error_request, response=error_response
            )
        )
        client._http_client = mock_http

        with patch("mcp_discovery.data.smithery_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await client._request_with_retry("GET", "https://example.com/api", max_retries=3)
        assert mock_http.request.call_count == 3


class TestFetchServerList:
    async def test_fetch_server_list_parses_response(self):
        client = SmitheryClient(base_url="https://registry.smithery.ai", rate_limit_seconds=0.0)
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "servers": [SAMPLE_LIST_ITEM, SAMPLE_LIST_ITEM_MINIMAL],
            "pagination": {"currentPage": 1, "totalPages": 5},
        }
        mock_http.request = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        summaries, pagination = await client.fetch_server_list(page=1, page_size=50)

        assert len(summaries) == 2
        assert summaries[0].qualified_name == "@anthropic/claude-code"
        assert summaries[1].qualified_name == "@test/minimal"
        assert pagination["currentPage"] == 1
        assert pagination["totalPages"] == 5

        call_kwargs = mock_http.request.call_args
        assert call_kwargs.args[0] == "GET"
        assert "/servers" in call_kwargs.args[1]

    async def test_fetch_server_list_empty_servers(self):
        client = SmitheryClient(base_url="https://registry.smithery.ai", rate_limit_seconds=0.0)
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"servers": [], "pagination": {}}
        mock_http.request = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        summaries, pagination = await client.fetch_server_list()
        assert summaries == []


class TestFetchServerDetail:
    async def test_fetch_server_detail_parses_response(self):
        client = SmitheryClient(base_url="https://registry.smithery.ai", rate_limit_seconds=0.0)
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = SAMPLE_DETAIL_RESPONSE
        mock_http.request = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        server = await client.fetch_server_detail("@anthropic/claude-code")

        assert isinstance(server, MCPServer)
        assert server.server_id == "@anthropic/claude-code"
        assert len(server.tools) == 2
        # Verify URL encoding — qualified name should be URL-encoded
        call_url = mock_http.request.call_args.args[1]
        assert "%40anthropic%2Fclaude-code" in call_url


class TestParseServerDetailEdgeCases:
    def test_skips_tool_with_missing_name(self):
        raw = {
            "qualifiedName": "@test/srv",
            "displayName": "Test Server",
            "tools": [
                {"name": "valid_tool", "description": "A valid tool"},
                {"description": "Missing name field"},
                {"name": "", "description": "Empty name"},
            ],
        }
        result = SmitheryClient.parse_server_detail(raw)
        # Only valid_tool should be included (empty string is falsy)
        assert len(result.tools) == 1
        assert result.tools[0].tool_name == "valid_tool"

    def test_tools_key_is_none(self):
        raw = {
            "qualifiedName": "@test/srv",
            "displayName": "Test Server",
            "tools": None,
        }
        result = SmitheryClient.parse_server_detail(raw)
        assert result.tools == []


class TestBaseUrlNormalization:
    def test_trailing_slash_stripped(self):
        client = SmitheryClient(base_url="https://example.com/")
        assert client.base_url == "https://example.com"

    def test_no_trailing_slash_unchanged(self):
        client = SmitheryClient(base_url="https://example.com")
        assert client.base_url == "https://example.com"
