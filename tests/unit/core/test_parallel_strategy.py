"""Tests for ParallelStrategy -- 2-Layer parallel search + RRF fusion."""

from unittest.mock import AsyncMock

import numpy as np
import pytest
from qdrant_client.models import FieldCondition, Filter, MatchAny

from mcp_discovery.models import MCPTool, SearchResult
from mcp_discovery.pipeline.parallel import ParallelStrategy
from mcp_discovery.pipeline.strategy import StrategyRegistry


def make_tool(server_id: str, name: str = "tool") -> MCPTool:
    return MCPTool(
        server_id=server_id,
        tool_name=name,
        tool_id=f"{server_id}::{name}",
    )


def make_result(server_id: str, name: str = "tool", score: float = 0.9) -> SearchResult:
    return SearchResult(tool=make_tool(server_id, name), score=score, rank=1)


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed_one = AsyncMock(return_value=np.zeros(1536))
    return embedder


@pytest.fixture
def mock_server_store():
    store = AsyncMock()
    store.search_server_ids = AsyncMock(return_value=["srv1", "srv2"])
    return store


@pytest.fixture
def mock_tool_store():
    """Returns global tool results first, then candidate-server-only results."""
    store = AsyncMock()
    store.search = AsyncMock(
        side_effect=[
            [
                make_result("srv1", "tool_a", score=0.9),
                make_result("srv3", "tool_c", score=0.85),
                make_result("srv2", "tool_b", score=0.8),
                make_result("srv4", "tool_d", score=0.7),
            ],
            [
                make_result("srv1", "tool_a", score=0.9),
                make_result("srv2", "tool_b", score=0.8),
            ],
        ]
    )
    return store


@pytest.fixture
def mock_tool_store_no_server_matches():
    store = AsyncMock()
    store.search = AsyncMock(
        side_effect=[
            [
                make_result("srv1", "tool_a", score=0.9),
                make_result("srv3", "tool_c", score=0.85),
                make_result("srv2", "tool_b", score=0.8),
                make_result("srv4", "tool_d", score=0.7),
            ],
            [],
        ]
    )
    return store


