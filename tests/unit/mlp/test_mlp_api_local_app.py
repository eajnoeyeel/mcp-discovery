from __future__ import annotations

import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

try:  # pragma: no cover - import guard for stripped local test envs
    import loguru  # noqa: F401
except ModuleNotFoundError:
    fake_loguru = types.ModuleType("loguru")
    fake_loguru.logger = MagicMock()
    sys.modules["loguru"] = fake_loguru


def test_local_api_app_exposes_provider_discovery_and_metadata_routes(monkeypatch) -> None:
    monkeypatch.setenv("MLP_API_KEY", "")
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")
    # _EXPECTED_API_KEY is captured at first import of local_app; earlier files
    # in the suite may have loaded it while MLP_API_KEY was set. Patch directly.
    monkeypatch.setattr("service.api.local_app._EXPECTED_API_KEY", "")
    # Other handler test modules pop these handler modules from sys.modules on
    # teardown, so force fresh imports before monkeypatching to ensure the
    # fake handlers are the attributes the endpoint resolves.
    import service.lambdas.catalog.handler  # noqa: F401 PLC0415
    import service.lambdas.dashboard.handler  # noqa: F401 PLC0415
    import service.lambdas.register.handler  # noqa: F401 PLC0415

    async def fake_register_handler(event, _context):
        path = event["rawPath"]
        if path == "/api/providers/servers/discovery":
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {"url": "https://provider.test/mcp", "tools": [], "warnings": []}
                ),
            }
        if path == "/api/servers":
            return {
                "statusCode": 201,
                "body": json.dumps({"server_id": "srv", "tools_count": 1}),
            }
        raise AssertionError(f"unexpected register path {path}")

    async def fake_catalog_handler(event, _context):
        path = event["rawPath"]
        return {
            "statusCode": 200,
            "body": json.dumps({"path": path, "method": event["requestContext"]["http"]["method"]}),
        }

    async def fake_dashboard_handler(event, _context):
        path = event["rawPath"]
        return {
            "statusCode": 200,
            "body": json.dumps({"path": path, "method": event["requestContext"]["http"]["method"]}),
        }

    monkeypatch.setattr("service.lambdas.register.handler._async_handler", fake_register_handler)
    monkeypatch.setattr("service.lambdas.catalog.handler._async_handler", fake_catalog_handler)
    monkeypatch.setattr("service.lambdas.dashboard.handler._async_handler", fake_dashboard_handler)

    from service.api.local_app import create_app

    client = TestClient(create_app())

    discovery = client.post(
        "/api/providers/servers/discovery",
        json={"url": "https://provider.test/mcp", "execution_auth": {"auth_type": "none"}},
    )
    assert discovery.status_code == 200
    assert discovery.json()["url"] == "https://provider.test/mcp"

    connect_discovery = client.post(
        "/api/providers/connect/discover",
        json={"server_id": "srv", "url": "https://provider.test/mcp"},
    )
    assert connect_discovery.status_code == 200
    assert connect_discovery.json()["url"] == "https://provider.test/mcp"
    assert connect_discovery.json()["auth_type"] == "none"

    update = client.put(
        "/api/providers/tools/srv::lookup",
        json={"description": "Published copy"},
    )
    assert update.status_code == 200
    assert update.json()["path"] == "/api/providers/tools/srv::lookup"

    preview = client.post(
        "/api/providers/tools/srv::lookup/metadata-refresh-preview",
        json={},
    )
    assert preview.status_code == 200
    assert preview.json()["path"].endswith("/metadata-refresh-preview")

    apply_resp = client.post(
        "/api/providers/tools/srv::lookup/metadata-refresh-apply",
        json={},
    )
    assert apply_resp.status_code == 200
    assert apply_resp.json()["path"].endswith("/metadata-refresh-apply")

    quality = client.get("/api/servers/srv/quality")
    assert quality.status_code == 200
    assert quality.json() == {"path": "/api/servers/srv/quality", "method": "GET"}


