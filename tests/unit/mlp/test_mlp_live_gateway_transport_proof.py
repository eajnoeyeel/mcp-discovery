"""Tests for the live gateway transport proof harness."""

from pathlib import Path

from service.harness.live_gateway_transport_proof import (
    fixture_script_path,
    run_sample,
    summarize_transport_runs,
)


def test_summarize_transport_runs_counts_success_by_transport():
    summary = summarize_transport_runs(
        [
            {"transport": "streamable_http", "ok": True},
            {"transport": "sse", "ok": False},
            {"transport": "stdio", "ok": True},
        ]
    )

    assert summary["runs"] == 3
    assert summary["success_rate"] == 2 / 3
    assert summary["per_transport"]["streamable_http"] == 1.0
    assert summary["per_transport"]["sse"] == 0.0
    assert summary["per_transport"]["stdio"] == 1.0


def test_run_sample_reports_local_stdio_fixture():
    payload = run_sample()

    assert payload["mode"] == "sample"
    assert payload["summary"]["runs"] == 3
    assert payload["summary"]["per_transport"]["stdio"] == 1.0
    assert Path(payload["fixture"]).resolve() == fixture_script_path().resolve()
    assert fixture_script_path().name == "stdio_echo_server.py"
