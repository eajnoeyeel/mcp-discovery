"""Tests for the search loop harness summary computation."""

import json

import pytest

from service.harness.search_loop import _load_runs, summarize_runs


def test_summarize_runs_computes_success_rate_and_p95():
    summary = summarize_runs(
        [
            {"ok": True, "latency_ms": 100},
            {"ok": True, "latency_ms": 140},
            {"ok": False, "latency_ms": 5000},
        ]
    )
    assert summary["success_rate"] == 2 / 3
    assert summary["p95_latency_ms"] >= 140


def test_summarize_runs_single_result():
    summary = summarize_runs([{"ok": True, "latency_ms": 50}])
    assert summary["runs"] == 1.0
    assert summary["success_rate"] == 1.0
    assert summary["p50_latency_ms"] == 50


def test_summarize_runs_all_failures():
    summary = summarize_runs([{"ok": False, "latency_ms": 200}, {"ok": False, "latency_ms": 300}])
    assert summary["success_rate"] == 0.0
    assert summary["runs"] == 2.0


def test_summarize_runs_empty():
    summary = summarize_runs([])
    assert summary == {
        "runs": 0.0,
        "success_rate": 0.0,
        "p50_latency_ms": 0.0,
        "p95_latency_ms": 0.0,
        "mean_latency_ms": 0.0,
    }


def test_load_runs_uses_sample_data_when_input_missing():
    runs = _load_runs(None)
    assert len(runs) == 3
    assert all("latency_ms" in item for item in runs)


def test_load_runs_reads_json_list(tmp_path):
    payload = [{"query": "q", "ok": True, "latency_ms": 12.3}]
    path = tmp_path / "runs.json"
    path.write_text(json.dumps(payload))
    assert _load_runs(str(path)) == payload


def test_load_runs_rejects_non_list_json(tmp_path):
    path = tmp_path / "runs.json"
    path.write_text(json.dumps({"bad": True}))
    with pytest.raises(ValueError, match="JSON list"):
        _load_runs(str(path))
