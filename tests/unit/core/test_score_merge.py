"""Tests for hard gate + score merge + enrichment in RAGService hot path."""

from unittest.mock import MagicMock

from mcp_discovery.models import MCPTool, SearchResult


def _make_result(tool_id: str, score: float) -> SearchResult:
    server_id, tool_name = tool_id.split("::")
    tool = MCPTool(
        tool_id=tool_id,
        server_id=server_id,
        tool_name=tool_name,
        description="test",
    )
    return SearchResult(tool=tool, score=score, rank=1)


def test_score_merge_reorders_by_operability():
    """Tool with lower retrieval but higher operability should rise."""
    from service.rag.service import _apply_score_merge

    results = [_make_result("a::t1", 0.8), _make_result("b::t2", 0.7)]
    snapshots = {
        "a::t1": MagicMock(operability_score=0.3, boost=0.0, status="active"),
        "b::t2": MagicMock(operability_score=0.95, boost=0.0, status="active"),
    }
    merged = _apply_score_merge(results, snapshots, w_rel=0.75, w_op=0.25, min_boost_rel=0.3)
    # a::t1: 0.8*0.75 + 0.3*0.25 = 0.675
    # b::t2: 0.7*0.75 + 0.95*0.25 = 0.7625
    assert merged[0].tool.tool_id == "b::t2"
    assert merged[1].tool.tool_id == "a::t1"


def test_score_merge_preserves_retrieval_score():
    from service.rag.service import _apply_score_merge

    results = [_make_result("a::t1", 0.85)]
    snapshots = {
        "a::t1": MagicMock(operability_score=0.9, boost=0.0, status="active"),
    }
    merged = _apply_score_merge(results, snapshots, w_rel=0.75, w_op=0.25, min_boost_rel=0.3)
    assert merged[0].retrieval_score == 0.85
    assert merged[0].score != 0.85  # composite, not retrieval


def test_score_merge_boost_requires_min_relevance():
    from service.rag.service import _apply_score_merge

    results = [_make_result("a::t1", 0.2)]  # below min_boost_relevance
    snapshots = {
        "a::t1": MagicMock(operability_score=0.5, boost=0.5, status="active"),
    }
    merged = _apply_score_merge(results, snapshots, w_rel=0.75, w_op=0.25, min_boost_rel=0.3)
    # boost should NOT apply (retrieval_score 0.2 < min_boost 0.3)
    expected = 0.2 * 0.75 + 0.5 * 0.25  # no boost
    assert abs(merged[0].score - expected) < 0.001


def test_score_merge_boost_applies_above_min_relevance():
    from service.rag.service import _apply_score_merge

    results = [_make_result("a::t1", 0.5)]  # above min_boost_relevance
    snapshots = {
        "a::t1": MagicMock(operability_score=0.5, boost=0.1, status="active"),
    }
    merged = _apply_score_merge(results, snapshots, w_rel=0.75, w_op=0.25, min_boost_rel=0.3)
    expected = 0.5 * 0.75 + 0.5 * 0.25 + 0.1  # boost applies
    assert abs(merged[0].score - expected) < 0.001


def test_hard_gate_filters_blocked_statuses():
    from service.rag.service import _apply_hard_gate

    results = [
        _make_result("a::t1", 0.9),
        _make_result("b::t2", 0.8),
        _make_result("c::t3", 0.7),
    ]
    snapshots = {
        "a::t1": MagicMock(status="active"),
        "b::t2": MagicMock(status="quarantined"),
        "c::t3": MagicMock(status="active"),
    }
    gated = _apply_hard_gate(results, snapshots)
    assert len(gated) == 2
    assert all(r.tool.tool_id != "b::t2" for r in gated)


def test_hard_gate_passes_unknown_tools():
    """Tools not in snapshots should pass through (degraded mode)."""
    from service.rag.service import _apply_hard_gate

    results = [_make_result("unknown::tool", 0.9)]
    gated = _apply_hard_gate(results, {})  # empty snapshots
    assert len(gated) == 1


def test_score_merge_degraded_mode():
    """Empty snapshots -> relevance-only scoring."""
    from service.rag.service import _apply_score_merge

    results = [_make_result("a::t1", 0.8)]
    merged = _apply_score_merge(results, {}, w_rel=0.75, w_op=0.25, min_boost_rel=0.3)
    assert abs(merged[0].score - 0.8 * 0.75) < 0.001
    assert merged[0].retrieval_score == 0.8
