"""Unit tests for mlp.services.insight_service."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_row(**overrides) -> dict:
    base = {
        "tool_id": "srv::tool",
        "server_id": "srv",
        "source_updated_at": None,
        "indexed_at": None,
        "entity_status": None,
    }
    base.update(overrides)
    return base


def _make_operability_row(**overrides) -> dict:
    base = {
        "call_count": 50,
        "call_count_7d": 10,
        "success_rate": 0.95,
        "success_rate_7d": 0.90,
        "avg_latency_ms": 120.0,
        "p95_latency_ms": 300.0,
        "timeout_rate": 0.01,
        "last_called_at": None,
        "entity_status": None,
    }
    base.update(overrides)
    return base


def _make_mock_insight(
    severity="info", category="quality", title="T", description="D", recommendation="R", data=None
):
    insight = MagicMock()
    insight.severity = severity
    insight.category = category
    insight.title = title
    insight.description = description
    insight.recommendation = recommendation
    insight.data = data or {}
    return insight


# ---------------------------------------------------------------------------
# _parse_dt
# ---------------------------------------------------------------------------


class TestParseDt:
    def test_returns_none_for_none_input(self):
        from service.services.insight_service import _parse_dt

        assert _parse_dt(None) is None

    def test_returns_datetime_unchanged(self):
        from service.services.insight_service import _parse_dt

        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = _parse_dt(dt)
        assert result is dt

    def test_parses_iso_string_with_z_suffix(self):
        from service.services.insight_service import _parse_dt

        result = _parse_dt("2024-03-10T08:30:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 10

    def test_parses_iso_string_with_offset(self):
        from service.services.insight_service import _parse_dt

        result = _parse_dt("2024-03-10T08:30:00+00:00")
        assert result is not None
        assert result.hour == 8

    def test_returns_none_for_invalid_string(self):
        from service.services.insight_service import _parse_dt

        assert _parse_dt("not-a-date") is None

    def test_returns_none_for_empty_string(self):
        from service.services.insight_service import _parse_dt

        assert _parse_dt("") is None


# ---------------------------------------------------------------------------
# _float_or_none
# ---------------------------------------------------------------------------


class TestFloatOrNone:
    def test_returns_none_for_none(self):
        from service.services.insight_service import _float_or_none

        assert _float_or_none(None) is None

    def test_converts_int_to_float(self):
        from service.services.insight_service import _float_or_none

        assert _float_or_none(5) == 5.0
        assert isinstance(_float_or_none(5), float)

    def test_converts_string_number_to_float(self):
        from service.services.insight_service import _float_or_none

        assert _float_or_none("3.14") == pytest.approx(3.14)

    def test_returns_none_for_non_numeric_string(self):
        from service.services.insight_service import _float_or_none

        assert _float_or_none("abc") is None

    def test_converts_zero_to_float(self):
        from service.services.insight_service import _float_or_none

        assert _float_or_none(0) == 0.0

    def test_returns_none_for_empty_string(self):
        from service.services.insight_service import _float_or_none

        assert _float_or_none("") is None


# ---------------------------------------------------------------------------
# InsightService._build_snapshot_from_mv
# ---------------------------------------------------------------------------


class TestBuildSnapshotFromMv:
    def test_maps_numeric_fields_to_snapshot(self):
        from service.services.insight_service import InsightService

        tool_row = _make_tool_row()
        op_row = _make_operability_row(call_count=100, success_rate=0.98)

        snapshot = InsightService._build_snapshot_from_mv(tool_row, op_row)

        assert snapshot.tool_id == "srv::tool"
        assert snapshot.server_id == "srv"
        assert snapshot.call_count == 100
        assert snapshot.success_rate == pytest.approx(0.98)

    def test_uses_active_status_when_entity_status_is_none(self):
        from service.services.insight_service import InsightService

        snapshot = InsightService._build_snapshot_from_mv(
            _make_tool_row(entity_status=None),
            _make_operability_row(entity_status=None),
        )

        assert snapshot.status == "active"

    def test_maps_superseded_status_to_deprecated(self):
        from service.services.insight_service import InsightService

        snapshot = InsightService._build_snapshot_from_mv(
            _make_tool_row(entity_status="superseded"),
            _make_operability_row(),
        )

        assert snapshot.status == "deprecated"

    def test_falls_back_to_active_for_unknown_status(self):
        from service.services.insight_service import InsightService

        snapshot = InsightService._build_snapshot_from_mv(
            _make_tool_row(entity_status="totally_unknown"),
            _make_operability_row(),
        )

        assert snapshot.status == "active"

    def test_prefers_operability_row_status_over_tool_row(self):
        from service.services.insight_service import InsightService

        snapshot = InsightService._build_snapshot_from_mv(
            _make_tool_row(entity_status="active"),
            _make_operability_row(entity_status="quarantined"),
        )

        assert snapshot.status == "quarantined"

    def test_parses_datetime_fields_from_iso_strings(self):
        from service.services.insight_service import InsightService

        tool_row = _make_tool_row(
            source_updated_at="2024-01-01T00:00:00Z",
            indexed_at="2024-01-02T00:00:00Z",
        )
        op_row = _make_operability_row(last_called_at="2024-01-03T00:00:00Z")

        snapshot = InsightService._build_snapshot_from_mv(tool_row, op_row)

        assert snapshot.freshness.source_updated_at is not None
        assert snapshot.freshness.indexed_at is not None
        assert snapshot.freshness.last_successful_call_at is not None

    def test_none_datetime_fields_produce_none_freshness(self):
        from service.services.insight_service import InsightService

        snapshot = InsightService._build_snapshot_from_mv(
            _make_tool_row(),
            _make_operability_row(),
        )

        assert snapshot.freshness.source_updated_at is None
        assert snapshot.freshness.indexed_at is None
        assert snapshot.freshness.last_successful_call_at is None

    def test_null_numeric_fields_map_to_none_in_snapshot(self):
        from service.services.insight_service import InsightService

        op_row = _make_operability_row(
            success_rate=None,
            avg_latency_ms=None,
            p95_latency_ms=None,
            timeout_rate=None,
        )

        snapshot = InsightService._build_snapshot_from_mv(_make_tool_row(), op_row)

        assert snapshot.success_rate is None
        assert snapshot.avg_latency_ms is None
        assert snapshot.p95_latency_ms is None
        assert snapshot.timeout_rate is None

    def test_min_support_is_set_to_default(self):
        from service.services.insight_service import _DEFAULT_MIN_SUPPORT, InsightService

        snapshot = InsightService._build_snapshot_from_mv(_make_tool_row(), _make_operability_row())

        assert snapshot.min_support == _DEFAULT_MIN_SUPPORT

    def test_computed_at_is_set_to_utc_now(self):
        from service.services.insight_service import InsightService

        before = datetime.now(timezone.utc)
        snapshot = InsightService._build_snapshot_from_mv(_make_tool_row(), _make_operability_row())
        after = datetime.now(timezone.utc)

        assert before <= snapshot.computed_at <= after


# ---------------------------------------------------------------------------
# InsightService.get_tool_insights
# ---------------------------------------------------------------------------


class TestInsightServiceGetToolInsights:
    async def test_returns_serialized_insights_from_engine(self):
        from service.services.insight_service import InsightService

        mock_insight = _make_mock_insight(
            severity="warning",
            category="latency",
            title="High p95",
            description="p95 is above threshold",
            recommendation="Optimize handler",
            data={"p95_latency_ms": 500},
        )
        mock_engine = MagicMock()
        mock_engine.analyze = MagicMock(return_value=[mock_insight])

        service = InsightService()
        service._engine = mock_engine

        result = await service.get_tool_insights(
            _make_tool_row(), _make_operability_row(), description="A tool"
        )

        assert len(result) == 1
        insight = result[0]
        assert insight["severity"] == "warning"
        assert insight["category"] == "latency"
        assert insight["title"] == "High p95"
        assert insight["description"] == "p95 is above threshold"
        assert insight["recommendation"] == "Optimize handler"
        assert insight["data"] == {"p95_latency_ms": 500}

    async def test_returns_empty_list_when_no_insights(self):
        from service.services.insight_service import InsightService

        mock_engine = MagicMock()
        mock_engine.analyze = MagicMock(return_value=[])

        service = InsightService()
        service._engine = mock_engine

        result = await service.get_tool_insights(_make_tool_row(), _make_operability_row())

        assert result == []

    async def test_passes_description_to_engine(self):
        from service.services.insight_service import InsightService

        mock_engine = MagicMock()
        mock_engine.analyze = MagicMock(return_value=[])

        service = InsightService()
        service._engine = mock_engine

        await service.get_tool_insights(
            _make_tool_row(), _make_operability_row(), description="Custom desc"
        )

        mock_engine.analyze.assert_called_once()
        call_kwargs = mock_engine.analyze.call_args.kwargs
        assert call_kwargs.get("description") == "Custom desc"

    async def test_passes_none_description_when_not_provided(self):
        from service.services.insight_service import InsightService

        mock_engine = MagicMock()
        mock_engine.analyze = MagicMock(return_value=[])

        service = InsightService()
        service._engine = mock_engine

        await service.get_tool_insights(_make_tool_row(), _make_operability_row())

        call_kwargs = mock_engine.analyze.call_args.kwargs
        assert call_kwargs.get("description") is None

    async def test_get_tool_insights_lazy_loads_engine_once(self):
        from service.services.insight_service import InsightService

        mock_engine = MagicMock()
        mock_engine.analyze = MagicMock(return_value=[])

        with patch(
            "service.services.insight_service.InsightService._get_engine", return_value=mock_engine
        ) as mock_get_engine:
            service = InsightService()
            await service.get_tool_insights(_make_tool_row(), _make_operability_row())
            await service.get_tool_insights(_make_tool_row(), _make_operability_row())

        assert mock_get_engine.call_count == 2  # called each time, but engine cached internally

    async def test_returns_multiple_insights(self):
        from service.services.insight_service import InsightService

        insights = [
            _make_mock_insight(severity="warning", title="Issue 1"),
            _make_mock_insight(severity="error", title="Issue 2"),
            _make_mock_insight(severity="info", title="Issue 3"),
        ]
        mock_engine = MagicMock()
        mock_engine.analyze = MagicMock(return_value=insights)

        service = InsightService()
        service._engine = mock_engine

        result = await service.get_tool_insights(_make_tool_row(), _make_operability_row())

        assert len(result) == 3
        titles = [r["title"] for r in result]
        assert "Issue 1" in titles
        assert "Issue 2" in titles
        assert "Issue 3" in titles
