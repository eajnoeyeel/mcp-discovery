"""Secret reference contracts for provider OAuth runtime state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from service.services.oauth_tokens import OAuthTokenRecord

SECRET_BACKEND_AWS = "aws_secrets_manager"


class OAuthSecretRefs(BaseModel):
    """Persistent references to provider OAuth secrets."""

    client_secret_ref: str | None = None
    refresh_token_ref: str
    secret_backend: Literal["aws_secrets_manager"] = SECRET_BACKEND_AWS


class ResolvedOAuthSecretBundle(BaseModel):
    """Resolved secret material used only in-memory for refresh calls."""

    client_secret: str | None = None
    refresh_token: str


class OAuthSecretResolver(Protocol):
    """Resolves durable secret refs into ephemeral secret values."""

    async def resolve_oauth_bundle(self, record: OAuthTokenRecord) -> ResolvedOAuthSecretBundle: ...


class OAuthSecretStore(OAuthSecretResolver, Protocol):
    """Persists OAuth secrets and resolves them later for refresh flows."""

    async def provision_oauth_secret_refs(
        self,
        *,
        server_id: str,
        client_secret: str | None,
        refresh_token: str,
    ) -> OAuthSecretRefs: ...

    async def provision_server_auth_secret_refs(
        self,
        *,
        server_id: str,
        bearer_token: str | None,
        api_key: str | None,
    ) -> ServerAuthSecretRefs: ...


def build_oauth_secret_refs(server_id: str, *, include_client_secret: bool) -> OAuthSecretRefs:
    """Build deterministic secret ids for one provider MCP server."""

    client_secret_ref = None
    if include_client_secret:
        client_secret_ref = f"mlp/{server_id}/oauth/client_secret"
    return OAuthSecretRefs(
        client_secret_ref=client_secret_ref,
        refresh_token_ref=f"mlp/{server_id}/oauth/refresh_token",
    )


class ServerAuthSecretRefs(BaseModel):
    """Persistent references to provider server auth secrets (bearer token / API key)."""

    bearer_token_ref: str | None = None
    api_key_ref: str | None = None
    secret_backend: Literal["aws_secrets_manager"] = SECRET_BACKEND_AWS


def build_server_auth_secret_refs(
    server_id: str,
    *,
    include_bearer_token: bool,
    include_api_key: bool,
) -> ServerAuthSecretRefs:
    """Build deterministic secret names for server auth credentials."""
    return ServerAuthSecretRefs(
        bearer_token_ref=f"mlp/{server_id}/auth/bearer_token" if include_bearer_token else None,
        api_key_ref=f"mlp/{server_id}/auth/api_key" if include_api_key else None,
    )


def build_provider_client_secret_ref(provider_key: str) -> str:
    """Build deterministic secret name for an OAuth provider client secret."""
    normalized = provider_key.strip().lower()
    if not normalized:
        raise ValueError("provider_key is required for provider client secret refs")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    if any(char not in allowed for char in normalized):
        raise ValueError("provider_key may contain only lowercase letters, numbers, '-' and '_'")
    return f"mlp/oauth-providers/{normalized}/client_secret"