def test_local_app_starts_and_stops_eventbridge_relay(monkeypatch) -> None:
    monkeypatch.setenv("MLP_API_KEY", "")
    monkeypatch.setenv("MLP_EVENT_MODE", "local_direct")

    import service.api.local_app as local_app
    import service.lambdas.register as register_package

    relay = MagicMock()
    relay.start = AsyncMock()
    relay.stop = AsyncMock()
    set_eventbridge_client = MagicMock()

    fake_index_handler = types.ModuleType("service.lambdas.index.handler")
    fake_index_handler._async_handler = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    fake_register_handler = types.ModuleType("service.lambdas.register.handler")
    fake_register_handler.set_eventbridge_client_for_local_runtime = set_eventbridge_client
    fake_register_handler._async_handler = AsyncMock(return_value={"statusCode": 201, "body": "{}"})

    with (
        patch.object(register_package, "handler", fake_register_handler, create=True),
        patch.dict(
            sys.modules,
            {
                "service.lambdas.index.handler": fake_index_handler,
                "service.lambdas.register.handler": fake_register_handler,
            },
        ),
        patch.object(local_app, "LocalEventBridgeRelay", return_value=relay),
    ):
        with TestClient(local_app.create_app()) as client:
            response = client.get("/health")

    assert response.status_code == 200
    relay.start.assert_awaited_once()
    relay.stop.assert_awaited_once()
    assert set_eventbridge_client.call_count == 2
    injected_client = set_eventbridge_client.call_args_list[0].args[0]
    assert injected_client is not None
    assert getattr(injected_client, "_publisher") is relay
    assert set_eventbridge_client.call_args_list[1].args == (None,)


def test_local_direct_register_route_wires_relay_backed_eventbridge_client(monkeypatch) -> None:
    monkeypatch.setenv("MLP_API_KEY", "")
    monkeypatch.setenv("MLP_EVENT_MODE", "local_direct")

    import service.api.local_app as local_app
    import service.lambdas.register as register_package

    relay = MagicMock()
    relay.start = AsyncMock()
    relay.stop = AsyncMock()
    set_eventbridge_client = MagicMock()
    register_async_handler = AsyncMock(
        return_value={
            "statusCode": 201,
            "body": json.dumps({"server_id": "srv-local", "tools_count": 1}),
        }
    )

    fake_index_handler = types.ModuleType("service.lambdas.index.handler")
    fake_index_handler._async_handler = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    fake_register_handler = types.ModuleType("service.lambdas.register.handler")
    fake_register_handler.set_eventbridge_client_for_local_runtime = set_eventbridge_client
    fake_register_handler._async_handler = register_async_handler

    with (
        patch.object(register_package, "handler", fake_register_handler, create=True),
        patch.dict(
            sys.modules,
            {
                "service.lambdas.index.handler": fake_index_handler,
                "service.lambdas.register.handler": fake_register_handler,
            },
        ),
        patch.object(local_app, "LocalEventBridgeRelay", return_value=relay),
    ):
        with TestClient(local_app.create_app()) as client:
            response = client.post(
                "/api/servers",
                json={
                    "server_id": "srv-local",
                    "name": "Local Server",
                    "url": "https://example.test/mcp",
                    "tools": [{"tool_name": "lookup", "description": "Lookup docs"}],
                },
            )

    assert response.status_code == 201
    assert response.json() == {"server_id": "srv-local", "tools_count": 1}
    relay.start.assert_awaited_once()
    relay.stop.assert_awaited_once()
    register_async_handler.assert_awaited_once()
    forwarded_event = register_async_handler.await_args.args[0]
    assert forwarded_event["rawPath"] == "/api/servers"
    assert forwarded_event["requestContext"]["http"]["method"] == "POST"
    assert json.loads(forwarded_event["body"]) == {
        "server_id": "srv-local",
        "name": "Local Server",
        "url": "https://example.test/mcp",
        "tools": [{"tool_name": "lookup", "description": "Lookup docs"}],
    }
    injected_client = set_eventbridge_client.call_args_list[0].args[0]
    assert injected_client is not None
    assert getattr(injected_client, "_publisher") is relay
    assert set_eventbridge_client.call_args_list[1].args == (None,)


def test_local_app_exposes_provider_oauth_routes():
    from service.api.local_app import create_app

    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/api/oauth/providers/{provider}/start" in paths
    assert "/api/oauth/providers/{provider}/callback" in paths


