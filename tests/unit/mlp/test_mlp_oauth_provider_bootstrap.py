from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from service.services.oauth_provider_bootstrap import (
    OAuthProviderBootstrapError,
    OAuthProviderBootstrapService,
    build_dcr_registration_payload,
    build_redirect_uri,
    decode_oauth_state,
    encode_oauth_state,
    hash_state_nonce,
    normalize_authorization_metadata,
    normalize_protected_resource_metadata,
    redact_sensitive,
)


def test_normalize_authorization_metadata_maps_supported_fields() -> None:
    result = normalize_authorization_metadata(
        {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/oauth/authorize",
            "token_endpoint": "https://auth.example.com/oauth/token",
            "registration_endpoint": "https://auth.example.com/oauth/register",
            "scopes_supported": ["repo", "issues:write"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "response_types_supported": ["code"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
            "code_challenge_methods_supported": ["S256"],
        },
        source_url="https://auth.example.com/.well-known/oauth-authorization-server",
        expected_issuer="https://auth.example.com",
    )

    assert result["authorize_url"] == "https://auth.example.com/oauth/authorize"
    assert result["token_url"] == "https://auth.example.com/oauth/token"
    assert result["registration_endpoint"] == "https://auth.example.com/oauth/register"
    assert result["supports_dcr"] is True
    assert result["supported_token_endpoint_auth_methods"] == ["none", "client_secret_basic"]
    assert result["pkce_required"] is True


def test_normalize_authorization_metadata_rejects_issuer_mismatch() -> None:
    with pytest.raises(OAuthProviderBootstrapError, match="issuer mismatch"):
        normalize_authorization_metadata(
            {
                "issuer": "https://evil.example.com",
                "authorization_endpoint": "https://auth.example.com/oauth/authorize",
                "token_endpoint": "https://auth.example.com/oauth/token",
            },
            source_url="https://auth.example.com/.well-known/oauth-authorization-server",
            expected_issuer="https://auth.example.com",
        )


def test_normalize_authorization_metadata_rejects_non_https_urls() -> None:
    with pytest.raises(OAuthProviderBootstrapError, match="HTTPS"):
        normalize_authorization_metadata(
            {
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "http://auth.example.com/oauth/authorize",
                "token_endpoint": "https://auth.example.com/oauth/token",
            },
            source_url="https://auth.example.com/.well-known/oauth-authorization-server",
        )


def test_normalize_authorization_metadata_blocks_private_advertised_endpoint() -> None:
    with pytest.raises(OAuthProviderBootstrapError) as exc_info:
        normalize_authorization_metadata(
            {
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://127.0.0.1/oauth/authorize",
                "token_endpoint": "https://auth.example.com/oauth/token",
            },
            source_url="https://auth.example.com/.well-known/oauth-authorization-server",
            enforce_public_network=True,
        )

    assert exc_info.value.code == "oauth_metadata_host_blocked"


def test_protected_resource_metadata_requires_explicit_selection_for_multiple_servers() -> None:
    with pytest.raises(OAuthProviderBootstrapError) as exc_info:
        normalize_protected_resource_metadata(
            {
                "authorization_servers": [
                    "https://auth-a.example.com",
                    "https://auth-b.example.com",
                ],
            },
            source_url="https://mcp.example.com/.well-known/oauth-protected-resource",
        )

    assert exc_info.value.code == "authorization_server_selection_required"


def test_build_dcr_registration_payload_uses_rfc7591_fields() -> None:
    payload = build_dcr_registration_payload(
        client_name="MLP MCP Broker - GitHub",
        redirect_uri="https://api.example.com/api/oauth/providers/github/callback",
        scopes=["repo", "repo", "read:user"],
        token_endpoint_auth_method="client_secret_basic",
        supports_refresh_token=True,
    )

    assert payload == {
        "client_name": "MLP MCP Broker - GitHub",
        "redirect_uris": ["https://api.example.com/api/oauth/providers/github/callback"],
        "response_types": ["code"],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "client_secret_basic",
        "scope": "repo read:user",
    }


def test_redact_sensitive_recursively() -> None:
    assert redact_sensitive(
        {
            "client_secret": "secret",
            "supports_refresh_token": True,
            "nested": {"access_token": "token", "safe": "ok"},
            "items": [{"refresh_token": "refresh"}],
        }
    ) == {
        "client_secret": "[REDACTED]",
        "supports_refresh_token": True,
        "nested": {"access_token": "[REDACTED]", "safe": "ok"},
        "items": [{"refresh_token": "[REDACTED]"}],
    }


def test_redirect_uri_uses_provider_callback_route() -> None:
    actual = build_redirect_uri(
        public_base_url="https://api.example.com/",
        provider_key="GitHub",
    )
    assert actual == ("https://api.example.com/api/oauth/providers/github/callback")


def test_state_nonce_hash_roundtrip() -> None:
    assert hash_state_nonce("nonce") == hash_state_nonce("nonce")
    state = encode_oauth_state({"nonce": "nonce", "exp": 9999999999})
    assert decode_oauth_state(state)["nonce"] == "nonce"


@pytest.mark.asyncio
async def test_manual_draft_stores_client_secret_ref_only() -> None:
    repo = AsyncMock()
    repo.fetch_bootstrap_draft_by_idempotency_key = AsyncMock(return_value=None)
    repo.create_oauth_provider_bootstrap_draft = AsyncMock(
        side_effect=lambda payload: {"id": "draft-1", **payload}
    )
    secret_store = AsyncMock()
    secret_store.provision_provider_client_secret_ref = AsyncMock(
        return_value="mlp/oauth-providers/github/client_secret"
    )

    result = await OAuthProviderBootstrapService(
        repo=repo,
        public_base_url="https://api.example.com",
        secret_store=secret_store,
    ).create_manual_draft(
        owner_user_id="user-1",
        provider_key="github",
        display_name="GitHub",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        client_id="client-id",
        client_secret="plain-secret",
        token_endpoint_auth_method="client_secret_post",
        default_scopes=["repo"],
    )

    payload = repo.create_oauth_provider_bootstrap_draft.await_args.args[0]
    assert result.status == "validated"
    assert payload["metadata"]["client_secret_ref"] == "mlp/oauth-providers/github/client_secret"
    assert "plain-secret" not in repr(payload)
    secret_store.provision_provider_client_secret_ref.assert_awaited_once_with(
        provider_key="github", client_secret="plain-secret"
    )


@pytest.mark.asyncio
async def test_manual_draft_is_idempotent() -> None:
    repo = AsyncMock()
    repo.fetch_bootstrap_draft_by_idempotency_key = AsyncMock(
        return_value={
            "id": "draft-existing",
            "provider_key": "github",
            "bootstrap_mode": "manual",
            "status": "validated",
            "metadata": {"provider_key": "github"},
            "diagnostics": {},
            "idempotency_key": "idem-1",
        }
    )
    repo.create_oauth_provider_bootstrap_draft = AsyncMock()

    result = await OAuthProviderBootstrapService(
        repo=repo,
        public_base_url="https://api.example.com",
    ).create_manual_draft(
        owner_user_id="user-1",
        provider_key="github",
        display_name="GitHub",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        client_id="client-id",
        idempotency_key="idem-1",
    )

    assert result.draft_id == "draft-existing"
    repo.create_oauth_provider_bootstrap_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_with_client_credentials_creates_enableable_validated_draft() -> None:
    repo = AsyncMock()
    repo.fetch_bootstrap_draft_by_idempotency_key = AsyncMock(return_value=None)
    repo.create_oauth_provider_bootstrap_draft = AsyncMock(
        side_effect=lambda payload: {"id": "draft-discovery", **payload}
    )
    repo.promote_oauth_provider_bootstrap_draft = AsyncMock(
        return_value={"provider_key": "github", "enabled": True}
    )

    class FakeHTTPClient:
        async def get(self, url, **_kwargs):
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json={
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "code_challenge_methods_supported": ["S256"],
                },
            )

    service = OAuthProviderBootstrapService(
        repo=repo,
        public_base_url="https://api.example.com",
        http_client=FakeHTTPClient(),
    )
    draft = await service.discover(
        owner_user_id="user-1",
        provider_key="github",
        authorization_server_metadata_url=(
            "https://auth.example.com/.well-known/oauth-authorization-server"
        ),
        client_id="client-id",
        token_endpoint_auth_method="none",
    )
    enabled = await service.enable(owner_user_id="user-1", draft_id=draft.draft_id or "")

    payload = repo.create_oauth_provider_bootstrap_draft.await_args.args[0]
    assert draft.status == "validated"
    assert payload["status"] == "validated"
    assert payload["metadata"]["client_id"] == "client-id"
    assert payload["metadata"]["supports_refresh_token"] is True
    assert payload["metadata"]["pkce_required"] is True
    assert enabled == {"provider_key": "github", "enabled": True}


@pytest.mark.asyncio
async def test_enable_rejects_path_provider_mismatch_before_promotion() -> None:
    repo = AsyncMock()
    repo.fetch_oauth_provider_bootstrap_draft = AsyncMock(
        return_value={
            "id": "draft-1",
            "provider_key": "github",
            "metadata": {"provider_key": "github"},
            "status": "validated",
        }
    )
    repo.promote_oauth_provider_bootstrap_draft = AsyncMock()
    service = OAuthProviderBootstrapService(repo=repo, public_base_url="https://api.example.com")

    with pytest.raises(OAuthProviderBootstrapError) as exc:
        await service.enable(owner_user_id="user-1", draft_id="draft-1", provider_key="slack")

    assert exc.value.code == "provider_key_mismatch"
    repo.promote_oauth_provider_bootstrap_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_enable_promotes_when_path_provider_matches_draft() -> None:
    repo = AsyncMock()
    repo.fetch_oauth_provider_bootstrap_draft = AsyncMock(
        return_value={
            "id": "draft-1",
            "provider_key": "github",
            "metadata": {"provider_key": "github"},
            "status": "validated",
        }
    )
    repo.promote_oauth_provider_bootstrap_draft = AsyncMock(
        return_value={"provider_key": "github", "enabled": True}
    )
    service = OAuthProviderBootstrapService(repo=repo, public_base_url="https://api.example.com")

    result = await service.enable(owner_user_id="user-1", draft_id="draft-1", provider_key="github")

    assert result == {"provider_key": "github", "enabled": True}
    repo.promote_oauth_provider_bootstrap_draft.assert_awaited_once_with(
        draft_id="draft-1", owner_user_id="user-1"
    )


@pytest.mark.asyncio
async def test_discovery_without_client_credentials_records_next_step_draft() -> None:
    repo = AsyncMock()
    repo.fetch_bootstrap_draft_by_idempotency_key = AsyncMock(return_value=None)
    repo.create_oauth_provider_bootstrap_draft = AsyncMock(
        side_effect=lambda payload: {"id": "draft-discovery", **payload}
    )

    class FakeHTTPClient:
        async def get(self, url, **_kwargs):
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json={
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                },
            )

    draft = await OAuthProviderBootstrapService(
        repo=repo,
        public_base_url="https://api.example.com",
        http_client=FakeHTTPClient(),
    ).discover(
        owner_user_id="user-1",
        provider_key="github",
        authorization_server_metadata_url=(
            "https://auth.example.com/.well-known/oauth-authorization-server"
        ),
    )

    payload = repo.create_oauth_provider_bootstrap_draft.await_args.args[0]
    assert draft.status == "draft"
    assert payload["metadata"]["bootstrap_status"] == "draft"
    assert payload["diagnostics"]["next_step"] == (
        "run_dcr_or_create_manual_draft_with_client_credentials"
    )


