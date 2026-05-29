"""Tests for FlatStrategy async hybrid retrieval — parallel dense + sparse execution."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from mcp_discovery.pipeline.flat import FlatStrategy


@pytest.mark.asyncio
async def test_flat_strategy_hybrid_runs_dense_sparse_concurrently():
    """Dense 50ms + Sparse 50ms run in parallel → total < 90ms."""

    async def _dense(q: str) -> np.ndarray:
        await asyncio.sleep(0.05)
        return np.zeros(3)

    def _sparse(q: str) -> MagicMock:
        time.sleep(0.05)
        try:
            from mcp_discovery.embedding.sparse_embedder import SparseVector

            return SparseVector(indices=[1], values=[0.1])
        except ImportError:
            return MagicMock(indices=[1], values=[0.1])

    embedder = MagicMock()
    embedder.embed_one = _dense
    sparse = MagicMock()
    sparse.embed_one = _sparse
    store = AsyncMock()
    store.hybrid_search.return_value = []
    store.search.return_value = []

    strat = FlatStrategy(
        embedder=embedder,
        tool_store=store,
        reranker=None,
        sparse_embedder=sparse,
    )
    t0 = time.perf_counter()
    await strat.search("q", top_k=3)
    dt = time.perf_counter() - t0
    assert dt < 0.09, f"Expected parallel exec, got {dt:.3f}s"
    store.hybrid_search.assert_awaited_once()
