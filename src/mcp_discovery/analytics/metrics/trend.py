"""Feature 3: Trend metric — week-over-week Before/After comparison."""

from __future__ import annotations

from mcp_discovery.analytics.metrics.base import MetricContext, MetricResult, ProviderMetric
from mcp_discovery.analytics.snapshot import WeeklySnapshot


class TrendMetric(ProviderMetric):
    """Compare current vs previous weekly snapshot for delta analysis."""

    @property
    def name(self) -> str:
        return "trend"

    def compute(self, context: MetricContext) -> MetricResult:
        raw_snapshots = context.extra.get("snapshots", [])
        snapshots = sorted(
            [WeeklySnapshot(**s) for s in raw_snapshots],
            key=lambda s: s.week_id,
        )

        if not snapshots:
            return MetricResult(
                metric_name=self.name,
                value={
                    "current_week": None,
                    "previous_week": None,
                    "win_rate_delta": None,
                    "selection_count_delta": None,
                    "geo_total_delta": None,
                    "history": [],
                },
            )

        current = snapshots[-1]
        previous = snapshots[-2] if len(snapshots) >= 2 else None

        return MetricResult(
            metric_name=self.name,
            value={
                "current_week": current.week_id,
                "previous_week": previous.week_id if previous else None,
                "win_rate_delta": (
                    round(current.win_rate - previous.win_rate, 4) if previous else None
                ),
                "selection_count_delta": (
                    current.selection_count - previous.selection_count if previous else None
                ),
                "geo_total_delta": (
                    round(current.geo_total - previous.geo_total, 4) if previous else None
                ),
                "history": [
                    {
                        "week_id": s.week_id,
                        "win_rate": s.win_rate,
                        "selection_count": s.selection_count,
                        "geo_total": s.geo_total,
                    }
                    for s in snapshots
                ],
            },
        )