class TestParallelStrategy:
    async def test_embeds_query_once(self, mock_embedder, mock_server_store, mock_tool_store):
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
        )
        await strategy.search("find github tool", top_k=3)
        mock_embedder.embed_one.assert_called_once_with("find github tool")

    async def test_calls_tool_and_server_search(
        self, mock_embedder, mock_server_store, mock_tool_store
    ):
        """Both tool_store.search and server_store.search_server_ids must be called."""
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
        )
        await strategy.search("test", top_k=3)
        assert mock_tool_store.search.await_count == 2
        mock_server_store.search_server_ids.assert_called_once()

    async def test_tool_search_unfiltered(self, mock_embedder, mock_server_store, mock_tool_store):
        """Tool search must NOT use server_id_filter (unlike Sequential)."""
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
        )
        await strategy.search("test", top_k=3)
        call_kwargs = mock_tool_store.search.await_args_list[0].kwargs
        assert call_kwargs.get("server_id_filter") is None

    async def test_server_matched_tools_rank_higher(
        self, mock_embedder, mock_server_store, mock_tool_store
    ):
        """Tools from matching servers (srv1, srv2) should rank higher via RRF boost."""
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
        )
        results = await strategy.search("test", top_k=4)
        tool_ids = [r.tool.tool_id for r in results]
        # srv1::tool_a and srv2::tool_b appear in both RRF lists -> boosted
        # They should appear before srv3::tool_c and srv4::tool_d
        srv_matched_positions = [
            i for i, tid in enumerate(tool_ids) if tid in ("srv1::tool_a", "srv2::tool_b")
        ]
        srv_unmatched_positions = [
            i for i, tid in enumerate(tool_ids) if tid in ("srv3::tool_c", "srv4::tool_d")
        ]
        assert max(srv_matched_positions) < min(srv_unmatched_positions)

    async def test_non_matching_tools_still_returned(
        self, mock_embedder, mock_server_store, mock_tool_store
    ):
        """Unlike Sequential, tools from non-candidate servers are NOT excluded."""
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
        )
        results = await strategy.search("test", top_k=4)
        tool_ids = {r.tool.tool_id for r in results}
        assert "srv3::tool_c" in tool_ids
        assert "srv4::tool_d" in tool_ids

    async def test_candidate_server_search_uses_server_filter(
        self, mock_embedder, mock_server_store, mock_tool_store
    ):
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
        )
        await strategy.search("test", top_k=3)

        second_call = mock_tool_store.search.await_args_list[1].kwargs
        query_filter = second_call["query_filter"]
        assert isinstance(query_filter, Filter)
        assert query_filter.must == [
            FieldCondition(key="server_id", match=MatchAny(any=["srv1", "srv2"]))
        ]

    async def test_candidate_server_search_recovers_missing_tool(
        self, mock_embedder, mock_server_store
    ):
        tool_store = AsyncMock()
        tool_store.search = AsyncMock(
            side_effect=[
                [
                    make_result("srvX", "wrong_1", score=0.95),
                    make_result("srvY", "wrong_2", score=0.94),
                ],
                [make_result("srv1", "recovered", score=0.91)],
            ]
        )
        server_store = AsyncMock()
        server_store.search_server_ids = AsyncMock(return_value=["srv1"])

        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=tool_store,
            server_store=server_store,
        )
        results = await strategy.search("test", top_k=3)

        tool_ids = [r.tool.tool_id for r in results]
        assert "srv1::recovered" in tool_ids
        assert tool_store.search.await_count == 2

    async def test_top_k_limits_results(self, mock_embedder, mock_server_store, mock_tool_store):
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
        )
        results = await strategy.search("test", top_k=2)
        assert len(results) == 2

    async def test_ranks_are_sequential(self, mock_embedder, mock_server_store, mock_tool_store):
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
        )
        results = await strategy.search("test", top_k=4)
        for i, r in enumerate(results):
            assert r.rank == i + 1

    async def test_scores_are_rrf_scores(self, mock_embedder, mock_server_store, mock_tool_store):
        """Result scores should be RRF scores, not original Qdrant scores."""
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
        )
        results = await strategy.search("test", top_k=4)
        # RRF scores are much smaller than original Qdrant scores (which were 0.7-0.9)
        for r in results:
            assert r.score < 0.5  # RRF scores with k=60 are ~0.03 max

    async def test_invalid_top_k_raises(self, mock_embedder, mock_server_store, mock_tool_store):
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
        )
        with pytest.raises(ValueError, match="top_k must be positive"):
            await strategy.search("test", top_k=0)

    async def test_empty_tool_results(self, mock_embedder, mock_server_store):
        tool_store = AsyncMock()
        tool_store.search = AsyncMock(return_value=[])
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=tool_store,
            server_store=mock_server_store,
        )
        results = await strategy.search("test", top_k=3)
        assert results == []

    async def test_empty_server_results_still_returns_tools(self, mock_embedder, mock_tool_store):
        """Empty server results = List B is empty, but List A still has all tools."""
        server_store = AsyncMock()
        server_store.search_server_ids = AsyncMock(return_value=[])
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=server_store,
        )
        results = await strategy.search("test", top_k=3)
        # Still returns tools from the unfiltered search (List A only)
        assert len(results) == 3
        assert mock_tool_store.search.await_count == 1

    async def test_empty_candidate_server_tool_results_keep_global_results(
        self, mock_embedder, mock_server_store, mock_tool_store_no_server_matches
    ):
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store_no_server_matches,
            server_store=mock_server_store,
        )
        results = await strategy.search("test", top_k=4)
        tool_ids = {r.tool.tool_id for r in results}
        assert tool_ids == {"srv1::tool_a", "srv2::tool_b", "srv3::tool_c", "srv4::tool_d"}

    async def test_search_calls_reranker_when_provided(
        self, mock_embedder, mock_server_store, mock_tool_store
    ):
        """When reranker is provided, it must be called with (query, rrf_results, top_k)."""
        mock_reranker = AsyncMock()
        reranked = [make_result("srv1", "tool_a", score=0.95)]
        mock_reranker.rerank = AsyncMock(return_value=reranked)

        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
            reranker=mock_reranker,
        )
        results = await strategy.search("find github tool", top_k=3)

        mock_reranker.rerank.assert_called_once()
        call_args = mock_reranker.rerank.call_args
        assert call_args[0][0] == "find github tool"  # query
        assert len(call_args[0][1]) == 3  # fused top_k results passed to reranker
        assert call_args[0][2] == 3  # top_k
        assert results == reranked

    async def test_search_skips_reranker_when_none(
        self, mock_embedder, mock_server_store, mock_tool_store
    ):
        """When reranker is None, RRF results are returned unchanged."""
        strategy = ParallelStrategy(
            embedder=mock_embedder,
            tool_store=mock_tool_store,
            server_store=mock_server_store,
            reranker=None,
        )
        results = await strategy.search("test", top_k=4)
        assert len(results) == 4

    def test_registered_as_parallel(self):
        assert "parallel" in StrategyRegistry.list_strategies()
        assert StrategyRegistry.get("parallel") is ParallelStrategy