def test_local_auth_probe_requires_api_key(monkeypatch) -> None:
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")

    import service.api.local_app as local_app

    monkeypatch.setattr(local_app, "_EXPECTED_API_KEY", "probe-key")
    client = TestClient(local_app.create_app())
    response = client.post(
        "/api/auth/probe",
        headers={"Authorization": "Bearer token-only"},
    )

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden"}


def test_local_auth_probe_requires_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")

    import service.api.local_app as local_app

    monkeypatch.setattr(local_app, "_EXPECTED_API_KEY", "probe-key")
    client = TestClient(local_app.create_app())
    response = client.post("/api/auth/probe", headers={"x-api-key": "probe-key"})

    assert response.status_code == 401
    assert response.json() == {"error": "Missing bearer token"}


def test_local_auth_probe_validates_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")

    import service.api.local_app as local_app

    monkeypatch.setattr(local_app, "_EXPECTED_API_KEY", "probe-key")
    auth_client = MagicMock()
    auth_client.get_user = AsyncMock(return_value={"id": "user-789"})
    monkeypatch.setattr(local_app, "SupabaseAuthClient", MagicMock(return_value=auth_client))

    client = TestClient(local_app.create_app())
    response = client.post(
        "/api/auth/probe",
        headers={"Authorization": "Bearer local-valid-token", "x-api-key": "probe-key"},
    )

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["status"] == "authenticated"
    assert response.json()["user_id"] == "user-789"
    assert response.json()["auth_source"] == "supabase_bearer"
    assert response.json()["issuer"] == "supabase"
    auth_client.get_user.assert_awaited_once_with("local-valid-token")


def test_local_auth_probe_returns_503_when_validation_backend_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")

    import service.api.local_app as local_app

    monkeypatch.setattr(local_app, "_EXPECTED_API_KEY", "probe-key")
    auth_client = MagicMock()
    auth_client.get_user = AsyncMock(side_effect=httpx.ConnectError("boom"))
    monkeypatch.setattr(local_app, "SupabaseAuthClient", MagicMock(return_value=auth_client))

    client = TestClient(local_app.create_app())
    response = client.post(
        "/api/auth/probe",
        headers={"Authorization": "Bearer local-valid-token", "x-api-key": "probe-key"},
    )

    assert response.status_code == 503
    assert response.json()["authenticated"] is False
    assert response.json()["status"] == "validation_unavailable"
    assert response.json()["auth_source"] == "supabase_bearer"
    assert response.json()["error"] == "supabase_validation_unavailable"


def test_local_resume_pending_execution_returns_resumed_result(monkeypatch) -> None:
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")

    import service.api.local_app as local_app
    import service.lambdas.execute.handler as execute_handler

    monkeypatch.setattr(local_app, "_EXPECTED_API_KEY", "probe-key")
    auth_client = MagicMock()
    auth_client.get_user = AsyncMock(return_value={"id": "user-789"})
    monkeypatch.setattr(local_app, "SupabaseAuthClient", MagicMock(return_value=auth_client))

    execute_service = MagicMock()
    execute_service.resume_pending_execution = AsyncMock(
        return_value=MagicMock(
            success=True,
            tool_id="srv::lookup",
            server_id="srv",
            result={"ok": True},
        )
    )
    monkeypatch.setattr(
        execute_handler,
        "_get_execute_service",
        MagicMock(return_value=execute_service),
    )

    client = TestClient(local_app.create_app())
    response = client.post(
        "/api/pending-executions/rt_123/resume",
        headers={"Authorization": "Bearer local-valid-token", "x-api-key": "probe-key"},
        json={},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "resumed",
        "tool_id": "srv::lookup",
        "server_id": "srv",
        "result": {"ok": True},
    }
    execute_service.resume_pending_execution.assert_awaited_once_with(
        "rt_123",
        user_id="user-789",
    )


