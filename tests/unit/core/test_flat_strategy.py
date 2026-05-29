"""Tests for FlatStrategy — 1-Layer direct tool search."""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from mcp_discovery.embedding.sparse_embedder import SparseVector
from mcp_discovery.models import MCPTool, SearchResult
from mcp_discovery.pipeline.flat import FlatStrategy
from mcp_discovery.pipeline.strategy import StrategyRegistry


def make_tool(n: int = 0) -> MCPTool:
    return MCPTool(
        server_id=f"@srv{n}",
        tool_name=f"tool{n}",
        tool_id=f"@srv{n}::tool{n}",
    )


def make_search_result(n: int = 0, score: float = 0.9) -> SearchResult:
    return SearchResult(tool=make_tool(n), score=score, rank=n + 1)


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed_one = AsyncMock(return_value=np.zeros(1536))
    return embedder


@pytest.fixture
def mock_tool_store():
    store = AsyncMock()
    store.search = AsyncMock(return_value=[make_search_result(0), make_search_result(1, 0.8)])
    return store


class TestFlatStrategy:
    async def test_search_embeds_query(self, mock_embedder, mock_tool_store):
        strategy = FlatStrategy(embedder=mock_embedder, tool_store=mock_tool_store)
        await strategy.search("find a github tool", top_k=3)
        mock_embedder.embed_one.assert_called_once_with("find a github tool")

    async def test_search_calls_tool_store_with_query_vector(self, mock_embedder, mock_tool_store):
        strategy = FlatStrategy(embedder=mock_embedder, tool_store=mock_tool_store)
        await strategy.search("test query", top_k=5)
        mock_tool_store.search.assert_called_once()
        call_kwargs = mock_tool_store.search.call_args
        assert call_kwargs.kwargs["top_k"] == 5

    async def test_search_returns_results_from_store(self, mock_embedder, mock_tool_store):
        strategy = FlatStrategy(embedder=mock_embedder, tool_store=mock_tool_store)
        results = await strategy.search("test", top_k=3)
        assert len(results) == 2
        assert results[0].score == 0.9

    async def test_search_no_server_filter(self, mock_embedder, mock_tool_store):
        """FlatStrategy must NOT apply any server_id filter."""
        strategy = FlatStrategy(embedder=mock_embedder, tool_store=mock_tool_store)
        await strategy.search("test", top_k=3)
        call_kwargs = mock_tool_store.search.call_args.kwargs
        assert call_kwargs.get("server_id_filter") is None

    async def test_invalid_top_k_raises(self, mock_embedder, mock_tool_store):
        strategy = FlatStrategy(embedder=mock_embedder, tool_store=mock_tool_store)
        with pytest.raises(ValueError, match="top_k must be positive"):
            await strategy.search("test", top_k=0)

    async def test_search_calls_reranker_when_provided(self, mock_embedder, mock_tool_store):
        """FlatStrategy delegates to reranker and returns reranked results."""
        reranked = [make_search_result(1, 0.95), make_search_result(0, 0.85)]
        mock_reranker = AsyncMock()
        mock_reranker.rerank = AsyncMock(return_value=reranked)

        strategy = FlatStrategy(
            embedder=mock_embedder, tool_store=mock_tool_store, reranker=mock_reranker
        )
        results = await strategy.search("find a github tool", top_k=3)

        store_results = [make_search_result(0), make_search_result(1, 0.8)]
        mock_reranker.rerank.assert_called_once_with("find a github tool", store_results, 3)
        assert results == reranked

    async def test_search_skips_reranker_when_none(self, mock_embedder, mock_tool_store):
        """When reranker is None, results come directly from the store without reranking."""
        strategy = FlatStrategy(embedder=mock_embedder, tool_store=mock_tool_store, reranker=None)
        results = await strategy.search("test query", top_k=3)

        assert len(results) == 2
        assert results[0].score == 0.9
        assert results[1].score == 0.8

    def test_registered_as_flat(self):
        assert "flat" in StrategyRegistry.list_strategies()
        assert StrategyRegistry.get("flat") is FlatStrategy

    async def test_search_uses_hybrid_when_sparse_embedder_provided(
        self, mock_embedder, mock_tool_store
    ):
        """When sparse_embedder is set, hybrid_search is called instead of search."""
        sparse_result = SparseVector(indices=[0, 5, 10], values=[0.8, 0.5, 0.3])
        mock_sparse_embedder = MagicMock()
        mock_sparse_embedder.embed_one = MagicMock(return_value=sparse_result)

        hybrid_results = [make_search_result(0, 0.95)]
        mock_tool_store.hybrid_search = AsyncMock(return_value=hybrid_results)

        strategy = FlatStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            sparse_embedder=mock_sparse_embedder,
        )
        results = await strategy.search("find a github tool", top_k=3)

        mock_sparse_embedder.embed_one.assert_called_once_with("find a github tool")
        mock_tool_store.hybrid_search.assert_called_once()
        mock_tool_store.search.assert_not_called()
        assert results == hybrid_results

    async def test_search_uses_dense_only_when_no_sparse_embedder(
        self, mock_embedder, mock_tool_store
    ):
        """When sparse_embedder is None, dense search is called (backward compatible)."""
        strategy = FlatStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            sparse_embedder=None,
        )
        await strategy.search("find a github tool", top_k=3)

        mock_tool_store.search.assert_called_once()
        assert not hasattr(mock_tool_store, "hybrid_search") or (
            not mock_tool_store.hybrid_search.called
        )
