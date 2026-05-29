"""Tests for OAuth secret-ref resolution and persistence."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from service.services.oauth_tokens import OAuthTokenRecord


def test_build_oauth_secret_refs_uses_server_scoped_paths():
    from service.services.secret_refs import build_oauth_secret_refs

    refs = build_oauth_secret_refs("srv", include_client_secret=True)

    assert refs.client_secret_ref == "mlp/srv/oauth/client_secret"
    assert refs.refresh_token_ref == "mlp/srv/oauth/refresh_token"
    assert refs.secret_backend == "aws_secrets_manager"


def test_build_provider_client_secret_ref_uses_provider_scoped_path():
    from service.services.secret_refs import build_provider_client_secret_ref

    assert (
        build_provider_client_secret_ref("GitHub-Enterprise")
        == "mlp/oauth-providers/github-enterprise/client_secret"
    )


def test_build_provider_client_secret_ref_rejects_unsafe_provider_key():
    from service.services.secret_refs import build_provider_client_secret_ref

    with pytest.raises(ValueError):
        build_provider_client_secret_ref("../github")


@pytest.mark.asyncio
async def test_aws_secret_store_provisions_server_scoped_secret_refs():
    from service.adapters.aws_secrets_manager import AWSSecretsManagerOAuthStore

    client = MagicMock()
    store = AWSSecretsManagerOAuthStore(client=client, region_name="ap-northeast-2")

    refs = await store.provision_oauth_secret_refs(
        server_id="srv",
        client_secret="client-secret",
        refresh_token="refresh-token",
    )

    assert refs.client_secret_ref == "mlp/srv/oauth/client_secret"
    assert refs.refresh_token_ref == "mlp/srv/oauth/refresh_token"
    assert client.create_secret.call_count == 2


@pytest.mark.asyncio
async def test_aws_secret_store_resolves_secret_backed_oauth_bundle():
    from service.adapters.aws_secrets_manager import AWSSecretsManagerOAuthStore

    client = MagicMock()
    client.get_secret_value.side_effect = [
        {"SecretString": "resolved-client-secret"},
        {"SecretString": "resolved-refresh-token"},
    ]
    store = AWSSecretsManagerOAuthStore(client=client, region_name="ap-northeast-2")
    record = OAuthTokenRecord(
        server_id="srv",
        token_endpoint="https://auth.example/token",
        client_id="client-id",
        client_secret_ref="mlp/srv/oauth/client_secret",
        refresh_token_ref="mlp/srv/oauth/refresh_token",
    )

    bundle = await store.resolve_oauth_bundle(record)

    assert bundle.client_secret == "resolved-client-secret"
    assert bundle.refresh_token == "resolved-refresh-token"