def test_local_client_connect_session_returns_oauth_start_url(monkeypatch) -> None:
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")

    import service.api.local_app as local_app
    import service.lambdas.oauth_start.handler as oauth_start_handler

    monkeypatch.setattr(local_app, "_EXPECTED_API_KEY", "probe-key")
    auth_client = MagicMock()
    auth_client.get_user = AsyncMock(return_value={"id": "user-789"})
    monkeypatch.setattr(local_app, "SupabaseAuthClient", MagicMock(return_value=auth_client))
    registry = MagicMock()
    registry.fetch_tool_contract = AsyncMock(
        return_value=types.SimpleNamespace(
            auth_requirement=types.SimpleNamespace(
                provider="github",
                required_scopes=["repo", "issues:write"],
            )
        )
    )
    monkeypatch.setattr(local_app, "SupabaseToolRegistry", MagicMock(return_value=registry))
    mocked_oauth_start = AsyncMock(
        return_value={
            "statusCode": 200,
            "body": json.dumps(
                {
                    "provider": "apify",
                    "oauth_url": "https://console.apify.com/authorize/oauth?client_id=demo",
                    "state": "state-123",
                }
            ),
        }
    )
    monkeypatch.setattr(oauth_start_handler, "_async_handler", mocked_oauth_start)
    monkeypatch.setattr(local_app, "oauth_start_handler", mocked_oauth_start)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/api/client-connections/session",
        headers={"Authorization": "Bearer local-valid-token", "x-api-key": "probe-key"},
        json={
            "server_id": "apify-oauth",
            "tool_name": "apify--google-search-scraper",
            "tool_id": "apify-oauth::apify--google-search-scraper",
            "auth_type": "oauth",
            "pending_execution_id": "pending-123",
        },
    )

    assert response.status_code == 200
    assert response.json()["connect_session_id"] == "pending-123"
    assert (
        response.json()["start_url"] == "https://console.apify.com/authorize/oauth?client_id=demo"
    )
    forwarded_event = mocked_oauth_start.await_args.args[0]
    assert forwarded_event["rawPath"] == "/api/oauth/providers/github/start"
    assert json.loads(forwarded_event["body"]) == {
        "provider": "github",
        "tool_id": "apify-oauth::apify--google-search-scraper",
        "required_scopes": ["repo", "issues:write"],
        "pending_execution_id": "pending-123",
    }


def test_local_client_connect_session_uses_persisted_auth_for_non_suffix_server(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")

    import service.api.local_app as local_app
    import service.lambdas.oauth_start.handler as oauth_start_handler

    monkeypatch.setattr(local_app, "_EXPECTED_API_KEY", "probe-key")
    auth_client = MagicMock()
    auth_client.get_user = AsyncMock(return_value={"id": "user-789"})
    monkeypatch.setattr(local_app, "SupabaseAuthClient", MagicMock(return_value=auth_client))
    registry = MagicMock()
    registry.fetch_tool_contract = AsyncMock(
        return_value=types.SimpleNamespace(
            auth_requirement=types.SimpleNamespace(
                provider="github",
                required_scopes=["repo"],
            )
        )
    )
    monkeypatch.setattr(local_app, "SupabaseToolRegistry", MagicMock(return_value=registry))
    mocked_oauth_start = AsyncMock(
        return_value={
            "statusCode": 200,
            "body": json.dumps(
                {
                    "provider": "github",
                    "oauth_url": "https://github.test/oauth/start",
                    "state": "state-123",
                }
            ),
        }
    )
    monkeypatch.setattr(oauth_start_handler, "_async_handler", mocked_oauth_start)
    monkeypatch.setattr(local_app, "oauth_start_handler", mocked_oauth_start)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/api/client-connections/session",
        headers={"Authorization": "Bearer local-valid-token", "x-api-key": "probe-key"},
        json={
            "server_id": "search-hub",
            "tool_name": "lookup",
            "tool_id": "search-hub::lookup",
            "auth_type": "oauth",
        },
    )

    assert response.status_code == 200
    forwarded_event = mocked_oauth_start.await_args.args[0]
    assert forwarded_event["rawPath"] == "/api/oauth/providers/github/start"
    assert json.loads(forwarded_event["body"]) == {
        "provider": "github",
        "tool_id": "search-hub::lookup",
        "required_scopes": ["repo"],
        "pending_execution_id": None,
    }