@pytest.mark.asyncio
async def test_manual_draft_blocks_private_network_token_url() -> None:
    repo = AsyncMock()
    repo.fetch_bootstrap_draft_by_idempotency_key = AsyncMock(return_value=None)

    with pytest.raises(OAuthProviderBootstrapError) as exc_info:
        await OAuthProviderBootstrapService(
            repo=repo,
            public_base_url="https://api.example.com",
        ).create_manual_draft(
            owner_user_id="user-1",
            provider_key="internal",
            display_name="Internal",
            authorize_url="https://127.0.0.1/authorize",
            token_url="https://127.0.0.1/token",
            client_id="client-id",
        )

    assert exc_info.value.code == "oauth_metadata_host_blocked"


@pytest.mark.asyncio
async def test_dcr_draft_stores_returned_secret_ref_only() -> None:
    repo = AsyncMock()
    repo.fetch_bootstrap_draft_by_idempotency_key = AsyncMock(return_value=None)
    repo.create_oauth_provider_bootstrap_draft = AsyncMock(
        side_effect=lambda payload: {"id": "draft-dcr", **payload}
    )
    secret_store = AsyncMock()
    secret_store.provision_provider_client_secret_ref = AsyncMock(
        return_value="mlp/oauth-providers/github/client_secret"
    )
    seen: dict[str, object] = {}

    class FakeHTTPClient:
        async def post(self, url, **kwargs):
            seen["url"] = url
            seen["json"] = kwargs["json"]
            return httpx.Response(
                201,
                request=httpx.Request("POST", url),
                json={"client_id": "dcr-client", "client_secret": "dcr-secret"},
            )

    result = await OAuthProviderBootstrapService(
        repo=repo,
        public_base_url="https://api.example.com",
        secret_store=secret_store,
        http_client=FakeHTTPClient(),
    ).run_dcr(
        owner_user_id="user-1",
        provider_key="github",
        display_name="GitHub",
        registration_endpoint="https://auth.example.com/register",
        authorize_url="https://auth.example.com/authorize",
        token_url="https://auth.example.com/token",
        client_name="MLP GitHub",
        token_endpoint_auth_method="client_secret_basic",
        scopes=["repo"],
        idempotency_key="dcr-1",
    )

    payload = repo.create_oauth_provider_bootstrap_draft.await_args.args[0]
    assert result.status == "validated"
    assert seen["json"]["redirect_uris"] == [
        "https://api.example.com/api/oauth/providers/github/callback"
    ]
    assert payload["metadata"]["client_id"] == "dcr-client"
    assert payload["metadata"]["client_secret_ref"] == "mlp/oauth-providers/github/client_secret"
    assert "dcr-secret" not in repr(payload)
