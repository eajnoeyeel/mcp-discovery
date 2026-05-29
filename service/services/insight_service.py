"""Bridge between InsightEngine and provider dashboard MVs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

# These imports work because mlp/shared/src_path.py adds src/ to sys.path
from mcp_discovery.operability.models import FreshnessTriple, ToolOperabilitySnapshot

_STATUS_MAP = {"superseded": "deprecated"}
_VALID_STATUSES = {"pending", "active", "quarantined", "unreachable", "deprecated", "stale"}
_DEFAULT_MIN_SUPPORT = 20


class InsightService:
    def __init__(self) -> None:
        # Lazy import to avoid circular / heavy init at module load time
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from mcp_discovery.analytics.insight_engine import InsightEngine

            self._engine = InsightEngine()
        return self._engine

    async def get_tool_insights(
        self,
        tool_row: dict[str, Any],
        operability_row: dict[str, Any],
        description: str | None = None,
    ) -> list[dict[str, Any]]:
        """Generate actionable insights for a tool from MV data."""
        snapshot = self._build_snapshot_from_mv(tool_row, operability_row)
        engine = self._get_engine()
        raw_insights = engine.analyze(snapshot, description=description)
        return [
            {
                "severity": insight.severity,
                "category": insight.category,
                "title": insight.title,
                "description": insight.description,
                "recommendation": insight.recommendation,
                "data": insight.data,
            }
            for insight in raw_insights
        ]

    @staticmethod
    def _build_snapshot_from_mv(
        tool_row: dict[str, Any],
        operability_row: dict[str, Any],
    ) -> ToolOperabilitySnapshot:
        """Convert MV dict data into ToolOperabilitySnapshot for InsightEngine."""
        raw_status = (
            operability_row.get("entity_status") or tool_row.get("entity_status") or "active"
        )
        status = _STATUS_MAP.get(raw_status, raw_status)
        if status not in _VALID_STATUSES:
            logger.warning(f"Unknown entity_status {raw_status!r}, falling back to 'active'")
            status = "active"

        freshness = FreshnessTriple(
            source_updated_at=_parse_dt(tool_row.get("source_updated_at")),
            indexed_at=_parse_dt(tool_row.get("indexed_at")),
            last_successful_call_at=_parse_dt(operability_row.get("last_called_at")),
        )

        return ToolOperabilitySnapshot(
            tool_id=tool_row.get("tool_id", ""),
            server_id=tool_row.get("server_id", ""),
            status=status,
            call_count=int(operability_row.get("call_count") or 0),
            call_count_7d=int(operability_row.get("call_count_7d") or 0),
            success_rate=_float_or_none(operability_row.get("success_rate")),
            success_rate_7d=_float_or_none(operability_row.get("success_rate_7d")),
            avg_latency_ms=_float_or_none(operability_row.get("avg_latency_ms")),
            p95_latency_ms=_float_or_none(operability_row.get("p95_latency_ms")),
            timeout_rate=_float_or_none(operability_row.get("timeout_rate")),
            min_support=_DEFAULT_MIN_SUPPORT,
            freshness=freshness,
            computed_at=datetime.now(timezone.utc),
        )


def _parse_dt(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _float_or_none(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
