"""Factory for building RAGService from configuration."""

from mcp_discovery.pipeline.strategy import PipelineStrategy
from mcp_discovery.reranking.base import Reranker
from service.rag.cache import QueryCache
from service.rag.fallback import SupabaseFallback
from service.rag.service import RAGService


class RAGServiceFactory:
    """Builds a RAGService from explicit parameters."""

    @staticmethod
    def create(
        strategy: PipelineStrategy,
        supabase_url: str = "",
        supabase_key: str = "",
        cache_ttl: int = 300,
        confidence_gap_threshold: float = 0.15,
        reranker: Reranker | None = None,
        enable_pending_freshness: bool = False,
        enable_per_client_routing: bool = False,
        rerank_candidate_pool_size: int = 10,
        pending_freshness_limit: int = 2,
        pending_freshness_timeout_ms: int = 150,
        operability_cache: object | None = None,
        w_relevance: float = 0.75,
        w_operability: float = 0.25,
        min_boost_relevance: float = 0.3,
    ) -> RAGService:
        fallback = SupabaseFallback(
            supabase_url=supabase_url,
            supabase_key=supabase_key,
        )
        cache = QueryCache(ttl_seconds=cache_ttl) if cache_ttl > 0 else None
        return RAGService(
            strategy=strategy,
            fallback=fallback if fallback.is_configured else None,
            cache=cache,
            confidence_gap_threshold=confidence_gap_threshold,
            reranker=reranker,
            enable_pending_freshness=enable_pending_freshness,
            enable_per_client_routing=enable_per_client_routing,
            rerank_candidate_pool_size=rerank_candidate_pool_size,
            pending_freshness_limit=pending_freshness_limit,
            pending_freshness_timeout_ms=pending_freshness_timeout_ms,
            operability_cache=operability_cache,
            w_relevance=w_relevance,
            w_operability=w_operability,
            min_boost_relevance=min_boost_relevance,
        )
