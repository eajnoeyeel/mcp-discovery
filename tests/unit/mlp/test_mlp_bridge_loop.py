"""Tests for the bridge loop harness summary computation."""

import json
from pathlib import Path

import pytest

from service.harness.bridge_loop import _load_runs, summarize_bridge_runs


def test_summarize_bridge_runs_computes_roundtrip_rates():
    summary = summarize_bridge_runs(
        [
            {
                "search_ok": True,
                "execute_ok": True,
                "search_latency_ms": 100,
                "execute_latency_ms": 25,
            },
            {
                "search_ok": True,
                "execute_ok": False,
                "search_latency_ms": 140,
                "execute_latency_ms": 1000,
            },
            {
                "search_ok": False,
                "execute_ok": False,
                "search_latency_ms": 500,
                "execute_latency_ms": 0,
            },
        ]
    )

    assert summary["runs"] == 3.0
    assert summary["search_success_rate"] == 2 / 3
    assert summary["execute_success_rate"] == 1 / 3
    assert summary["roundtrip_success_rate"] == 1 / 3
    assert summary["p95_total_latency_ms"] >= summary["p50_total_latency_ms"]


def test_summarize_bridge_runs_defaults_missing_latency_to_zero():
    summary = summarize_bridge_runs([{"search_ok": True, "execute_ok": True}])
    assert summary["p50_total_latency_ms"] == 0.0
    assert summary["mean_total_latency_ms"] == 0.0


def test_summarize_bridge_runs_empty():
    summary = summarize_bridge_runs([])
    assert summary == {
        "runs": 0.0,
        "search_success_rate": 0.0,
        "execute_success_rate": 0.0,
        "roundtrip_success_rate": 0.0,
        "p50_total_latency_ms": 0.0,
        "p95_total_latency_ms": 0.0,
        "mean_total_latency_ms": 0.0,
    }


def test_load_runs_uses_sample_data_when_input_missing():
    runs = _load_runs(None)
    assert len(runs) == 3
    assert all("search_ok" in item for item in runs)
    assert all("execute_ok" in item for item in runs)


def test_load_runs_reads_json_list(tmp_path):
    payload = [{"query": "q", "search_ok": True, "execute_ok": True}]
    path = tmp_path / "runs.json"
    path.write_text(json.dumps(payload))
    assert _load_runs(str(path)) == payload


def test_recorded_fixture_loads_and_summarizes():
    fixture_path = Path("service/harness/fixtures/bridge_runs_recorded_sample.json")
    runs = _load_runs(str(fixture_path))
    summary = summarize_bridge_runs(runs)

    assert len(runs) == 3
    assert summary == {
        "runs": 3.0,
        "search_success_rate": 1.0,
        "execute_success_rate": 2 / 3,
        "roundtrip_success_rate": 2 / 3,
        "p50_total_latency_ms": 594.0,
        "p95_total_latency_ms": 2989.5,
        "mean_total_latency_ms": 1372.5,
    }


def test_load_runs_rejects_non_list_json(tmp_path):
    path = tmp_path / "runs.json"
    path.write_text(json.dumps({"bad": True}))
    with pytest.raises(ValueError, match="JSON list"):
        _load_runs(str(path))
