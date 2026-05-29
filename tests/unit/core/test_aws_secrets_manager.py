"""Unit tests for mlp/adapters/aws_secrets_manager.py — AWSSecretsManagerOAuthStore."""

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from service.adapters.aws_secrets_manager import AWSSecretsManagerOAuthStore
from service.services.oauth_tokens import OAuthTokenRecord
from service.services.secret_refs import OAuthSecretRefs


def _client_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "error"}},
        "OperationName",
    )


def _make_record(
    server_id: str = "srv_test",
    client_secret: str | None = None,
    client_secret_ref: str | None = None,
    refresh_token: str | None = "rt-abc",
    refresh_token_ref: str | None = None,
) -> OAuthTokenRecord:
    return OAuthTokenRecord(
        server_id=server_id,
        token_endpoint="https://auth.example/token",
        client_id="client-id",
        client_secret=client_secret,
        client_secret_ref=client_secret_ref,
        refresh_token=refresh_token,
        refresh_token_ref=refresh_token_ref,
    )


def _make_sync_client(
    create_raises: ClientError | None = None,
    get_value: str | None = "secret-value",
    get_raises: ClientError | None = None,
) -> MagicMock:
    client = MagicMock()
    if create_raises:
        client.create_secret.side_effect = create_raises
    client.put_secret_value = MagicMock()
    if get_raises:
        client.get_secret_value.side_effect = get_raises
    else:
        client.get_secret_value.return_value = {"SecretString": get_value}
    return client


class TestProvisionOAuthSecretRefs:
    async def test_provisions_refresh_token_ref_always(self):
        sync_client = _make_sync_client()
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        refs = await store.provision_oauth_secret_refs(
            server_id="srv_x",
            client_secret=None,
            refresh_token="rt-123",
        )
        assert refs.refresh_token_ref == "mlp/srv_x/oauth/refresh_token"
        assert refs.client_secret_ref is None

    async def test_provisions_client_secret_ref_when_provided(self):
        sync_client = _make_sync_client()
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        refs = await store.provision_oauth_secret_refs(
            server_id="srv_x",
            client_secret="cs-secret",
            refresh_token="rt-123",
        )
        assert refs.client_secret_ref == "mlp/srv_x/oauth/client_secret"

    async def test_calls_create_secret_for_refresh_token(self):
        sync_client = _make_sync_client()
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        await store.provision_oauth_secret_refs(
            server_id="srv_y",
            client_secret=None,
            refresh_token="rt-456",
        )
        # create_secret called for refresh_token_ref
        sync_client.create_secret.assert_called()
        call_kwargs = sync_client.create_secret.call_args[1]
        assert call_kwargs["SecretString"] == "rt-456"

    async def test_calls_create_secret_for_client_secret_when_provided(self):
        sync_client = _make_sync_client()
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        await store.provision_oauth_secret_refs(
            server_id="srv_z",
            client_secret="my-client-secret",
            refresh_token="rt-789",
        )
        calls = [call[1]["SecretString"] for call in sync_client.create_secret.call_args_list]
        assert "my-client-secret" in calls

    async def test_returns_oauth_secret_refs_instance(self):
        sync_client = _make_sync_client()
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        refs = await store.provision_oauth_secret_refs(
            server_id="srv_a",
            client_secret=None,
            refresh_token="rt-xxx",
        )
        assert isinstance(refs, OAuthSecretRefs)


