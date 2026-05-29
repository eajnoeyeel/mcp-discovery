import asyncio
import time

import numpy as np
import pytest

from mcp_discovery.models import MCPTool, SearchResult
from mcp_discovery.pipeline.sequential import SequentialStrategy


class SlowMockStore:
    """Mock store that takes 100ms per search to prove parallelization."""

    def __init__(self, delay: float = 0.1):
        self._delay = delay

    async def search_server_ids(self, query_vector, top_k: int = 5) -> list[str]:
        return ["s1", "s2", "s3"]

    async def search(
        self, query_vector, top_k: int = 10, server_id_filter: str | None = None
    ) -> list[SearchResult]:
        await asyncio.sleep(self._delay)
        tool = MCPTool(
            server_id=server_id_filter or "s1",
            tool_name="tool1",
            tool_id=f"{server_id_filter or 's1'}::tool1",
            description="test",
        )
        return [SearchResult(tool=tool, score=0.5, rank=1)]


class MockEmbedder:
    async def embed_one(self, text: str) -> np.ndarray:
        return np.zeros(1536)


@pytest.mark.asyncio
async def test_layer2_runs_in_parallel():
    """Layer 2 searches 3 servers — should complete in ~100ms, not ~300ms."""
    strategy = SequentialStrategy(
        embedder=MockEmbedder(),
        tool_store=SlowMockStore(delay=0.1),
        server_store=SlowMockStore(delay=0.0),
    )
    start = time.monotonic()
    results = await strategy.search("test query", top_k=3)
    elapsed = time.monotonic() - start

    assert len(results) == 3
    # If sequential: ~300ms. If parallel: ~100ms.
    assert elapsed < 0.25, f"Layer 2 took {elapsed:.3f}s — should be parallel (<0.25s)"
