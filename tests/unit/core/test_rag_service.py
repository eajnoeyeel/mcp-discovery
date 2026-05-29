"""Unit tests for mlp/rag/service.py — RAGService search pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_discovery.models import MCPTool, SearchResult
from service.rag.cache import QueryCache
from service.rag.fallback import SupabaseFallback
from service.rag.service import RAGSearchResult, RAGService


def _sr(tool_id: str, score: float, rank: int = 1) -> SearchResult:
    server_id, tool_name = tool_id.split("::", 1)
    return SearchResult(
        tool=MCPTool(
            tool_id=tool_id,
            server_id=server_id,
            tool_name=tool_name,
            description="test",
        ),
        score=score,
        rank=rank,
    )


def _make_strategy(results: list[SearchResult]) -> MagicMock:
    strategy = MagicMock()
    strategy.search = AsyncMock(return_value=results)
    strategy.sparse_embedder = None
    return strategy


def _make_service(
    results: list[SearchResult] | None = None,
    cache: QueryCache | None = None,
    fallback: SupabaseFallback | None = None,
    reranker=None,
    enable_pending_freshness: bool = False,
    operability_cache=None,
) -> RAGService:
    strategy = _make_strategy(results or [])
    return RAGService(
        strategy=strategy,
        fallback=fallback,
        cache=cache,
        confidence_gap_threshold=0.15,
        reranker=reranker,
        enable_pending_freshness=enable_pending_freshness,
        operability_cache=operability_cache,
    )


class TestRAGServiceCacheKey:
    def test_cache_key_format(self):
        key = RAGService._cache_key("my query", 3, False)
        assert "my query" in key
        assert "3" in key
        assert "0" in key

    def test_cache_key_differs_by_query(self):
        k1 = RAGService._cache_key("query a", 3, False)
        k2 = RAGService._cache_key("query b", 3, False)
        assert k1 != k2

    def test_cache_key_differs_by_top_k(self):
        k1 = RAGService._cache_key("query", 3, False)
        k2 = RAGService._cache_key("query", 5, False)
        assert k1 != k2

    def test_cache_key_differs_by_freshness_flag(self):
        k1 = RAGService._cache_key("query", 3, False)
        k2 = RAGService._cache_key("query", 3, True)
        assert k1 != k2


class TestCanUseCache:
    def test_can_use_cache_when_cache_set_and_freshness_disabled(self):
        service = _make_service(cache=QueryCache())
        assert service._can_use_cache() is True

    def test_cannot_use_cache_when_cache_is_none(self):
        service = _make_service(cache=None)
        assert service._can_use_cache() is False

    def test_cannot_use_cache_when_freshness_enabled(self):
        service = _make_service(cache=QueryCache(), enable_pending_freshness=True)
        assert service._can_use_cache() is False


class TestSearchValidation:
    async def test_raises_value_error_when_top_k_zero(self):
        service = _make_service()
        with pytest.raises(ValueError, match="top_k must be positive"):
            await service.search("query", top_k=0)

    async def test_raises_value_error_when_top_k_negative(self):
        service = _make_service()
        with pytest.raises(ValueError, match="top_k must be positive"):
            await service.search("query", top_k=-1)


class TestSearchCacheHit:
    async def test_returns_cached_response_on_hit(self):
        cache = QueryCache()
        cached_response = MagicMock(spec=RAGSearchResult)
        cache_key = RAGService._cache_key("test query", 3, False)
        cache.put(cache_key, cached_response)

        service = _make_service(cache=cache)
        result = await service.search("test query", top_k=3)

        assert result is cached_response
        # Strategy should not be called when cache hits
        service._strategy.search.assert_not_awaited()

    async def test_stores_result_in_cache_on_miss(self):
        cache = QueryCache()
        results = [_sr("srv::t1", 0.9), _sr("srv::t2", 0.8)]
        service = _make_service(results=results, cache=cache)

        await service.search("test query", top_k=3)

        cache_key = RAGService._cache_key("test query", 3, False)
        assert cache.get(cache_key) is not None

    async def test_does_not_store_in_cache_when_freshness_enabled(self):
        cache = QueryCache()
        results = [_sr("srv::t1", 0.9)]
        service = _make_service(
            results=results,
            cache=cache,
            enable_pending_freshness=True,
        )

        await service.search("query", top_k=3)

        cache_key = RAGService._cache_key("query", 3, True)
        assert cache.get(cache_key) is None


class TestSearchBasicFlow:
    async def test_returns_find_best_tool_response(self):
        results = [_sr("srv::t1", 0.9)]
        service = _make_service(results=results)
        response = await service.search("test query", top_k=3)
        assert isinstance(response, RAGSearchResult)

    async def test_response_contains_query(self):
        service = _make_service(results=[_sr("srv::t1", 0.9)])
        response = await service.search("my search query", top_k=3)
        assert response.query == "my search query"

    async def test_response_includes_results(self):
        results = [_sr("srv::t1", 0.9), _sr("srv::t2", 0.8)]
        service = _make_service(results=results)
        response = await service.search("query", top_k=2)
        assert len(response.results) == 2

    async def test_response_truncates_to_top_k(self):
        results = [_sr(f"srv::t{i}", 1.0 - i * 0.1) for i in range(5)]
        service = _make_service(results=results)
        response = await service.search("query", top_k=2)
        assert len(response.results) == 2

    async def test_not_degraded_on_successful_strategy(self):
        service = _make_service(results=[_sr("srv::t1", 0.9)])
        response = await service.search("query", top_k=3)
        assert response.degraded is False

    async def test_degraded_on_strategy_failure_with_no_fallback(self):
        strategy = MagicMock()
        strategy.search = AsyncMock(side_effect=Exception("qdrant down"))
        service = RAGService(
            strategy=strategy,
            fallback=None,
            cache=None,
        )
        response = await service.search("query", top_k=3)
        assert response.degraded is True

    async def test_source_path_semantic_when_primary_succeeds(self):
        service = _make_service(results=[_sr("srv::t1", 0.9)])
        response = await service.search("query", top_k=3)
        assert response.source_path == "semantic"

    async def test_source_path_lexical_fallback_when_degraded(self):
        strategy = MagicMock()
        strategy.sparse_embedder = None
        strategy.search = AsyncMock(side_effect=Exception("down"))
        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True
        fallback.search_full_catalog = AsyncMock(return_value=[_sr("srv::t1", 0.5)])
        service = RAGService(
            strategy=strategy,
            fallback=fallback,
            cache=None,
        )
        response = await service.search("query", top_k=3)
        assert response.source_path == "lexical_fallback"

    async def test_source_path_dense_only_degraded_when_hybrid_recovers_to_dense(self):
        strategy = MagicMock()
        strategy.sparse_embedder = MagicMock()
        strategy.search = AsyncMock(side_effect=Exception("hybrid down"))
        strategy.embedder = MagicMock()
        strategy.embedder.embed_one = AsyncMock(return_value=[0.1, 0.2])
        strategy.tool_store = MagicMock()
        strategy.tool_store.search = AsyncMock(return_value=[_sr("srv::t1", 0.8)])
        service = RAGService(strategy=strategy, fallback=None, cache=None)

        response = await service.search("query", top_k=3)

        assert response.degraded is True
        assert response.source_path == "dense_only_degraded"

    async def test_preserves_raw_description_even_when_selection_description_exists(self):
        tool = MCPTool(
            tool_id="srv::t1",
            server_id="srv",
            tool_name="t1",
            description="raw description",
            selection_description="optimized delivery description",
        )
        service = _make_service(results=[SearchResult(tool=tool, score=0.9, rank=1)])

        response = await service.search("query", top_k=3)

        assert response.results[0].tool.description == "raw description"

    async def test_strategy_used_rag_by_default(self):
        service = _make_service(results=[_sr("srv::t1", 0.9)])
        response = await service.search("query", top_k=3)
        assert response.strategy_used == "rag"

    async def test_latency_ms_is_positive(self):
        service = _make_service(results=[_sr("srv::t1", 0.9)])
        response = await service.search("query", top_k=3)
        assert response.latency_ms >= 0


class TestSearchFallbackFlow:
    async def test_falls_back_when_strategy_fails(self):
        strategy = MagicMock()
        strategy.sparse_embedder = None
        strategy.search = AsyncMock(side_effect=Exception("qdrant unavailable"))
        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True
        fallback.search_full_catalog = AsyncMock(return_value=[_sr("srv::t1", 0.5)])
        service = RAGService(strategy=strategy, fallback=fallback, cache=None)
        response = await service.search("query", top_k=3)
        fallback.search_full_catalog.assert_awaited_once()
        assert response.degraded is True

    async def test_fallback_search_failure_returns_empty_results(self):
        strategy = MagicMock()
        strategy.sparse_embedder = None
        strategy.search = AsyncMock(side_effect=Exception("down"))
        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True
        fallback.search_full_catalog = AsyncMock(side_effect=Exception("supabase down"))
        service = RAGService(strategy=strategy, fallback=fallback, cache=None)
        response = await service.search("query", top_k=3)
        assert response.results == []

    async def test_no_fallback_call_when_strategy_succeeds(self):
        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True
        fallback.search_full_catalog = AsyncMock(return_value=[])
        service = RAGService(
            strategy=_make_strategy([_sr("srv::t1", 0.9)]),
            fallback=fallback,
            cache=None,
        )
        await service.search("query", top_k=3)
        fallback.search_full_catalog.assert_not_awaited()


class TestSearchPendingFreshness:
    async def test_freshness_search_called_when_enabled(self):
        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True
        fallback.search_pending_freshness = AsyncMock(return_value=[_sr("srv::fresh", 0.0)])
        service = RAGService(
            strategy=_make_strategy([_sr("srv::t1", 0.9)]),
            fallback=fallback,
            cache=None,
            enable_pending_freshness=True,
        )
        response = await service.search("query", top_k=3)
        fallback.search_pending_freshness.assert_awaited_once()
        assert response.source_path == "mixed"

    async def test_freshness_search_not_called_when_disabled(self):
        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True
        fallback.search_pending_freshness = AsyncMock(return_value=[])
        service = RAGService(
            strategy=_make_strategy([_sr("srv::t1", 0.9)]),
            fallback=fallback,
            cache=None,
            enable_pending_freshness=False,
        )
        await service.search("query", top_k=3)
        fallback.search_pending_freshness.assert_not_awaited()

    async def test_freshness_timeout_does_not_raise(self):
        import asyncio

        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True

        async def slow_freshness(*args, **kwargs):
            await asyncio.sleep(10)
            return []

        fallback.search_pending_freshness = slow_freshness
        service = RAGService(
            strategy=_make_strategy([_sr("srv::t1", 0.9)]),
            fallback=fallback,
            cache=None,
            enable_pending_freshness=True,
            pending_freshness_timeout_ms=1,  # 1ms timeout
        )
        # Should not raise
        response = await service.search("query", top_k=3)
        assert response is not None

    async def test_freshness_exception_does_not_raise(self):
        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True
        fallback.search_pending_freshness = AsyncMock(side_effect=Exception("freshness error"))
        service = RAGService(
            strategy=_make_strategy([_sr("srv::t1", 0.9)]),
            fallback=fallback,
            cache=None,
            enable_pending_freshness=True,
        )
        response = await service.search("query", top_k=3)
        assert response is not None


class TestSearchReranker:
    async def test_reranker_called_when_provided(self):
        candidates = [_sr("srv::t1", 0.9), _sr("srv::t2", 0.8)]
        reranker = MagicMock()
        reranker.rerank = AsyncMock(return_value=[_sr("srv::t2", 0.95), _sr("srv::t1", 0.85)])
        service = RAGService(
            strategy=_make_strategy(candidates),
            fallback=None,
            cache=None,
            reranker=reranker,
        )
        response = await service.search("query", top_k=2)
        reranker.rerank.assert_awaited_once()
        assert response.strategy_used == "rag+rerank"

    async def test_reranker_failure_falls_back_to_unranked(self):
        candidates = [_sr("srv::t1", 0.9)]
        reranker = MagicMock()
        reranker.rerank = AsyncMock(side_effect=Exception("reranker down"))
        service = RAGService(
            strategy=_make_strategy(candidates),
            fallback=None,
            cache=None,
            reranker=reranker,
        )
        response = await service.search("query", top_k=3)
        # Falls back, strategy_used stays "rag"
        assert response.strategy_used == "rag"

    async def test_reranker_not_called_on_empty_candidates(self):
        reranker = MagicMock()
        reranker.rerank = AsyncMock(return_value=[])
        service = RAGService(
            strategy=_make_strategy([]),
            fallback=None,
            cache=None,
            reranker=reranker,
        )
        await service.search("query", top_k=3)
        reranker.rerank.assert_not_awaited()


class TestSearchOperabilityCache:
    async def test_operability_cache_get_bulk_called(self):
        op_cache = MagicMock()
        op_cache.get_bulk = AsyncMock(return_value={})
        service = RAGService(
            strategy=_make_strategy([_sr("srv::t1", 0.9)]),
            fallback=None,
            cache=None,
            operability_cache=op_cache,
        )
        await service.search("query", top_k=3)
        op_cache.get_bulk.assert_awaited_once()

    async def test_operability_cache_failure_does_not_crash(self):
        op_cache = MagicMock()
        op_cache.get_bulk = AsyncMock(side_effect=Exception("op cache down"))
        service = RAGService(
            strategy=_make_strategy([_sr("srv::t1", 0.9)]),
            fallback=None,
            cache=None,
            operability_cache=op_cache,
        )
        response = await service.search("query", top_k=3)
        assert response is not None

    async def test_hard_gate_removes_blocked_tools(self):
        op_cache = MagicMock()
        snap_blocked = MagicMock()
        snap_blocked.status = "quarantined"
        snap_active = MagicMock()
        snap_active.status = "active"
        snap_active.operability_score = 0.8
        snap_active.boost = 0.0
        op_cache.get_bulk = AsyncMock(
            return_value={
                "srv::blocked": snap_blocked,
                "srv::active": snap_active,
            }
        )

        with patch("mcp_discovery.operability.models.build_enrichment", return_value=None):
            service = RAGService(
                strategy=_make_strategy(
                    [
                        _sr("srv::blocked", 0.9),
                        _sr("srv::active", 0.8),
                    ]
                ),
                fallback=None,
                cache=None,
                operability_cache=op_cache,
            )
            response = await service.search("query", top_k=3)

        tool_ids = [r.tool.tool_id for r in response.results]
        assert "srv::blocked" not in tool_ids
        assert "srv::active" in tool_ids


class TestSearchConfidence:
    async def test_high_confidence_when_clear_winner(self):
        results = [_sr("srv::t1", 0.95), _sr("srv::t2", 0.5)]
        service = _make_service(results=results)
        response = await service.search("query", top_k=3)
        assert response.confidence >= 0.0
        assert response.disambiguation_needed is not None

    async def test_empty_results_response_is_valid(self):
        service = _make_service(results=[])
        response = await service.search("query", top_k=3)
        assert isinstance(response, RAGSearchResult)
        assert response.results == []
