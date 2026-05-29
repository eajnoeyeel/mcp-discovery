"""Integration tests for SmitheryClient — runs against real Smithery Registry API."""

import os

import pytest

from mcp_discovery.data.smithery_client import SmitheryClient
from mcp_discovery.models import MCPServer, MCPServerSummary

SMITHERY_BASE_URL = "https://registry.smithery.ai"

# Skip if explicitly disabled or no network
pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_SMITHERY", "false").lower() == "true",
    reason="SKIP_SMITHERY=true",
)


class TestSmitheryContextManager:
    async def test_enter_and_exit(self):
        client = SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.0)
        async with client as c:
            assert c._http_client is not None
        assert c._http_client is None

    async def test_get_client_without_context_raises(self):
        client = SmitheryClient(base_url=SMITHERY_BASE_URL)
        with pytest.raises(RuntimeError, match="async context manager"):
            client._get_client()


class TestFetchServerList:
    async def test_fetches_first_page(self):
        async with SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.5) as client:
            summaries, pagination = await client.fetch_server_list(page=1, page_size=5)

        assert len(summaries) > 0
        assert all(isinstance(s, MCPServerSummary) for s in summaries)
        assert "currentPage" in pagination or "totalPages" in pagination

    async def test_summary_has_required_fields(self):
        async with SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.5) as client:
            summaries, _ = await client.fetch_server_list(page=1, page_size=3)

        for s in summaries:
            assert s.qualified_name
            assert s.display_name


class TestFetchServerDetail:
    async def test_fetches_known_server(self):
        async with SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.5) as client:
            # First get a server name from the list
            summaries, _ = await client.fetch_server_list(page=1, page_size=1)
            assert len(summaries) > 0
            name = summaries[0].qualified_name

            server = await client.fetch_server_detail(name)

        assert isinstance(server, MCPServer)
        assert server.server_id == name
        assert server.name  # display name exists

    async def test_detail_tools_have_correct_ids(self):
        async with SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.5) as client:
            summaries, _ = await client.fetch_server_list(page=1, page_size=1)
            name = summaries[0].qualified_name
            server = await client.fetch_server_detail(name)

        for tool in server.tools:
            assert tool.server_id == name
            assert tool.tool_id.startswith(name)
            assert "::" in tool.tool_id


class TestFetchAllSummaries:
    async def test_fetches_multiple_pages(self):
        async with SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.5) as client:
            summaries = await client.fetch_all_summaries(max_pages=2)

        assert len(summaries) > 0
        assert all(isinstance(s, MCPServerSummary) for s in summaries)


class TestRetryLogic:
    async def test_retries_on_server_error(self):
        """Test _request_with_retry with a server that returns 500 then 200."""

        import httpx

        client = SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.0)
        async with client:
            real_client = client._get_client()

            call_count = 0
            original_request = real_client.request

            async def flaky_request(method, url, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise httpx.ConnectError("simulated connection error")
                return await original_request(method, url, **kwargs)

            real_client.request = flaky_request

            # Should retry and succeed on second attempt
            summaries, _ = await client.fetch_server_list(page=1, page_size=1)
            assert call_count == 2
            assert len(summaries) > 0

    async def test_raises_after_max_retries(self):
        """After max retries exhausted, should raise."""
        import httpx

        client = SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.0)
        async with client:
            real_client = client._get_client()

            async def always_fail(method, url, **kwargs):
                raise httpx.ConnectError("always fails")

            real_client.request = always_fail

            with pytest.raises(httpx.ConnectError):
                url = f"{SMITHERY_BASE_URL}/servers"
                await client._request_with_retry("GET", url, max_retries=2)

    async def test_retries_on_http_429(self):
        """Test retry on HTTP 429 (rate limited)."""
        import httpx

        client = SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.0)
        async with client:
            real_client = client._get_client()
            call_count = 0
            original_request = real_client.request

            async def rate_limited_then_ok(method, url, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    req = httpx.Request(method, url)
                    resp = httpx.Response(429, request=req)
                    raise httpx.HTTPStatusError("rate limited", request=req, response=resp)
                return await original_request(method, url, **kwargs)

            real_client.request = rate_limited_then_ok
            response = await client._request_with_retry(
                "GET",
                f"{SMITHERY_BASE_URL}/servers",
                params={"page": 1, "pageSize": 1},
                max_retries=3,
            )
            assert call_count == 2
            assert response.status_code == 200

    async def test_non_retryable_http_error_raises_immediately(self):
        """HTTP 400 should not be retried."""
        import httpx

        client = SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.0)
        async with client:
            real_client = client._get_client()

            async def bad_request(method, url, **kwargs):
                req = httpx.Request(method, url)
                resp = httpx.Response(400, request=req)
                raise httpx.HTTPStatusError("bad request", request=req, response=resp)

            real_client.request = bad_request
            url = f"{SMITHERY_BASE_URL}/servers"
            with pytest.raises(httpx.HTTPStatusError):
                await client._request_with_retry("GET", url, max_retries=3)


class TestParseServerDetailWarning:
    def test_skips_tool_with_missing_name(self):
        """parse_server_detail should skip tools without 'name'."""
        raw = {
            "qualifiedName": "@test/srv",
            "displayName": "Test",
            "tools": [
                {"name": "valid_tool", "description": "ok"},
                {"description": "no name here"},
            ],
        }
        server = SmitheryClient.parse_server_detail(raw)
        assert len(server.tools) == 1
        assert server.tools[0].tool_name == "valid_tool"


class TestRateLimit:
    async def test_rate_limit_enforced(self):
        import time

        client = SmitheryClient(base_url=SMITHERY_BASE_URL, rate_limit_seconds=0.3)
        async with client:
            start = time.monotonic()
            await client._rate_limit()
            await client._rate_limit()
            elapsed = time.monotonic() - start
            # Second call should wait ~0.3s
            assert elapsed >= 0.2
