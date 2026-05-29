from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from service.rag.fallback import SupabaseFallback


class TestSupabaseFallback:
    @pytest.fixture
    def fallback(self):
        return SupabaseFallback(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            timeout=5.0,
        )

    async def test_search_returns_results(self, fallback):
        mock_rows = [
            {
                "server_id": "github",
                "tool_name": "search_repos",
                "tool_id": "github::search_repos",
                "description": "Search GitHub repositories",
                "input_schema": None,
            }
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_rows
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            results = await fallback.search("search repos", limit=5)

        assert len(results) == 1
        assert results[0].tool.tool_id == "github::search_repos"
        # Reciprocal-rank score: (1 / (i+1)) * DEGRADED_SCORE_CEILING, i=0 => 0.5
        assert results[0].score == 0.5
        assert results[0].rank == 1

    async def test_search_returns_empty_on_no_config(self):
        fallback = SupabaseFallback(supabase_url="", supabase_key="")
        results = await fallback.search("anything", limit=5)
        assert results == []

    async def test_search_returns_empty_on_http_error(self, fallback):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "500", request=AsyncMock(), response=AsyncMock()
            )
            mock_client_cls.return_value = mock_client

            results = await fallback.search("test", limit=5)

        assert results == []

    def test_is_configured(self, fallback):
        assert fallback.is_configured is True

    def test_is_not_configured(self):
        fallback = SupabaseFallback(supabase_url="", supabase_key="")
        assert fallback.is_configured is False

    async def test_search_pending_freshness_sends_pending_filter(self, fallback):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await fallback.search_pending_freshness("repo search", limit=3)

        sent = mock_client.post.await_args.kwargs["json"]
        assert sent["status_filter"] == "pending"

    async def test_search_full_catalog_omits_status_filter(self, fallback):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await fallback.search_full_catalog("repo search", limit=3)

        sent = mock_client.post.await_args.kwargs["json"]
        assert "status_filter" not in sent

    async def test_search_reuses_lazily_created_async_client_across_calls(self, fallback):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await fallback.search_pending_freshness("repo search", limit=3)
            await fallback.search_full_catalog("repo search", limit=3)

        mock_client_cls.assert_called_once_with(timeout=5.0)
        assert mock_client.post.await_count == 2

    async def test_search_uses_injected_client_without_constructing_new_client(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        fallback = SupabaseFallback(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            client=mock_client,
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            await fallback.search("repo search", limit=3)

        mock_client_cls.assert_not_called()
        mock_client.post.assert_awaited_once()

    async def test_aclose_closes_owned_cached_client(self, fallback):
        mock_client = AsyncMock()
        mock_client.is_closed = False
        fallback._client = mock_client

        await fallback.aclose()

        mock_client.aclose.assert_awaited_once()

    async def test_aclose_skips_injected_client(self):
        mock_client = AsyncMock()
        mock_client.is_closed = False
        fallback = SupabaseFallback(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            client=mock_client,
        )

        await fallback.aclose()

        mock_client.aclose.assert_not_called()
