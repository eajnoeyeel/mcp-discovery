"""Supabase REST client adapter for MLP services."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger

from service.adapters.supabase_oauth_tokens import SupabaseOAuthTokenRepository
from service.services.contracts import UpstreamAuthConfig, UserProviderConnection
from service.services.delegated_oauth import scopes_cover
from service.services.oauth_tokens import OAuthTokenService
from service.services.secret_refs import OAuthSecretRefs, ServerAuthSecretRefs
from service.shared.content_hash import compute_content_hash
from service.shared.provider_ownership import (
    add_owner_tag,
    extract_owner_user_id,
    is_missing_column_error_payload,
    is_missing_owner_column_error_payload,
    strip_internal_owner_tags,
)

BASE_TOOL_SELECT_COLUMNS = (
    "tool_id,server_id,tool_name,description,input_schema,geo_score,index_status,created_at"
)

TOOL_METADATA_OVERRIDE_COLUMNS = (
    "upstream_description",
    "upstream_parameter_metadata",
    "published_parameter_metadata",
    "parameter_notes",
    "usage_examples",
    "usage_hints",
    "metadata_origin",
    "metadata_last_fetched_at",
    "override_updated_at",
)

TOOL_METADATA_SELECT_COLUMNS = (
    "tool_id,server_id,tool_name,description,upstream_description,input_schema,"
    "upstream_parameter_metadata,published_parameter_metadata,"
    "parameter_notes,usage_examples,usage_hints,metadata_origin,"
    "metadata_last_fetched_at,override_updated_at,geo_score,index_status,created_at"
)


class SupabaseClient:
    """Async Supabase REST wrapper for server/tool persistence."""

    def __init__(self, url: str, service_key: str) -> None:
        self._url = url.rstrip("/")
        self._service_key = service_key
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        payload: dict | list | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        client = self._get_client()
        response = await client.request(
            method,
            f"{self._url}{path}",
            headers=headers or self._headers,
            params=params,
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        return response

    async def _get(self, path: str, *, params: dict | None = None) -> list[dict]:
        resp = await self._request("GET", path, params=params)
        return resp.json()

    async def _post(self, path: str, *, payload: dict | None = None) -> dict | list:
        resp = await self._request("POST", path, payload=payload or {})
        return resp.json()

    async def _patch(
        self,
        path: str,
        *,
        params: dict | None = None,
        payload: dict | None = None,
        extra_headers: dict | None = None,
    ) -> list[dict]:
        headers = {**self._headers, **(extra_headers or {})}
        resp = await self._request("PATCH", path, params=params, payload=payload, headers=headers)
        return resp.json()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    async def fetch_provider_by_user_id(self, user_id: str) -> dict | None:
        """Fetch a provider row by owner user_id, or None if not found."""
        try:
            rows = await self._get(
                "/rest/v1/providers",
                params={"user_id": f"eq.{user_id}", "limit": 1},
            )
        except Exception:
            return None
        return rows[0] if rows else None

    async def create_provider(self, user_id: str, display_name: str | None = None) -> dict:
        """Create a new provider row and return the created record."""
        headers = {
            **self._headers,
            "Prefer": "return=representation",
        }
        resp = await self._request(
            "POST",
            "/rest/v1/providers",
            payload={"user_id": user_id, "display_name": display_name},
            headers=headers,
        )
        rows = resp.json()
        return rows[0] if isinstance(rows, list) else rows

    async def update_provider(self, provider_id: str, data: dict) -> dict | None:
        """Patch a provider row by id and return the updated record, or None on failure."""
        try:
            rows = await self._patch(
                "/rest/v1/providers",
                params={"id": f"eq.{provider_id}"},
                payload=data,
                extra_headers={"Prefer": "return=representation"},
            )
        except Exception:
            return None
        return rows[0] if rows else None

    async def fetch_provider_dashboard_tools(
        self, provider_id: str, owner_user_id: str
    ) -> list[dict]:
        """Fetch dashboard tool rows for a provider filtered by owner_user_id."""
        try:
            return await self._get(
                "/rest/v1/provider_tool_dashboard",
                params={
                    "owner_user_id": f"eq.{owner_user_id}",
                    "select": (
                        "tool_id,tool_name,server_id,server_name,description,"
                        "geo_score,index_status,tool_created_at,"
                        "call_count,success_rate,avg_latency_ms,p95_latency_ms,"
                        "call_count_7d,success_rate_7d,avg_latency_ms_7d,"
                        "times_selected,avg_confidence,times_exposed,selection_rate,"
                        "times_exposed_7d,selection_rate_7d,owner_user_id"
                    ),
                },
            )
        except Exception:
            return []

    async def fetch_tool_daily_stats(self, tool_id: str) -> list[dict]:
        """Fetch up to 30 days of daily stats for a tool, most recent first."""
        try:
            return await self._get(
                "/rest/v1/tool_daily_stats",
                params={
                    "tool_id": f"eq.{tool_id}",
                    "order": "day.desc",
                    "limit": 30,
                },
            )
        except Exception:
            return []

    async def fetch_tool_client_stats(self, tool_id: str) -> list[dict]:
        """Fetch per-client stats for a tool."""
        try:
            return await self._get(
                "/rest/v1/tool_client_stats",
                params={"tool_id": f"eq.{tool_id}"},
            )
        except Exception:
            return []

    async def fetch_tool_client_selection_stats(self, tool_id: str) -> list[dict]:
        """Fetch per-client selection stats for a tool."""
        try:
            return await self._get(
                "/rest/v1/tool_client_selection_stats",
                params={"tool_id": f"eq.{tool_id}"},
            )
        except Exception:
            return []

    async def upsert_server(self, server_row: dict) -> list:
        """Upsert a server row into mcp_servers.

        On PGRST "missing column" errors for `owner_user_id`, drops the
        column and retries once (schema-compatibility fallback for older
        Supabase deployments without provider ownership migrations).
        """
        headers = {
            **self._headers,
            "Prefer": "return=representation, resolution=merge-duplicates",
        }
        try:
            resp = await self._request(
                "POST",
                "/rest/v1/mcp_servers",
                payload=server_row,
                headers=headers,
            )
            return resp.json()
        except httpx.HTTPStatusError as exc:
            if not (self._is_missing_owner_column_error(exc) and server_row.get("owner_user_id")):
                raise

        logger.warning(
            "mcp_servers insert hit schema-compat fallback; dropping owner_user_id "
            "and retrying. Upgrade Supabase migrations to remove this path."
        )
        fallback_row = dict(server_row)
        fallback_row["tags"] = add_owner_tag(
            fallback_row.get("tags"),
            str(fallback_row.pop("owner_user_id")),
        )
        resp = await self._request(
            "POST",
            "/rest/v1/mcp_servers",
            payload=fallback_row,
            headers=headers,
        )
        return resp.json()

    async def upsert_server_auth(
        self,
        server_id: str,
        auth: UpstreamAuthConfig,
        *,
        secret_refs: ServerAuthSecretRefs | None = None,
    ) -> list:
        """Upsert a row into mcp_server_auth.

        Writes only _ref columns for secrets (post-029 schema). Plaintext
        bearer_token / api_key columns must not be written.
        """
        row: dict = {
            "server_id": server_id,
            "auth_type": auth.auth_type,
            "api_key_header_name": auth.api_key_header_name,
            "headers": auth.headers,
            # Secret Manager ref columns only
            "bearer_token_ref": secret_refs.bearer_token_ref if secret_refs else None,
            "api_key_ref": secret_refs.api_key_ref if secret_refs else None,
        }
        headers = {
            **self._headers,
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        resp = await self._request(
            "POST",
            "/rest/v1/mcp_server_auth",
            payload=row,
            params={"on_conflict": "server_id"},
            headers=headers,
        )
        return resp.json()

    async def upsert_oauth_session(
        self,
        server_id: str,
        auth: UpstreamAuthConfig,
        *,
        secret_refs: OAuthSecretRefs | None = None,
    ) -> list:
        """Upsert a row into mcp_oauth_sessions.

        Writes only _ref columns for secrets (post-029 schema). Plaintext
        client_secret / refresh_token columns must not be written.
        """
        row: dict = {
            "server_id": server_id,
            "token_endpoint": auth.oauth_token_endpoint,
            "client_id": auth.oauth_client_id,
            "client_secret_ref": secret_refs.client_secret_ref if secret_refs else None,
            "refresh_token_ref": secret_refs.refresh_token_ref if secret_refs else None,
            "scope": auth.oauth_scope,
            "secret_backend": secret_refs.secret_backend if secret_refs else None,
        }
        headers = {
            **self._headers,
            "Prefer": "resolution=merge-duplicates",
        }
        resp = await self._request(
            "POST",
            "/rest/v1/mcp_oauth_sessions",
            payload=row,
            params={"on_conflict": "server_id"},
            headers=headers,
        )
        return resp.json()

    async def find_user_provider_connection(
        self,
        *,
        user_id: str,
        provider_key: str,
        required_scopes: list[str],
    ) -> UserProviderConnection | None:
        """Return an active user provider connection covering required scopes, if any."""
        rows = await self._get(
            "/rest/v1/user_provider_connections",
            params={
                "user_id": f"eq.{user_id}",
                "provider_key": f"eq.{provider_key}",
                "status": "eq.active",
                "select": (
                    "id,user_id,provider_key,provider_account_id,granted_scopes,"
                    "scope_fingerprint,status,token_storage_mode"
                ),
            },
        )
        for row in rows:
            if scopes_cover(row.get("granted_scopes") or [], required_scopes):
                return UserProviderConnection.model_validate(row)
        return None

    async def create_pending_execution(
        self,
        *,
        user_id: str,
        tool_id: str,
        params_json: dict,
        provider_key: str,
        required_scopes: list[str],
        retry_token: str | None = None,
        resume_token: str | None = None,
        expires_at: str,
    ) -> dict | list:
        """Persist a short-lived pending execution context for OAuth retry UX."""
        token = retry_token or resume_token
        if not token:
            raise ValueError("retry_token or resume_token is required")
        payload = {
            "user_id": user_id,
            "tool_id": tool_id,
            "params_json": params_json,
            "provider_key": provider_key,
            "required_scopes": required_scopes,
            "retry_token": token,
            "expires_at": expires_at,
        }
        headers = {
            **self._headers,
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        resp = await self._request(
            "POST",
            "/rest/v1/pending_executions",
            payload=payload,
            headers=headers,
        )
        return resp.json()

    async def update_pending_execution(
        self,
        pending_execution_id: str,
        payload: dict,
    ) -> dict | list:
        """Patch a pending execution row by id."""
        headers = {
            **self._headers,
            "Prefer": "return=representation",
        }
        resp = await self._request(
            "PATCH",
            "/rest/v1/pending_executions",
            payload=payload,
            params={"id": f"eq.{pending_execution_id}"},
            headers=headers,
        )
        return resp.json()

    async def fetch_pending_execution_by_resume_token(self, resume_token: str) -> dict | None:
        """Fetch one pending execution by resume token."""
        rows = await self._get(
            "/rest/v1/pending_executions",
            params={"retry_token": f"eq.{resume_token}", "limit": 1},
        )
        return rows[0] if rows else None

    async def fetch_user_provider_token(self, connection_id: str) -> dict | None:
        """Fetch one user-owned provider token row by connection id."""
        rows = await self._get(
            "/rest/v1/user_provider_tokens",
            params={
                "connection_id": f"eq.{connection_id}",
                "select": (
                    "connection_id,access_token,refresh_token,expires_at,token_type,"
                    "user_provider_connections(provider_key)"
                ),
                "limit": 1,
            },
        )
        if not rows:
            return None

        row = dict(rows[0])
        connection = row.get("user_provider_connections")
        if isinstance(connection, dict):
            provider_key = connection.get("provider_key")
        elif isinstance(connection, list) and connection:
            provider_key = connection[0].get("provider_key")
        else:
            provider_key = None
        if provider_key:
            row["provider_key"] = provider_key
        return row

    async def fetch_provider_registry(self, provider_key: str) -> dict | None:
        """Fetch a curated OAuth provider registry row."""
        rows = await self._get(
            "/rest/v1/oauth_provider_registry",
            params={"provider_key": f"eq.{provider_key}", "limit": 1},
        )
        return rows[0] if rows else None

    async def fetch_bootstrap_draft_by_idempotency_key(
        self, *, owner_user_id: str, idempotency_key: str
    ) -> dict | None:
        """Fetch an OAuth provider bootstrap draft for idempotent retries."""
        rows = await self._get(
            "/rest/v1/oauth_provider_bootstrap_drafts",
            params={
                "owner_user_id": f"eq.{owner_user_id}",
                "idempotency_key": f"eq.{idempotency_key}",
                "limit": 1,
            },
        )
        return rows[0] if rows else None

    async def fetch_oauth_provider_bootstrap_draft(
        self, *, draft_id: str, owner_user_id: str
    ) -> dict | None:
        """Fetch a provider bootstrap draft before promotion-time path binding."""
        rows = await self._get(
            "/rest/v1/oauth_provider_bootstrap_drafts",
            params={
                "id": f"eq.{draft_id}",
                "owner_user_id": f"eq.{owner_user_id}",
                "select": "id,provider_key,metadata,status",
                "limit": 1,
            },
        )
        return rows[0] if rows else None

    async def create_oauth_provider_bootstrap_draft(self, payload: dict) -> dict | list:
        """Create an OAuth provider bootstrap draft row."""
        headers = {
            **self._headers,
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        resp = await self._request(
            "POST",
            "/rest/v1/oauth_provider_bootstrap_drafts",
            payload=payload,
            params={"on_conflict": "owner_user_id,idempotency_key"}
            if payload.get("idempotency_key")
            else None,
            headers=headers,
        )
        return resp.json()

    async def promote_oauth_provider_bootstrap_draft(
        self, *, draft_id: str, owner_user_id: str
    ) -> dict | list:
        """Promote a validated provider bootstrap draft into active registry metadata."""
        headers = {**self._headers, "Prefer": "return=representation"}
        resp = await self._request(
            "POST",
            "/rest/v1/rpc/promote_oauth_provider_bootstrap_draft",
            payload={"p_draft_id": draft_id, "p_owner_user_id": owner_user_id},
            headers=headers,
        )
        return resp.json()

    async def create_oauth_state_nonce(self, payload: dict) -> dict | list:
        """Persist an OAuth state nonce hash before redirecting to a provider."""
        headers = {**self._headers, "Prefer": "return=representation"}
        resp = await self._request(
            "POST",
            "/rest/v1/oauth_state_nonces",
            payload=payload,
            headers=headers,
        )
        return resp.json()

    async def consume_oauth_state_nonce(self, *, nonce_hash: str, provider_key: str) -> dict | list:
        """Atomically consume an OAuth state nonce hash exactly once."""
        headers = {**self._headers, "Prefer": "return=representation"}
        resp = await self._request(
            "POST",
            "/rest/v1/rpc/consume_oauth_state_nonce",
            payload={"p_nonce_hash": nonce_hash, "p_provider_key": provider_key},
            headers=headers,
        )
        return resp.json()

    async def replace_auth_requirements(
        self,
        server_id: str,
        requirements: list[dict],
    ) -> list[dict]:
        """Atomically replace delegated client-auth requirements for a server."""
        headers = {
            **self._headers,
            "Prefer": "return=representation",
        }
        resp = await self._request(
            "POST",
            "/rest/v1/rpc/replace_mcp_auth_requirements",
            payload={
                "p_server_id": server_id,
                "p_requirements": requirements,
            },
            headers=headers,
        )
        return resp.json()

    async def upsert_user_provider_connection(
        self,
        *,
        user_id: str,
        provider_key: str,
        provider_account_id: str | None,
        granted_scopes: list[str],
        scope_fingerprint: str,
        token_storage_mode: str,
    ) -> dict | list:
        """Upsert user-owned provider connection metadata."""
        payload = {
            "user_id": user_id,
            "provider_key": provider_key,
            "provider_account_id": provider_account_id,
            "granted_scopes": granted_scopes,
            "scope_fingerprint": scope_fingerprint,
            "status": "active",
            "token_storage_mode": token_storage_mode,
        }
        headers = {
            **self._headers,
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        resp = await self._request(
            "POST",
            "/rest/v1/user_provider_connections",
            payload=payload,
            params={"on_conflict": "user_id,provider_key,scope_fingerprint"},
            headers=headers,
        )
        return resp.json()

    async def store_user_provider_tokens(
        self,
        *,
        connection_id: str,
        access_token: str | None,
        refresh_token: str | None,
        expires_in: int | str | None,
        token_type: str,
    ) -> dict | list:
        """Persist token material for a user-owned provider connection."""
        expires_at = None
        if expires_in:
            expires_at = (
                (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in)))
                .isoformat()
                .replace("+00:00", "Z")
            )
        payload = {
            "connection_id": connection_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "token_type": token_type,
        }
        headers = {
            **self._headers,
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        resp = await self._request(
            "POST",
            "/rest/v1/user_provider_tokens",
            payload=payload,
            params={"on_conflict": "connection_id"},
            headers=headers,
        )
        return resp.json()

    @staticmethod
    def _normalize_upstream_parameter_metadata(tool: dict) -> list:
        upstream_parameter_metadata = tool.get("upstream_parameter_metadata")
        if isinstance(upstream_parameter_metadata, list) and upstream_parameter_metadata:
            return upstream_parameter_metadata

        parameter_metadata = tool.get("parameter_metadata")
        if isinstance(parameter_metadata, list):
            return parameter_metadata

        if isinstance(upstream_parameter_metadata, list):
            return upstream_parameter_metadata

        return []

    @staticmethod
    def build_tool_insert_rows(server_id: str, tools: list[dict]) -> list[dict]:
        """Build mcp_tools insert rows for registration flows."""
        tool_rows: list[dict] = []
        for tool in tools:
            upstream_parameter_metadata = SupabaseClient._normalize_upstream_parameter_metadata(
                tool
            )
            row = {
                "tool_id": f"{server_id}::{tool['tool_name']}",
                "server_id": server_id,
                "tool_name": tool["tool_name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("input_schema"),
                "upstream_description": tool.get("upstream_description") or "",
                "upstream_parameter_metadata": upstream_parameter_metadata,
                "published_parameter_metadata": (
                    tool.get("published_parameter_metadata")
                    if isinstance(tool.get("published_parameter_metadata"), list)
                    else []
                ),
                "usage_examples": (
                    tool.get("usage_examples")
                    if isinstance(tool.get("usage_examples"), list)
                    else []
                ),
                "usage_hints": (
                    tool.get("usage_hints") if isinstance(tool.get("usage_hints"), list) else []
                ),
                "index_status": "pending",
                "content_hash": compute_content_hash(
                    tool["tool_name"],
                    tool.get("description", ""),
                ),
            }
            if tool.get("parameter_notes") is not None:
                row["parameter_notes"] = tool.get("parameter_notes")
            if tool.get("metadata_origin"):
                row["metadata_origin"] = tool.get("metadata_origin")
            if tool.get("metadata_last_fetched_at"):
                row["metadata_last_fetched_at"] = tool.get("metadata_last_fetched_at")
            if tool.get("override_updated_at"):
                row["override_updated_at"] = tool.get("override_updated_at")
            tool_rows.append(row)
        return tool_rows

    async def insert_tools(self, server_id: str, tools: list[dict]) -> list:
        """Upsert tool rows into mcp_tools with pending index_status.

        Uses PostgREST merge-duplicates on the ``tool_id`` primary key so
        re-registration of an existing server+tool pair updates rather than
        raising 409. Required for idempotent register flows per ADR-0015.
        """
        headers = {
            **self._headers,
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        tool_rows = self.build_tool_insert_rows(server_id, tools)
        resp = await self._request(
            "POST",
            "/rest/v1/mcp_tools",
            payload=tool_rows,
            headers=headers,
        )
        return resp.json()

    async def mark_tools_event_failed(self, server_id: str) -> list[dict]:
        """Mark pending tools for a server as ``event_failed``.

        Used by the register→index_replay retry contract: when the EventBridge
        publish fails after tools are persisted, flipping ``index_status`` from
        ``pending`` → ``event_failed`` lets the index_replay Lambda pick them
        up on the next scan. Only pending rows are touched (idempotent).
        """
        return await self._patch(
            "/rest/v1/mcp_tools",
            params={
                "server_id": f"eq.{server_id}",
                "index_status": "eq.pending",
            },
            payload={"index_status": "event_failed"},
        )

    async def fetch_pending_tools(self, server_id: str) -> list[dict]:
        """Fetch tools with pending index_status for a given server."""
        params = {
            "server_id": f"eq.{server_id}",
            "index_status": "eq.pending",
            "select": "*",
        }
        resp = await self._request("GET", "/rest/v1/mcp_tools", params=params)
        return resp.json()

    async def mark_indexed(self, tool_ids: list[str]) -> None:
        """Update index_status to 'indexed' for the given tool IDs."""
        if not tool_ids:
            return
        params = {"tool_id": f"in.({','.join(tool_ids)})"}
        await self._request(
            "PATCH",
            "/rest/v1/mcp_tools",
            params=params,
            payload={"index_status": "indexed"},
        )
        logger.info(f"Marked {len(tool_ids)} tools as indexed")

    async def fetch_platform_stats(self) -> dict:
        """Fetch aggregate platform stats through the existing RPC."""
        data = await self._post("/rest/v1/rpc/get_platform_stats")
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    async def fetch_server_tool_counts(self) -> dict[str, int]:
        """Fetch tool counts keyed by server_id."""
        rows = await self._get("/rest/v1/server_tool_counts", params={"select": "*"})
        return {row["server_id"]: row["tool_count"] for row in rows}

    async def fetch_server_count(self) -> int:
        """Fetch total count of public MCP servers via PostgREST count header."""
        headers = {**self._headers, "Prefer": "count=exact"}
        resp = await self._request(
            "GET",
            "/rest/v1/mcp_servers",
            params={"select": "server_id", "limit": 0},
            headers=headers,
        )
        content_range = resp.headers.get("content-range", "")
        if "/" in content_range:
            try:
                return int(content_range.split("/")[-1])
            except ValueError:
                pass
        return 0

    async def fetch_servers(
        self, *, limit: int = 50, offset: int = 0, public_only: bool = True
    ) -> list[dict]:
        """Fetch server listing rows.

        public_only=True (default) filters out servers with is_published=false.
        Callers that need unpublished rows (owner dashboard, execute path)
        must pass public_only=False explicitly.
        """
        params: dict = {
            "select": "server_id,name,description,url,tags,index_status,created_at,updated_at",
            "order": "name.asc",
            "limit": limit,
            "offset": offset,
        }
        if public_only:
            params["is_published"] = "eq.true"
        rows = await self._get("/rest/v1/mcp_servers", params=params)
        counts = await self.fetch_server_tool_counts()
        for row in rows:
            row["tags"] = strip_internal_owner_tags(row.get("tags"))
            row["tool_count"] = counts.get(row["server_id"], 0)
        return rows

    async def fetch_server(self, server_id: str, *, public_only: bool = True) -> dict | None:
        """Fetch a single server row.

        public_only=True (default) returns None for unpublished servers.
        Callers that need unpublished rows (owner dashboard, execute path)
        must pass public_only=False explicitly.
        """
        select_columns = (
            "server_id,name,description,url,tags,"
            "index_status,created_at,updated_at,owner_user_id,provider_id,is_published"
        )
        base_params: dict = {
            "server_id": f"eq.{server_id}",
            "select": select_columns,
            "limit": 1,
        }
        if public_only:
            base_params["is_published"] = "eq.true"
        try:
            rows = await self._get("/rest/v1/mcp_servers", params=base_params)
        except httpx.HTTPStatusError as exc:
            if not self._is_missing_owner_column_error(exc):
                raise
            fallback_columns = [
                "server_id",
                "name",
                "description",
                "url",
                "tags",
                "index_status",
                "created_at",
                "updated_at",
                "provider_id",
                "is_published",
            ]
            fallback_params: dict = {
                "server_id": f"eq.{server_id}",
                "select": ",".join(fallback_columns),
                "limit": 1,
            }
            if public_only:
                fallback_params["is_published"] = "eq.true"
            rows = await self._get("/rest/v1/mcp_servers", params=fallback_params)
        return self._normalize_server_row(rows[0]) if rows else None

    async def fetch_server_tools(self, server_id: str) -> list[dict]:
        """Fetch tool rows for a single server."""
        try:
            return await self._get(
                "/rest/v1/mcp_tools",
                params={
                    "server_id": f"eq.{server_id}",
                    "select": TOOL_METADATA_SELECT_COLUMNS,
                    "order": "tool_name.asc",
                },
            )
        except httpx.HTTPStatusError as exc:
            if not self._is_missing_tool_metadata_column_error(exc):
                raise
            return await self._get(
                "/rest/v1/mcp_tools",
                params={
                    "server_id": f"eq.{server_id}",
                    "select": BASE_TOOL_SELECT_COLUMNS,
                    "order": "tool_name.asc",
                },
            )

    async def fetch_tool(self, tool_id: str) -> dict | None:
        """Fetch a single tool row."""
        try:
            rows = await self._get(
                "/rest/v1/mcp_tools",
                params={
                    "tool_id": f"eq.{tool_id}",
                    "select": TOOL_METADATA_SELECT_COLUMNS,
                    "limit": 1,
                },
            )
        except httpx.HTTPStatusError as exc:
            if not self._is_missing_tool_metadata_column_error(exc):
                raise
            rows = await self._get(
                "/rest/v1/mcp_tools",
                params={
                    "tool_id": f"eq.{tool_id}",
                    "select": BASE_TOOL_SELECT_COLUMNS,
                    "limit": 1,
                },
            )
        return rows[0] if rows else None

    async def fetch_server_execution_auth(self, server_id: str) -> UpstreamAuthConfig:
        """Load stored upstream auth for a server from auth/OAuth persistence."""
        auth_row = await self._fetch_server_auth_row(server_id)
        if auth_row is not None:
            return UpstreamAuthConfig(
                auth_type=auth_row.get("auth_type") or "none",
                bearer_token=auth_row.get("bearer_token"),  # resolved from Secrets Manager
                api_key_header_name=auth_row.get("api_key_header_name"),
                api_key=auth_row.get("api_key"),  # resolved from Secrets Manager
                headers=auth_row.get("headers") or {},
            )

        oauth_row = await self._fetch_oauth_session_row(server_id)
        if oauth_row is None:
            return UpstreamAuthConfig()

        oauth_repo = SupabaseOAuthTokenRepository(self._url, self._service_key)
        access_token = await OAuthTokenService(repo=oauth_repo).get_access_token(server_id)
        return UpstreamAuthConfig(auth_type="bearer", bearer_token=access_token)

    async def _fetch_server_auth_row(self, server_id: str) -> dict | None:
        try:
            rows = await self._get(
                "/rest/v1/mcp_server_auth",
                params={
                    "server_id": f"eq.{server_id}",
                    "select": (
                        "auth_type,api_key_header_name,headers,bearer_token_ref,api_key_ref"
                    ),
                    "limit": 1,
                },
            )
        except httpx.HTTPStatusError as exc:
            if self._is_missing_auth_table_error(exc):
                return None
            raise

        if not rows:
            return None

        row = rows[0]
        bearer_token_ref = row.get("bearer_token_ref")
        api_key_ref = row.get("api_key_ref")

        bearer_token: str | None = None
        api_key: str | None = None
        if bearer_token_ref or api_key_ref:
            try:
                from service.adapters.aws_secrets_manager import AWSSecretsManagerOAuthStore

                region_name = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
                kms_key_id = os.environ.get("OAUTH_SECRET_KMS_KEY_ID")
                secret_store = AWSSecretsManagerOAuthStore(
                    region_name=region_name,
                    kms_key_id=kms_key_id,
                )
                bearer_token, api_key = await secret_store.resolve_server_auth_secrets(
                    bearer_token_ref=bearer_token_ref,
                    api_key_ref=api_key_ref,
                )
            except Exception as exc:
                logger.warning(
                    f"Failed to resolve stored server auth secrets from Secrets Manager: {exc}"
                )

        return {
            **row,
            "bearer_token": bearer_token,
            "api_key": api_key,
        }

    async def _fetch_oauth_session_row(self, server_id: str) -> dict | None:
        try:
            rows = await self._get(
                "/rest/v1/mcp_oauth_sessions",
                params={
                    "server_id": f"eq.{server_id}",
                    "select": "server_id",
                    "limit": 1,
                },
            )
        except httpx.HTTPStatusError as exc:
            if self._is_missing_oauth_sessions_table_error(exc):
                return None
            raise
        return rows[0] if rows else None

    async def update_tool_metadata_override(self, tool_id: str, payload: dict) -> dict | None:
        """Persist provider-authored metadata overrides for a single tool."""
        patch_payload = {
            **payload,
            "override_updated_at": payload.get("override_updated_at") or self._timestamp(),
        }
        rows = await self._patch(
            "/rest/v1/mcp_tools",
            params={"tool_id": f"eq.{tool_id}"},
            payload=patch_payload,
            extra_headers={"Prefer": "return=representation"},
        )
        return rows[0] if rows else None

    async def apply_tool_metadata_refresh(self, tool_id: str, payload: dict) -> dict | None:
        """Persist upstream metadata refresh fields for a single tool."""
        patch_payload = {
            **payload,
            "metadata_last_fetched_at": (
                payload.get("metadata_last_fetched_at") or self._timestamp()
            ),
        }
        rows = await self._patch(
            "/rest/v1/mcp_tools",
            params={"tool_id": f"eq.{tool_id}"},
            payload=patch_payload,
            extra_headers={"Prefer": "return=representation"},
        )
        return rows[0] if rows else None

    async def fetch_owned_servers(self, owner_user_id: str) -> list[dict]:
        """Fetch servers owned by a specific Supabase user."""
        select_columns = (
            "server_id,name,description,url,tags,index_status,created_at,updated_at,owner_user_id"
        )
        try:
            rows = await self._get(
                "/rest/v1/mcp_servers",
                params={
                    "owner_user_id": f"eq.{owner_user_id}",
                    "select": select_columns,
                    "order": "name.asc",
                },
            )
        except httpx.HTTPStatusError as exc:
            if not self._is_missing_owner_column_error(exc):
                raise
            rows = await self._get(
                "/rest/v1/mcp_servers",
                params={
                    "select": (
                        "server_id,name,description,url,tags,index_status,created_at,updated_at"
                    ),
                    "order": "name.asc",
                },
            )
            rows = [row for row in rows if extract_owner_user_id(row) == owner_user_id]
        return [self._normalize_server_row(row) for row in rows]

    async def fetch_owned_tool_detail(self, owner_user_id: str, tool_id: str) -> dict | None:
        """Fetch a single owned tool plus server display fields."""
        tool = await self.fetch_tool(tool_id)
        if tool is None:
            return None
        # Owner can see their own unpublished servers.
        server = await self.fetch_server(tool["server_id"], public_only=False)
        if server is None or server.get("owner_user_id") != owner_user_id:
            return None
        return {
            **tool,
            "server_name": server["name"],
            "server_url": server.get("url"),
        }

    async def fetch_owned_server_tools(
        self,
        owner_user_id: str,
        server_id: str,
        *,
        exclude_tool_id: str | None = None,
    ) -> list[dict]:
        """Fetch all owned tools for a server, optionally excluding one tool."""
        # Owner can see their own unpublished servers.
        server = await self.fetch_server(server_id, public_only=False)
        if server is None or server.get("owner_user_id") != owner_user_id:
            return []
        tools = await self.fetch_server_tools(server_id)
        if exclude_tool_id:
            tools = [tool for tool in tools if tool["tool_id"] != exclude_tool_id]
        for tool in tools:
            tool["server_name"] = server["name"]
        return tools

    async def fetch_tool_simulations(self, tool_id: str) -> list[dict]:
        """Fetch aggregated search simulation rows for a tool."""
        try:
            return await self._get(
                "/rest/v1/provider_search_simulations",
                params={
                    "recommended_tool_id": f"eq.{tool_id}",
                    "select": "*",
                },
            )
        except Exception:
            # Table may not exist yet — graceful degradation
            return []

    async def fetch_server_quality_data(self, server_id: str) -> dict:
        """Fetch all data needed for quality checklist computation.

        Returns a dict with server, tools, and has_usage keys. GitHub
        metadata lookup was retired along with the quality-checklist
        GitHub integration feature.
        """
        server = await self.fetch_server(server_id)
        if server is None:
            raise LookupError(f"Server '{server_id}' not found")

        tools = await self.fetch_server_tools(server_id)

        has_usage = False
        try:
            rows = await self._get(
                "/rest/v1/tool_operability_view",
                params={
                    "server_id": f"eq.{server_id}",
                    "select": "call_count",
                    "call_count": "gt.0",
                    "limit": 1,
                },
            )
            has_usage = len(rows) > 0
        except Exception:
            pass

        return {
            "server": server,
            "tools": tools,
            "has_usage": has_usage,
        }

    async def fetch_tool_exposure_count(self, tool_id: str) -> int:
        """Count total exposures for a tool from tool_exposure_facts view.

        Returns 0 if the view does not exist (migration 022 not applied).
        """
        try:
            # PostgREST count=exact: send Prefer + Range headers, read Content-Range total
            headers = {
                **self._headers,
                "Prefer": "count=exact",
                "Range-Unit": "items",
                "Range": "0-0",
            }
            resp = await self._request(
                "GET",
                "/rest/v1/tool_exposure_facts",
                params={"exposed_tool_id": f"eq.{tool_id}", "select": "query_log_id"},
                headers=headers,
            )
            content_range = resp.headers.get("Content-Range", "")
            # Content-Range: 0-0/42 — extract total after /
            if "/" in content_range:
                return int(content_range.split("/")[1])
            return len(resp.json())
        except Exception as exc:
            logger.warning(f"fetch_tool_exposure_count failed for {tool_id}: {exc}")
            return 0

    async def fetch_tool_conversion_stats(self, tool_id: str) -> dict:
        """Aggregate conversion funnel stats for a tool from tool_conversion_funnel view.

        Returns dict with keys: recommendation_count, converted_count.
        Returns zeros if the view does not exist (migration 022 not applied).

        tool_conversion_funnel is a LEFT JOIN view: one query_log_id can
        produce multiple rows (multi-execution recommendations). We dedupe
        by query_log_id; a recommendation counts as 'converted' if ANY of
        its execution rows converted.
        """
        try:
            rows = await self._get(
                "/rest/v1/tool_conversion_funnel",
                params={
                    "recommended_tool_id": f"eq.{tool_id}",
                    "select": "query_log_id,funnel_outcome",
                },
            )
        except Exception as exc:
            logger.warning(f"fetch_tool_conversion_stats failed for {tool_id}: {exc}")
            return {"recommendation_count": 0, "converted_count": 0}

        seen: dict = {}
        for row in rows:
            qid = row.get("query_log_id")
            if qid is None:
                continue
            outcome = row.get("funnel_outcome")
            # 'converted' wins over other outcomes for the same query_log_id
            if outcome == "converted" or qid not in seen:
                seen[qid] = outcome

        recommendation_count = len(seen)
        converted_count = sum(1 for o in seen.values() if o == "converted")
        return {
            "recommendation_count": recommendation_count,
            "converted_count": converted_count,
        }

    async def fetch_tool_public_stats(self, tool_id: str) -> dict | None:
        """Public-safe aggregated stats from tool_operability_view.

        Field allowlist: call_count, success_rate, avg_latency_ms ONLY.
        Returns None if view/data doesn't exist (migration 008 not applied).
        """
        try:
            rows = await self._get(
                "/rest/v1/tool_operability_view",
                params={
                    "tool_id": f"eq.{tool_id}",
                    "select": "call_count,success_rate,avg_latency_ms",
                    "limit": 1,
                },
            )
        except Exception:
            return None
        if not rows:
            return None
        row = rows[0]
        return {
            "call_count": row.get("call_count", 0),
            "success_rate": row.get("success_rate"),
            "avg_latency_ms": row.get("avg_latency_ms"),
        }

    @staticmethod
    def _is_missing_owner_column_error(exc: httpx.HTTPStatusError) -> bool:
        try:
            payload = exc.response.json()
        except ValueError:
            return False
        return is_missing_owner_column_error_payload(payload)

    @staticmethod
    def _is_missing_tool_metadata_column_error(exc: httpx.HTTPStatusError) -> bool:
        try:
            payload = exc.response.json()
        except ValueError:
            return False
        return any(
            is_missing_column_error_payload(payload, column)
            for column in TOOL_METADATA_OVERRIDE_COLUMNS
        )

    @staticmethod
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

    @staticmethod
    def _is_missing_oauth_sessions_table_error(exc: httpx.HTTPStatusError) -> bool:
        try:
            payload = exc.response.json()
        except ValueError:
            payload = {}
        code = str(payload.get("code") or "")
        message = str(payload.get("message") or "").lower()
        return code in {"42P01", "PGRST205"} or (
            "mcp_oauth_sessions" in message and "does not exist" in message
        )

    @staticmethod
    def _normalize_server_row(row: dict) -> dict:
        normalized = dict(row)
        normalized["owner_user_id"] = extract_owner_user_id(normalized)
        normalized["tags"] = strip_internal_owner_tags(normalized.get("tags"))
        return normalized
