"""Unit tests for demo_mcp_server — E4v2 demo tool.

E4v2 design: same embedding search, enriched selection_description injected before reranking.

pytest pythonpath includes 'scripts/' so imports work without path manipulation.
asyncio_mode="auto" from pyproject.toml — no @pytest.mark.asyncio needed.
"""

from unittest.mock import AsyncMock, patch

import pytest

from mcp_discovery.models import MCPTool, SearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    server_id: str,
    tool_name: str,
    description: str | None,
    score: float,
    rank: int,
    selection_description: str | None = None,
) -> SearchResult:
    return SearchResult(
        tool=MCPTool(
            server_id=server_id,
            tool_name=tool_name,
            tool_id=f"{server_id}::{tool_name}",
            description=description,
            selection_description=selection_description,
        ),
        score=score,
        rank=rank,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def airtable_cluster_results() -> list[SearchResult]:
    """Simulates embedding search results for database_records cluster (original)."""
    return [
        _make_result("mongodb", "find", "Run a find query against a MongoDB collection", 0.72, 1),
        _make_result(
            "airtable", "search_records", "Search for records containing specific text", 0.68, 2
        ),
        _make_result(
            "airtable", "list_records", "Lists records from a specified Airtable table", 0.61, 3
        ),
    ]


@pytest.fixture
def airtable_cluster_results_with_selection_desc() -> list[SearchResult]:
    """Simulates candidates after enriched selection_description injection."""
    return [
        _make_result("mongodb", "find", "Run a find query against a MongoDB collection", 0.72, 1),
        _make_result(
            "airtable",
            "search_records",
            "Search for records containing specific text",
            0.68,
            2,
            selection_description=(
                "Searches for records in a specified table that contain a specific text, "
                "useful for retrieving relevant data based on defined criteria."
            ),
        ),
        _make_result(
            "airtable", "list_records", "Lists records from a specified Airtable table", 0.61, 3
        ),
    ]


@pytest.fixture
def original_results() -> list[SearchResult]:
    return [
        _make_result("airtable", "list_tables", "Lists all tables in a specific base", 0.61, 1),
        _make_result("mongodb", "find", "Run a find query against a MongoDB collection", 0.55, 2),
        _make_result(
            "airtable", "search_records", "Search for records containing specific text", 0.50, 3
        ),
    ]


@pytest.fixture
def reranked_enriched_results() -> list[SearchResult]:
    return [
        _make_result(
            "airtable",
            "search_records",
            "Search for records containing specific text",
            0.87,
            1,
            selection_description=(
                "Searches for records in a specified table that contain a specific text, "
                "useful for retrieving relevant data based on defined criteria."
            ),
        ),
        _make_result("mongodb", "find", "Run a find query against a MongoDB collection", 0.62, 2),
    ]


# ---------------------------------------------------------------------------
# _inject_selection_descriptions
# ---------------------------------------------------------------------------


class TestInjectSelectionDescriptions:
    def test_injects_enriched_desc_for_known_tool(self, airtable_cluster_results):
        from demo_mcp_server import _inject_selection_descriptions

        enriched = {"airtable::search_records": "Enriched description here"}
        result = _inject_selection_descriptions(airtable_cluster_results, enriched)

        airtable_tool = next(r for r in result if r.tool.tool_id == "airtable::search_records")
        assert airtable_tool.tool.selection_description == "Enriched description here"

    def test_does_not_inject_for_unknown_tool(self, airtable_cluster_results):
        from demo_mcp_server import _inject_selection_descriptions

        enriched = {"airtable::search_records": "Enriched"}
        result = _inject_selection_descriptions(airtable_cluster_results, enriched)

        mongodb_tool = next(r for r in result if r.tool.tool_id == "mongodb::find")
        assert mongodb_tool.tool.selection_description is None

    def test_does_not_mutate_original_results(self, airtable_cluster_results):
        from demo_mcp_server import _inject_selection_descriptions

        enriched = {"airtable::search_records": "Enriched"}
        _inject_selection_descriptions(airtable_cluster_results, enriched)

        # Original should be unchanged
        original = next(
            r for r in airtable_cluster_results if r.tool.tool_id == "airtable::search_records"
        )
        assert original.tool.selection_description is None

    def test_preserves_scores_and_ranks(self, airtable_cluster_results):
        from demo_mcp_server import _inject_selection_descriptions

        enriched = {"airtable::search_records": "Enriched"}
        result = _inject_selection_descriptions(airtable_cluster_results, enriched)

        airtable = next(r for r in result if r.tool.tool_id == "airtable::search_records")
        assert airtable.score == 0.68
        assert airtable.rank == 2

    def test_empty_enriched_dict_returns_unchanged(self, airtable_cluster_results):
        from demo_mcp_server import _inject_selection_descriptions

        result = _inject_selection_descriptions(airtable_cluster_results, {})
        for r in result:
            assert r.tool.selection_description is None


# ---------------------------------------------------------------------------
# _format_results
# ---------------------------------------------------------------------------


class TestFormatResults:
    def test_contains_rank_markers(self, original_results):
        from demo_mcp_server import _format_results

        output = _format_results(original_results, use_enriched=False)
        assert "#1" in output
        assert "#2" in output
        assert "#3" in output

    def test_contains_tool_id(self, original_results):
        from demo_mcp_server import _format_results

        output = _format_results(original_results, use_enriched=False)
        assert "airtable::search_records" in output

    def test_contains_score(self, original_results):
        from demo_mcp_server import _format_results

        output = _format_results(original_results, use_enriched=False)
        assert "0.61" in output

    def test_original_label_when_not_enriched(self, original_results):
        from demo_mcp_server import _format_results

        output = _format_results(original_results, use_enriched=False)
        assert "original" in output.lower()

    def test_enriched_label_when_enriched(self, reranked_enriched_results):
        from demo_mcp_server import _format_results

        output = _format_results(reranked_enriched_results, use_enriched=True)
        assert "enriched" in output.lower()

    def test_shows_selection_description_when_enriched(self, reranked_enriched_results):
        from demo_mcp_server import _format_results

        output = _format_results(reranked_enriched_results, use_enriched=True)
        assert "defined criteria" in output

    def test_shows_description_when_not_enriched(self, original_results):
        from demo_mcp_server import _format_results

        output = _format_results(original_results, use_enriched=False)
        assert "Search for records containing specific text" in output

    def test_empty_results_returns_no_results_message(self):
        from demo_mcp_server import _format_results

        output = _format_results([], use_enriched=False)
        assert "no results" in output.lower()


# ---------------------------------------------------------------------------
# _run_search — E4v2 strategy dispatch
# ---------------------------------------------------------------------------


class TestRunSearch:
    @patch("demo_mcp_server._STRATEGY")
    @patch("demo_mcp_server._STRATEGY_NO_RERANK")
    async def test_calls_strategy_when_use_enriched_false(
        self, mock_no_rerank, mock_strategy, original_results
    ):
        mock_strategy.search = AsyncMock(return_value=original_results)

        from demo_mcp_server import _run_search

        results = await _run_search("test query", top_k=3, use_enriched=False)

        mock_strategy.search.assert_called_once_with("test query", top_k=3)
        mock_no_rerank.search.assert_not_called()
        assert results == original_results

    @patch("demo_mcp_server._RERANKER")
    @patch("demo_mcp_server._STRATEGY")
    @patch("demo_mcp_server._STRATEGY_NO_RERANK")
    async def test_uses_no_rerank_strategy_then_injects_then_reranks(
        self,
        mock_no_rerank,
        mock_strategy,
        mock_reranker,
        airtable_cluster_results,
        reranked_enriched_results,
    ):
        mock_no_rerank.search = AsyncMock(return_value=airtable_cluster_results)
        mock_reranker.rerank = AsyncMock(return_value=reranked_enriched_results)

        import demo_mcp_server

        demo_mcp_server._ENRICHED_DESCRIPTIONS = {
            "airtable::search_records": (
                "Searches for records in a specified table that contain a specific text, "
                "useful for retrieving relevant data based on defined criteria."
            )
        }

        results = await demo_mcp_server._run_search("test query", top_k=3, use_enriched=True)

        mock_no_rerank.search.assert_called_once_with("test query", top_k=9)
        mock_strategy.search.assert_not_called()
        mock_reranker.rerank.assert_called_once()
        # Verify description was injected before passing to reranker
        rerank_call_candidates = mock_reranker.rerank.call_args[0][1]
        airtable = next(
            r for r in rerank_call_candidates if r.tool.tool_id == "airtable::search_records"
        )
        assert airtable.tool.selection_description is not None
        assert results == reranked_enriched_results


# ---------------------------------------------------------------------------
# _handle_find_best_tool — MCP handler
# ---------------------------------------------------------------------------


class TestHandleFindBestTool:
    @patch("demo_mcp_server._run_search")
    async def test_returns_list_with_one_text_content(self, mock_run_search, original_results):
        from mcp.types import TextContent

        mock_run_search.return_value = original_results

        from demo_mcp_server import _handle_find_best_tool

        result = await _handle_find_best_tool({"query": "Search for records in the Sales table"})

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].type == "text"

    @patch("demo_mcp_server._run_search")
    async def test_text_contains_tool_id(self, mock_run_search, original_results):
        mock_run_search.return_value = original_results

        from demo_mcp_server import _handle_find_best_tool

        result = await _handle_find_best_tool({"query": "Search for records in the Sales table"})

        assert "airtable::search_records" in result[0].text

    @patch("demo_mcp_server._run_search")
    async def test_defaults_top_k_6_use_enriched_false(self, mock_run_search, original_results):
        mock_run_search.return_value = original_results

        from demo_mcp_server import _handle_find_best_tool

        await _handle_find_best_tool({"query": "test"})

        mock_run_search.assert_called_once_with("test", top_k=6, use_enriched=False, cluster=None)

    @patch("demo_mcp_server._run_search")
    async def test_passes_use_enriched_true(self, mock_run_search, reranked_enriched_results):
        mock_run_search.return_value = reranked_enriched_results

        from demo_mcp_server import _handle_find_best_tool

        await _handle_find_best_tool({"query": "test", "use_enriched": True})

        mock_run_search.assert_called_once_with("test", top_k=6, use_enriched=True, cluster=None)

    @patch("demo_mcp_server._run_search")
    async def test_passes_cluster_param(self, mock_run_search, original_results):
        mock_run_search.return_value = original_results

        from demo_mcp_server import _handle_find_best_tool

        await _handle_find_best_tool({"query": "test", "cluster": "database_records"})

        mock_run_search.assert_called_once_with(
            "test", top_k=6, use_enriched=False, cluster="database_records"
        )
