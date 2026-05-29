"""Tests for ToolIndexer — embed + upsert orchestrator."""

from unittest.mock import AsyncMock

import numpy as np
import pytest

from mcp_discovery.data.indexer import ToolIndexer
from mcp_discovery.embedding.base import Embedder
from mcp_discovery.models import MCPTool
from mcp_discovery.retrieval.qdrant_store import QdrantStore


@pytest.fixture
def sample_tools() -> list[MCPTool]:
    return [
        MCPTool(
            server_id="@a/srv",
            tool_name="tool1",
            tool_id="@a/srv::tool1",
            description="First tool",
        ),
        MCPTool(
            server_id="@a/srv",
            tool_name="tool2",
            tool_id="@a/srv::tool2",
            description="Second tool",
        ),
        MCPTool(
            server_id="@b/srv",
            tool_name="tool3",
            tool_id="@b/srv::tool3",
        ),
    ]


@pytest.fixture
def mock_embedder() -> Embedder:
    embedder = AsyncMock(spec=Embedder)
    embedder.model = "test-model"
    embedder.dimension = 4

    async def mock_embed_batch(texts, batch_size=50):
        return [np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32) for _ in texts]

    embedder.embed_batch = mock_embed_batch
    return embedder


@pytest.fixture
def mock_store() -> QdrantStore:
    store = AsyncMock(spec=QdrantStore)
    store.upsert_tools = AsyncMock()
    return store


class TestToolIndexer:
    async def test_index_tools_returns_count(self, sample_tools, mock_embedder, mock_store):
        indexer = ToolIndexer(embedder=mock_embedder, store=mock_store)
        count = await indexer.index_tools(sample_tools)
        assert count == 3

    async def test_index_tools_calls_upsert(self, sample_tools, mock_embedder, mock_store):
        indexer = ToolIndexer(embedder=mock_embedder, store=mock_store)
        await indexer.index_tools(sample_tools)
        mock_store.upsert_tools.assert_called_once()
        call_args = mock_store.upsert_tools.call_args
        assert len(call_args[0][0]) == 3  # tools
        assert len(call_args[0][1]) == 3  # vectors

    async def test_index_tools_batching(self, sample_tools, mock_embedder, mock_store):
        indexer = ToolIndexer(embedder=mock_embedder, store=mock_store)
        await indexer.index_tools(sample_tools, batch_size=2)
        # 3 tools with batch_size=2: 2 upsert calls (2 + 1)
        assert mock_store.upsert_tools.call_count == 2

    async def test_index_empty_list(self, mock_embedder, mock_store):
        indexer = ToolIndexer(embedder=mock_embedder, store=mock_store)
        count = await indexer.index_tools([])
        assert count == 0
        mock_store.upsert_tools.assert_not_called()
