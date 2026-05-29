"""Unit tests for the health check Lambda handler."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_httpx_response(status_code: int = 200, json_data: object = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# _check_mv_freshness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_mv_freshness_returns_ok_when_mv_is_empty(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")

    from service.lambdas.health import handler as h

    mock_resp = _make_httpx_response(200, [])
    with patch("service.lambdas.health.handler.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await h._check_mv_freshness()

    assert result["status"] == "ok"
    assert result.get("reason") == "mv_empty"


@pytest.mark.asyncio
async def test_check_mv_freshness_returns_ok_when_fresh(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")

    from service.lambdas.health import handler as h

    recent_ts = (datetime.now(tz=timezone.utc) - timedelta(minutes=2)).isoformat()
    mock_resp = _make_httpx_response(200, [{"last_called_at": recent_ts}])
    with patch("service.lambdas.health.handler.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await h._check_mv_freshness()

    assert result["status"] == "ok"
    assert result["age_seconds"] < 300


@pytest.mark.asyncio
async def test_check_mv_freshness_returns_degraded_when_stale(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")

    from service.lambdas.health import handler as h

    stale_ts = (datetime.now(tz=timezone.utc) - timedelta(minutes=20)).isoformat()
    mock_resp = _make_httpx_response(200, [{"last_called_at": stale_ts}])
    with patch("service.lambdas.health.handler.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await h._check_mv_freshness()

    assert result["status"] == "degraded"
    assert result["reason"] == "mv_stale"
    assert result["age_seconds"] > 900


@pytest.mark.asyncio
async def test_check_mv_freshness_returns_skip_on_exception(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")

    from service.lambdas.health import handler as h

    with patch("service.lambdas.health.handler.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_client_cls.return_value = mock_client

        result = await h._check_mv_freshness()

    assert result["status"] == "skip"
    assert "check_failed" in result["reason"]


@pytest.mark.asyncio
async def test_check_mv_freshness_skips_when_supabase_url_not_set(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)

    from service.lambdas.health import handler as h

    result = await h._check_mv_freshness()

    assert result["status"] == "skip"
    assert "SUPABASE_URL" in result["reason"]


# ---------------------------------------------------------------------------
# _async_handler — mv_freshness included in response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_handler_includes_mv_freshness_in_checks(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")

    from service.lambdas.health import handler as h

    with (
        patch(
            "service.lambdas.health.handler._check_qdrant",
            new_callable=AsyncMock,
            return_value={"status": "ok"},
        ),
        patch(
            "service.lambdas.health.handler._check_supabase",
            new_callable=AsyncMock,
            return_value={"status": "ok"},
        ),
        patch(
            "service.lambdas.health.handler._check_mv_freshness",
            new_callable=AsyncMock,
            return_value={"status": "ok", "age_seconds": 60},
        ),
    ):
        result = await h._async_handler()

    import json

    body = json.loads(result["body"])
    assert "mv_freshness" in body["checks"]
    assert body["checks"]["mv_freshness"]["status"] == "ok"
    assert body["status"] == "healthy"


@pytest.mark.asyncio
async def test_async_handler_degraded_when_mv_stale(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")

    from service.lambdas.health import handler as h

    with (
        patch(
            "service.lambdas.health.handler._check_qdrant",
            new_callable=AsyncMock,
            return_value={"status": "ok"},
        ),
        patch(
            "service.lambdas.health.handler._check_supabase",
            new_callable=AsyncMock,
            return_value={"status": "ok"},
        ),
        patch(
            "service.lambdas.health.handler._check_mv_freshness",
            new_callable=AsyncMock,
            return_value={"status": "degraded", "reason": "mv_stale", "age_seconds": 1200},
        ),
    ):
        result = await h._async_handler()

    import json

    body = json.loads(result["body"])
    assert body["status"] == "degraded"
    assert result["statusCode"] == 503
