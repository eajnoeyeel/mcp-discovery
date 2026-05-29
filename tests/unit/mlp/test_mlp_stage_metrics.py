"""Unit tests for service.analytics.stage_metrics.StageMetrics."""

from service.analytics.stage_metrics import StageMetrics


def test_stage_metrics_schema_contract() -> None:
    """All schema keys are present; values may be None or False (observability contract)."""
    m = StageMetrics()
    dumped = m.model_dump()
    assert "source_path" in dumped
    assert "candidate_ms" in dumped
    assert "freshness_ms" in dumped
    assert "rerank_ms" in dumped
    assert "fallback_used" in dumped
    assert "cold_cache" in dumped
    assert dumped["fallback_used"] is False
    assert dumped["cold_cache"] is False


def test_stage_metrics_exclude_none_omits_null_timings() -> None:
    """model_dump(exclude_none=True) omits None timing fields but keeps cold_cache=False."""
    m = StageMetrics(source_path="hybrid_semantic")
    dumped = m.model_dump(exclude_none=True)
    assert dumped["source_path"] == "hybrid_semantic"
    assert "candidate_ms" not in dumped
    assert "freshness_ms" not in dumped
    assert "rerank_ms" not in dumped
    assert dumped["cold_cache"] is False


def test_stage_metrics_default_constructible() -> None:
    """Bridge emits StageMetrics() with no args — must not raise."""
    m = StageMetrics()
    assert m.source_path is None
    assert m.fallback_used is False
    assert m.cold_cache is False


def test_stage_metrics_full_payload_round_trips() -> None:
    """Full payload round-trips through model_dump."""
    m = StageMetrics(
        source_path="semantic",
        candidate_ms=12.5,
        freshness_ms=3.1,
        rerank_ms=None,
        fallback_used=False,
        cold_cache=True,
    )
    dumped = m.model_dump(exclude_none=True)
    assert dumped == {
        "source_path": "semantic",
        "candidate_ms": 12.5,
        "freshness_ms": 3.1,
        "fallback_used": False,
        "cold_cache": True,
    }