class TestUpsertSecretSync:
    def test_creates_new_secret_successfully(self):
        sync_client = _make_sync_client()
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        store._upsert_secret_sync("mlp/srv/token", "secret-val")
        sync_client.create_secret.assert_called_once_with(
            Name="mlp/srv/token", SecretString="secret-val"
        )

    def test_updates_existing_secret_on_resource_exists_exception(self):
        sync_client = _make_sync_client(create_raises=_client_error("ResourceExistsException"))
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        store._upsert_secret_sync("mlp/srv/token", "new-val")
        sync_client.put_secret_value.assert_called_once_with(
            SecretId="mlp/srv/token", SecretString="new-val"
        )

    def test_re_raises_non_resource_exists_errors(self):
        sync_client = _make_sync_client(create_raises=_client_error("AccessDeniedException"))
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        with pytest.raises(ClientError):
            store._upsert_secret_sync("mlp/srv/token", "val")

    def test_includes_kms_key_id_when_set(self):
        sync_client = _make_sync_client()
        store = AWSSecretsManagerOAuthStore(client=sync_client, kms_key_id="alias/my-key")
        store._upsert_secret_sync("mlp/srv/token", "val")
        call_kwargs = sync_client.create_secret.call_args[1]
        assert call_kwargs["KmsKeyId"] == "alias/my-key"

    def test_no_kms_key_when_not_set(self):
        sync_client = _make_sync_client()
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        store._upsert_secret_sync("mlp/srv/token", "val")
        call_kwargs = sync_client.create_secret.call_args[1]
        assert "KmsKeyId" not in call_kwargs


class TestReadSecretStringSync:
    def test_reads_secret_string_successfully(self):
        sync_client = _make_sync_client(get_value="my-secret")
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        result = store._read_secret_string_sync("mlp/srv/token")
        assert result == "my-secret"
        sync_client.get_secret_value.assert_called_once_with(SecretId="mlp/srv/token")

    def test_raises_value_error_when_secret_string_missing(self):
        sync_client = MagicMock()
        sync_client.get_secret_value.return_value = {"SecretBinary": b"binary"}
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        with pytest.raises(ValueError, match="SecretString missing"):
            store._read_secret_string_sync("mlp/srv/token")

    def test_raises_client_error_on_not_found(self):
        sync_client = _make_sync_client(get_raises=_client_error("ResourceNotFoundException"))
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        with pytest.raises(ClientError):
            store._read_secret_string_sync("mlp/nonexistent/token")


class TestResolveOAuthBundle:
    """Post-029: plaintext client_secret/refresh_token columns are dropped.
    resolve_oauth_bundle only supports ref-based resolution; inline plaintext
    on the record is ignored."""

    async def test_resolves_refresh_token_from_ref_via_sync_client(self):
        sync_client = _make_sync_client(get_value="ref-rt-value")
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        record = _make_record(
            refresh_token=None,
            refresh_token_ref="mlp/srv/oauth/refresh_token",
        )
        bundle = await store.resolve_oauth_bundle(record)
        assert bundle.refresh_token == "ref-rt-value"

    async def test_resolves_client_secret_from_ref_via_sync_client(self):
        sync_client = MagicMock()
        # client_secret_ref and refresh_token_ref both read via sync client
        sync_client.get_secret_value.side_effect = [
            {"SecretString": "ref-cs-value"},
            {"SecretString": "ref-rt-value"},
        ]
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        record = _make_record(
            client_secret=None,
            client_secret_ref="mlp/srv/oauth/client_secret",
            refresh_token=None,
            refresh_token_ref="mlp/srv/oauth/refresh_token",
        )
        bundle = await store.resolve_oauth_bundle(record)
        assert bundle.client_secret == "ref-cs-value"
        assert bundle.refresh_token == "ref-rt-value"

    async def test_raises_when_no_refresh_token_or_ref(self):
        store = AWSSecretsManagerOAuthStore()
        record = _make_record(
            refresh_token=None,
            refresh_token_ref=None,
        )
        with pytest.raises(ValueError, match="refresh_token_ref is required"):
            await store.resolve_oauth_bundle(record)


class TestUpsertSecretAsync:
    async def test_upsert_via_sync_client_uses_thread(self):
        """When sync client is injected, _upsert_secret uses asyncio.to_thread."""
        sync_client = _make_sync_client()
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        # Should complete without error (uses thread executor)
        await store._upsert_secret("mlp/srv/token", "val")
        sync_client.create_secret.assert_called_once()

    async def test_read_secret_via_sync_client_uses_thread(self):
        sync_client = _make_sync_client(get_value="threaded-result")
        store = AWSSecretsManagerOAuthStore(client=sync_client)
        result = await store._read_secret_string("mlp/srv/token")
        assert result == "threaded-result"
        sync_client.get_secret_value.assert_called_once_with(SecretId="mlp/srv/token")
