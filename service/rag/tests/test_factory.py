"""Tests for RAGServiceFactory."""

from unittest.mock import AsyncMock, MagicMock, patch

from mcp_discovery.reranking.base import Reranker
from service.rag.factory import RAGServiceFactory
from service.rag.service import RAGService


class TestRAGServiceFactory:
    def test_create_returns_rag_service(self):
        mock_strategy = AsyncMock()
        service = RAGServiceFactory.create(
            strategy=mock_strategy,
            supabase_url="https://test.supabase.co",
            supabase_key="key",
            cache_ttl=300,
            confidence_gap_threshold=0.15,
        )
        assert isinstance(service, RAGService)

    def test_create_without_supabase(self):
        mock_strategy = AsyncMock()
        service = RAGServiceFactory.create(
            strategy=mock_strategy,
            supabase_url="",
            supabase_key="",
            cache_ttl=300,
            confidence_gap_threshold=0.15,
        )
        assert isinstance(service, RAGService)

    def test_create_without_cache(self):
        mock_strategy = AsyncMock()
        service = RAGServiceFactory.create(
            strategy=mock_strategy,
            supabase_url="",
            supabase_key="",
            cache_ttl=0,
            confidence_gap_threshold=0.15,
        )
        assert isinstance(service, RAGService)
        assert service._cache is None

    def test_create_passes_new_contract_fields(self):
        mock_strategy = AsyncMock()
        reranker = MagicMock(spec=Reranker)
        variant_map = {"server::tool": {"openai": "optimized"}}
        with patch("service.rag.service._load_variant_map", return_value=variant_map):
            service = RAGServiceFactory.create(
                strategy=mock_strategy,
                reranker=reranker,
                enable_pending_freshness=True,
                enable_per_client_routing=True,
                rerank_candidate_pool_size=12,
                pending_freshness_limit=4,
                pending_freshness_timeout_ms=250,
            )
        assert service._reranker is reranker
        assert service._enable_pending_freshness is True
        assert service._variant_map == variant_map
        assert service._rerank_candidate_pool_size == 12
        assert service._pending_freshness_limit == 4
        assert service._pending_freshness_timeout_ms == 250
