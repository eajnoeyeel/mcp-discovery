"""Tests for provider upstream OAuth token refresh."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_returns_cached_access_token_when_not_expiring():
    from service.services.oauth_tokens import OAuthTokenRecord, OAuthTokenService

    repo = AsyncMock()
    repo.fetch.return_value = OAuthTokenRecord(
        server_id="srv",
        token_endpoint="https://auth.example/token",
        client_id="client-id",
        client_secret="client-secret",
        access_token="cached-token",
        refresh_token="refresh-token",
        scope="tools.execute",
        token_type="Bearer",
        expires_at=datetime.now(UTC) + timedelta(minutes=20),
    )
    service = OAuthTokenService(repo=repo)

    token = await service.get_access_token("srv")

    assert token == "cached-token"
    repo.fetch.assert_awaited_once_with("srv")
    repo.store.assert_not_awaited()


@pytest.mark.asyncio
async def test_refreshes_expiring_access_token_and_stores_result():
    from service.services.oauth_tokens import OAuthTokenRecord, OAuthTokenService

    repo = AsyncMock()
    repo.fetch.return_value = OAuthTokenRecord(
        server_id="srv",
        token_endpoint="https://auth.example/token",
        client_id="client-id",
        client_secret="client-secret",
        access_token="old-token",
        refresh_token="refresh-token",
        scope="tools.execute",
        token_type="Bearer",
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "grant_type=refresh_token" in body
        assert "refresh_token=refresh-token" in body
        assert "client_id=client-id" in body
        assert "client_secret=client-secret" in body
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        return httpx.Response(
            200,
            json={
                "access_token": "new-token",
                "refresh_token": "new-refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "tools.execute",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = OAuthTokenService(repo=repo, http_client=client)
        token = await service.get_access_token("srv")

    assert token == "new-token"
    repo.store.assert_awaited_once()
    stored = repo.store.await_args.args[0]
    assert stored.access_token == "new-token"
    assert stored.refresh_token == "new-refresh-token"
    assert stored.token_type == "Bearer"
    assert stored.scope == "tools.execute"
    assert stored.expires_at > datetime.now(UTC) + timedelta(minutes=50)


@pytest.mark.asyncio
async def test_refresh_keeps_existing_refresh_token_when_response_omits_one():
    from service.services.oauth_tokens import OAuthTokenRecord, OAuthTokenService

    repo = AsyncMock()
    repo.fetch.return_value = OAuthTokenRecord(
        server_id="srv",
        token_endpoint="https://auth.example/token",
        client_id="client-id",
        access_token=None,
        refresh_token="existing-refresh-token",
        token_type="Bearer",
        expires_at=None,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "new-token", "expires_in": 600},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = OAuthTokenService(repo=repo, http_client=client)
        token = await service.get_access_token("srv")

    assert token == "new-token"
    stored = repo.store.await_args.args[0]
    assert stored.refresh_token == "existing-refresh-token"
    assert stored.token_type == "Bearer"


@pytest.mark.asyncio
async def test_refresh_uses_secret_resolver_when_secret_refs_are_present():
    from service.services.oauth_tokens import OAuthTokenRecord, OAuthTokenService
    from service.services.secret_refs import ResolvedOAuthSecretBundle

    repo = AsyncMock()
    repo.fetch.return_value = OAuthTokenRecord(
        server_id="srv",
        token_endpoint="https://auth.example/token",
        client_id="client-id",
        client_secret_ref="mlp/srv/oauth/client_secret",
        refresh_token_ref="mlp/srv/oauth/refresh_token",
        access_token=None,
        refresh_token=None,
        token_type="Bearer",
        expires_at=None,
    )
    resolver = AsyncMock()
    resolver.resolve_oauth_bundle = AsyncMock(
        return_value=ResolvedOAuthSecretBundle(
            client_secret="resolved-client-secret",
            refresh_token="resolved-refresh-token",
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "client_secret=resolved-client-secret" in body
        assert "refresh_token=resolved-refresh-token" in body
        return httpx.Response(200, json={"access_token": "fresh-token", "expires_in": 300})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = OAuthTokenService(repo=repo, http_client=client, secret_resolver=resolver)
        token = await service.get_access_token("srv")

    assert token == "fresh-token"
    resolver.resolve_oauth_bundle.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_oauth_session_raises_lookup_error():
    from service.services.oauth_tokens import OAuthTokenService

    repo = AsyncMock()
    repo.fetch.return_value = None
    service = OAuthTokenService(repo=repo)

    with pytest.raises(LookupError, match="OAuth session not found"):
        await service.get_access_token("missing")


@pytest.mark.asyncio
async def test_supabase_repository_fetch_maps_secret_ref_row_to_token_record():
    from service.adapters.supabase_oauth_tokens import SupabaseOAuthTokenRepository

    repo = SupabaseOAuthTokenRepository(
        "https://db.example",
        "service-key",
        secret_resolver=AsyncMock(),
    )
    row = {
        "server_id": "srv",
        "token_endpoint": "https://auth.example/token",
        "client_id": "client-id",
        "client_secret_ref": "mlp/srv/oauth/client_secret",
        "access_token": "access-token",
        "refresh_token_ref": "mlp/srv/oauth/refresh_token",
        "scope": "tools.execute",
        "token_type": "Bearer",
        "expires_at": "2026-04-13T12:00:00Z",
        "secret_backend": "aws_secrets_manager",
    }

    with patch.object(repo, "_fetch_sync", return_value=[row]) as fetch_sync:
        record = await repo.fetch("srv")

    fetch_sync.assert_called_once_with("srv")
    assert record is not None
    assert record.server_id == "srv"
    assert record.token_endpoint == "https://auth.example/token"
    assert record.client_id == "client-id"
    assert record.client_secret_ref == "mlp/srv/oauth/client_secret"
    assert record.access_token == "access-token"
    assert record.refresh_token_ref == "mlp/srv/oauth/refresh_token"
    assert record.scope == "tools.execute"
    assert record.token_type == "Bearer"
    assert record.secret_backend == "aws_secrets_manager"
    assert record.expires_at == datetime(2026, 4, 13, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_supabase_repository_fetch_returns_none_for_missing_row():
    from service.adapters.supabase_oauth_tokens import SupabaseOAuthTokenRepository

    repo = SupabaseOAuthTokenRepository("https://db.example", "service-key")

    with patch.object(repo, "_fetch_sync", return_value=[]) as fetch_sync:
        record = await repo.fetch("missing")

    fetch_sync.assert_called_once_with("missing")
    assert record is None


@pytest.mark.asyncio
async def test_supabase_repository_store_persists_secret_refs_without_raw_secrets():
    from service.adapters.supabase_oauth_tokens import SupabaseOAuthTokenRepository
    from service.services.oauth_tokens import OAuthTokenRecord

    repo = SupabaseOAuthTokenRepository("https://db.example", "service-key")
    record = OAuthTokenRecord(
        server_id="srv",
        token_endpoint="https://auth.example/token",
        client_id="client-id",
        client_secret="resolved-client-secret",
        client_secret_ref="mlp/srv/oauth/client_secret",
        access_token="access-token",
        refresh_token="resolved-refresh-token",
        refresh_token_ref="mlp/srv/oauth/refresh_token",
        scope="tools.execute",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 13, 12, 0, tzinfo=UTC),
        secret_backend="aws_secrets_manager",
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_http = MagicMock()
    mock_http.post = MagicMock(return_value=mock_resp)
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)

    with patch("service.adapters.supabase_oauth_tokens.httpx.Client", return_value=mock_http):
        repo._store_sync(record)

    payload = mock_http.post.call_args.kwargs["json"]
    assert payload["client_secret_ref"] == "mlp/srv/oauth/client_secret"
    assert payload["refresh_token_ref"] == "mlp/srv/oauth/refresh_token"
    assert payload["secret_backend"] == "aws_secrets_manager"
    assert "client_secret" not in payload
    assert "refresh_token" not in payload


# ---------------------------------------------------------------------------
# SupabaseOAuthTokenRepository._fetch_sync — synchronous HTTP GET path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supabase_repository_fetch_sync_calls_correct_endpoint():
    from service.adapters.supabase_oauth_tokens import SupabaseOAuthTokenRepository

    repo = SupabaseOAuthTokenRepository("https://db.example", "svc-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = []
    mock_http = MagicMock()
    mock_http.get = MagicMock(return_value=mock_resp)
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)

    with patch("service.adapters.supabase_oauth_tokens.httpx.Client", return_value=mock_http):
        result = repo._fetch_sync("srv-abc")

    mock_http.get.assert_called_once()
    call_kwargs = mock_http.get.call_args
    assert "mcp_oauth_sessions" in call_kwargs.args[0]
    params = call_kwargs.kwargs["params"]
    assert params["server_id"] == "eq.srv-abc"
    assert params["limit"] == 1
    assert result == []


@pytest.mark.asyncio
async def test_supabase_repository_fetch_sync_raises_on_http_error():
    import httpx

    from service.adapters.supabase_oauth_tokens import SupabaseOAuthTokenRepository

    repo = SupabaseOAuthTokenRepository("https://db.example", "svc-key")

    mock_resp = MagicMock()
    request = httpx.Request("GET", "https://db.example/rest/v1/mcp_oauth_sessions")
    response = httpx.Response(500, request=request, json={"message": "internal error"})
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=request, response=response
    )
    mock_http = MagicMock()
    mock_http.get = MagicMock(return_value=mock_resp)
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)

    with patch("service.adapters.supabase_oauth_tokens.httpx.Client", return_value=mock_http):
        with pytest.raises(httpx.HTTPStatusError):
            repo._fetch_sync("srv-abc")


# ---------------------------------------------------------------------------
# SupabaseOAuthTokenRepository.store — async upsert path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supabase_repository_store_sends_upsert_post():
    from service.adapters.supabase_oauth_tokens import SupabaseOAuthTokenRepository
    from service.services.oauth_tokens import OAuthTokenRecord

    repo = SupabaseOAuthTokenRepository("https://db.example", "svc-key")
    record = OAuthTokenRecord(
        server_id="srv",
        token_endpoint="https://auth.example/token",
        client_id="client-id",
        client_secret_ref="mlp/srv/oauth/client_secret",
        access_token="access-tok",
        refresh_token_ref="mlp/srv/oauth/refresh_token",
        scope="tools.execute",
        token_type="Bearer",
        expires_at=datetime(2026, 12, 31, 0, 0, tzinfo=UTC),
        secret_backend="aws_secrets_manager",
    )

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    oauth_patch = "service.adapters.supabase_oauth_tokens.httpx.AsyncClient"
    with patch(oauth_patch, return_value=mock_client):
        await repo.store(record)

    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.await_args.kwargs
    assert "mcp_oauth_sessions" in mock_client.post.await_args.args[0]
    payload = call_kwargs["json"]
    assert payload["server_id"] == "srv"
    assert payload["access_token"] == "access-tok"
    assert payload["client_secret_ref"] == "mlp/srv/oauth/client_secret"
    assert payload["refresh_token_ref"] == "mlp/srv/oauth/refresh_token"
    assert payload["expires_at"] == "2026-12-31T00:00:00Z"
    assert payload["secret_backend"] == "aws_secrets_manager"
    assert "client_secret" not in payload
    assert "refresh_token" not in payload
    headers = call_kwargs["headers"]
    assert "merge-duplicates" in headers["Prefer"]
    params = call_kwargs["params"]
    assert params["on_conflict"] == "server_id"


@pytest.mark.asyncio
async def test_supabase_repository_store_handles_none_expires_at():
    from service.adapters.supabase_oauth_tokens import SupabaseOAuthTokenRepository
    from service.services.oauth_tokens import OAuthTokenRecord

    repo = SupabaseOAuthTokenRepository("https://db.example", "svc-key")
    record = OAuthTokenRecord(
        server_id="srv",
        token_endpoint="https://auth.example/token",
        client_id="client-id",
        refresh_token_ref="mlp/srv/oauth/refresh_token",
        token_type="Bearer",
        expires_at=None,
    )

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    oauth_patch = "service.adapters.supabase_oauth_tokens.httpx.AsyncClient"
    with patch(oauth_patch, return_value=mock_client):
        await repo.store(record)

    payload = mock_client.post.await_args.kwargs["json"]
    assert payload["expires_at"] is None
    assert payload["secret_backend"] == "aws_secrets_manager"


# ---------------------------------------------------------------------------
# _parse_datetime helper
# ---------------------------------------------------------------------------


def test_parse_datetime_parses_z_suffix():
    from service.adapters.supabase_oauth_tokens import _parse_datetime

    result = _parse_datetime("2026-04-15T12:30:00Z")
    assert result is not None
    assert result.year == 2026
    assert result.month == 4
    assert result.day == 15
    assert result.tzinfo is not None


def test_parse_datetime_parses_utc_offset():
    from service.adapters.supabase_oauth_tokens import _parse_datetime

    result = _parse_datetime("2026-04-15T12:30:00+00:00")
    assert result is not None
    assert result.hour == 12


def test_parse_datetime_returns_none_for_none_input():
    from service.adapters.supabase_oauth_tokens import _parse_datetime

    assert _parse_datetime(None) is None


def test_parse_datetime_returns_none_for_empty_string():
    from service.adapters.supabase_oauth_tokens import _parse_datetime

    assert _parse_datetime("") is None
