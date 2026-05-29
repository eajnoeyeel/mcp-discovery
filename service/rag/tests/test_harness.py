"""E2E test harness for the RAG pipeline."""

from unittest.mock import AsyncMock, MagicMock

from mcp_discovery.reranking.base import Reranker
from service.rag.cache import QueryCache
from service.rag.fallback import SupabaseFallback
from service.rag.service import RAGSearchResult, RAGService
from service.rag.tests.conftest import make_result


def _build_service(
    strategy_results=None,
    strategy_error=None,
    fallback_results=None,
    cache_ttl=0,
    gap_threshold=0.15,
    reranker=None,
    enable_pending_freshness=False,
    pending_freshness_results=None,
    rerank_candidate_pool_size=10,
):
    strategy = AsyncMock()
    if strategy_error is not None:
        strategy.search = AsyncMock(side_effect=strategy_error)
    else:
        strategy.search = AsyncMock(return_value=strategy_results or [])
    # Prevent AsyncMock from auto-creating sparse_embedder, which would make
    # RAGService detect hybrid mode and emit hybrid_semantic source_path.
    strategy.sparse_embedder = None

    fallback = None
    if fallback_results is not None or pending_freshness_results is not None:
        fallback = MagicMock(spec=SupabaseFallback)
        fallback.is_configured = True
        fallback.search = AsyncMock(return_value=fallback_results or [])
        fallback.search_full_catalog = AsyncMock(return_value=fallback_results or [])
        fallback.search_pending_freshness = AsyncMock(return_value=pending_freshness_results or [])

    cache = QueryCache(ttl_seconds=cache_ttl) if cache_ttl > 0 else None

    return RAGService(
        strategy=strategy,
        fallback=fallback,
        cache=cache,
        confidence_gap_threshold=gap_threshold,
        reranker=reranker,
        enable_pending_freshness=enable_pending_freshness,
        rerank_candidate_pool_size=rerank_candidate_pool_size,
    )


class TestRAGHarness:
    async def test_happy_path_single_clear_winner(self):
        service = _build_service(
            strategy_results=[
                make_result(tool_name="github_search", server_id="github", score=0.95, rank=1),
                make_result(tool_name="gitlab_search", server_id="gitlab", score=0.60, rank=2),
            ],
        )
        resp = await service.search("search GitHub repos", top_k=3)

        assert isinstance(resp, RAGSearchResult)
        assert resp.results[0].tool.tool_name == "github_search"
        assert resp.confidence == 0.95
        assert resp.disambiguation_needed is False
        assert resp.latency_ms >= 0

    async def test_happy_path_no_fallback_when_primary_ok(self):
        service = _build_service(
            strategy_results=[make_result(tool_name="tool_a", server_id="srv1", score=0.9, rank=1)],
            fallback_results=[make_result(tool_name="tool_b", server_id="srv2", score=0.0, rank=1)],
        )
        resp = await service.search("find tools", top_k=5)

        assert len(resp.results) == 1
        assert resp.results[0].tool.tool_name == "tool_a"

    async def test_degraded_mode_fallback_merge_dedup(self):
        service = _build_service(
            strategy_error=Exception("Qdrant down"),
            fallback_results=[
                make_result(tool_name="tool_b", server_id="srv2", score=0.0, rank=1),
                make_result(tool_name="tool_a", server_id="srv1", score=0.3, rank=2),
            ],
        )
        resp = await service.search("find tools", top_k=5)

        assert len(resp.results) == 2
        assert resp.results[0].tool.tool_name == "tool_a"

    async def test_reranking_applied_after_merge(self):
        primary = [make_result(tool_name="embedding_hit", score=0.8, rank=1)]
        pending = [make_result(tool_name="pending_hit", score=0.0, rank=1)]
        reranked = [make_result(tool_name="pending_hit", score=0.97, rank=1)]
        reranker = AsyncMock(spec=Reranker)
        reranker.rerank = AsyncMock(return_value=reranked)

        service = _build_service(
            strategy_results=primary,
            fallback_results=[],
            reranker=reranker,
            enable_pending_freshness=True,
            pending_freshness_results=pending,
        )
        resp = await service.search("find a GitHub search tool", top_k=3)

        reranker.rerank.assert_awaited_once()
        candidate_names = [item.tool.tool_name for item in reranker.rerank.await_args.args[1]]
        assert candidate_names == ["embedding_hit", "pending_hit"]
        assert resp.results[0].score == 0.97
        assert resp.strategy_used == "rag+rerank"

    async def test_pending_freshness_supplements_results_in_normal_mode(self):
        primary = [make_result(tool_name="indexed_tool", score=0.9, rank=1)]
        fresh_pending = [make_result(tool_name="brand_new_tool", score=0.0, rank=1)]

        service = _build_service(
            strategy_results=primary,
            fallback_results=[],
            enable_pending_freshness=True,
            pending_freshness_results=fresh_pending,
        )
        resp = await service.search("need the newest tool", top_k=5)
        tool_names = [r.tool.tool_name for r in resp.results]
        assert "indexed_tool" in tool_names
        assert "brand_new_tool" in tool_names

    async def test_reranker_error_falls_back_gracefully(self):
        primary = [make_result(tool_name="safe_tool", score=0.85, rank=1)]
        reranker = AsyncMock(spec=Reranker)
        reranker.rerank = AsyncMock(side_effect=Exception("Cohere timeout"))

        service = _build_service(strategy_results=primary, fallback_results=[], reranker=reranker)
        resp = await service.search("safe query", top_k=3)
        assert resp.results[0].tool.tool_name == "safe_tool"
        assert resp.strategy_used == "rag"

    async def test_cache_hit_skips_search(self):
        service = _build_service(strategy_results=[make_result(score=0.9)], cache_ttl=300)
        resp1 = await service.search("cached query", top_k=3)
        resp2 = await service.search("cached query", top_k=3)

        assert resp1.query == resp2.query
        assert resp1.results == resp2.results
        service._strategy.search.assert_called_once()

    async def test_confidence_clear_gap(self):
        service = _build_service(
            strategy_results=[
                make_result(tool_name="a", score=0.95, rank=1),
                make_result(tool_name="b", score=0.50, rank=2),
            ],
            gap_threshold=0.15,
        )
        resp = await service.search("clear query", top_k=3)
        assert resp.disambiguation_needed is False

    async def test_confidence_ambiguous_gap(self):
        service = _build_service(
            strategy_results=[
                make_result(tool_name="a", score=0.90, rank=1),
                make_result(tool_name="b", score=0.89, rank=2),
            ],
            gap_threshold=0.15,
        )
        resp = await service.search("ambiguous query", top_k=3)
        assert resp.disambiguation_needed is True

    async def test_empty_results(self):
        service = _build_service(strategy_results=[], fallback_results=[])
        resp = await service.search("obscure query", top_k=3)
        assert resp.results == []
        assert resp.confidence == 0.0
        assert resp.disambiguation_needed is True

    async def test_single_result_no_disambiguation(self):
        service = _build_service(
            strategy_results=[make_result(tool_name="only_one", score=0.8, rank=1)]
        )
        resp = await service.search("specific query", top_k=1)
        assert len(resp.results) == 1
        assert resp.disambiguation_needed is False

    async def test_top_k_respected(self):
        many_results = [
            make_result(tool_name=f"tool_{i}", score=1.0 - i * 0.05, rank=i + 1) for i in range(10)
        ]
        service = _build_service(strategy_results=many_results)
        resp = await service.search("query", top_k=3)
        assert len(resp.results) == 3
