"""Tests verifying AsyncQdrantClient timeout and FlatStrategy prefetch_limit scaling."""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


def test_build_search_runtime_sets_qdrant_timeout(monkeypatch):
    """AsyncQdrantClient must be constructed with timeout=10."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_API_KEY", "test-key")

    captured: dict = {}

    def fake_client(*args, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    with (
        patch("service.shared.runtime.AsyncQdrantClient", side_effect=fake_client),
        patch("service.shared.runtime.OpenAIEmbedder"),
        patch("service.shared.runtime.QdrantStore"),
        patch("service.shared.runtime.FlatStrategy"),
        patch("service.shared.runtime._get_sparse_embedder", return_value=None),
        patch("mcp_discovery.operability.cache.OperabilityCache"),
    ):
        from service.shared import runtime as rt

        rt.build_search_runtime()

    assert captured.get("timeout") == 10, (
        f"Expected AsyncQdrantClient(timeout=10), got timeout={captured.get('timeout')}"
    )


@pytest.mark.asyncio
async def test_flat_strategy_scales_prefetch_limit_with_top_k():
    """FlatStrategy must pass prefetch_limit=max(20, top_k*3) to hybrid_search."""
    try:
        from mcp_discovery.embedding.sparse_embedder import SparseVector
    except ImportError:
        pytest.skip("fastembed not installed — sparse embedder unavailable")

    from mcp_discovery.pipeline.flat import FlatStrategy

    sparse_vector = SparseVector(indices=[0], values=[1.0])
    sparse_embedder = MagicMock()
    sparse_embedder.embed_one = MagicMock(return_value=sparse_vector)

    embedder = AsyncMock()
    embedder.embed_one = AsyncMock(return_value=np.zeros(3))

    tool_store = AsyncMock()
    tool_store.hybrid_search = AsyncMock(return_value=[])

    strategy = FlatStrategy(
        embedder=embedder,
        tool_store=tool_store,
        reranker=None,
        sparse_embedder=sparse_embedder,
    )

    for top_k, expected_prefetch in [(3, 20), (5, 20), (10, 30)]:
        tool_store.hybrid_search.reset_mock()
        await strategy.search("test query", top_k=top_k)
        tool_store.hybrid_search.assert_awaited_once()
        got = tool_store.hybrid_search.call_args.kwargs.get("prefetch_limit")
        assert got == expected_prefetch, (
            f"top_k={top_k}: expected prefetch_limit={expected_prefetch}, got {got}"
        )
