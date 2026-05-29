from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient


def _load_local_mcp_app(monkeypatch):
    monkeypatch.setenv("MLP_MCP_LOCAL_MOCK", "1")
    sys.modules.pop("service.mcp_server.local_app", None)
    import service.mcp_server.local_app as local_app

    return local_app


def _mock_valid_local_bearer(monkeypatch, local_app, user_id: str = "user-123") -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    auth_client = AsyncMock()
    auth_client.get_user = AsyncMock(return_value={"id": user_id})
    monkeypatch.setattr(local_app, "SupabaseAuthClient", MagicMock(return_value=auth_client))


def _authed_headers() -> dict[str, str]:
    return {"Authorization": "Bearer valid-token"}


def test_local_mcp_app_health_and_oauth_metadata(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)

    app = local_app.create_app()
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
    metadata = client.get("/.well-known/oauth-authorization-server")
    assert metadata.status_code == 200
    metadata_body = metadata.json()
    assert metadata_body["registration_endpoint"].endswith("/oauth/register")
    assert client.get("/mcp/.well-known/oauth-authorization-server").status_code == 200
    protected = client.get("/.well-known/oauth-protected-resource")
    assert protected.status_code == 200
    assert protected.json()["resource"].endswith("/mcp")
    authorize = client.get(
        "/oauth/authorize",
        params={"redirect_uri": "https://example.com/callback", "state": "state-123"},
        follow_redirects=False,
    )
    assert authorize.status_code == 302
    assert authorize.headers["location"].startswith("http://127.0.0.1:3001/login?redirect=")
    registration = client.post(
        "/oauth/register",
        json={
            "redirect_uris": ["http://localhost:9999/callback"],
            "client_name": "Claude",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert registration.status_code == 201
    assert registration.json()["client_id"] == "local-dev-claude-client"
    token = client.post("/oauth/token")
    assert token.status_code == 200
    assert token.json()["access_token"] == "local-dev-access-token"


def test_local_mcp_app_wraps_bridge_handler(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app)

    fake_handler = AsyncMock(
        return_value={
            "statusCode": 200,
            "headers": {"MCP-Version": "2025-03-26", "X-Test": "bridge"},
            "body": json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"tools": [{"name": "find_best_tool"}]},
                }
            ),
        }
    )
    monkeypatch.setattr(local_app, "_async_handler", fake_handler)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers=_authed_headers(),
    )

    assert response.status_code == 200
    assert response.headers["mcp-version"] == "2025-03-26"
    assert response.json()["result"]["tools"][0]["name"] == "find_best_tool"


def test_local_mcp_app_requires_bearer_auth_for_mcp_requests(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    assert response.status_code == 401
    assert response.json() == {"error": "Missing bearer token"}


def test_local_oauth_issue_code_validates_bearer_token(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    auth_client = AsyncMock()
    auth_client.get_user = AsyncMock(
        side_effect=local_app.httpx.HTTPStatusError(
            "bad token",
            request=local_app.httpx.Request("GET", "https://supabase.test/auth/v1/user"),
            response=local_app.httpx.Response(401),
        )
    )
    monkeypatch.setattr(local_app, "SupabaseAuthClient", MagicMock(return_value=auth_client))

    client = TestClient(local_app.create_app())
    response = client.post(
        "/oauth/issue-code",
        headers={"Authorization": "Bearer stale-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"error": "Invalid bearer token"}


def test_local_oauth_issue_code_mints_code_for_valid_bearer(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app, user_id="user-999")

    client = TestClient(local_app.create_app())
    response = client.post(
        "/oauth/issue-code",
        headers=_authed_headers(),
    )

    assert response.status_code == 200
    assert response.json()["code"].startswith("local-dev-code-")


def test_local_mcp_app_mock_find_best_tool_proxies_backend(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app)

    class FakeHTTPClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            import httpx

            return httpx.Response(
                200,
                request=httpx.Request("POST", "http://backend/api/search"),
                json={"results": [{"tool_id": "apify::google_search"}], "confidence": 0.9},
            )

    monkeypatch.setattr(local_app.httpx, "AsyncClient", FakeHTTPClient)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "find_best_tool", "arguments": {"query": "apify google search"}},
        },
        headers=_authed_headers(),
    )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["confidence"] == 0.9
    assert payload["results"][0]["tool_id"] == "apify::google_search"
    assert isinstance(payload["query_log_id"], int)


def test_local_mcp_app_mock_uses_configured_timeouts_for_search_and_execute(monkeypatch) -> None:
    monkeypatch.setenv("MLP_MCP_LOCAL_SEARCH_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("MLP_MCP_LOCAL_EXECUTE_TIMEOUT_SECONDS", "35")
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app)
    client_timeouts: list[float] = []

    class FakeHTTPClient:
        def __init__(self, *args, **kwargs):
            client_timeouts.append(kwargs["timeout"])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            import httpx

            if url.endswith("/api/search"):
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={"results": [{"tool_id": "srv::lookup"}], "confidence": 0.9},
                )
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"ok": True},
            )

    monkeypatch.setattr(local_app.httpx, "AsyncClient", FakeHTTPClient)

    client = TestClient(local_app.create_app())
    search_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {
                "name": "find_best_tool",
                "arguments": {"query": "lookup", "top_k": 1},
            },
        },
        headers=_authed_headers(),
    )
    execute_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {
                "name": "execute_tool",
                "arguments": {"tool_id": "srv::lookup", "params": {"query": "x"}},
            },
        },
        headers=_authed_headers(),
    )

    assert search_response.status_code == 200
    assert execute_response.status_code == 200
    assert client_timeouts == [7.5, 35.0]
    assert client_timeouts[1] > client_timeouts[0]


