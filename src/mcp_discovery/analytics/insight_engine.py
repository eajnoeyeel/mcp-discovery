"""Provider insight engine — threshold-based actionable recommendations.

Control-plane artifact. Insights are precomputed from ToolOperabilitySnapshot.
Per-call pattern analytics (e.g., input size → error correlation) is Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from mcp_discovery.analytics.geo_score import DescriptionGEOScorer
from mcp_discovery.operability.models import ToolOperabilitySnapshot


@dataclass(frozen=True)
class ProviderInsight:
    severity: Literal["info", "warning", "critical"]
    category: str
    title: str
    description: str
    recommendation: str
    data: dict[str, Any] = field(default_factory=dict)


class InsightEngine:
    """Analyzes a ToolOperabilitySnapshot and produces actionable insights."""

    def __init__(self) -> None:
        self._geo_scorer = DescriptionGEOScorer()

    def analyze(
        self,
        snap: ToolOperabilitySnapshot,
        description: str | None = None,
    ) -> list[ProviderInsight]:
        insights: list[ProviderInsight] = []

        # Health
        if snap.status in ("quarantined", "unreachable"):
            insights.append(
                ProviderInsight(
                    severity="critical",
                    category="health",
                    title="서버 상태 이상",
                    description=f"현재 상태: {snap.status}",
                    recommendation="서버 접근성과 응답 상태를 확인하세요.",
                    data={"status": snap.status},
                )
            )

        # Freshness (operational)
        op_days = snap.freshness.operational_freshness_days
        if op_days is not None and op_days > 90 and snap.call_count >= snap.min_support:
            insights.append(
                ProviderInsight(
                    severity="warning",
                    category="freshness",
                    title="장기간 미호출",
                    description=f"이 tool은 {op_days}일 동안 호출되지 않았습니다.",
                    recommendation="Description을 개선하거나 tool이 정상 동작하는지 확인하세요.",
                    data={"operational_freshness_days": op_days},
                )
            )

        # Index stale
        src_days = snap.freshness.source_freshness_days
        idx_days = snap.freshness.index_freshness_days
        if src_days is not None and idx_days is not None and idx_days > src_days + 7:
            insights.append(
                ProviderInsight(
                    severity="info",
                    category="index_stale",
                    title="인덱스 미갱신",
                    description="Description이 업데이트되었지만 검색 인덱스에 반영되지 않았습니다.",
                    recommendation="재인덱싱이 필요합니다.",
                    data={"source_freshness_days": src_days, "index_freshness_days": idx_days},
                )
            )

        # Success rate
        if (
            snap.success_rate is not None
            and snap.call_count >= snap.min_support
            and snap.success_rate < 0.8
        ):
            insights.append(
                ProviderInsight(
                    severity="warning",
                    category="success_rate",
                    title="낮은 성공률",
                    description=(
                        f"성공률이 {snap.success_rate:.0%}입니다"
                        f" (최근 {snap.call_count_7d}건 기준)."
                    ),
                    recommendation="에러 패턴을 확인하고 안정성을 개선하세요.",
                    data={"success_rate": snap.success_rate, "call_count_7d": snap.call_count_7d},
                )
            )

        # Timeout
        if (
            snap.timeout_rate is not None
            and snap.call_count >= snap.min_support
            and snap.timeout_rate > 0.1
        ):
            insights.append(
                ProviderInsight(
                    severity="warning",
                    category="timeout",
                    title="높은 타임아웃 비율",
                    description=f"타임아웃 비율이 {snap.timeout_rate:.0%}입니다.",
                    recommendation="서버 응답 시간을 확인하세요.",
                    data={"timeout_rate": snap.timeout_rate, "p95_latency_ms": snap.p95_latency_ms},
                )
            )

        # Description quality
        if description is not None:
            geo = self._geo_scorer.score(description)
            if geo.total < 0.4:
                weakest = min(
                    [
                        ("clarity", geo.clarity),
                        ("disambiguation", geo.disambiguation),
                        ("parameter_coverage", geo.parameter_coverage),
                        ("boundary", geo.boundary),
                        ("stats", geo.stats),
                        ("precision", geo.precision),
                    ],
                    key=lambda x: x[1],
                )
                insights.append(
                    ProviderInsight(
                        severity="info",
                        category="description",
                        title="Description 품질 개선 필요",
                        description=f"GEO 점수: {geo.total:.2f}. 가장 약한 항목: {weakest[0]}",
                        recommendation=f"{weakest[0]}을 개선하면 검색 노출이 향상됩니다.",
                        data={
                            "geo_total": round(geo.total, 4),
                            "weakest_dimension": weakest[0],
                            "weakest_score": round(weakest[1], 4),
                        },
                    )
                )

        # Cold start
        if (
            snap.call_count == 0
            and snap.freshness.source_freshness_days is not None
            and snap.freshness.source_freshness_days > 7
        ):
            insights.append(
                ProviderInsight(
                    severity="info",
                    category="cold_start",
                    title="등록 후 미호출",
                    description=(
                        f"등록 후 {snap.freshness.source_freshness_days}일 동안 호출이 없습니다."
                    ),
                    recommendation="Description을 개선하면 발견 확률이 높아집니다.",
                    data={"call_count": 0, "registered_days": snap.freshness.source_freshness_days},
                )
            )

        return insights
