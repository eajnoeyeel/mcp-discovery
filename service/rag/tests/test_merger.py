"""Tests for ResultMerger — deduplication and merging of search results."""

from service.rag.merger import ResultMerger
from service.rag.tests.conftest import make_result


class TestResultMerger:
    """Test suite for ResultMerger.merge_and_deduplicate()."""

    def test_empty_lists(self):
        """Merging two empty lists returns empty list."""
        merged = ResultMerger.merge_and_deduplicate([], [], top_k=3)
        assert merged == []

    def test_primary_only(self):
        """Only primary results are merged and ranked."""
        results = [
            make_result(score=0.9, rank=1),
            make_result(tool_name="tool_b", score=0.8, rank=2),
        ]
        merged = ResultMerger.merge_and_deduplicate(results, [], top_k=3)
        assert len(merged) == 2
        assert merged[0].tool.tool_name == "tool_a"
        assert merged[0].rank == 1

    def test_fallback_only(self):
        """Only fallback results are merged and ranked."""
        fb = [make_result(tool_name="fb_tool", score=0.0, rank=1)]
        merged = ResultMerger.merge_and_deduplicate([], fb, top_k=3)
        assert len(merged) == 1
        assert merged[0].tool.tool_name == "fb_tool"

    def test_deduplication_keeps_higher_score(self):
        """Duplicate tool_id keeps higher score from primary."""
        primary = [make_result(score=0.9, rank=1)]
        fallback = [make_result(score=0.5, rank=1)]  # same tool_id
        merged = ResultMerger.merge_and_deduplicate(primary, fallback, top_k=3)
        assert len(merged) == 1
        assert merged[0].score == 0.9

    def test_top_k_truncation(self):
        """Results are truncated to top_k."""
        results = [
            make_result(tool_name=f"tool_{i}", score=1.0 - i * 0.1, rank=i + 1) for i in range(5)
        ]
        merged = ResultMerger.merge_and_deduplicate(results, [], top_k=3)
        assert len(merged) == 3

    def test_ranks_are_reassigned(self):
        """Ranks are reassigned 1..N after merge and sort."""
        primary = [make_result(tool_name="a", score=0.5, rank=3)]
        fallback = [make_result(tool_name="b", score=0.8, rank=1)]
        merged = ResultMerger.merge_and_deduplicate(primary, fallback, top_k=3)
        assert merged[0].rank == 1
        assert merged[0].tool.tool_name == "b"
        assert merged[1].rank == 2
        assert merged[1].tool.tool_name == "a"