def test_local_mcp_app_mock_execute_tool_forwards_query_log_id(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app)
    calls: list[dict] = []

    class FakeHTTPClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            import httpx

            calls.append({"url": url, "json": kwargs["json"]})
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"ok": True},
            )

    monkeypatch.setattr(local_app.httpx, "AsyncClient", FakeHTTPClient)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "execute_tool",
                "arguments": {
                    "tool_id": "srv::lookup",
                    "params": {"query": "x"},
                    "query_log_id": "42",
                },
            },
        },
        headers=_authed_headers(),
    )

    assert response.status_code == 200
    assert calls[0]["json"]["query_log_id"] == 42
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload == {"ok": True}


def test_local_mcp_app_mock_execute_tool_rejects_invalid_query_log_id(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "execute_tool",
                "arguments": {
                    "tool_id": "srv::lookup",
                    "params": {"query": "x"},
                    "query_log_id": "not-an-int",
                },
            },
        },
        headers=_authed_headers(),
    )

    assert response.status_code == 200
    assert response.json()["error"]["message"] == "query_log_id must be an integer"


def test_local_mcp_app_mock_execute_tool_preserves_backend_auth_required(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app)

    class FakeHTTPClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            import httpx

            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "status": "auth_required",
                    "tool_id": "apify-oauth::apify--google-search-scraper",
                    "server_id": "apify-oauth",
                    "auth": {
                        "provider": "apify",
                        "required_scopes": [],
                        "oauth_url": "http://127.0.0.1:3001/login?redirect=%2Fconnect",
                        "retry_token": "rt_123",
                        "pending_execution_id": None,
                        "message": "apify authorization is required before this tool can run.",
                    },
                },
            )

    monkeypatch.setattr(local_app.httpx, "AsyncClient", FakeHTTPClient)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "execute_tool",
                "arguments": {
                    "tool_id": "apify-oauth::apify--google-search-scraper",
                    "params": {"queries": "대한민국 대통령"},
                },
            },
        },
        headers=_authed_headers(),
    )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["status"] == "auth_required"
    assert payload["auth"]["provider"] == "apify"


def test_local_mcp_app_mock_execute_tool_normalizes_backend_timeout(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app)

    class FakeHTTPClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            import httpx

            raise httpx.ReadTimeout("backend timed out", request=httpx.Request("POST", url))

    monkeypatch.setattr(local_app.httpx, "AsyncClient", FakeHTTPClient)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 51,
            "method": "tools/call",
            "params": {
                "name": "execute_tool",
                "arguments": {"tool_id": "srv::lookup", "params": {}},
            },
        },
        headers=_authed_headers(),
    )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload == {
        "status": "execution_failed",
        "error": "Backend execute timed out",
        "status_code": 504,
    }


def test_local_mcp_app_mock_execute_tool_wraps_non_json_backend_error(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app)

    class FakeHTTPClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            import httpx

            return httpx.Response(
                500,
                request=httpx.Request("POST", url),
                content=b"Internal Server Error",
            )

    monkeypatch.setattr(local_app.httpx, "AsyncClient", FakeHTTPClient)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "execute_tool",
                "arguments": {"tool_id": "srv::lookup", "params": {}},
            },
        },
        headers=_authed_headers(),
    )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload == {
        "status": "execution_failed",
        "error": "Backend returned non-JSON response",
        "status_code": 500,
    }


def test_local_mcp_app_query_log_id_flows_from_search_to_execute(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app)
    calls: list[dict] = []

    class FakeHTTPClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            import httpx

            calls.append({"url": url, "json": kwargs["json"]})
            if url.endswith("/api/search"):
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={"results": [{"tool_id": "srv::lookup"}], "confidence": 0.9},
                )
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"ok": True},
            )

    monkeypatch.setattr(local_app.httpx, "AsyncClient", FakeHTTPClient)

    client = TestClient(local_app.create_app())
    search_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "find_best_tool",
                "arguments": {"query": "apify google search", "top_k": 3},
            },
        },
        headers=_authed_headers(),
    )
    search_payload = json.loads(search_response.json()["result"]["content"][0]["text"])

    execute_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "execute_tool",
                "arguments": {
                    "tool_id": "srv::lookup",
                    "params": {"query": "x"},
                    "query_log_id": search_payload["query_log_id"],
                },
            },
        },
        headers=_authed_headers(),
    )

    assert execute_response.status_code == 200
    assert calls[1]["json"]["query_log_id"] == search_payload["query_log_id"]


def test_local_mcp_app_returns_204_for_notifications(monkeypatch) -> None:
    local_app = _load_local_mcp_app(monkeypatch)
    _mock_valid_local_bearer(monkeypatch, local_app)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers=_authed_headers(),
    )

    assert response.status_code == 204


def test_mock_provider_tools_list_and_lookup() -> None:
    from service.mcp_server.mock_provider import create_app

    client = TestClient(create_app())

    list_response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert list_response.status_code == 200
    assert list_response.json()["result"]["tools"][0]["name"] == "lookup"

    call_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "lookup", "arguments": {"query": "alpha"}},
        },
    )
    assert call_response.status_code == 200
    content = call_response.json()["result"]["content"][0]["text"]
    assert json.loads(content) == {
        "lookup_query": "alpha",
        "server": "mock_provider",
        "ok": True,
    }
