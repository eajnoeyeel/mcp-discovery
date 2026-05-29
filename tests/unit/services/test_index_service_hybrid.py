from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest


def _row(i):
    return {
        "tool_id": f"s::t{i}",
        "server_id": "s",
        "tool_name": f"t{i}",
        "description": "d",
        "input_schema": {"properties": {"p": {"type": "string"}}},
    }


@pytest.mark.asyncio
async def test_index_rows_dense_only_when_no_sparse_embedder():
    from service.services.index_service import IndexService

    embedder = AsyncMock()
    embedder.embed_batch.return_value = [np.zeros(3)]
    store = AsyncMock()
    svc = IndexService(embedder=embedder, qdrant_store=store)
    n = await svc.index_rows([_row(0)])
    assert n == 1
    store.upsert_tools.assert_awaited_once()
    store.upsert_tools_hybrid.assert_not_called()


@pytest.mark.asyncio
async def test_index_rows_hybrid_branch_uses_cache_on_hit():
    from service.services.index_service import IndexService

    embedder = AsyncMock()
    embedder.embed_batch.return_value = [np.zeros(3)]
    sparse_embedder = MagicMock()
    try:
        from mcp_discovery.embedding.sparse_embedder import SparseVector

        sparse_embedder.embed_one.return_value = SparseVector(indices=[1], values=[0.1])
    except ImportError:
        sparse_embedder.embed_one.return_value = MagicMock(indices=[1], values=[0.1])
    cache = AsyncMock()
    cache.get.return_value = {"sparse_input": "cached text", "sparse_source": "keyword_llm_cached"}
    store = AsyncMock()
    svc = IndexService(
        embedder=embedder,
        qdrant_store=store,
        sparse_embedder=sparse_embedder,
        llm_client=AsyncMock(),
        enrichment_cache=cache,
    )
    await svc.index_rows([_row(0)])
    store.upsert_tools_hybrid.assert_awaited_once()
    call_kwargs = store.upsert_tools_hybrid.await_args.kwargs
    extras = call_kwargs.get("extra_payloads", [])
    assert len(extras) == 1
    assert extras[0]["sparse_source"] == "keyword_llm_cached"


@pytest.mark.asyncio
async def test_index_rows_llm_failure_uses_rule_based():
    import service.services.index_service as mod
    from service.services.index_service import IndexService

    embedder = AsyncMock()
    embedder.embed_batch.return_value = [np.zeros(3)]
    sparse_embedder = MagicMock()
    try:
        from mcp_discovery.embedding.sparse_embedder import SparseVector

        sparse_embedder.embed_one.return_value = SparseVector(indices=[1], values=[0.1])
    except ImportError:
        sparse_embedder.embed_one.return_value = MagicMock(indices=[1], values=[0.1])
    cache = AsyncMock()
    cache.get.return_value = None
    original_enrich = getattr(mod, "enrich_tool", None)

    async def _raising(*a, **kw):
        raise TimeoutError("OpenAI timeout")

    mod.enrich_tool = _raising
    store = AsyncMock()
    try:
        svc = IndexService(
            embedder=embedder,
            qdrant_store=store,
            sparse_embedder=sparse_embedder,
            llm_client=AsyncMock(),
            enrichment_cache=cache,
            max_llm_retries=0,
        )
        await svc.index_rows([_row(0)])
        call_kwargs = store.upsert_tools_hybrid.await_args.kwargs
        extras = call_kwargs.get("extra_payloads", [])
        assert extras[0]["sparse_source"] == "rule_based"
    finally:
        if original_enrich is not None:
            mod.enrich_tool = original_enrich
