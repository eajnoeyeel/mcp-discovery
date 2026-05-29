"""Tests for compute_confidence with strategy_hint parameter (hybrid/RRF path)."""

from unittest.mock import MagicMock

from mcp_discovery.pipeline.confidence import compute_confidence


def _mk(score: float, rank: int, tool_id: str = "s::t") -> MagicMock:
    r = MagicMock()
    r.score = score
    r.rank = rank
    r.tool.tool_id = tool_id + str(rank)
    r.retrieval_score = None  # force fallback to .score
    return r


def test_compute_confidence_dense_default_gap_015():
    results = [_mk(0.9, 1), _mk(0.7, 2), _mk(0.5, 3)]
    conf, ambig = compute_confidence(results)
    assert conf == 0.9
    assert ambig is False


def test_compute_confidence_hybrid_uses_smaller_threshold():
    # RRF scores are close — with default 0.15 threshold this would be ambiguous
    # and with a smaller threshold (0.005) it is also ambiguous (gap < 0.005)
    results = [_mk(0.0164, 1), _mk(0.0161, 2)]
    conf, ambig = compute_confidence(results, strategy_hint="hybrid", gap_threshold=0.005)
    assert ambig is True


def test_compute_confidence_hybrid_confident_when_gap_above_threshold():
    # gap = 0.020 - 0.012 = 0.008 > 0.005 → confident
    results = [_mk(0.020, 1), _mk(0.012, 2)]
    conf, ambig = compute_confidence(results, strategy_hint="hybrid", gap_threshold=0.005)
    assert ambig is False


def test_compute_confidence_strategy_hint_dense_unchanged():
    """strategy_hint='dense' with default threshold behaves exactly as before."""
    results = [_mk(0.8, 1), _mk(0.72, 2)]
    _, ambig = compute_confidence(results, strategy_hint="dense")
    # gap = 0.08 < 0.15 → ambiguous
    assert ambig is True
