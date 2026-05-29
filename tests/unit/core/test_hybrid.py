"""Tests for Reciprocal Rank Fusion utility."""

import pytest

from mcp_discovery.retrieval.hybrid import reciprocal_rank_fusion


class TestReciprocalRankFusion:
    def test_single_list_single_item(self) -> None:
        """Single item in single list: score = 1/(k+1)."""
        result = reciprocal_rank_fusion([["tool_a"]], k=60)
        assert len(result) == 1
        assert result[0][0] == "tool_a"
        assert result[0][1] == pytest.approx(1 / 61)

    def test_single_list_preserves_rank_order(self) -> None:
        """Items in single list get decreasing scores by rank."""
        result = reciprocal_rank_fusion([["tool_a", "tool_b", "tool_c"]], k=60)
        scores = {tid: s for tid, s in result}
        assert scores["tool_a"] > scores["tool_b"] > scores["tool_c"]

    def test_item_in_both_lists_scores_higher(self) -> None:
        """tool_a appears in both lists -- its score must exceed tool_b (one list only)."""
        result = reciprocal_rank_fusion(
            [["tool_a", "tool_b"], ["tool_a"]],
            k=60,
        )
        scores = {tid: s for tid, s in result}
        # tool_a: 1/61 + 1/61 = 2/61
        # tool_b: 1/62
        assert scores["tool_a"] > scores["tool_b"]
        assert scores["tool_a"] == pytest.approx(2 / 61)

    def test_exact_rrf_scores(self) -> None:
        """Verify exact RRF score computation with known values."""
        result = reciprocal_rank_fusion(
            [["a", "b"], ["b", "a"]],
            k=60,
        )
        scores = {tid: s for tid, s in result}
        # a: 1/61 + 1/62
        # b: 1/62 + 1/61 = same
        assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)
        assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)

    def test_empty_lists_returns_empty(self) -> None:
        result = reciprocal_rank_fusion([], k=60)
        assert result == []

    def test_all_empty_inner_lists(self) -> None:
        result = reciprocal_rank_fusion([[], []], k=60)
        assert result == []

    def test_result_sorted_descending(self) -> None:
        result = reciprocal_rank_fusion(
            [["tool_c", "tool_a", "tool_b"], ["tool_a", "tool_b"]],
            k=60,
        )
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)

    def test_custom_k_parameter(self) -> None:
        """k=1 should produce different scores than k=60."""
        result_k1 = reciprocal_rank_fusion([["a", "b"]], k=1)
        result_k60 = reciprocal_rank_fusion([["a", "b"]], k=60)
        scores_k1 = {tid: s for tid, s in result_k1}
        scores_k60 = {tid: s for tid, s in result_k60}
        # k=1: rank-1 score = 1/2 = 0.5. k=60: rank-1 score = 1/61
        assert scores_k1["a"] > scores_k60["a"]
