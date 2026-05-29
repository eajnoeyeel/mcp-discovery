"""Provider upstream OAuth token refresh service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from service.services.secret_refs import OAuthSecretResolver


class OAuthTokenRecord(BaseModel):
    """OAuth session state for one provider MCP server."""

    server_id: str
    token_endpoint: str
    client_id: str
    client_secret: str | None = None
    client_secret_ref: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    refresh_token_ref: str | None = None
    scope: str | None = None
    token_type: str = "Bearer"
    expires_at: datetime | None = None
    secret_backend: str | None = None


class OAuthTokenRepository(Protocol):
    """Persistence boundary for provider OAuth session state."""

    async def fetch(self, server_id: str) -> OAuthTokenRecord | None: ...
    async def store(self, record: OAuthTokenRecord) -> None: ...


class OAuthTokenService:
    """Resolves a valid provider access token and refreshes it when expiring."""

    def __init__(
        self,
        *,
        repo: OAuthTokenRepository,
        http_client: httpx.AsyncClient | None = None,
        refresh_skew_seconds: int = 120,
        secret_resolver: OAuthSecretResolver | None = None,
    ) -> None:
        self._repo = repo
        self._http_client = http_client
        self._refresh_skew = timedelta(seconds=refresh_skew_seconds)
        self._secret_resolver = secret_resolver

    async def get_access_token(self, server_id: str) -> str:
        """Return a non-expiring access token for ``server_id``."""
        record = await self._repo.fetch(server_id)
        if record is None:
            raise LookupError(f"OAuth session not found for server '{server_id}'")
        if record.access_token and not self._is_expiring(record):
            return record.access_token

        refresh_record = await self._hydrate_refresh_record(record)
        refreshed = await self._refresh(refresh_record)
        await self._repo.store(refreshed)
        return refreshed.access_token or ""

    def _is_expiring(self, record: OAuthTokenRecord) -> bool:
        if record.expires_at is None:
            return True
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= datetime.now(UTC) + self._refresh_skew

    async def _hydrate_refresh_record(self, record: OAuthTokenRecord) -> OAuthTokenRecord:
        if self._secret_resolver is None or not record.refresh_token_ref:
            return record

        bundle = await self._secret_resolver.resolve_oauth_bundle(record)
        return record.model_copy(
            update={
                "client_secret": bundle.client_secret,
                "refresh_token": bundle.refresh_token,
            }
        )

    async def _refresh(self, record: OAuthTokenRecord) -> OAuthTokenRecord:
        if not record.refresh_token:
            raise ValueError("refresh_token is required to refresh provider OAuth session")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": record.refresh_token,
            "client_id": record.client_id,
        }
        if record.client_secret:
            payload["client_secret"] = record.client_secret
        if record.scope:
            payload["scope"] = record.scope

        async def _post(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                record.token_endpoint,
                content=urlencode(payload),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if self._http_client is None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await _post(client)
        else:
            response = await _post(self._http_client)

        response.raise_for_status()
        data = response.json()
        expires_in = int(data.get("expires_in") or 3600)
        return record.model_copy(
            update={
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token") or record.refresh_token,
                "token_type": data.get("token_type") or record.token_type,
                "scope": data.get("scope") or record.scope,
                "expires_at": datetime.now(UTC) + timedelta(seconds=expires_in),
            }
        )
