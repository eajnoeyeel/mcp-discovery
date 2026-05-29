"""Unit tests for mlp/rag/merger.py — ResultMerger."""

import pytest

from mcp_discovery.models import MCPTool, SearchResult
from service.rag.merger import ResultMerger


def _sr(tool_id: str, score: float, rank: int = 1) -> SearchResult:
    server_id, tool_name = tool_id.split("::", 1)
    return SearchResult(
        tool=MCPTool(
            tool_id=tool_id,
            server_id=server_id,
            tool_name=tool_name,
            description="test tool",
        ),
        score=score,
        rank=rank,
    )


class TestMergeCandidates:
    def test_merges_two_non_overlapping_sources(self):
        primary = [_sr("srv_a::tool_x", 0.9), _sr("srv_a::tool_y", 0.8)]
        fallback = [_sr("srv_b::tool_z", 0.7)]
        result = ResultMerger.merge_candidates(primary, fallback)
        tool_ids = [r.tool.tool_id for r in result]
        assert "srv_a::tool_x" in tool_ids
        assert "srv_a::tool_y" in tool_ids
        assert "srv_b::tool_z" in tool_ids

    def test_deduplicates_overlapping_results_keeps_higher_score(self):
        primary = [_sr("srv::tool_a", 0.9)]
        fallback = [_sr("srv::tool_a", 0.5)]
        result = ResultMerger.merge_candidates(primary, fallback)
        assert len(result) == 1
        assert result[0].score == 0.9

    def test_deduplicates_prefers_lower_score_if_fallback_higher(self):
        primary = [_sr("srv::tool_a", 0.4)]
        fallback = [_sr("srv::tool_a", 0.8)]
        result = ResultMerger.merge_candidates(primary, fallback)
        assert len(result) == 1
        assert result[0].score == 0.8

    def test_results_sorted_by_score_descending(self):
        primary = [_sr("srv::t1", 0.6), _sr("srv::t2", 0.9)]
        fallback = [_sr("srv::t3", 0.75)]
        result = ResultMerger.merge_candidates(primary, fallback)
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_ranks_reassigned_from_one(self):
        primary = [_sr("srv::t1", 0.9), _sr("srv::t2", 0.7)]
        result = ResultMerger.merge_candidates(primary)
        assert result[0].rank == 1
        assert result[1].rank == 2

    def test_empty_sources_returns_empty_list(self):
        result = ResultMerger.merge_candidates([], [], [])
        assert result == []

    def test_single_source_with_single_result(self):
        result = ResultMerger.merge_candidates([_sr("srv::t1", 0.85)])
        assert len(result) == 1
        assert result[0].tool.tool_id == "srv::t1"
        assert result[0].rank == 1

    def test_three_sources_merged_correctly(self):
        a = [_sr("srv::t1", 0.9)]
        b = [_sr("srv::t2", 0.8)]
        c = [_sr("srv::t3", 0.7)]
        result = ResultMerger.merge_candidates(a, b, c)
        assert len(result) == 3
        assert result[0].tool.tool_id == "srv::t1"

    def test_no_sources_returns_empty(self):
        result = ResultMerger.merge_candidates()
        assert result == []

    def test_duplicate_in_same_source_deduplicates(self):
        """Duplicates within a single source are also deduped."""
        primary = [_sr("srv::t1", 0.9), _sr("srv::t1", 0.6)]
        result = ResultMerger.merge_candidates(primary)
        assert len(result) == 1
        assert result[0].score == 0.9


class TestTruncateAndReassign:
    def test_truncates_to_top_k(self):
        results = [_sr(f"srv::t{i}", 1.0 - i * 0.1) for i in range(5)]
        truncated = ResultMerger.truncate_and_reassign(results, top_k=3)
        assert len(truncated) == 3

    def test_reassigns_ranks_starting_at_one(self):
        results = [_sr(f"srv::t{i}", 1.0 - i * 0.1, rank=i + 10) for i in range(3)]
        truncated = ResultMerger.truncate_and_reassign(results, top_k=3)
        assert [r.rank for r in truncated] == [1, 2, 3]

    def test_top_k_larger_than_results_returns_all(self):
        results = [_sr("srv::t1", 0.9), _sr("srv::t2", 0.8)]
        truncated = ResultMerger.truncate_and_reassign(results, top_k=10)
        assert len(truncated) == 2

    def test_top_k_zero_raises_value_error(self):
        results = [_sr("srv::t1", 0.9)]
        with pytest.raises(ValueError, match="top_k must be positive"):
            ResultMerger.truncate_and_reassign(results, top_k=0)

    def test_negative_top_k_raises_value_error(self):
        results = [_sr("srv::t1", 0.9)]
        with pytest.raises(ValueError, match="top_k must be positive"):
            ResultMerger.truncate_and_reassign(results, top_k=-1)

    def test_empty_results_returns_empty(self):
        truncated = ResultMerger.truncate_and_reassign([], top_k=3)
        assert truncated == []

    def test_top_k_one_returns_first_result(self):
        results = [_sr("srv::t1", 0.9), _sr("srv::t2", 0.8)]
        truncated = ResultMerger.truncate_and_reassign(results, top_k=1)
        assert len(truncated) == 1
        assert truncated[0].tool.tool_id == "srv::t1"
        assert truncated[0].rank == 1


class TestMergeAndDeduplicate:
    def test_combines_merge_and_truncate(self):
        primary = [_sr("srv::t1", 0.9), _sr("srv::t2", 0.8)]
        fallback = [_sr("srv::t3", 0.7), _sr("srv::t4", 0.6)]
        result = ResultMerger.merge_and_deduplicate(primary, fallback, top_k=2)
        assert len(result) == 2
        assert result[0].tool.tool_id == "srv::t1"
        assert result[1].tool.tool_id == "srv::t2"

    def test_deduplication_before_truncation(self):
        primary = [_sr("srv::t1", 0.9)]
        fallback = [_sr("srv::t1", 0.5), _sr("srv::t2", 0.8)]
        result = ResultMerger.merge_and_deduplicate(primary, fallback, top_k=2)
        assert len(result) == 2
        tool_ids = [r.tool.tool_id for r in result]
        assert "srv::t1" in tool_ids
        assert "srv::t2" in tool_ids
