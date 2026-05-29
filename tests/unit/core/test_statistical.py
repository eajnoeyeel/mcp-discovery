"""Tests for statistical analysis module."""

import pytest

from mcp_discovery.analytics.statistical import (
    ToolLevelComparison,
    cluster_bootstrap_ci,
    compute_tool_level_stats,
    wilcoxon_signed_rank,
)


class TestToolLevelComparison:
    def test_from_per_query_results(self):
        """Tool-level P@1을 쿼리 결과에서 올바르게 집계하는지 확인."""
        before = [
            {"tool_id": "a::x", "query_id": "q1", "top_1_correct": True},
            {"tool_id": "a::x", "query_id": "q2", "top_1_correct": False},
            {"tool_id": "b::y", "query_id": "q3", "top_1_correct": False},
        ]
        after = [
            {"tool_id": "a::x", "query_id": "q1", "top_1_correct": True},
            {"tool_id": "a::x", "query_id": "q2", "top_1_correct": True},
            {"tool_id": "b::y", "query_id": "q3", "top_1_correct": True},
        ]
        result = compute_tool_level_stats(before, after)
        assert len(result) == 2
        a_tool = next(r for r in result if r.tool_id == "a::x")
        assert a_tool.p1_before == 0.5
        assert a_tool.p1_after == 1.0
        assert a_tool.n_queries == 2

    def test_perfect_improvement(self):
        """모든 tool이 개선된 경우 Wilcoxon p-value가 낮아야 함."""
        comparisons = [
            ToolLevelComparison(tool_id=f"t{i}", p1_before=0.0, p1_after=1.0, n_queries=5)
            for i in range(10)
        ]
        stat, p_value = wilcoxon_signed_rank(comparisons)
        assert p_value < 0.05

    def test_no_change(self):
        """변화 없으면 p-value가 높아야 함."""
        comparisons = [
            ToolLevelComparison(tool_id=f"t{i}", p1_before=0.5, p1_after=0.5, n_queries=5)
            for i in range(10)
        ]
        stat, p_value = wilcoxon_signed_rank(comparisons)
        assert p_value > 0.3

    def test_bootstrap_ci_contains_mean(self):
        """Bootstrap CI가 관측된 평균 delta를 포함해야 함."""
        comparisons = [
            ToolLevelComparison(tool_id=f"t{i}", p1_before=0.3, p1_after=0.6, n_queries=5)
            for i in range(20)
        ]
        ci_low, ci_high, mean_delta = cluster_bootstrap_ci(comparisons, n_bootstrap=1000, seed=42)
        assert ci_low <= mean_delta <= ci_high
        assert mean_delta == pytest.approx(0.3, abs=0.01)
