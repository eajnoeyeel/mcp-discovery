from datetime import datetime, timedelta, timezone

import pytest

from mcp_discovery.operability.models import FreshnessTriple, ToolOperabilitySnapshot


@pytest.fixture
def healthy_snap():
    return ToolOperabilitySnapshot(
        tool_id="a::t1",
        server_id="a",
        status="active",
        call_count=500,
        call_count_7d=100,
        success_rate=0.98,
        timeout_rate=0.01,
        avg_latency_ms=200,
        min_support=20,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
        freshness=FreshnessTriple(
            last_successful_call_at=datetime.now(timezone.utc),
            source_updated_at=datetime.now(timezone.utc),
            indexed_at=datetime.now(timezone.utc),
        ),
    )


@pytest.fixture
def unhealthy_snap():
    return ToolOperabilitySnapshot(
        tool_id="b::t2",
        server_id="b",
        status="active",
        call_count=100,
        call_count_7d=50,
        success_rate=0.6,
        timeout_rate=0.15,
        avg_latency_ms=3000,
        p95_latency_ms=8000,
        min_support=20,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
        freshness=FreshnessTriple(
            last_successful_call_at=datetime.now(timezone.utc) - timedelta(days=100),
        ),
    )


def test_no_insights_for_healthy_tool(healthy_snap):
    from mcp_discovery.analytics.insight_engine import InsightEngine

    engine = InsightEngine()
    insights = engine.analyze(healthy_snap)
    assert len(insights) == 0


def test_multiple_insights_for_unhealthy_tool(unhealthy_snap):
    from mcp_discovery.analytics.insight_engine import InsightEngine

    engine = InsightEngine()
    insights = engine.analyze(unhealthy_snap)
    assert len(insights) >= 2
    categories = {i.category for i in insights}
    assert "success_rate" in categories or "timeout" in categories


def test_cold_start_insight():
    from mcp_discovery.analytics.insight_engine import InsightEngine

    snap = ToolOperabilitySnapshot(
        tool_id="c::t3",
        server_id="c",
        status="active",
        call_count=0,
        call_count_7d=0,
        min_support=20,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
        freshness=FreshnessTriple(
            source_updated_at=datetime.now(timezone.utc) - timedelta(days=10),
        ),
    )
    engine = InsightEngine()
    insights = engine.analyze(snap)
    assert any(i.category == "cold_start" for i in insights)


def test_stale_freshness_insight():
    from mcp_discovery.analytics.insight_engine import InsightEngine

    snap = ToolOperabilitySnapshot(
        tool_id="d::t4",
        server_id="d",
        status="active",
        call_count=50,
        call_count_7d=0,
        success_rate=0.9,
        min_support=20,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
        freshness=FreshnessTriple(
            last_successful_call_at=datetime.now(timezone.utc) - timedelta(days=95),
        ),
    )
    engine = InsightEngine()
    insights = engine.analyze(snap)
    assert any(i.category == "freshness" for i in insights)


def test_insight_has_data_field(unhealthy_snap):
    from mcp_discovery.analytics.insight_engine import InsightEngine

    engine = InsightEngine()
    insights = engine.analyze(unhealthy_snap)
    for insight in insights:
        assert insight.data is not None
        assert isinstance(insight.data, dict)
        assert len(insight.data) > 0


def test_description_quality_insight():
    from mcp_discovery.analytics.insight_engine import InsightEngine

    snap = ToolOperabilitySnapshot(
        tool_id="e::t5",
        server_id="e",
        status="active",
        call_count=50,
        call_count_7d=20,
        success_rate=0.9,
        min_support=20,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
    )
    engine = InsightEngine()
    insights = engine.analyze(snap, description="A tool")  # very short description
    assert any(i.category == "description" for i in insights)
