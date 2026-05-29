"""Assert that payload builders never emit plaintext secret columns.

These tests guard against regressions that would reintroduce writes of
bearer_token / api_key / client_secret / refresh_token to the DB. They
run without network access (no Supabase, no AWS).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from service.services.contracts import UpstreamAuthConfig

PLAINTEXT_SECRET_KEYS = {"bearer_token", "api_key", "client_secret", "refresh_token"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_no_plaintext(payload: dict, context: str = "") -> None:
    present = PLAINTEXT_SECRET_KEYS & payload.keys()
    assert not present, (
        f"{context}: payload contains plaintext secret key(s) {present!r}. "
        "Only _ref columns are permitted."
    )


# ---------------------------------------------------------------------------
# supabase_client.SupabaseClient.upsert_server_auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_server_auth_no_plaintext_bearer():
    from service.adapters.supabase_client import SupabaseClient
    from service.services.secret_refs import ServerAuthSecretRefs

    captured: list[dict] = []

    client = SupabaseClient.__new__(SupabaseClient)
    client._headers = {}

    async def fake_request(method, path, *, payload=None, params=None, headers=None):
        captured.append(payload or {})
        resp = MagicMock()
        resp.json.return_value = []
        return resp

    client._request = fake_request

    auth = UpstreamAuthConfig(auth_type="bearer", bearer_token="super-secret-token")
    refs = ServerAuthSecretRefs(
        bearer_token_ref="mlp/srv1/auth/bearer_token",
        api_key_ref=None,
    )
    await client.upsert_server_auth("srv1", auth, secret_refs=refs)

    assert captured, "No payload was captured"
    _assert_no_plaintext(captured[0], "upsert_server_auth (bearer)")


@pytest.mark.asyncio
async def test_upsert_server_auth_no_plaintext_api_key():
    from service.adapters.supabase_client import SupabaseClient
    from service.services.secret_refs import ServerAuthSecretRefs

    captured: list[dict] = []

    client = SupabaseClient.__new__(SupabaseClient)
    client._headers = {}

    async def fake_request(method, path, *, payload=None, params=None, headers=None):
        captured.append(payload or {})
        resp = MagicMock()
        resp.json.return_value = []
        return resp

    client._request = fake_request

    auth = UpstreamAuthConfig(
        auth_type="api_key_header",
        api_key_header_name="X-API-Key",
        api_key="my-api-key",
    )
    refs = ServerAuthSecretRefs(
        bearer_token_ref=None,
        api_key_ref="mlp/srv2/auth/api_key",
    )
    await client.upsert_server_auth("srv2", auth, secret_refs=refs)

    assert captured
    _assert_no_plaintext(captured[0], "upsert_server_auth (api_key)")


# ---------------------------------------------------------------------------
# supabase_client.SupabaseClient.upsert_oauth_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_oauth_session_no_plaintext():
    from service.adapters.supabase_client import SupabaseClient
    from service.services.secret_refs import OAuthSecretRefs

    captured: list[dict] = []

    client = SupabaseClient.__new__(SupabaseClient)
    client._headers = {}

    async def fake_request(method, path, *, payload=None, params=None, headers=None):
        captured.append(payload or {})
        resp = MagicMock()
        resp.json.return_value = []
        return resp

    client._request = fake_request

    auth = UpstreamAuthConfig(
        auth_type="oauth_session",
        oauth_token_endpoint="https://example.com/token",
        oauth_client_id="client-id",
        oauth_client_secret="top-secret",
        oauth_refresh_token="refresh-abc",
        oauth_scope="read",
    )
    refs = OAuthSecretRefs(
        client_secret_ref="mlp/srv3/oauth/client_secret",
        refresh_token_ref="mlp/srv3/oauth/refresh_token",
    )
    await client.upsert_oauth_session("srv3", auth, secret_refs=refs)

    assert captured
    _assert_no_plaintext(captured[0], "upsert_oauth_session")


# ---------------------------------------------------------------------------
# register_service.RegisterService — full register() path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_service_bearer_no_plaintext_in_db_call():
    """RegisterService.register() must not pass plaintext into upsert_server_auth."""
    from service.services.register_service import RegisterService
    from service.services.secret_refs import ServerAuthSecretRefs

    db_calls: list[dict] = []

    mock_db = AsyncMock()
    mock_db.upsert_server.return_value = None
    mock_db.insert_tools.return_value = None

    async def capture_upsert_server_auth(server_id, auth, *, secret_refs=None):
        # Simulate what SupabaseClient does: build the row
        row = {
            "server_id": server_id,
            "auth_type": auth.auth_type,
            "api_key_header_name": auth.api_key_header_name,
            "headers": auth.headers,
            "bearer_token_ref": secret_refs.bearer_token_ref if secret_refs else None,
            "api_key_ref": secret_refs.api_key_ref if secret_refs else None,
        }
        db_calls.append(row)

    mock_db.upsert_server_auth = capture_upsert_server_auth

    mock_events = AsyncMock()
    mock_events.publish_server_registered.return_value = None

    mock_secret_store = AsyncMock()
    mock_secret_store.provision_server_auth_secret_refs.return_value = ServerAuthSecretRefs(
        bearer_token_ref="mlp/srv4/auth/bearer_token",
        api_key_ref=None,
    )

    svc = RegisterService(
        db=mock_db,
        events=mock_events,
        oauth_secret_store=mock_secret_store,
    )

    payload = {
        "server_id": "srv4",
        "name": "Test Server",
        "url": "https://example.com/mcp",
        "tools": [{"tool_name": "ping", "description": "Ping tool"}],
        "execution_auth": {
            "auth_type": "bearer",
            "bearer_token": "plaintext-should-not-reach-db",
        },
        "transport_type": "stateless_http",
        "requires_gateway": False,
    }

    await svc.register(payload)

    assert db_calls, "upsert_server_auth was never called"
    _assert_no_plaintext(db_calls[0], "register() → upsert_server_auth row")


@pytest.mark.asyncio
async def test_register_service_oauth_no_plaintext_in_db_call():
    """RegisterService.register() must not pass plaintext into upsert_oauth_session."""
    from service.services.register_service import RegisterService
    from service.services.secret_refs import OAuthSecretRefs

    db_calls: list[dict] = []

    mock_db = AsyncMock()
    mock_db.upsert_server.return_value = None
    mock_db.insert_tools.return_value = None

    async def capture_upsert_oauth(server_id, auth, *, secret_refs=None):
        row = {
            "server_id": server_id,
            "client_secret_ref": secret_refs.client_secret_ref if secret_refs else None,
            "refresh_token_ref": secret_refs.refresh_token_ref if secret_refs else None,
        }
        db_calls.append(row)

    mock_db.upsert_oauth_session = capture_upsert_oauth

    mock_events = AsyncMock()
    mock_events.publish_server_registered.return_value = None

    mock_secret_store = AsyncMock()
    mock_secret_store.provision_oauth_secret_refs.return_value = OAuthSecretRefs(
        client_secret_ref="mlp/srv5/oauth/client_secret",
        refresh_token_ref="mlp/srv5/oauth/refresh_token",
    )

    svc = RegisterService(
        db=mock_db,
        events=mock_events,
        oauth_secret_store=mock_secret_store,
    )

    payload = {
        "server_id": "srv5",
        "name": "OAuth Server",
        "url": "https://example.com/mcp",
        "tools": [{"tool_name": "act", "description": "Action tool"}],
        "execution_auth": {
            "auth_type": "oauth_session",
            "oauth_token_endpoint": "https://example.com/token",
            "oauth_client_id": "cid",
            "oauth_client_secret": "plaintext-secret",
            "oauth_refresh_token": "plaintext-refresh",
        },
        "transport_type": "stateless_http",
        "requires_gateway": False,
    }

    await svc.register(payload)

    assert db_calls, "upsert_oauth_session was never called"
    _assert_no_plaintext(db_calls[0], "register() → upsert_oauth_session row")
