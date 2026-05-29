"""Integration tests for Cohere Reranker (requires COHERE_API_KEY)."""

import os
from importlib.util import find_spec

import pytest

from mcp_discovery.models import MCPTool, SearchResult
from mcp_discovery.reranking.cohere_reranker import CohereReranker

pytestmark = pytest.mark.skipif(
    not os.getenv("COHERE_API_KEY") or find_spec("cohere") is None,
    reason="legacy reranker API key or optional cohere package not available",
)


def _make_tool(name: str, description: str) -> MCPTool:
    server_id = "integration-server"
    return MCPTool(
        server_id=server_id,
        tool_name=name,
        tool_id=f"{server_id}::{name}",
        description=description,
    )


@pytest.fixture
def reranker() -> CohereReranker:
    return CohereReranker(api_key=os.environ["COHERE_API_KEY"])


@pytest.fixture
def sample_results() -> list[SearchResult]:
    return [
        SearchResult(
            tool=_make_tool("web_search", "Search the web for information"),
            score=0.8,
            rank=1,
        ),
        SearchResult(
            tool=_make_tool("calculator", "Perform mathematical calculations"),
            score=0.7,
            rank=2,
        ),
        SearchResult(
            tool=_make_tool("file_reader", "Read files from the filesystem"),
            score=0.6,
            rank=3,
        ),
    ]


class TestCohereIntegration:
    async def test_rerank_returns_results(
        self,
        reranker: CohereReranker,
        sample_results: list[SearchResult],
    ):
        """Real Cohere API rerank call returns valid results."""
        reranked = await reranker.rerank(
            "I need to search for something online",
            sample_results,
            top_k=2,
        )

        assert len(reranked) == 2
        for result in reranked:
            assert isinstance(result, SearchResult)
            assert 0.0 <= result.score <= 1.0
            assert result.rank >= 1

    async def test_rerank_empty_input(self, reranker: CohereReranker):
        """Real Cohere API with empty input returns empty list."""
        reranked = await reranker.rerank("some query", [], top_k=3)
        assert reranked == []
