from unittest.mock import AsyncMock

import numpy as np
import pytest

from mcp_discovery.embedding.sparse_embedder import SparseVector
from mcp_discovery.models import MCPTool
from mcp_discovery.retrieval.qdrant_store import QdrantStore


def _tool(i: int) -> MCPTool:
    return MCPTool(tool_id=f"s::t{i}", server_id="s", tool_name=f"t{i}", description="d")


@pytest.mark.asyncio
async def test_upsert_tools_hybrid_without_extra_payloads_unchanged() -> None:
    client = AsyncMock()
    store = QdrantStore(client=client, collection_name="mcp_tools_hybrid")
    tools = [_tool(0), _tool(1)]
    dense = [np.zeros(3), np.zeros(3)]
    sparse = [SparseVector(indices=[1], values=[0.1]), SparseVector(indices=[2], values=[0.2])]
    await store.upsert_tools_hybrid(tools, dense, sparse)
    call = client.upsert.call_args
    points = call.kwargs["points"]
    assert len(points) == 2


@pytest.mark.asyncio
async def test_upsert_tools_hybrid_merges_extra_payloads() -> None:
    client = AsyncMock()
    store = QdrantStore(client=client, collection_name="mcp_tools_hybrid")
    tools = [_tool(0)]
    dense = [np.zeros(3)]
    sparse = [SparseVector(indices=[1], values=[0.1])]
    extras = [{"sparse_source": "keyword_llm", "enrichment_hash": "abc"}]
    await store.upsert_tools_hybrid(tools, dense, sparse, extra_payloads=extras)
    point = client.upsert.call_args.kwargs["points"][0]
    assert point.payload["sparse_source"] == "keyword_llm"
    assert point.payload["enrichment_hash"] == "abc"
    assert point.payload["tool_id"] == "s::t0"


@pytest.mark.asyncio
async def test_upsert_tools_hybrid_rejects_mismatched_extras_length() -> None:
    client = AsyncMock()
    store = QdrantStore(client=client, collection_name="mcp_tools_hybrid")
    tools = [_tool(0), _tool(1)]
    dense = [np.zeros(3), np.zeros(3)]
    sparse = [SparseVector(indices=[1], values=[0.1])] * 2
    with pytest.raises(ValueError, match="extra_payloads"):
        await store.upsert_tools_hybrid(tools, dense, sparse, extra_payloads=[{}])
