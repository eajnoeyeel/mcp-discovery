"""Tests for the gateway health probe harness."""

import httpx
import pytest

from service.harness.gateway_health_probe import (
    probe_gateway_health,
    run_sample,
    summarize_gateway_health_runs,
)


def test_summarize_gateway_health_runs_tracks_success_rate_and_p95_latency():
    summary = summarize_gateway_health_runs(
        [
            {
                "path": "/gateway/health",
                "ok": True,
                "latency_ms": 110.0,
                "payload": {},
                "error": None,
            },
            {
                "path": "/gateway/health",
                "ok": True,
                "latency_ms": 140.0,
                "payload": {},
                "error": None,
            },
            {
                "path": "/gateway/health",
                "ok": False,
                "latency_ms": 2500.0,
                "payload": None,
                "error": "timeout",
            },
        ]
    )

    assert summary["runs"] == 3
    assert summary["success_rate"] == 2 / 3
    assert summary["p95_latency_ms"] == 2500.0


@pytest.mark.asyncio
async def test_probe_gateway_health_reports_stable_timeout_error(monkeypatch):
    async def fake_get(self, url, timeout):
        raise httpx.TimeoutException("")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await probe_gateway_health("https://example.test", timeout_s=0.1)

    assert result["path"] == "/gateway/health"
    assert result["ok"] is False
    assert result["payload"] is None
    assert result["error"] == "timeout"


def test_run_sample_returns_expected_gateway_health_payload_shape():
    payload = run_sample()

    assert payload["mode"] == "sample"
    assert payload["summary"]["runs"] == 3
    assert payload["summary"]["success_rate"] == 2 / 3
    assert payload["results"][0]["path"] == "/gateway/health"
