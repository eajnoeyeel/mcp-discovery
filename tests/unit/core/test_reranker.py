"""Tests for Reranker ABC and CohereReranker."""

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_discovery.models import MCPTool, SearchResult
from mcp_discovery.reranking.base import Reranker
from mcp_discovery.reranking.cohere_reranker import CohereReranker


def _make_tool(name: str, description: str = "A tool") -> MCPTool:
    """Helper to build an MCPTool with valid tool_id."""
    server_id = "test-server"
    return MCPTool(
        server_id=server_id,
        tool_name=name,
        tool_id=f"{server_id}::{name}",
        description=description,
    )


def _make_result(name: str, score: float, rank: int) -> SearchResult:
    """Helper to build a SearchResult."""
    return SearchResult(
        tool=_make_tool(name, description=f"Description of {name}"),
        score=score,
        rank=rank,
        reason=f"reason-{name}",
    )


class TestRerankerABC:
    def test_reranker_abc_cannot_instantiate(self):
        """ABC cannot be instantiated directly."""
        assert inspect.isabstract(Reranker)
        with pytest.raises(TypeError):
            Reranker()


class TestCohereReranker:
    @pytest.fixture(autouse=True)
    def fake_cohere_module(self, monkeypatch):
        fake_module = SimpleNamespace(AsyncClientV2=MagicMock(return_value=AsyncMock()))
        monkeypatch.setattr(
            "mcp_discovery.reranking.cohere_reranker.cohere",
            fake_module,
        )

    @pytest.fixture
    def mock_cohere_response(self) -> MagicMock:
        """Build a mock Cohere rerank response: indices [2, 0] with scores."""
        response = MagicMock()
        response.results = [
            MagicMock(index=2, relevance_score=0.95),
            MagicMock(index=0, relevance_score=0.80),
        ]
        return response

    @pytest.fixture
    def three_results(self) -> list[SearchResult]:
        return [
            _make_result("tool_a", score=0.7, rank=1),
            _make_result("tool_b", score=0.6, rank=2),
            _make_result("tool_c", score=0.5, rank=3),
        ]

    @pytest.fixture
    def reranker_with_mock(self, mock_cohere_response: MagicMock) -> CohereReranker:
        reranker = CohereReranker(api_key="fake-key")
        reranker._client = AsyncMock()
        reranker._client.rerank = AsyncMock(return_value=mock_cohere_response)
        return reranker

    async def test_cohere_reranker_reranks_results(
        self,
        reranker_with_mock: CohereReranker,
        three_results: list[SearchResult],
    ):
        """Mock cohere client, 3 results reranked to 2."""
        reranked = await reranker_with_mock.rerank("test query", three_results, top_k=2)

        assert len(reranked) == 2
        # First result should correspond to original index 2 (tool_c)
        assert reranked[0].tool.tool_name == "tool_c"
        # Second result should correspond to original index 0 (tool_a)
        assert reranked[1].tool.tool_name == "tool_a"

    async def test_cohere_reranker_empty_results(self):
        """Empty input returns empty output without calling API."""
        reranker = CohereReranker(api_key="fake-key")
        mock_rerank = AsyncMock()
        reranker._client = AsyncMock()
        reranker._client.rerank = mock_rerank

        result = await reranker.rerank("test query", [], top_k=3)

        assert result == []
        mock_rerank.assert_not_called()

    async def test_cohere_reranker_fewer_than_top_k(self):
        """When results < top_k, return all results reranked."""
        results = [
            _make_result("tool_a", score=0.7, rank=1),
            _make_result("tool_b", score=0.6, rank=2),
        ]

        mock_response = MagicMock()
        mock_response.results = [
            MagicMock(index=1, relevance_score=0.90),
            MagicMock(index=0, relevance_score=0.75),
        ]

        reranker = CohereReranker(api_key="fake-key")
        reranker._client = AsyncMock()
        reranker._client.rerank = AsyncMock(return_value=mock_response)

        reranked = await reranker.rerank("test query", results, top_k=5)

        assert len(reranked) == 2
        assert reranked[0].tool.tool_name == "tool_b"
        assert reranked[1].tool.tool_name == "tool_a"

    async def test_cohere_reranker_api_error_graceful_degradation(
        self,
        three_results: list[SearchResult],
    ):
        """API error returns original results truncated to top_k."""
        reranker = CohereReranker(api_key="fake-key")
        reranker._client = AsyncMock()
        reranker._client.rerank = AsyncMock(side_effect=Exception("API down"))

        reranked = await reranker.rerank("test query", three_results, top_k=2)

        assert len(reranked) == 2
        # Should preserve original order, truncated
        assert reranked[0].tool.tool_name == "tool_a"
        assert reranked[1].tool.tool_name == "tool_b"

    async def test_cohere_reranker_score_and_rank_updated(
        self,
        reranker_with_mock: CohereReranker,
        three_results: list[SearchResult],
    ):
        """After rerank, score and rank reflect Cohere response."""
        reranked = await reranker_with_mock.rerank("test query", three_results, top_k=2)

        # Scores from mock: 0.95, 0.80
        assert reranked[0].score == pytest.approx(0.95)
        assert reranked[1].score == pytest.approx(0.80)
        # Ranks: 1-based sequential
        assert reranked[0].rank == 1
        assert reranked[1].rank == 2

    async def test_cohere_reranker_preserves_tool_data(
        self,
        reranker_with_mock: CohereReranker,
        three_results: list[SearchResult],
    ):
        """After rerank, tool data (server_id, tool_name, etc.) is preserved."""
        reranked = await reranker_with_mock.rerank("test query", three_results, top_k=2)

        # First reranked result is original index 2 → tool_c
        tool = reranked[0].tool
        assert tool.tool_name == "tool_c"
        assert tool.server_id == "test-server"
        assert tool.tool_id == "test-server::tool_c"
        assert tool.description == "Description of tool_c"

        # Reason is preserved from original
        assert reranked[0].reason == "reason-tool_c"

    def test_cohere_reranker_is_reranker_subclass(self):
        """CohereReranker implements the Reranker ABC."""
        assert issubclass(CohereReranker, Reranker)

    def test_cohere_reranker_model_property(self):
        reranker = CohereReranker(api_key="fake-key", model="rerank-v3.5")
        assert reranker.model == "rerank-v3.5"

    def test_cohere_reranker_requires_optional_dependency(self, monkeypatch):
        monkeypatch.setattr("mcp_discovery.reranking.cohere_reranker.cohere", None)
        with pytest.raises(RuntimeError, match="legacy optional experiment component"):
            CohereReranker(api_key="fake-key")

    async def test_cohere_reranker_uses_selection_description_when_set(self):
        """Reranker uses selection_description over description when both present."""
        server_id = "test-server"
        tool = MCPTool(
            server_id=server_id,
            tool_name="search_records",
            tool_id=f"{server_id}::search_records",
            description="Search for records containing specific text",
            selection_description="Accepts base_id, table_name, and search_text.",
        )
        result = SearchResult(tool=tool, score=0.9, rank=1)

        captured_docs: list[list[str]] = []

        async def capture_rerank(**kwargs: object) -> MagicMock:
            captured_docs.append(list(kwargs["documents"]))
            response = MagicMock()
            response.results = [MagicMock(index=0, relevance_score=0.95)]
            return response

        reranker = CohereReranker(api_key="fake-key")
        reranker._client = AsyncMock()
        reranker._client.rerank = capture_rerank

        await reranker.rerank("find airtable records", [result], top_k=1)

        assert len(captured_docs) == 1
        doc = captured_docs[0][0]
        assert "Accepts base_id" in doc
        assert "Search for records" not in doc

    async def test_cohere_reranker_falls_back_to_description_when_no_selection_desc(self):
        """Without selection_description, reranker uses description."""
        server_id = "test-server"
        tool = MCPTool(
            server_id=server_id,
            tool_name="search_records",
            tool_id=f"{server_id}::search_records",
            description="Search for records containing specific text",
        )
        result = SearchResult(tool=tool, score=0.9, rank=1)

        captured_docs: list[list[str]] = []

        async def capture_rerank(**kwargs: object) -> MagicMock:
            captured_docs.append(list(kwargs["documents"]))
            response = MagicMock()
            response.results = [MagicMock(index=0, relevance_score=0.95)]
            return response

        reranker = CohereReranker(api_key="fake-key")
        reranker._client = AsyncMock()
        reranker._client.rerank = capture_rerank

        await reranker.rerank("find airtable records", [result], top_k=1)

        doc = captured_docs[0][0]
        assert "Search for records containing specific text" in doc
