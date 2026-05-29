"""Unit tests for QueryLogger stage_metrics contract."""

from service.services.query_logger import QueryLogger


def _make_logger() -> QueryLogger:
    return QueryLogger(supabase_url="http://fake", supabase_key="fake-key")


def test_log_query_persists_source_path_under_stage_metrics() -> None:
    """_build_payload passes stage_metrics dict through to the payload unchanged."""
    ql = _make_logger()
    payload = ql._build_payload(
        event_id="ev-001",
        query="find a github tool",
        results=[{"tool_id": "srv::t1", "score": 0.9, "rank": 1}],
        confidence=0.9,
        strategy="rag",
        latency_ms=42.0,
        stage_metrics={"source_path": "hybrid_semantic"},
    )
    assert payload["stage_metrics"]["source_path"] == "hybrid_semantic"


def test_stage_metrics_schema_contract() -> None:
    """_build_payload includes stage_metrics key; value may be None (Bridge pre-Phase-2)."""
    ql = _make_logger()
    payload = ql._build_payload(
        event_id="ev-002",
        query="q",
        results=[],
        confidence=0.0,
        strategy="rag",
        latency_ms=10.0,
        stage_metrics=None,
    )
    assert "stage_metrics" in payload
    assert payload["stage_metrics"] is None


def test_stage_metrics_cold_cache_flag() -> None:
    """cold_cache=True is preserved in stage_metrics JSONB payload."""
    ql = _make_logger()
    payload = ql._build_payload(
        event_id="ev-003",
        query="q",
        results=[],
        confidence=0.0,
        strategy="rag",
        latency_ms=5.0,
        stage_metrics={"source_path": "semantic", "cold_cache": True},
    )
    assert payload["stage_metrics"]["cold_cache"] is True
    assert payload["stage_metrics"]["source_path"] == "semantic"
