"""Feature 1: Selection/Rejection analysis — why was this tool recommended or not.

Renamed from selection_rate.py; SelectionRateMetric alias retained for 1 release.
"""

from __future__ import annotations

from mcp_discovery.analytics.metrics.base import MetricContext, MetricResult, ProviderMetric


class RecommendationRateMetric(ProviderMetric):
    """Computes recommendation count, runner-up count, win rate, and lost-to analysis."""

    @property
    def name(self) -> str:
        return "selection_rate"

    def compute(self, context: MetricContext) -> MetricResult:
        tool_id = context.tool_id
        selection_count = 0
        runner_up_count = 0
        lost_to: dict[str, int] = {}
        score_diffs: list[dict] = []

        for entry in context.logs:
            if entry.recommended_tool_id == tool_id:
                selection_count += 1
            elif tool_id in entry.alternatives:
                runner_up_count += 1
                winner = entry.recommended_tool_id
                lost_to[winner] = lost_to.get(winner, 0) + 1

                my_score = next((c for c in entry.candidates if c.tool_id == tool_id), None)
                winner_score = next((c for c in entry.candidates if c.tool_id == winner), None)
                if my_score and winner_score:
                    score_diffs.append(
                        {
                            "winner": winner,
                            "my_score": my_score.score,
                            "winner_score": winner_score.score,
                            "dense_gap": (winner_score.dense_score or 0)
                            - (my_score.dense_score or 0),
                            "sparse_gap": (winner_score.sparse_score or 0)
                            - (my_score.sparse_score or 0),
                        }
                    )

        total = selection_count + runner_up_count
        win_rate = selection_count / total if total > 0 else 0.0

        sorted_lost = sorted(lost_to.items(), key=lambda x: x[1], reverse=True)[:5]
        lost_to_top5 = [{"winner": w, "count": c} for w, c in sorted_lost]

        return MetricResult(
            metric_name=self.name,
            value={
                "selection_count": selection_count,
                "runner_up_count": runner_up_count,
                "win_rate": win_rate,
                "lost_to_top5": lost_to_top5,
                "score_diffs_sample": score_diffs[:10],
            },
        )


# Deprecated alias — remove after next release cycle
SelectionRateMetric = RecommendationRateMetric
