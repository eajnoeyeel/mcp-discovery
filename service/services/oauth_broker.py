"""Provider OAuth broker service for user-owned delegated connections."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from service.services.delegated_oauth import fingerprint_scopes, normalize_scopes
from service.services.oauth_provider_bootstrap import build_state_nonce, hash_state_nonce
from service.services.pending_execution import mark_pending_execution_ready


class OAuthBrokerError(ValueError):
    """Raised when an OAuth broker request cannot be completed."""


def _encode_state(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_state(state: str) -> dict[str, Any]:
    padded = state + "=" * (-len(state) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, json.JSONDecodeError) as exc:
        raise OAuthBrokerError("Invalid OAuth state") from exc
    if int(payload.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
        raise OAuthBrokerError("OAuth state expired")
    return payload


def _build_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class OAuthBrokerService:
    """Start and complete provider OAuth grants for platform users."""

    def __init__(
        self,
        *,
        repo,
        http_client: httpx.AsyncClient | None = None,
        client_secret_resolver=None,
    ) -> None:
        self._repo = repo
        self._http_client = http_client
        self._client_secret_resolver = client_secret_resolver

    async def start_authorization(
        self,
        *,
        user_id: str,
        provider: str,
        tool_id: str,
        required_scopes: list[str],
        pending_execution_id: str | None = None,
    ) -> dict[str, str]:
        provider_row = await self._repo.fetch_provider_registry(provider)
        if provider_row is None:
            raise OAuthBrokerError(f"OAuth provider '{provider}' is not registered")
        self._assert_provider_enabled(provider_row, provider)

        scopes = normalize_scopes(required_scopes)
        code_verifier = None
        code_challenge = None
        if provider_row.get("pkce_required", True):
            code_verifier, code_challenge = _build_pkce_pair()
        nonce, nonce_hash = build_state_nonce()
        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        redirect_uri = provider_row["redirect_uri"]
        create_nonce = getattr(self._repo, "create_oauth_state_nonce", None)
        if not callable(create_nonce):
            raise OAuthBrokerError("OAuth state replay protection is unavailable")
        await create_nonce(
            {
                "nonce_hash": nonce_hash,
                "code_verifier": code_verifier,
                "required_scopes": scopes,
                "user_id": user_id,
                "provider_key": provider,
                "issuer": provider_row.get("issuer"),
                "redirect_uri": redirect_uri,
                "tool_id": tool_id,
                "pending_execution_id": pending_execution_id,
                "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            }
        )
        state = _encode_state(
            {
                "provider": provider,
                "nonce": nonce,
                "exp": int(expires_at.timestamp()),
            }
        )
        params = {
            "client_id": provider_row["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
        }
        if code_challenge is not None:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        query = urlencode(params)
        return {
            "provider": provider,
            "oauth_url": f"{provider_row['authorize_url']}?{query}",
            "state": state,
        }

    async def complete_authorization(self, *, provider: str, code: str, state: str) -> dict:
        payload = _decode_state(state)
        if payload.get("provider") != provider:
            raise OAuthBrokerError("OAuth state provider mismatch")

        nonce = str(payload.get("nonce") or "").strip()
        if not nonce:
            raise OAuthBrokerError("OAuth state nonce missing")
        consume_nonce = getattr(self._repo, "consume_oauth_state_nonce", None)
        if not callable(consume_nonce):
            raise OAuthBrokerError("OAuth state replay protection is unavailable")
        nonce_record = await consume_nonce(
            nonce_hash=hash_state_nonce(nonce), provider_key=provider
        )
        if isinstance(nonce_record, list):
            nonce_record = nonce_record[0] if nonce_record else {}
        if not isinstance(nonce_record, dict):
            raise OAuthBrokerError("OAuth state replay proof is invalid")
        self._assert_nonce_matches_state(nonce_record, payload)

        provider_row = await self._repo.fetch_provider_registry(provider)
        if provider_row is None:
            raise OAuthBrokerError(f"OAuth provider '{provider}' is not registered")
        self._assert_provider_enabled(provider_row, provider)
        if nonce_record.get("issuer") and provider_row.get("issuer") != nonce_record.get("issuer"):
            raise OAuthBrokerError("OAuth state issuer mismatch")
        if nonce_record.get("redirect_uri") != provider_row.get("redirect_uri"):
            raise OAuthBrokerError("OAuth state redirect_uri mismatch")

        scopes = normalize_scopes(nonce_record.get("required_scopes") or [])
        token_payload = await self._exchange_code(
            provider_row,
            code,
            code_verifier=nonce_record.get("code_verifier"),
        )
        granted_scopes = normalize_scopes(
            str(token_payload.get("scope") or " ".join(scopes)).replace(",", " ").split()
        )
        if not granted_scopes:
            granted_scopes = scopes

        connection = await self._repo.upsert_user_provider_connection(
            user_id=nonce_record["user_id"],
            provider_key=provider,
            provider_account_id=token_payload.get("provider_account_id"),
            granted_scopes=granted_scopes,
            scope_fingerprint=fingerprint_scopes(granted_scopes),
            token_storage_mode="refreshable"
            if token_payload.get("refresh_token")
            else "session_only",
        )
        connection_id = connection["id"] if isinstance(connection, dict) else connection[0]["id"]
        await self._repo.store_user_provider_tokens(
            connection_id=connection_id,
            access_token=token_payload.get("access_token"),
            refresh_token=token_payload.get("refresh_token"),
            expires_in=token_payload.get("expires_in"),
            token_type=token_payload.get("token_type") or "Bearer",
        )
        pending_execution_id = nonce_record.get("pending_execution_id")
        if pending_execution_id:
            await self._repo.update_pending_execution(
                str(pending_execution_id),
                mark_pending_execution_ready(
                    {
                        "status": "waiting_for_connect",
                        "connection_id": connection_id,
                    }
                ),
            )
        return {
            "status": "connected",
            "provider": provider,
            "connection_id": connection_id,
            "granted_scopes": granted_scopes,
        }

    @staticmethod
    def _assert_nonce_matches_state(nonce_record: dict[str, Any], payload: dict[str, Any]) -> None:
        """Ensure mutable front-channel state is bound to server-side nonce facts."""
        expected = {
            "provider": nonce_record.get("provider_key"),
        }
        for field, value in expected.items():
            if value is None:
                continue
            if payload.get(field) != value:
                raise OAuthBrokerError(f"OAuth state {field} mismatch")

    @staticmethod
    def _assert_provider_enabled(provider_row: dict[str, Any], provider: str) -> None:
        """Fail closed when an admin disables a provider registry entry."""
        if provider_row.get("enabled") is not True:
            raise OAuthBrokerError(f"OAuth provider '{provider}' is disabled or unavailable")

    async def _exchange_code(
        self,
        provider_row: dict,
        code: str,
        *,
        code_verifier: str | None = None,
    ) -> dict:
        request_payload = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": provider_row["client_id"],
            "redirect_uri": provider_row["redirect_uri"],
        }
        if code_verifier:
            request_payload["code_verifier"] = code_verifier

        headers = {"Accept": "application/json"}
        auth: tuple[str, str] | None = None
        token_auth_method = provider_row.get("token_endpoint_auth_method") or "none"
        client_secret = await self._resolve_client_secret(provider_row)
        if token_auth_method == "client_secret_post":
            if not client_secret:
                raise OAuthBrokerError("OAuth provider client secret is unavailable")
            request_payload["client_secret"] = client_secret
        elif token_auth_method == "client_secret_basic":
            if not client_secret:
                raise OAuthBrokerError("OAuth provider client secret is unavailable")
            auth = (provider_row["client_id"], client_secret)
        elif token_auth_method != "none":
            raise OAuthBrokerError("Unsupported OAuth token endpoint auth method")

        async def _post(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                provider_row["token_url"],
                data=request_payload,
                headers=headers,
                auth=auth,
            )

        if self._http_client is None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await _post(client)
        else:
            response = await _post(self._http_client)
        response.raise_for_status()
        return response.json()

    async def _resolve_client_secret(self, provider_row: dict) -> str | None:
        client_secret_ref = provider_row.get("client_secret_ref")
        if not client_secret_ref:
            return None
        resolver = self._client_secret_resolver
        if resolver is None:
            raise OAuthBrokerError("OAuth provider client secret resolver is unavailable")
        if hasattr(resolver, "resolve_provider_client_secret"):
            return await resolver.resolve_provider_client_secret(str(client_secret_ref))
        return await resolver(str(client_secret_ref))
