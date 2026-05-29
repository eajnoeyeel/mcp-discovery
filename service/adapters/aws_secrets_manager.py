"""AWS Secrets Manager adapter for provider OAuth and server auth secret refs."""

from __future__ import annotations

from botocore.exceptions import ClientError

from service.services.oauth_tokens import OAuthTokenRecord
from service.services.secret_refs import (
    OAuthSecretRefs,
    ResolvedOAuthSecretBundle,
    ServerAuthSecretRefs,
    build_oauth_secret_refs,
    build_provider_client_secret_ref,
    build_server_auth_secret_refs,
)


class AWSSecretsManagerOAuthStore:
    """Persist and resolve provider OAuth secrets through AWS Secrets Manager."""

    def __init__(
        self,
        *,
        region_name: str | None = None,
        kms_key_id: str | None = None,
        client=None,
    ) -> None:
        self._region_name = region_name
        self._kms_key_id = kms_key_id
        self._sync_client = client  # kept for tests that inject a mock boto3 client

    async def provision_oauth_secret_refs(
        self,
        *,
        server_id: str,
        client_secret: str | None,
        refresh_token: str,
    ) -> OAuthSecretRefs:
        refs = build_oauth_secret_refs(server_id, include_client_secret=client_secret is not None)
        if refs.client_secret_ref and client_secret is not None:
            await self._upsert_secret(refs.client_secret_ref, client_secret)
        await self._upsert_secret(refs.refresh_token_ref, refresh_token)
        return refs

    async def provision_provider_client_secret_ref(
        self,
        *,
        provider_key: str,
        client_secret: str,
    ) -> str:
        """Store an OAuth provider client secret and return its durable ref."""
        secret_ref = build_provider_client_secret_ref(provider_key)
        await self._upsert_secret(secret_ref, client_secret)
        return secret_ref

    async def provision_server_auth_secret_refs(
        self,
        *,
        server_id: str,
        bearer_token: str | None,
        api_key: str | None,
    ) -> ServerAuthSecretRefs:
        """Store server auth credentials in Secrets Manager; return their refs."""
        refs = build_server_auth_secret_refs(
            server_id,
            include_bearer_token=bearer_token is not None,
            include_api_key=api_key is not None,
        )
        if refs.bearer_token_ref and bearer_token is not None:
            await self._upsert_secret(refs.bearer_token_ref, bearer_token)
        if refs.api_key_ref and api_key is not None:
            await self._upsert_secret(refs.api_key_ref, api_key)
        return refs

    async def resolve_provider_client_secret(self, client_secret_ref: str) -> str:
        """Resolve an OAuth provider client secret from a durable ref."""
        return await self._read_secret_string(client_secret_ref)

    async def resolve_server_auth_secrets(
        self,
        *,
        bearer_token_ref: str | None,
        api_key_ref: str | None,
    ) -> tuple[str | None, str | None]:
        """Resolve server auth credentials from Secrets Manager refs only.

        Returns (bearer_token, api_key).
        """
        bearer_token: str | None = None
        if bearer_token_ref:
            bearer_token = await self._read_secret_string(bearer_token_ref)

        api_key: str | None = None
        if api_key_ref:
            api_key = await self._read_secret_string(api_key_ref)

        return bearer_token, api_key

    async def resolve_oauth_bundle(self, record: OAuthTokenRecord) -> ResolvedOAuthSecretBundle:
        client_secret: str | None = None
        if record.client_secret_ref:
            client_secret = await self._read_secret_string(record.client_secret_ref)

        if not record.refresh_token_ref:
            raise ValueError("refresh_token_ref is required for secret-backed OAuth sessions")
        refresh_token = await self._read_secret_string(record.refresh_token_ref)

        return ResolvedOAuthSecretBundle(
            client_secret=client_secret,
            refresh_token=refresh_token,
        )

    async def _upsert_secret(self, secret_id: str, secret_string: str) -> None:
        import asyncio

        if self._sync_client is not None:
            # Test-injected sync client — wrap in thread for backward compat
            return await asyncio.to_thread(self._upsert_secret_sync, secret_id, secret_string)
        return await asyncio.to_thread(
            self._with_default_client()._upsert_secret_sync,
            secret_id,
            secret_string,
        )

    async def _read_secret_string(self, secret_id: str) -> str:
        import asyncio

        if self._sync_client is not None:
            return await asyncio.to_thread(self._read_secret_string_sync, secret_id)
        return await asyncio.to_thread(
            self._with_default_client()._read_secret_string_sync,
            secret_id,
        )

    def _with_default_client(self) -> "AWSSecretsManagerOAuthStore":
        """Return a store backed by boto3's synchronous Secrets Manager client."""
        import boto3

        return AWSSecretsManagerOAuthStore(
            client=boto3.client("secretsmanager", region_name=self._region_name),
            region_name=self._region_name,
            kms_key_id=self._kms_key_id,
        )

    # --- sync helpers kept for test-injected mock clients ---

    def _upsert_secret_sync(self, secret_id: str, secret_string: str) -> None:
        create_kwargs = {"Name": secret_id, "SecretString": secret_string}
        if self._kms_key_id:
            create_kwargs["KmsKeyId"] = self._kms_key_id
        try:
            self._sync_client.create_secret(**create_kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "ResourceExistsException":
                raise
            self._sync_client.put_secret_value(SecretId=secret_id, SecretString=secret_string)

    def _read_secret_string_sync(self, secret_id: str) -> str:
        response = self._sync_client.get_secret_value(SecretId=secret_id)
        secret_string = response.get("SecretString")
        if secret_string is None:
            raise ValueError(f"SecretString missing for {secret_id}")
        return secret_string
