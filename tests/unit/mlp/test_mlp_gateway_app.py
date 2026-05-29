"""Tests for internal MLP MCP gateway API."""

from __future__ import annotations

import sys
import time
from unittest.mock import AsyncMock

import anyio
from fastapi.testclient import TestClient

from service.gateway.internal_auth import build_internal_auth_headers
from service.gateway.settings import GatewaySettings


class FakeSession:
    def __init__(self) -> None:
        self.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})


class FakeSessionPool:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.get = AsyncMock(return_value=session)

    def status(self) -> dict[str, int]:
        return {"active": 0, "idle": 0, "max_sessions": 4}

    async def close_all(self) -> None:
        pass


def _settings() -> GatewaySettings:
    return GatewaySettings.model_validate({"internal_auth_secret": "shared-secret"})


def test_gateway_health_reports_session_pool_status() -> None:
    from service.gateway.app import create_app

    pool = FakeSessionPool(FakeSession())
    app = create_app(session_pool=pool, config_loader=AsyncMock(), settings=_settings())

    response = TestClient(app).get("/gateway/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "sessions": {"active": 0, "idle": 0, "max_sessions": 4},
    }


def test_gateway_execute_rejects_missing_internal_auth() -> None:
    from service.gateway.app import create_app

    fake_session = FakeSession()
    pool = FakeSessionPool(fake_session)
    config_loader = AsyncMock(
        return_value={"pool_key": "srv:streamable_http:https://p.example/mcp"}
    )
    app = create_app(session_pool=pool, config_loader=config_loader, settings=_settings())

    response = TestClient(app).post(
        "/gateway/execute",
        json={"server_id": "srv", "tool_name": "lookup", "arguments": {"query": "x"}},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid internal gateway auth"}
    config_loader.assert_not_awaited()
    pool.get.assert_not_awaited()
    fake_session.call_tool.assert_not_awaited()


def test_gateway_execute_loads_config_reuses_session_and_calls_tool() -> None:
    from service.gateway.app import create_app

    fake_session = FakeSession()
    pool = FakeSessionPool(fake_session)
    config_loader = AsyncMock(
        return_value={"pool_key": "srv:streamable_http:https://p.example/mcp"}
    )
    app = create_app(session_pool=pool, config_loader=config_loader, settings=_settings())

    payload = b'{"server_id":"srv","tool_name":"lookup","arguments":{"query":"x"}}'
    headers = build_internal_auth_headers(
        secret="shared-secret",
        method="POST",
        path="/gateway/execute",
        body=payload,
        timestamp=str(int(time.time())),
    )
    headers["Content-Type"] = "application/json"

    response = TestClient(app).post(
        "/gateway/execute",
        content=payload,
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "server_id": "srv",
        "tool_name": "lookup",
        "result": {"content": [{"type": "text", "text": "ok"}]},
    }
    config_loader.assert_awaited_once_with("srv")
    pool.get.assert_awaited_once_with("srv:streamable_http:https://p.example/mcp")
    fake_session.call_tool.assert_awaited_once_with("lookup", {"query": "x"})


def test_gateway_execute_uses_ephemeral_session_when_headers_are_present(monkeypatch) -> None:
    from service.gateway import app as gateway_app
    from service.gateway.app import create_app

    fake_session = FakeSession()
    pool = FakeSessionPool(FakeSession())
    config_loader = AsyncMock(
        return_value={
            "server_id": "apify-oauth",
            "transport_type": "streamable_http",
            "url": "https://mcp.apify.com?tools=apify/google-search-scraper",
            "pool_key": "apify-oauth:streamable_http:https://mcp.apify.com?tools=apify/google-search-scraper",
        }
    )
    create_session = AsyncMock(return_value=fake_session)
    fake_session.close = AsyncMock()
    monkeypatch.setattr(gateway_app, "create_pooled_mcp_session", create_session)
    app = create_app(session_pool=pool, config_loader=config_loader, settings=_settings())

    payload = (
        b'{"server_id":"apify-oauth","tool_name":"lookup","arguments":{"query":"x"},'
        b'"headers":{"Authorization":"Bearer token"}}'
    )
    headers = build_internal_auth_headers(
        secret="shared-secret",
        method="POST",
        path="/gateway/execute",
        body=payload,
        timestamp=str(int(time.time())),
    )
    headers["Content-Type"] = "application/json"

    response = TestClient(app).post(
        "/gateway/execute",
        content=payload,
        headers=headers,
    )

    assert response.status_code == 200
    pool.get.assert_not_awaited()
    create_session.assert_awaited_once()
    assert create_session.await_args.args[0].headers == {"Authorization": "Bearer token"}
    fake_session.call_tool.assert_awaited_once_with("lookup", {"query": "x"})
    fake_session.close.assert_awaited_once()


def test_gateway_main_loads_supabase_server_config(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_INTERNAL_AUTH_SECRET", "shared-secret")
    sys.modules.pop("service.gateway.main", None)
    import service.gateway.main as main

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {
                    "server_id": "apify-oauth",
                    "transport_type": "streamable_http",
                    "url": "https://mcp.apify.com?tools=apify/google-search-scraper",
                }
            ]

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, **kwargs):
            self.url = url
            self.kwargs = kwargs
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setenv("SUPABASE_URL", "https://db.example.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda timeout: fake_client)

    config = anyio.run(main.load_gateway_config, "apify-oauth")

    assert config["pool_key"] == (
        "apify-oauth:streamable_http:https://mcp.apify.com?tools=apify/google-search-scraper"
    )
    assert config["server_id"] == "apify-oauth"
    assert config["transport_type"] == "streamable_http"
    assert config["url"] == "https://mcp.apify.com?tools=apify/google-search-scraper"
