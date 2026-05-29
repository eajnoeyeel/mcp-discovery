"""Supabase repository for provider upstream OAuth sessions."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import httpx

from service.services.oauth_tokens import OAuthTokenRecord
from service.services.secret_refs import OAuthSecretResolver


class SupabaseOAuthTokenRepository:
    """Async repository backed by Supabase PostgREST service-role access."""

    def __init__(
        self,
        url: str,
        service_key: str,
        secret_resolver: OAuthSecretResolver | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        self._secret_resolver = secret_resolver

    async def fetch(self, server_id: str) -> OAuthTokenRecord | None:
        """Fetch OAuth session state for a provider MCP server."""
        rows = await asyncio.to_thread(self._fetch_sync, server_id)
        if not rows:
            return None
        row = rows[0]
        record = OAuthTokenRecord(
            server_id=row["server_id"],
            token_endpoint=row["token_endpoint"],
            client_id=row["client_id"],
            client_secret_ref=row.get("client_secret_ref"),
            access_token=row.get("access_token"),
            refresh_token_ref=row.get("refresh_token_ref"),
            scope=row.get("scope"),
            token_type=row.get("token_type") or "Bearer",
            expires_at=_parse_datetime(row.get("expires_at")),
            secret_backend=row.get("secret_backend"),
        )
        resolver = self._secret_resolver or _build_default_secret_resolver()
        if resolver is not None and record.refresh_token_ref:
            bundle = await resolver.resolve_oauth_bundle(record)
            record = record.model_copy(
                update={
                    "client_secret": bundle.client_secret,
                    "refresh_token": bundle.refresh_token,
                }
            )
        return record

    def _fetch_sync(self, server_id: str) -> list[dict]:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{self._url}/rest/v1/mcp_oauth_sessions",
                headers=self._headers,
                params={
                    "server_id": f"eq.{server_id}",
                    "select": (
                        "server_id,token_endpoint,client_id,client_secret_ref,"
                        "access_token,refresh_token_ref,scope,token_type,"
                        "expires_at,secret_backend"
                    ),
                    "limit": 1,
                },
            )
            response.raise_for_status()
            return response.json()

    async def store(self, record: OAuthTokenRecord) -> None:
        """Upsert OAuth session state after a token refresh."""
        payload = {
            "server_id": record.server_id,
            "token_endpoint": record.token_endpoint,
            "client_id": record.client_id,
            "client_secret_ref": record.client_secret_ref,
            "access_token": record.access_token,
            "refresh_token_ref": record.refresh_token_ref,
            "scope": record.scope,
            "token_type": record.token_type,
            "expires_at": (
                record.expires_at.isoformat().replace("+00:00", "Z") if record.expires_at else None
            ),
            "secret_backend": record.secret_backend or "aws_secrets_manager",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self._url}/rest/v1/mcp_oauth_sessions",
                headers={
                    **self._headers,
                    "Prefer": "return=minimal, resolution=merge-duplicates",
                },
                params={"on_conflict": "server_id"},
                json=payload,
            )
            response.raise_for_status()

    def _store_sync(self, record: OAuthTokenRecord) -> None:
        """Sync helper retained for test compatibility.

        TODO: Migrate callers to use the async store() method and remove this.
        """
        payload = {
            "server_id": record.server_id,
            "token_endpoint": record.token_endpoint,
            "client_id": record.client_id,
            "client_secret_ref": record.client_secret_ref,
            "access_token": record.access_token,
            "refresh_token_ref": record.refresh_token_ref,
            "scope": record.scope,
            "token_type": record.token_type,
            "expires_at": (
                record.expires_at.isoformat().replace("+00:00", "Z") if record.expires_at else None
            ),
            "secret_backend": record.secret_backend or "aws_secrets_manager",
        }
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{self._url}/rest/v1/mcp_oauth_sessions",
                headers={
                    **self._headers,
                    "Prefer": "return=minimal, resolution=merge-duplicates",
                },
                params={"on_conflict": "server_id"},
                json=payload,
            )
            response.raise_for_status()


def _build_default_secret_resolver() -> OAuthSecretResolver | None:
    region_name = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    try:
        from service.adapters.aws_secrets_manager import AWSSecretsManagerOAuthStore

        return AWSSecretsManagerOAuthStore(region_name=region_name)
    except Exception:
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
