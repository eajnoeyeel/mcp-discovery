"""Tests for the API smoke harness helpers."""

from service.harness.smoke_api import classify_status, summarize_smoke_runs


def test_classify_status_marks_5xx_as_failure():
    assert classify_status(200) == "ok"
    assert classify_status(504) == "timeout"
    assert classify_status(500) == "error"


def test_summarize_smoke_runs_computes_timeout_and_latency():
    summary = summarize_smoke_runs(
        [
            {"status_code": 200, "latency_ms": 120},
            {"status_code": 504, "latency_ms": 5000},
            {"status_code": 200, "latency_ms": 150},
        ]
    )
    assert summary["success_rate"] == 2 / 3
    assert summary["timeout_rate"] == 1 / 3
    assert summary["p95_latency_ms"] >= 150
