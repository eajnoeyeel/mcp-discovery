"""Tests for QueryInflowMetric (Feature 4)."""

from mcp_discovery.analytics.logger import CandidateScore, QueryLogEntry
from mcp_discovery.analytics.metrics.base import MetricContext
from mcp_discovery.analytics.metrics.query_inflow import QueryInflowMetric


def _make_log_entry(**overrides) -> QueryLogEntry:
    defaults = {
        "query": "find repos",
        "selected_tool_id": "github::search",
        "server_id": "github",
        "confidence": 0.85,
        "disambiguation_needed": False,
        "strategy": "flat",
        "latency_ms": 150.0,
        "alternatives": ["gitlab::search"],
        "candidates": [
            CandidateScore(
                tool_id="github::search", score=0.85, dense_score=0.80, sparse_score=0.90
            ),
            CandidateScore(
                tool_id="gitlab::search", score=0.72, dense_score=0.75, sparse_score=0.68
            ),
        ],
    }
    defaults.update(overrides)
    return QueryLogEntry(**defaults)


class TestQueryInflowMetric:
    def test_winning_queries(self) -> None:
        logs = [
            _make_log_entry(query="find GitHub repos for ML", selected_tool_id="github::search"),
            _make_log_entry(query="search code repositories", selected_tool_id="github::search"),
            _make_log_entry(
                query="project management tool",
                selected_tool_id="gitlab::search",
                alternatives=["github::search"],
            ),
        ]
        metric = QueryInflowMetric()
        ctx = MetricContext(tool_id="github::search", server_id="github", logs=logs)
        result = metric.compute(ctx)

        assert result.value["total_appearances"] == 3
        assert result.value["won"] == 2
        assert result.value["lost"] == 1
        assert len(result.value["winning_queries"]) == 2
        assert len(result.value["losing_queries"]) == 1

    def test_empty_logs(self) -> None:
        metric = QueryInflowMetric()
        ctx = MetricContext(tool_id="t1", server_id="s1", logs=[])
        result = metric.compute(ctx)
        assert result.value["total_appearances"] == 0
        assert result.value["winning_queries"] == []

    def test_query_keywords(self) -> None:
        logs = [
            _make_log_entry(
                query="search repositories on GitHub", selected_tool_id="github::search"
            ),
            _make_log_entry(query="find repositories by topic", selected_tool_id="github::search"),
            _make_log_entry(query="database migration tool", selected_tool_id="github::search"),
        ]
        metric = QueryInflowMetric()
        ctx = MetricContext(tool_id="github::search", server_id="github", logs=logs)
        result = metric.compute(ctx)

        assert "top_keywords" in result.value
        assert len(result.value["top_keywords"]) > 0
        keywords = [k["keyword"] for k in result.value["top_keywords"]]
        assert "repositories" in keywords

    def test_losing_query_includes_winner(self) -> None:
        logs = [
            _make_log_entry(
                query="manage projects",
                selected_tool_id="gitlab::search",
                alternatives=["github::search"],
            ),
        ]
        metric = QueryInflowMetric()
        ctx = MetricContext(tool_id="github::search", server_id="github", logs=logs)
        result = metric.compute(ctx)

        assert result.value["losing_queries"][0]["winner"] == "gitlab::search"
