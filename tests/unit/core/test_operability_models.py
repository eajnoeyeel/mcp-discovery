from datetime import datetime, timezone


def test_freshness_triple_all_fresh():
    from mcp_discovery.operability.models import FreshnessTriple

    now = datetime.now(timezone.utc)
    ft = FreshnessTriple(
        source_updated_at=now,
        indexed_at=now,
        last_successful_call_at=now,
    )
    assert ft.source_freshness_days == 0
    assert ft.index_freshness_days == 0
    assert ft.operational_freshness_days == 0


def test_freshness_triple_none_fields():
    from mcp_discovery.operability.models import FreshnessTriple

    ft = FreshnessTriple()
    assert ft.source_freshness_days is None
    assert ft.index_freshness_days is None
    assert ft.operational_freshness_days is None


def test_operability_snapshot_cold_start():
    from mcp_discovery.operability.models import ToolOperabilitySnapshot

    snap = ToolOperabilitySnapshot(
        tool_id="test::tool",
        server_id="test",
        status="active",
        call_count=5,
        call_count_7d=3,
        min_support=20,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
    )
    assert snap.cold_start is True


def test_operability_snapshot_not_cold_start():
    from mcp_discovery.operability.models import ToolOperabilitySnapshot

    snap = ToolOperabilitySnapshot(
        tool_id="test::tool",
        server_id="test",
        status="active",
        call_count=25,
        call_count_7d=10,
        success_rate=0.95,
        min_support=20,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
    )
    assert snap.cold_start is False
    assert snap.success_rate == 0.95


def test_operability_enrichment_from_snapshot():
    from mcp_discovery.operability.models import (
        ToolOperabilityEnrichment,
        ToolOperabilitySnapshot,
        build_enrichment,
    )

    snap = ToolOperabilitySnapshot(
        tool_id="test::tool",
        server_id="test",
        status="active",
        call_count=50,
        call_count_7d=20,
        success_rate=0.92,
        avg_latency_ms=150.0,
        min_support=20,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
    )
    enrichment = build_enrichment(snap)
    assert isinstance(enrichment, ToolOperabilityEnrichment)
    assert enrichment.status == "active"
    assert enrichment.cold_start is False
    assert enrichment.success_rate == 0.92
    assert enrichment.operability_grade in ("A", "B", "C", "D", "F")


def test_operability_enrichment_none_for_none():
    from mcp_discovery.operability.models import build_enrichment

    assert build_enrichment(None) is None


def test_compute_operability_float_healthy():
    from mcp_discovery.operability.models import compute_operability_float

    score = compute_operability_float(
        success_rate=0.95,
        avg_latency_ms=200.0,
        timeout_rate=0.01,
    )
    assert 0.7 < score <= 1.0


def test_compute_operability_float_cold_start():
    from mcp_discovery.operability.models import compute_operability_float

    score = compute_operability_float(
        success_rate=None,
        avg_latency_ms=None,
        timeout_rate=None,
    )
    assert score == 0.5


def test_search_result_has_operability_field():
    from mcp_discovery.models import MCPTool, SearchResult

    tool = MCPTool(tool_id="a::t", server_id="a", tool_name="t", description="test")
    result = SearchResult(tool=tool, score=0.8, rank=1)
    assert result.operability is None
    assert result.retrieval_score is None
