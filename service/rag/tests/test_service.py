"""Tests for RAGService orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_discovery.models import SearchResult
from mcp_discovery.reranking.base import Reranker
from service.rag.cache import QueryCache
from service.rag.fallback import SupabaseFallback
from service.rag.service import RAGSearchResult, RAGService
from service.rag.tests.conftest import make_result


def _mock_strategy(results: list[SearchResult] | None = None) -> AsyncMock:
    strategy = AsyncMock()
    strategy.search = AsyncMock(return_value=results or [])
    # Prevent AsyncMock from auto-creating sparse_embedder, which would make
    # RAGService detect hybrid mode and emit hybrid_semantic source_path.
    strategy.sparse_embedder = None
    return strategy


def _mock_fallback(results: list[SearchResult] | None = None) -> MagicMock:
    results = results or []
    fb = MagicMock(spec=SupabaseFallback)
    fb.is_configured = True
    fb.search = AsyncMock(return_value=results)
    fb.search_full_catalog = AsyncMock(return_value=results)
    fb.search_pending_freshness = AsyncMock(return_value=[])
    return fb


class TestRAGService:
    @pytest.fixture
    def service(self):
        return RAGService(
            strategy=_mock_strategy(
                [
                    make_result(tool_name="tool_a", score=0.95, rank=1),
                    make_result(tool_name="tool_b", score=0.70, rank=2),
                ]
            ),
            fallback=_mock_fallback([]),
            cache=QueryCache(ttl_seconds=300),
            confidence_gap_threshold=0.15,
        )

    async def test_search_returns_response(self, service):
        resp = await service.search("find a tool", top_k=3)
        assert isinstance(resp, RAGSearchResult)
        assert resp.query == "find a tool"
        assert len(resp.results) == 2
        assert resp.strategy_used == "rag"

    async def test_search_uses_cache_for_identical_query_and_top_k(self, service):
        await service.search("cached query", top_k=3)
        await service.search("cached query", top_k=3)
        service._strategy.search.assert_called_once()

    async def test_cache_isolated_by_top_k(self):
        strategy = _mock_strategy([make_result(tool_name="tool_a", score=0.9, rank=1)])
        service = RAGService(
            strategy=strategy,
            fallback=_mock_fallback([]),
            cache=QueryCache(ttl_seconds=300),
            confidence_gap_threshold=0.15,
        )
        await service.search("query", top_k=3)
        await service.search("query", top_k=5)
        assert strategy.search.await_count == 2

    async def test_cache_bypassed_when_freshness_enabled(self):
        strategy = _mock_strategy([make_result(tool_name="tool_a", score=0.9, rank=1)])
        service = RAGService(
            strategy=strategy,
            fallback=_mock_fallback([]),
            cache=QueryCache(ttl_seconds=300),
            confidence_gap_threshold=0.15,
            enable_pending_freshness=True,
        )
        await service.search("query", top_k=3)
        await service.search("query", top_k=3)
        assert strategy.search.await_count == 2

    async def test_search_no_fallback_when_primary_ok(self):
        primary = [make_result(tool_name="tool_a", score=0.9, rank=1)]
        fb = _mock_fallback([make_result(tool_name="fb_tool", score=0.0, rank=1)])
        service = RAGService(
            strategy=_mock_strategy(primary),
            fallback=fb,
            cache=None,
            confidence_gap_threshold=0.15,
        )
        resp = await service.search("query", top_k=3)
        tool_names = [r.tool.tool_name for r in resp.results]
        assert "tool_a" in tool_names
        assert "fb_tool" not in tool_names
        fb.search_full_catalog.assert_not_awaited()

    async def test_search_merges_fallback_in_degraded_mode(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(side_effect=Exception("Qdrant down"))
        fallback_results = [make_result(tool_name="fb_tool", score=0.0, rank=1)]
        service = RAGService(
            strategy=strategy,
            fallback=_mock_fallback(fallback_results),
            cache=None,
            confidence_gap_threshold=0.15,
        )
        resp = await service.search("query", top_k=3)
        tool_names = [r.tool.tool_name for r in resp.results]
        assert "fb_tool" in tool_names

    async def test_strategy_uses_candidate_pool_larger_than_top_k(self):
        strategy = _mock_strategy([make_result(tool_name="tool_a", score=0.9, rank=1)])
        service = RAGService(
            strategy=strategy,
            fallback=_mock_fallback([]),
            cache=None,
            confidence_gap_threshold=0.15,
            rerank_candidate_pool_size=10,
        )
        await service.search("query", top_k=3)
        strategy.search.assert_awaited_once_with("query", 10)

    async def test_reranker_called_after_merge(self):
        primary = [make_result(tool_name="qdrant_tool", score=0.9, rank=1)]
        fresh = [make_result(tool_name="fresh_tool", score=0.0, rank=1)]
        reranked = [make_result(tool_name="fresh_tool", score=0.99, rank=1)]
        fb = _mock_fallback([])
        fb.search_pending_freshness = AsyncMock(return_value=fresh)
        reranker = AsyncMock(spec=Reranker)
        reranker.rerank = AsyncMock(return_value=reranked)

        service = RAGService(
            strategy=_mock_strategy(primary),
            fallback=fb,
            cache=None,
            confidence_gap_threshold=0.15,
            reranker=reranker,
            enable_pending_freshness=True,
            pending_freshness_limit=2,
        )
        resp = await service.search("query", top_k=3)

        reranker.rerank.assert_awaited_once()
        call_args = reranker.rerank.await_args
        assert call_args.args[0] == "query"
        candidate_names = [item.tool.tool_name for item in call_args.args[1]]
        assert candidate_names == ["qdrant_tool", "fresh_tool"]
        assert call_args.args[2] == 3
        assert resp.results[0].tool.tool_name == "fresh_tool"
        assert resp.strategy_used == "rag+rerank"

    async def test_reranker_not_called_when_none(self):
        service = RAGService(
            strategy=_mock_strategy([make_result(score=0.9)]),
            fallback=_mock_fallback([]),
            cache=None,
            confidence_gap_threshold=0.15,
            reranker=None,
        )
        resp = await service.search("query", top_k=3)
        assert resp.strategy_used == "rag"

    async def test_reranker_fallback_to_original_on_error(self):
        reranker = AsyncMock(spec=Reranker)
        reranker.rerank = AsyncMock(side_effect=Exception("Cohere API down"))

        primary = [make_result(tool_name="original_tool", score=0.9, rank=1)]
        service = RAGService(
            strategy=_mock_strategy(primary),
            fallback=_mock_fallback([]),
            cache=None,
            confidence_gap_threshold=0.15,
            reranker=reranker,
        )
        resp = await service.search("query", top_k=3)
        assert resp.results[0].tool.tool_name == "original_tool"
        assert resp.strategy_used == "rag"

    async def test_pending_freshness_called_in_normal_path_when_enabled(self):
        primary = [make_result(tool_name="qdrant_tool", score=0.9, rank=1)]
        fresh = [make_result(tool_name="fresh_pending_tool", score=0.0, rank=1)]
        fb = _mock_fallback([])
        fb.search_pending_freshness = AsyncMock(return_value=fresh)

        service = RAGService(
            strategy=_mock_strategy(primary),
            fallback=fb,
            cache=None,
            confidence_gap_threshold=0.15,
            enable_pending_freshness=True,
            pending_freshness_limit=5,
        )
        resp = await service.search("query", top_k=5)
        fb.search_pending_freshness.assert_awaited_once_with("query", limit=5)
        fb.search_full_catalog.assert_not_awaited()
        tool_names = [r.tool.tool_name for r in resp.results]
        assert "qdrant_tool" in tool_names
        assert "fresh_pending_tool" in tool_names

    async def test_pending_freshness_not_called_when_disabled(self):
        primary = [make_result(tool_name="qdrant_tool", score=0.9, rank=1)]
        fb = _mock_fallback([])

        service = RAGService(
            strategy=_mock_strategy(primary),
            fallback=fb,
            cache=None,
            confidence_gap_threshold=0.15,
            enable_pending_freshness=False,
        )
        await service.search("query", top_k=3)
        fb.search_pending_freshness.assert_not_awaited()

    async def test_search_confidence_clear_winner(self, service):
        resp = await service.search("query", top_k=3)
        assert resp.disambiguation_needed is False
        assert resp.confidence == 0.95

    async def test_search_confidence_ambiguous(self):
        close_results = [
            make_result(tool_name="a", score=0.90, rank=1),
            make_result(tool_name="b", score=0.88, rank=2),
        ]
        service = RAGService(
            strategy=_mock_strategy(close_results),
            fallback=_mock_fallback([]),
            cache=None,
            confidence_gap_threshold=0.15,
        )
        resp = await service.search("query", top_k=3)
        assert resp.disambiguation_needed is True

    async def test_search_degraded_mode_on_strategy_error(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(side_effect=Exception("Qdrant down"))
        fb_results = [make_result(tool_name="fb_only", score=0.0, rank=1)]
        service = RAGService(
            strategy=strategy,
            fallback=_mock_fallback(fb_results),
            cache=None,
            confidence_gap_threshold=0.15,
        )
        resp = await service.search("query", top_k=3)
        assert len(resp.results) == 1
        assert resp.results[0].tool.tool_name == "fb_only"

    async def test_search_no_cache(self):
        service = RAGService(
            strategy=_mock_strategy([make_result(score=0.9)]),
            fallback=_mock_fallback([]),
            cache=None,
            confidence_gap_threshold=0.15,
        )
        resp = await service.search("query", top_k=3)
        assert isinstance(resp, RAGSearchResult)

    async def test_search_latency_recorded(self, service):
        resp = await service.search("query", top_k=3)
        assert resp.latency_ms >= 0

    async def test_search_rejects_non_positive_top_k(self):
        service = RAGService(
            strategy=_mock_strategy([make_result(score=0.9)]),
            fallback=_mock_fallback([]),
            cache=None,
            confidence_gap_threshold=0.15,
        )
        with pytest.raises(ValueError, match="top_k must be positive"):
            await service.search("query", top_k=0)


# ===================================================================
# Provenance propagation tests (Task 2)
# ===================================================================


class TestProvenancePropagation:
    """Verify degraded flag and source_path are set correctly on FindBestToolResponse."""

    async def test_degraded_flag_propagated_when_strategy_fails(self):
        """When strategy raises, response.degraded=True and source_path='lexical_fallback'."""
        strategy = AsyncMock()
        strategy.sparse_embedder = None  # non-hybrid strategy fixture
        strategy.search = AsyncMock(side_effect=RuntimeError("Qdrant down"))

        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True
        fallback.search_full_catalog = AsyncMock(
            return_value=[make_result(tool_name="tool1", score=0.5, rank=1)]
        )
        fallback.search_pending_freshness = AsyncMock(return_value=[])

        svc = RAGService(
            strategy=strategy,
            fallback=fallback,
            cache=None,
            reranker=None,
        )
        resp = await svc.search("test query", top_k=3)
        assert resp.degraded is True
        assert resp.source_path == "lexical_fallback"

    async def test_source_path_semantic_when_strategy_succeeds(self):
        """When strategy succeeds without fallback, source_path='semantic'."""
        strategy = AsyncMock()
        strategy.sparse_embedder = None  # non-hybrid strategy fixture
        strategy.search = AsyncMock(return_value=[make_result(tool_name="tool1", score=0.9)])

        svc = RAGService(
            strategy=strategy,
            fallback=None,
            cache=None,
            reranker=None,
        )
        resp = await svc.search("test query", top_k=3)
        assert resp.degraded is False
        assert resp.source_path == "semantic"

    async def test_source_path_mixed_when_freshness_contributes(self):
        """When freshness results are merged, source_path='mixed'."""
        strategy = AsyncMock()
        strategy.sparse_embedder = None  # non-hybrid strategy fixture
        strategy.search = AsyncMock(return_value=[make_result(tool_name="tool1", score=0.9)])

        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True
        fallback.search_pending_freshness = AsyncMock(
            return_value=[make_result(tool_name="tool2", score=0.4, rank=2)]
        )
        fallback.search_full_catalog = AsyncMock(return_value=[])

        svc = RAGService(
            strategy=strategy,
            fallback=fallback,
            cache=None,
            reranker=None,
            enable_pending_freshness=True,
        )
        resp = await svc.search("test query", top_k=3)
        assert resp.degraded is False
        assert resp.source_path == "mixed"


# ===================================================================
# Stage-level timing tests (Task 6)
# ===================================================================


@pytest.mark.asyncio
async def test_response_includes_valid_latency():
    """Response latency_ms is non-negative (mocked I/O may resolve sub-millisecond)."""
    strategy = AsyncMock()
    strategy.search.return_value = [make_result(tool_name="tool1", score=0.9)]
    svc = RAGService(strategy=strategy, fallback=None, cache=None, reranker=None)
    resp = await svc.search("test query", top_k=3)
    assert resp.latency_ms >= 0