def test_local_client_connect_session_fails_closed_when_contract_fetch_raises_runtime_error(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")

    import service.api.local_app as local_app

    monkeypatch.setattr(local_app, "_EXPECTED_API_KEY", "probe-key")
    auth_client = MagicMock()
    auth_client.get_user = AsyncMock(return_value={"id": "user-789"})
    monkeypatch.setattr(local_app, "SupabaseAuthClient", MagicMock(return_value=auth_client))
    registry = MagicMock()
    registry.fetch_tool_contract = AsyncMock(side_effect=RuntimeError("server read failed"))
    monkeypatch.setattr(local_app, "SupabaseToolRegistry", MagicMock(return_value=registry))
    mocked_oauth_start = AsyncMock()
    monkeypatch.setattr(local_app, "oauth_start_handler", mocked_oauth_start)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/api/client-connections/session",
        headers={"Authorization": "Bearer local-valid-token", "x-api-key": "probe-key"},
        json={
            "server_id": "search-hub",
            "tool_name": "lookup",
            "tool_id": "search-hub::lookup",
            "auth_type": "oauth",
            "provider_key": "github",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": "Unable to resolve delegated auth metadata for hosted connect"
    }
    mocked_oauth_start.assert_not_awaited()


def test_local_client_connect_session_fails_closed_when_auth_metadata_read_fails(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")

    import service.api.local_app as local_app

    monkeypatch.setattr(local_app, "_EXPECTED_API_KEY", "probe-key")
    auth_client = MagicMock()
    auth_client.get_user = AsyncMock(return_value={"id": "user-789"})
    monkeypatch.setattr(local_app, "SupabaseAuthClient", MagicMock(return_value=auth_client))
    registry = MagicMock()
    registry.fetch_tool_contract = AsyncMock(
        side_effect=local_app.AuthRequirementLookupError("metadata read failed")
    )
    monkeypatch.setattr(local_app, "SupabaseToolRegistry", MagicMock(return_value=registry))
    mocked_oauth_start = AsyncMock()
    monkeypatch.setattr(local_app, "oauth_start_handler", mocked_oauth_start)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/api/client-connections/session",
        headers={"Authorization": "Bearer local-valid-token", "x-api-key": "probe-key"},
        json={
            "server_id": "search-hub",
            "tool_name": "lookup",
            "tool_id": "search-hub::lookup",
            "auth_type": "oauth",
            "provider_key": "github",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": "Unable to resolve delegated auth metadata for hosted connect"
    }
    mocked_oauth_start.assert_not_awaited()


def test_local_client_connect_session_falls_back_to_legacy_provider_scope(monkeypatch) -> None:
    monkeypatch.setenv("MLP_EVENT_MODE", "disabled")
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")

    import service.api.local_app as local_app
    import service.lambdas.oauth_start.handler as oauth_start_handler

    monkeypatch.setattr(local_app, "_EXPECTED_API_KEY", "probe-key")
    auth_client = MagicMock()
    auth_client.get_user = AsyncMock(return_value={"id": "user-789"})
    monkeypatch.setattr(local_app, "SupabaseAuthClient", MagicMock(return_value=auth_client))
    registry = MagicMock()
    registry.fetch_tool_contract = AsyncMock(return_value=None)
    monkeypatch.setattr(local_app, "SupabaseToolRegistry", MagicMock(return_value=registry))
    mocked_oauth_start = AsyncMock(
        return_value={
            "statusCode": 200,
            "body": json.dumps(
                {
                    "provider": "apify",
                    "oauth_url": "https://console.apify.com/authorize/oauth?client_id=demo",
                    "state": "state-123",
                }
            ),
        }
    )
    monkeypatch.setattr(oauth_start_handler, "_async_handler", mocked_oauth_start)
    monkeypatch.setattr(local_app, "oauth_start_handler", mocked_oauth_start)

    client = TestClient(local_app.create_app())
    response = client.post(
        "/api/client-connections/session",
        headers={"Authorization": "Bearer local-valid-token", "x-api-key": "probe-key"},
        json={
            "server_id": "apify-oauth",
            "tool_name": "apify--google-search-scraper",
            "auth_type": "oauth",
        },
    )

    assert response.status_code == 200
    forwarded_event = mocked_oauth_start.await_args.args[0]
    assert forwarded_event["rawPath"] == "/api/oauth/providers/apify/start"
    assert json.loads(forwarded_event["body"]) == {
        "provider": "apify",
        "tool_id": "apify-oauth::apify--google-search-scraper",
        "required_scopes": ["full_api_access"],
        "pending_execution_id": None,
    }
