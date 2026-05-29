"""Tests for TrendMetric (Feature 3)."""

import pytest

from mcp_discovery.analytics.metrics.base import MetricContext
from mcp_discovery.analytics.metrics.trend import TrendMetric
from mcp_discovery.analytics.snapshot import WeeklySnapshot


class TestTrendMetric:
    def test_compute_with_two_weeks(self) -> None:
        snapshots = [
            WeeklySnapshot(
                week_id="2026-W14",
                tool_id="t1",
                selection_count=20,
                runner_up_count=10,
                win_rate=0.67,
                geo_total=0.5,
                token_count=100,
            ),
            WeeklySnapshot(
                week_id="2026-W15",
                tool_id="t1",
                selection_count=35,
                runner_up_count=12,
                win_rate=0.74,
                geo_total=0.65,
                token_count=90,
            ),
        ]
        metric = TrendMetric()
        ctx = MetricContext(
            tool_id="t1",
            server_id="s1",
            extra={"snapshots": [s.model_dump() for s in snapshots]},
        )
        result = metric.compute(ctx)

        assert result.value["current_week"] == "2026-W15"
        assert result.value["previous_week"] == "2026-W14"
        assert result.value["win_rate_delta"] == pytest.approx(0.07)
        assert result.value["selection_count_delta"] == 15

    def test_compute_single_week(self) -> None:
        snapshots = [
            WeeklySnapshot(
                week_id="2026-W15",
                tool_id="t1",
                selection_count=35,
                runner_up_count=12,
                win_rate=0.74,
                geo_total=0.65,
                token_count=90,
            ),
        ]
        metric = TrendMetric()
        ctx = MetricContext(
            tool_id="t1",
            server_id="s1",
            extra={"snapshots": [s.model_dump() for s in snapshots]},
        )
        result = metric.compute(ctx)
        assert result.value["previous_week"] is None
        assert result.value["win_rate_delta"] is None

    def test_compute_empty(self) -> None:
        metric = TrendMetric()
        ctx = MetricContext(tool_id="t1", server_id="s1")
        result = metric.compute(ctx)
        assert result.value["current_week"] is None

    def test_history_ordering(self) -> None:
        snapshots = [
            WeeklySnapshot(
                week_id="2026-W16",
                tool_id="t1",
                selection_count=40,
                runner_up_count=10,
                win_rate=0.80,
                geo_total=0.7,
                token_count=85,
            ),
            WeeklySnapshot(
                week_id="2026-W14",
                tool_id="t1",
                selection_count=20,
                runner_up_count=10,
                win_rate=0.67,
                geo_total=0.5,
                token_count=100,
            ),
            WeeklySnapshot(
                week_id="2026-W15",
                tool_id="t1",
                selection_count=35,
                runner_up_count=12,
                win_rate=0.74,
                geo_total=0.65,
                token_count=90,
            ),
        ]
        metric = TrendMetric()
        ctx = MetricContext(
            tool_id="t1",
            server_id="s1",
            extra={"snapshots": [s.model_dump() for s in snapshots]},
        )
        result = metric.compute(ctx)
        weeks = [h["week_id"] for h in result.value["history"]]
        assert weeks == ["2026-W14", "2026-W15", "2026-W16"]
