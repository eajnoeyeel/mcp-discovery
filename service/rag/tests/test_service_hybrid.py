"""Tests for hybrid source_path branching in RAGService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_discovery.models import SearchResult
from mcp_discovery.models.core import MCPTool
from service.rag.service import RAGSearchResult


def _make_search_result(score: float = 0.9, rank: int = 1) -> SearchResult:
    tool = MCPTool(
        server_id="srv",
        tool_name="tool",
        tool_id="srv::tool",
        description="A test tool",
    )
    return SearchResult(tool=tool, score=score, rank=rank)


def _make_rag_service(sparse_active: bool = False, degraded: bool = False):
    """Build a minimal RAGService with mocked collaborators."""
    try:
        from service.rag.service import RAGService
    except ImportError:
        pytest.skip("RAGService not importable in this environment")

    strategy = AsyncMock()
    if sparse_active:
        strategy.sparse_embedder = MagicMock()
        strategy.embedder = MagicMock()
        strategy.embedder.embed_one = AsyncMock(return_value=[0.1, 0.2])
        strategy.tool_store = MagicMock()
        strategy.tool_store.search = AsyncMock(return_value=[_make_search_result()])
    else:
        strategy.sparse_embedder = None

    if degraded:
        strategy.search.side_effect = RuntimeError("strategy down")
    else:
        strategy.search.return_value = [_make_search_result()]

    svc = RAGService(
        strategy=strategy,
        fallback=None,
        cache=None,
        confidence_gap_threshold=0.15,
    )
    return svc, strategy


@pytest.mark.asyncio
async def test_source_path_semantic_when_dense_only() -> None:
    """Dense-only path (no sparse_embedder) → source_path='semantic'."""
    svc, _ = _make_rag_service(sparse_active=False)
    response = await svc.search("find a weather tool", top_k=1)
    assert isinstance(response, RAGSearchResult)
    assert response.source_path == "semantic"


@pytest.mark.asyncio
async def test_source_path_hybrid_semantic_when_sparse_used() -> None:
    """Sparse embedder present and search succeeds → source_path='hybrid_semantic'."""
    svc, _ = _make_rag_service(sparse_active=True)
    response = await svc.search("find a weather tool", top_k=1)
    assert isinstance(response, RAGSearchResult)
    assert response.source_path == "hybrid_semantic"


@pytest.mark.asyncio
async def test_source_path_dense_only_degraded_when_sparse_fails() -> None:
    """Sparse embedder present but strategy.search fails → source_path='dense_only_degraded'."""
    svc, _ = _make_rag_service(sparse_active=True, degraded=True)
    response = await svc.search("find a weather tool", top_k=1)
    assert isinstance(response, RAGSearchResult)
    assert response.source_path == "dense_only_degraded"


@pytest.mark.asyncio
async def test_source_path_lexical_fallback_when_dense_fails() -> None:
    """Dense-only strategy fails without fallback recovery → source_path stays semantic."""
    svc, _ = _make_rag_service(sparse_active=False, degraded=True)
    response = await svc.search("find a weather tool", top_k=1)
    assert isinstance(response, RAGSearchResult)
    assert response.source_path == "semantic"


@pytest.mark.asyncio
async def test_strategy_hint_hybrid_passed_to_confidence() -> None:
    """When sparse is active, compute_confidence is called with strategy_hint='hybrid'."""
    svc, _ = _make_rag_service(sparse_active=True)
    with patch("service.rag.service.compute_confidence", return_value=(0.9, False)) as mock_conf:
        await svc.search("find a calendar tool", top_k=1)
    mock_conf.assert_called_once()
    _, kwargs = mock_conf.call_args
    assert kwargs.get("strategy_hint") == "hybrid"


@pytest.mark.asyncio
async def test_strategy_hint_dense_passed_when_no_sparse() -> None:
    """When no sparse embedder, compute_confidence is called with strategy_hint='dense'."""
    svc, _ = _make_rag_service(sparse_active=False)
    with patch("service.rag.service.compute_confidence", return_value=(0.9, False)) as mock_conf:
        await svc.search("find a calendar tool", top_k=1)
    mock_conf.assert_called_once()
    _, kwargs = mock_conf.call_args
    assert kwargs.get("strategy_hint") == "dense"
