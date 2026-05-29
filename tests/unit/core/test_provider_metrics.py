"""Tests for ProviderMetric ABC and MetricRegistry."""

import pytest

from mcp_discovery.analytics.logger import CandidateScore, QueryLogEntry
from mcp_discovery.analytics.metrics.base import (
    MetricContext,
    MetricRegistry,
    MetricResult,
    ProviderMetric,
)
from mcp_discovery.analytics.metrics.recommendation_rate import (
    RecommendationRateMetric as SelectionRateMetric,
)


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


class TestProviderMetricABC:
    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            ProviderMetric()  # type: ignore[abstract]

    def test_metric_result_model(self) -> None:
        result = MetricResult(
            metric_name="selection_rate",
            value={"win_rate": 0.67, "selection_count": 35},
        )
        assert result.metric_name == "selection_rate"
        assert result.value["win_rate"] == 0.67


class TestMetricRegistry:
    def test_register_and_get(self) -> None:
        registry = MetricRegistry()

        @registry.register("test_metric")
        class TestMetric(ProviderMetric):
            @property
            def name(self) -> str:
                return "test_metric"

            def compute(self, context):
                return MetricResult(metric_name=self.name, value={})

        metric_cls = registry.get("test_metric")
        assert metric_cls.__name__ == "TestMetric"

    def test_list_metrics(self) -> None:
        registry = MetricRegistry()

        @registry.register("a")
        class A(ProviderMetric):
            @property
            def name(self) -> str:
                return "a"

            def compute(self, context):
                return MetricResult(metric_name=self.name, value={})

        @registry.register("b")
        class B(ProviderMetric):
            @property
            def name(self) -> str:
                return "b"

            def compute(self, context):
                return MetricResult(metric_name=self.name, value={})

        assert sorted(registry.list_metrics()) == ["a", "b"]

    def test_get_unknown_raises(self) -> None:
        registry = MetricRegistry()
        with pytest.raises(ValueError, match="Unknown metric"):
            registry.get("nonexistent")


class TestSelectionRateMetric:
    def test_compute_winner(self) -> None:
        logs = [
            _make_log_entry(selected_tool_id="github::search"),
            _make_log_entry(selected_tool_id="github::search"),
            _make_log_entry(selected_tool_id="gitlab::search", alternatives=["github::search"]),
        ]
        metric = SelectionRateMetric()
        ctx = MetricContext(tool_id="github::search", server_id="github", logs=logs)
        result = metric.compute(ctx)

        assert result.value["selection_count"] == 2
        assert result.value["runner_up_count"] == 1
        assert result.value["win_rate"] == pytest.approx(2 / 3)

    def test_lost_to_analysis(self) -> None:
        logs = [
            _make_log_entry(
                selected_tool_id="gitlab::search",
                alternatives=["github::search"],
                candidates=[
                    CandidateScore(
                        tool_id="gitlab::search", score=0.90, dense_score=0.85, sparse_score=0.95
                    ),
                    CandidateScore(
                        tool_id="github::search", score=0.72, dense_score=0.80, sparse_score=0.65
                    ),
                ],
            ),
        ]
        metric = SelectionRateMetric()
        ctx = MetricContext(tool_id="github::search", server_id="github", logs=logs)
        result = metric.compute(ctx)

        assert "lost_to_top5" in result.value
        assert result.value["lost_to_top5"][0]["winner"] == "gitlab::search"
        assert result.value["lost_to_top5"][0]["count"] == 1

    def test_empty_logs(self) -> None:
        metric = SelectionRateMetric()
        ctx = MetricContext(tool_id="github::search", server_id="github", logs=[])
        result = metric.compute(ctx)
        assert result.value["selection_count"] == 0
        assert result.value["win_rate"] == 0.0
