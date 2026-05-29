"""Execution-side Supabase adapters shared across Lambda artifacts.

Hosts the Protocol implementations (``SupabaseToolRegistry``,
``SupabaseExecutionLogger``) and supporting Supabase helpers used by the
``execute`` Lambda.  They live under ``service/adapters/`` — rather than
``service/services/`` — for build-isolation pragmatism: both the execute
and bridge Lambda artifacts ship ``service/adapters/`` already, so moving
them here lets the bridge reuse them without adding ``lambdas`` to
``MLP_RUNTIME_PACKAGES``.

Future orchestration-heavy execution code may relocate to
``service/services/execution_service.py``; this module is intentionally
limited to Supabase I/O + gateway HTTP glue.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger

from service.gateway.internal_auth import build_internal_auth_headers

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# MLP: only pre-registered hosted servers can be executed.
# Populated from Supabase at init; Phase 2 will make this dynamic.
ALLOWED_EXECUTION_SERVERS: set[str] = set()


class AuthRequirementLookupError(RuntimeError):
    """Raised when delegated auth metadata cannot be read safely."""


def _supabase_headers() -> dict[str, str]:
    return {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


# Supabase-backed ToolRegistry


class SupabaseToolRegistry:
    """Fetches tool contract (metadata + URL) from Supabase mcp_servers + mcp_tools."""

    async def fetch_tool_contract(self, tool_id: str):
        """Return a ToolContract or None if the tool/server is not found."""
        from mcp_discovery.models import TOOL_ID_SEPARATOR
        from service.services.contracts import ToolContract

        if TOOL_ID_SEPARATOR not in tool_id:
            return None

        server_id, tool_name = tool_id.split(TOOL_ID_SEPARATOR, 1)

        # Fetch server metadata
        server = await _fetch_server(server_id)
        if server is None:
            return None

        server_url = server.get("url")
        if not server_url:
            return None

        # Fetch tool input_schema if available
        input_schema = await _fetch_tool_schema(tool_id)
        upstream_auth = await _fetch_server_auth(server_id)
        requires_gateway = bool(server.get("requires_gateway"))
        gateway_url = await _fetch_gateway_url(server_id) if requires_gateway else None
        auth_requirement = await _fetch_auth_requirement(server_id, tool_id)

        return ToolContract(
            tool_id=tool_id,
            server_id=server_id,
            tool_name=tool_name,
            url=server_url,
            input_schema=input_schema,
            upstream_auth=upstream_auth,
            transport_type=server.get("transport_type") or "stateless_http",
            requires_gateway=requires_gateway,
            gateway_url=gateway_url,
            auth_requirement=auth_requirement or self._infer_auth_requirement(server_id),
        )

    async def find_user_provider_connection(
        self,
        *,
        user_id: str,
        provider_key: str,
        required_scopes: list[str],
    ):
        from service.adapters.supabase_client import SupabaseClient

        if not _SUPABASE_URL or not _SUPABASE_KEY:
            return None
        repo = SupabaseClient(url=_SUPABASE_URL, service_key=_SUPABASE_KEY)
        try:
            return await repo.find_user_provider_connection(
                user_id=user_id,
                provider_key=provider_key,
                required_scopes=required_scopes,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                f"user_provider_connections lookup unavailable; treating as missing: {exc}"
            )
            return None

    async def create_pending_execution(
        self,
        *,
        user_id: str,
        tool_id: str,
        params_json: dict[str, Any],
        provider_key: str,
        required_scopes: list[str],
        resume_token: str,
        expires_at: str,
    ) -> dict | list:
        from service.adapters.supabase_client import SupabaseClient

        if not _SUPABASE_URL or not _SUPABASE_KEY:
            return {}
        repo = SupabaseClient(url=_SUPABASE_URL, service_key=_SUPABASE_KEY)
        return await repo.create_pending_execution(
            user_id=user_id,
            tool_id=tool_id,
            params_json=params_json,
            provider_key=provider_key,
            required_scopes=required_scopes,
            retry_token=resume_token,
            expires_at=expires_at,
        )

    async def fetch_pending_execution_by_resume_token(self, resume_token: str) -> dict | None:
        from service.adapters.supabase_client import SupabaseClient

        if not _SUPABASE_URL or not _SUPABASE_KEY:
            return None
        repo = SupabaseClient(url=_SUPABASE_URL, service_key=_SUPABASE_KEY)
        return await repo.fetch_pending_execution_by_resume_token(resume_token)

    async def update_pending_execution(
        self,
        pending_execution_id: str,
        payload: dict[str, Any],
    ) -> dict | list:
        from service.adapters.supabase_client import SupabaseClient

        if not _SUPABASE_URL or not _SUPABASE_KEY:
            return {}
        repo = SupabaseClient(url=_SUPABASE_URL, service_key=_SUPABASE_KEY)
        return await repo.update_pending_execution(pending_execution_id, payload)

    async def resolve_user_provider_headers(self, connection_id: str) -> dict[str, str]:
        from service.adapters.supabase_client import SupabaseClient

        if not _SUPABASE_URL or not _SUPABASE_KEY:
            return {}
        repo = SupabaseClient(url=_SUPABASE_URL, service_key=_SUPABASE_KEY)
        token_row = await repo.fetch_user_provider_token(connection_id)
        if token_row is None:
            return {}
        access_token = str(token_row.get("access_token") or "").strip()
        refresh_token = str(token_row.get("refresh_token") or "").strip()
        expires_at_raw = str(token_row.get("expires_at") or "").strip()
        expires_at = None
        if expires_at_raw:
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        provider_key = str(token_row.get("provider_key") or "").strip()
        if not provider_key and isinstance(token_row.get("user_provider_connections"), dict):
            provider_key = str(
                token_row["user_provider_connections"].get("provider_key") or ""
            ).strip()
        if not provider_key:
            return {}
        provider_row = await repo.fetch_provider_registry(provider_key)
        if provider_row is None or provider_row.get("enabled") is not True:
            return {}
        refresh_deadline = datetime.now(UTC) + timedelta(minutes=2)
        needs_refresh = not access_token or (
            expires_at is not None and expires_at <= refresh_deadline
        )

        if refresh_token and needs_refresh:
            if (
                provider_row is not None
                and provider_row.get("token_url")
                and provider_row.get("client_id")
            ):
                request_payload = {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": provider_row["client_id"],
                }
                auth = None
                token_auth_method = provider_row.get("token_endpoint_auth_method") or "none"
                client_secret = await _resolve_provider_client_secret(provider_row)
                if token_auth_method == "client_secret_post":
                    if not client_secret:
                        return {}
                    request_payload["client_secret"] = client_secret
                elif token_auth_method == "client_secret_basic":
                    if not client_secret:
                        return {}
                    auth = (provider_row["client_id"], client_secret)
                elif token_auth_method != "none":
                    return {}

                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        provider_row["token_url"],
                        data=request_payload,
                        headers={"Accept": "application/json"},
                        auth=auth,
                    )
                    response.raise_for_status()
                    payload = response.json()
                access_token = str(payload.get("access_token") or "").strip()
                next_token_type = payload.get("token_type") or str(
                    token_row.get("token_type") or "Bearer"
                )
                expires_in = payload.get("expires_in")
                if expires_in:
                    expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))
                else:
                    expires_at = None
                await repo.store_user_provider_tokens(
                    connection_id=connection_id,
                    access_token=access_token,
                    refresh_token=payload.get("refresh_token") or refresh_token,
                    expires_in=expires_in,
                    token_type=next_token_type,
                )
        if not access_token:
            return {}
        if expires_at is not None and expires_at <= refresh_deadline:
            return {}
        return {"Authorization": f"Bearer {access_token}"}

    async def build_provider_oauth_url(
        self,
        *,
        user_id: str,
        tool_id: str,
        provider: str,
        required_scopes: list[str],
        params: dict[str, Any],
        pending_execution_id: str | None = None,
        resume_token: str | None = None,
    ) -> str:
        frontend_base = os.environ.get("MLP_FRONTEND_URL", "http://127.0.0.1:3001").rstrip("/")
        from urllib.parse import urlencode

        connect_query = urlencode(
            {
                "provider": provider,
                "server_id": tool_id.split("::", 1)[0],
                "tool_id": tool_id,
                "auth_type": "oauth",
                "pending_execution_id": pending_execution_id,
                "resume_token": resume_token,
            }
        )
        redirect_target = f"/connect?{connect_query}"
        login_query = urlencode({"redirect": redirect_target})
        return f"{frontend_base}/login?{login_query}"

    @staticmethod
    def _infer_auth_requirement(server_id: str):
        from service.services.contracts import ProviderAuthRequirement

        if server_id.endswith("-oauth"):
            return ProviderAuthRequirement(provider=server_id.removesuffix("-oauth"))
        return None


class SupabaseExecutionLogger:
    """Best-effort logging to Supabase execution_logs."""

    async def log(
        self,
        tool_id: str,
        server_id: str,
        success: bool,
        latency_ms: float,
        error_message: str | None = None,
        client_id: str | None = None,
        event_id: str | None = None,
        query_log_id: int | None = None,
    ) -> None:
        await _log_execution(
            tool_id,
            server_id,
            success,
            latency_ms,
            error_message,
            client_id,
            event_id,
            query_log_id,
        )


# Supabase helpers


async def _fetch_server(server_id: str) -> dict[str, Any] | None:
    """Fetch server metadata from Supabase by server_id."""
    if not _SUPABASE_URL:
        raise RuntimeError("Supabase registry is not configured")
    url = (
        f"{_SUPABASE_URL}/rest/v1/mcp_servers"
        f"?server_id=eq.{server_id}"
        "&select=server_id,name,url,transport_type,requires_gateway"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_supabase_headers())
            resp.raise_for_status()
            rows = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch server metadata: {exc}") from exc
    return rows[0] if rows else None


async def _fetch_tool_schema(tool_id: str) -> dict[str, Any] | None:
    """Fetch tool input_schema from Supabase mcp_tools if available."""
    if not _SUPABASE_URL:
        return None
    url = f"{_SUPABASE_URL}/rest/v1/mcp_tools?tool_id=eq.{tool_id}&select=input_schema"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_supabase_headers())
            resp.raise_for_status()
            rows = resp.json()
        if rows and rows[0].get("input_schema"):
            return rows[0]["input_schema"]
    except Exception as exc:
        logger.warning(f"Failed to fetch tool schema: {exc}")
    return None


async def _fetch_auth_requirement(server_id: str, tool_id: str):
    """Fetch delegated auth requirements, preferring DB rows over legacy suffix inference."""
    from service.services.contracts import ProviderAuthRequirement
    from service.services.delegated_oauth import normalize_scopes

    if not _SUPABASE_URL:
        return None

    try:
        row = await _fetch_auth_requirement_row(server_id=server_id, tool_id=tool_id)
        if row is None:
            row = await _fetch_auth_requirement_row(server_id=server_id, tool_id=None)
        if row is None:
            return None
    except httpx.HTTPStatusError as exc:
        if _is_missing_auth_requirements_table_error(exc):
            raise AuthRequirementLookupError(
                "mcp_auth_requirements table is unavailable; "
                "cannot safely resolve delegated auth metadata"
            ) from exc
        raise AuthRequirementLookupError(
            "Failed to fetch delegated auth requirement metadata"
        ) from exc
    except Exception as exc:
        raise AuthRequirementLookupError(
            "Failed to fetch delegated auth requirement metadata"
        ) from exc

    provider_key = str(row.get("provider_key") or "").strip()
    if not provider_key:
        return None

    try:
        provider_row = await _fetch_provider_registry(provider_key)
    except Exception as exc:
        raise AuthRequirementLookupError(
            f"Failed to fetch provider registry defaults for {provider_key}"
        ) from exc
    if provider_row is None:
        raise AuthRequirementLookupError(
            f"Delegated auth provider registry row not found for {provider_key}"
        )
    if provider_row.get("enabled") is not True:
        raise AuthRequirementLookupError(
            f"Delegated auth provider '{provider_key}' is disabled"
        )

    scope_mode = "override" if row.get("scope_mode") == "override" else "default"
    required_scopes = [str(scope) for scope in row.get("required_scopes") or []]
    effective_scopes = required_scopes
    if scope_mode == "default":
        default_scopes = [str(scope) for scope in provider_row.get("default_scopes") or []]
        effective_scopes = [*default_scopes, *required_scopes]

    return ProviderAuthRequirement(
        provider=provider_key,
        auth_kind="oauth",
        required_scopes=normalize_scopes(effective_scopes),
        scope_mode=scope_mode,
    )


async def _fetch_auth_requirement_row(
    *,
    server_id: str,
    tool_id: str | None,
) -> dict[str, Any] | None:
    params = {
        "server_id": f"eq.{server_id}",
        "select": "provider_key,auth_kind,required_scopes,scope_mode",
        "limit": 1,
    }
    params["tool_id"] = f"eq.{tool_id}" if tool_id else "is.null"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_SUPABASE_URL}/rest/v1/mcp_auth_requirements",
            params=params,
            headers=_supabase_headers(),
        )
        resp.raise_for_status()
        rows = resp.json()
    return rows[0] if rows else None


async def _fetch_provider_registry(provider_key: str) -> dict[str, Any] | None:
    if not _SUPABASE_URL:
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_SUPABASE_URL}/rest/v1/oauth_provider_registry",
            params={
                "provider_key": f"eq.{provider_key}",
                "select": "provider_key,default_scopes,enabled,token_url,client_id,"
                "client_secret_ref,token_endpoint_auth_method",
                "limit": 1,
            },
            headers=_supabase_headers(),
        )
        resp.raise_for_status()
        rows = resp.json()
    return rows[0] if rows else None


async def _resolve_provider_client_secret(provider_row: dict[str, Any]) -> str | None:
    client_secret_ref = provider_row.get("client_secret_ref")
    if not client_secret_ref:
        return None
    from service.adapters.aws_secrets_manager import AWSSecretsManagerOAuthStore

    region_name = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    kms_key_id = os.environ.get("OAUTH_SECRET_KMS_KEY_ID")
    secret_store = AWSSecretsManagerOAuthStore(region_name=region_name, kms_key_id=kms_key_id)
    return await secret_store.resolve_provider_client_secret(str(client_secret_ref))


async def _fetch_server_auth(server_id: str):
    """Fetch provider upstream auth metadata from the service-role-only table.

    Resolves secrets exclusively via bearer_token_ref / api_key_ref from
    AWS Secrets Manager (post-029 schema — plaintext columns are gone).
    """
    from service.adapters.aws_secrets_manager import AWSSecretsManagerOAuthStore
    from service.services.contracts import UpstreamAuthConfig

    if not _SUPABASE_URL:
        return UpstreamAuthConfig()

    url = (
        f"{_SUPABASE_URL}/rest/v1/mcp_server_auth"
        f"?server_id=eq.{server_id}"
        "&select=auth_type,api_key_header_name,headers"
        ",bearer_token_ref,api_key_ref"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_supabase_headers())
            resp.raise_for_status()
            rows = resp.json()
        if not rows:
            return UpstreamAuthConfig()
        row = rows[0]

        bearer_token: str | None = None
        api_key: str | None = None
        bearer_token_ref = row.get("bearer_token_ref")
        api_key_ref = row.get("api_key_ref")

        if bearer_token_ref or api_key_ref:
            try:
                region_name = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
                kms_key_id = os.environ.get("OAUTH_SECRET_KMS_KEY_ID")
                secret_store = AWSSecretsManagerOAuthStore(
                    region_name=region_name, kms_key_id=kms_key_id
                )
                bearer_token, api_key = await secret_store.resolve_server_auth_secrets(
                    bearer_token_ref=bearer_token_ref,
                    api_key_ref=api_key_ref,
                )
            except Exception as exc:
                logger.warning(f"Failed to resolve server auth secrets from Secrets Manager: {exc}")

        return UpstreamAuthConfig(
            auth_type=row.get("auth_type") or "none",
            bearer_token=bearer_token,
            api_key_header_name=row.get("api_key_header_name"),
            api_key=api_key,
            headers=row.get("headers") or {},
        )
    except httpx.HTTPStatusError as exc:
        if _is_missing_auth_table_error(exc):
            logger.warning(f"mcp_server_auth table unavailable; using no upstream auth: {exc}")
            return UpstreamAuthConfig()
        raise RuntimeError(f"Failed to fetch server auth metadata: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch server auth metadata: {exc}") from exc


def _is_missing_auth_table_error(exc: httpx.HTTPStatusError) -> bool:
    try:
        payload = exc.response.json()
    except ValueError:
        payload = {}
    code = str(payload.get("code") or "")
    message = str(payload.get("message") or "").lower()
    return code in {"42P01", "PGRST205"} or (
        "mcp_server_auth" in message and "does not exist" in message
    )


def _is_missing_auth_requirements_table_error(exc: httpx.HTTPStatusError) -> bool:
    try:
        payload = exc.response.json()
    except ValueError:
        payload = {}
    code = str(payload.get("code") or "")
    message = str(payload.get("message") or "").lower()
    return code in {"42P01", "PGRST205"} or (
        "mcp_auth_requirements" in message and "does not exist" in message
    )


async def _fetch_gateway_url(server_id: str) -> str | None:
    """Fetch internal gateway URL for a server that requires pooled execution."""
    if not _SUPABASE_URL:
        return None
    url = (
        f"{_SUPABASE_URL}/rest/v1/mcp_gateway_routes"
        f"?server_id=eq.{server_id}"
        "&select=gateway_url&limit=1"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_supabase_headers())
            resp.raise_for_status()
            rows = resp.json()
        return rows[0]["gateway_url"] if rows else None
    except httpx.HTTPStatusError as exc:
        if _is_missing_gateway_routes_error(exc):
            logger.warning(f"mcp_gateway_routes table unavailable; no gateway URL: {exc}")
            return None
        raise RuntimeError(f"Failed to fetch gateway route metadata: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch gateway route metadata: {exc}") from exc


def _is_missing_gateway_routes_error(exc: httpx.HTTPStatusError) -> bool:
    try:
        payload = exc.response.json()
    except ValueError:
        payload = {}
    code = str(payload.get("code") or "")
    message = str(payload.get("message") or "").lower()
    return code in {"42P01", "PGRST205"} or (
        "mcp_gateway_routes" in message and "does not exist" in message
    )


async def _call_gateway(
    contract,
    params: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Delegate pooled MCP transport execution to the internal gateway."""
    if not contract.gateway_url:
        raise RuntimeError("Gateway URL is missing")

    secret = os.environ.get("GATEWAY_INTERNAL_AUTH_SECRET", "")
    if not secret:
        raise RuntimeError("GATEWAY_INTERNAL_AUTH_SECRET is missing")

    payload = {
        "server_id": contract.server_id,
        "tool_name": contract.tool_name,
        "arguments": params,
        "headers": headers or {},
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = build_internal_auth_headers(
        secret=secret,
        method="POST",
        path="/gateway/execute",
        body=body,
        timestamp=str(int(time.time())),
    )
    headers["Content-Type"] = "application/json"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{contract.gateway_url.rstrip('/')}/gateway/execute",
            content=body,
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["result"]


async def _log_execution(
    tool_id: str,
    server_id: str,
    success: bool,
    latency_ms: float,
    error_message: str | None = None,
    client_id: str | None = None,
    event_id: str | None = None,
    query_log_id: int | None = None,
) -> None:
    """Best-effort log to Supabase execution_logs (fire-and-forget)."""
    if not _SUPABASE_URL:
        return
    payload = {
        "tool_id": tool_id,
        "server_id": server_id,
        "success": success,
        "latency_ms": latency_ms,
        "error_message": error_message,
    }
    if client_id:
        payload["client_id"] = client_id
    if event_id:
        payload["event_id"] = event_id
    if query_log_id is not None:
        payload["query_log_id"] = query_log_id
    try:
        headers = _supabase_headers()
        if event_id:
            headers["Prefer"] = "resolution=ignore-duplicates"
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{_SUPABASE_URL}/rest/v1/execution_logs",
                headers=headers,
                json=payload,
            )
    except Exception as exc:
        logger.warning(f"Failed to log execution: {exc}")
