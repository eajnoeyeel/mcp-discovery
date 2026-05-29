"""Unit tests for mlp/rag/fallback.py — SupabaseFallback lexical search."""

from unittest.mock import AsyncMock, MagicMock

import httpx

from service.rag.fallback import SupabaseFallback


def _make_row(
    server_id: str = "srv",
    tool_name: str = "tool_a",
    tool_id: str = "srv::tool_a",
    description: str = "A test tool",
) -> dict:
    return {
        "server_id": server_id,
        "tool_name": tool_name,
        "tool_id": tool_id,
        "description": description,
        "input_schema": None,
    }


def _mock_response(rows: list[dict], status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = rows
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestIsConfigured:
    def test_configured_when_url_and_key_provided(self):
        fb = SupabaseFallback(supabase_url="https://example.supabase.co", supabase_key="key123")
        assert fb.is_configured is True

    def test_not_configured_when_url_is_empty(self):
        fb = SupabaseFallback(supabase_url="", supabase_key="key123")
        assert fb.is_configured is False

    def test_not_configured_when_key_is_empty(self):
        fb = SupabaseFallback(supabase_url="https://example.supabase.co", supabase_key="")
        assert fb.is_configured is False

    def test_not_configured_when_both_empty(self):
        fb = SupabaseFallback(supabase_url="", supabase_key="")
        assert fb.is_configured is False


class TestSearch:
    async def test_search_returns_results_on_success(self):
        rows = [_make_row("srv_a", "tool_x", "srv_a::tool_x", "desc")]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=_mock_response(rows))
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        results = await fb.search("github search", limit=5)
        assert len(results) == 1
        assert results[0].tool.tool_id == "srv_a::tool_x"
        assert results[0].source_path == "lexical_fallback"
        assert results[0].rank == 1

    async def test_search_returns_empty_when_not_configured(self):
        fb = SupabaseFallback(supabase_url="", supabase_key="")
        results = await fb.search("any query")
        assert results == []

    async def test_search_posts_to_correct_rpc_endpoint(self):
        rows = [_make_row()]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=_mock_response(rows))
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        await fb.search("test", limit=3)
        call_args = mock_client.post.call_args
        assert "/rest/v1/rpc/search_tools_fts" in call_args[0][0]

    async def test_search_sends_correct_payload(self):
        rows = [_make_row()]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=_mock_response(rows))
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        await fb.search("my query", limit=7)
        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["search_query"] == "my query"
        assert payload["result_limit"] == 7
        assert "status_filter" not in payload

    async def test_search_returns_empty_on_http_error(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
        )
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        results = await fb.search("query")
        assert results == []

    async def test_search_returns_empty_on_network_error(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        results = await fb.search("query")
        assert results == []

    async def test_search_assigns_ranks_sequentially(self):
        rows = [
            _make_row("s", "t1", "s::t1"),
            _make_row("s", "t2", "s::t2"),
            _make_row("s", "t3", "s::t3"),
        ]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=_mock_response(rows))
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        results = await fb.search("query", limit=5)
        assert [r.rank for r in results] == [1, 2, 3]


class TestSearchPendingFreshness:
    async def test_sends_status_filter_pending(self):
        rows = [_make_row()]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=_mock_response(rows))
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        await fb.search_pending_freshness("query", limit=2)
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["status_filter"] == "pending"

    async def test_results_have_freshness_source_path(self):
        rows = [_make_row()]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=_mock_response(rows))
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        results = await fb.search_pending_freshness("query")
        assert results[0].source_path == "freshness"

    async def test_returns_empty_when_not_configured(self):
        fb = SupabaseFallback(supabase_url="", supabase_key="")
        results = await fb.search_pending_freshness("query")
        assert results == []


class TestSearchFullCatalog:
    async def test_does_not_send_status_filter(self):
        rows = [_make_row()]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=_mock_response(rows))
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        await fb.search_full_catalog("query")
        call_kwargs = mock_client.post.call_args[1]
        assert "status_filter" not in call_kwargs["json"]

    async def test_results_have_lexical_fallback_source_path(self):
        rows = [_make_row()]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=_mock_response(rows))
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        results = await fb.search_full_catalog("query")
        assert results[0].source_path == "lexical_fallback"


class TestGetClient:
    def test_creates_new_client_when_none(self):
        fb = SupabaseFallback(supabase_url="https://x.supabase.co", supabase_key="key")
        client = fb._get_client()
        assert isinstance(client, httpx.AsyncClient)

    def test_reuses_existing_open_client(self):
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        returned = fb._get_client()
        assert returned is mock_client

    def test_creates_new_client_when_existing_is_closed(self):
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.is_closed = True
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        returned = fb._get_client()
        assert returned is not mock_client
        assert isinstance(returned, httpx.AsyncClient)


class TestAclose:
    async def test_aclose_closes_owned_client(self):
        fb = SupabaseFallback(supabase_url="https://x.supabase.co", supabase_key="key")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        fb._client = mock_client
        fb._owns_client = True
        await fb.aclose()
        mock_client.aclose.assert_awaited_once()

    async def test_aclose_does_not_close_injected_client(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        fb = SupabaseFallback(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
            client=mock_client,
        )
        await fb.aclose()
        mock_client.aclose.assert_not_awaited()

    async def test_aclose_skips_already_closed_client(self):
        fb = SupabaseFallback(supabase_url="https://x.supabase.co", supabase_key="key")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = True
        fb._client = mock_client
        fb._owns_client = True
        await fb.aclose()
        mock_client.aclose.assert_not_awaited()
