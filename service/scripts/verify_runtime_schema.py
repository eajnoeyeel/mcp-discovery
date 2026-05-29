"""Verify hosted Supabase runtime schema readiness for the MLP gateway stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import suppress
from typing import Any
from uuid import uuid4

import httpx

REQUIRED_CHECKS = (
    # Transport + auth primitives (migrations 008-014).
    "mcp_servers.transport_type",
    "mcp_servers.requires_gateway",
    "mcp_oauth_sessions",
    "mcp_gateway_routes",
    # Analytics + semantic-redesign surface (migrations 011, 012, 020, 022).
    # Without these the bridge/search analytics contract and provider dashboard
    # read model are broken even if the Lambda builds land.
    "query_logs.recommended_tool_id",
    "execution_logs.query_log_id",
    "tool_operational_stats",
    # Delegated provider OAuth + resumable execution (migrations 025-026).
    "oauth_provider_registry.bootstrap_metadata",
    "oauth_provider_bootstrap_drafts",
    "oauth_state_nonces",
    "mcp_auth_requirements",
    "user_provider_connections",
    "pending_executions.resume_contract",
)

# Post-029: verify plaintext secret columns are absent. Gated on VERIFY_POST_029=1
# so the verifier stays green before migration 029 is applied.
POST_029_ABSENT_COLUMNS = (
    "mcp_server_auth.bearer_token",
    "mcp_server_auth.api_key",
    "mcp_oauth_sessions.client_secret",
    "mcp_oauth_sessions.access_token",
    "mcp_oauth_sessions.refresh_token",
)

MCP_AUTH_REQUIREMENTS_UNIQUENESS_CHECKS = (
    "mcp_auth_requirements.server_default_unique",
    "mcp_auth_requirements.tool_id_unique",
)

_POST_029_ABSENT_REQUESTS: dict[str, tuple[str, str]] = {
    "mcp_server_auth.bearer_token": ("mcp_server_auth", "bearer_token"),
    "mcp_server_auth.api_key": ("mcp_server_auth", "api_key"),
    "mcp_oauth_sessions.client_secret": ("mcp_oauth_sessions", "client_secret"),
    "mcp_oauth_sessions.access_token": ("mcp_oauth_sessions", "access_token"),
    "mcp_oauth_sessions.refresh_token": ("mcp_oauth_sessions", "refresh_token"),
}

_CHECK_REQUESTS: dict[str, tuple[str, dict[str, str]]] = {
    "mcp_servers.transport_type": (
        "mcp_servers",
        {"select": "transport_type", "limit": "1"},
    ),
    "mcp_servers.requires_gateway": (
        "mcp_servers",
        {"select": "requires_gateway", "limit": "1"},
    ),
    "mcp_oauth_sessions": (
        "mcp_oauth_sessions",
        {"select": "server_id", "limit": "1"},
    ),
    "mcp_gateway_routes": (
        "mcp_gateway_routes",
        {"select": "server_id", "limit": "1"},
    ),
    "query_logs.recommended_tool_id": (
        "query_logs",
        {"select": "recommended_tool_id", "limit": "1"},
    ),
    "execution_logs.query_log_id": (
        "execution_logs",
        {"select": "query_log_id", "limit": "1"},
    ),
    "tool_operational_stats": (
        "tool_operational_stats",
        {"select": "tool_id", "limit": "1"},
    ),
    "oauth_provider_registry.bootstrap_metadata": (
        "oauth_provider_registry",
        {
            "select": (
                "provider_key,issuer,metadata_url,registration_endpoint,"
                "client_secret_ref,token_endpoint_auth_method,bootstrap_status"
            ),
            "limit": "1",
        },
    ),
    "oauth_provider_bootstrap_drafts": (
        "oauth_provider_bootstrap_drafts",
        {"select": "id,owner_user_id,provider_key,status,idempotency_key", "limit": "1"},
    ),
    "oauth_state_nonces": (
        "oauth_state_nonces",
        {
            "select": (
                "nonce_hash,code_verifier,required_scopes,user_id,provider_key,"
                "expires_at,consumed_at"
            ),
            "limit": "1",
        },
    ),
    "mcp_auth_requirements": (
        "mcp_auth_requirements",
        {"select": "provider_key,tool_id,required_scopes,scope_mode", "limit": "1"},
    ),
    "user_provider_connections": (
        "user_provider_connections",
        {"select": "id,user_id,provider_key,status", "limit": "1"},
    ),
    "pending_executions.resume_contract": (
        "pending_executions",
        {
            "select": "id,retry_token,status,connection_id,result_json,error_message",
            "limit": "1",
        },
    ),
}


def summarize_schema_checks(checks: dict[str, bool]) -> dict[str, Any]:
    missing = [name for name in REQUIRED_CHECKS if not checks.get(name, False)]
    present = sorted(name for name in REQUIRED_CHECKS if checks.get(name, False))
    return {
        "ready": not missing,
        "missing": missing,
        "present": present,
    }


def summarize_post_029_checks(absent_checks: dict[str, bool]) -> dict[str, Any]:
    """Summarise post-029 absent-column checks (column present = FAIL)."""
    still_present = [col for col in POST_029_ABSENT_COLUMNS if absent_checks.get(col, False)]
    confirmed_absent = sorted(
        col for col in POST_029_ABSENT_COLUMNS if not absent_checks.get(col, False)
    )
    return {
        "ready": not still_present,
        "columns_still_present": still_present,
        "columns_confirmed_absent": confirmed_absent,
    }


def summarize_mcp_auth_requirements_uniqueness_checks(
    uniqueness_checks: dict[str, bool],
) -> dict[str, Any]:
    missing = [
        name
        for name in MCP_AUTH_REQUIREMENTS_UNIQUENESS_CHECKS
        if not uniqueness_checks.get(name, False)
    ]
    present = sorted(
        name
        for name in MCP_AUTH_REQUIREMENTS_UNIQUENESS_CHECKS
        if uniqueness_checks.get(name, False)
    )
    return {
        "ready": not missing,
        "missing": missing,
        "present": present,
    }


def _build_headers(service_key: str) -> dict[str, str]:
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }


def _is_present_response(response: httpx.Response) -> bool:
    if response.status_code == 200:
        return True
    if response.status_code in {400, 404}:
        return False
    response.raise_for_status()
    return False


def _is_unique_violation_response(response: httpx.Response) -> bool:
    if response.status_code == 409:
        return True
    if response.status_code != 400:
        return False
    with suppress(ValueError):
        body = response.json()
        return body.get("code") == "23505"
    return False


def _failed_mcp_auth_requirements_uniqueness_checks() -> dict[str, bool]:
    return dict.fromkeys(MCP_AUTH_REQUIREMENTS_UNIQUENESS_CHECKS, False)


async def fetch_runtime_schema_state(
    base_url: str,
    service_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, bool]:
    base_url = base_url.rstrip("/")
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)

    try:
        checks: dict[str, bool] = {}
        for check_name in REQUIRED_CHECKS:
            relation, params = _CHECK_REQUESTS[check_name]
            response = await client.get(
                f"{base_url}/rest/v1/{relation}",
                headers=_build_headers(service_key),
                params=params,
            )
            checks[check_name] = _is_present_response(response)
        return checks
    finally:
        if owns_client:
            await client.aclose()


async def fetch_mcp_auth_requirements_uniqueness_state(
    base_url: str,
    service_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, bool]:
    """Probe migration 034 uniqueness enforcement with temporary rows.

    This is intentionally opt-in from ``main`` because it performs writes using
    the service key.  It creates a disposable server/tool pair, attempts
    duplicate auth-requirement inserts, and then deletes the probe server.  The
    delete cascades through ``mcp_tools`` and ``mcp_auth_requirements``; explicit
    cleanup calls are still issued so the probe remains safe on partially
    migrated schemas.
    """

    base_url = base_url.rstrip("/")
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)

    headers = _build_headers(service_key)
    write_headers = {
        **headers,
        "Prefer": "return=representation",
    }
    cleanup_headers = {
        **headers,
        "Prefer": "return=minimal",
    }
    server_id = f"runtime-schema-probe-{uuid4().hex}"
    tool_id = f"{server_id}::probe_tool"

    try:
        provider_response = await client.get(
            f"{base_url}/rest/v1/oauth_provider_registry",
            headers=headers,
            params={"select": "provider_key", "enabled": "eq.true", "limit": "1"},
        )
        if not _is_present_response(provider_response):
            return _failed_mcp_auth_requirements_uniqueness_checks()
        provider_rows = provider_response.json()
        if not provider_rows:
            return _failed_mcp_auth_requirements_uniqueness_checks()
        provider_key = str(provider_rows[0]["provider_key"])

        server_response = await client.post(
            f"{base_url}/rest/v1/mcp_servers",
            headers=write_headers,
            json={
                "server_id": server_id,
                "name": "runtime schema uniqueness probe",
                "description": "Temporary row created by verify_runtime_schema.py",
                "url": "https://example.invalid/mcp",
                "index_status": "pending",
                "transport_type": "stateless_http",
                "requires_gateway": False,
            },
        )
        server_response.raise_for_status()

        tool_response = await client.post(
            f"{base_url}/rest/v1/mcp_tools",
            headers=write_headers,
            json={
                "tool_id": tool_id,
                "server_id": server_id,
                "tool_name": "probe_tool",
                "description": "Temporary row created by verify_runtime_schema.py",
                "input_schema": {"type": "object", "properties": {}},
                "index_status": "pending",
            },
        )
        tool_response.raise_for_status()

        checks: dict[str, bool] = {}
        server_requirement = {
            "server_id": server_id,
            "tool_id": None,
            "provider_key": provider_key,
            "auth_kind": "oauth",
            "required_scopes": [],
            "scope_mode": "default",
        }
        first_server_response = await client.post(
            f"{base_url}/rest/v1/mcp_auth_requirements",
            headers=write_headers,
            json=server_requirement,
        )
        first_server_response.raise_for_status()
        duplicate_server_response = await client.post(
            f"{base_url}/rest/v1/mcp_auth_requirements",
            headers=write_headers,
            json=server_requirement,
        )
        checks["mcp_auth_requirements.server_default_unique"] = _is_unique_violation_response(
            duplicate_server_response
        )

        tool_requirement = {
            **server_requirement,
            "tool_id": tool_id,
        }
        first_tool_response = await client.post(
            f"{base_url}/rest/v1/mcp_auth_requirements",
            headers=write_headers,
            json=tool_requirement,
        )
        first_tool_response.raise_for_status()
        duplicate_tool_response = await client.post(
            f"{base_url}/rest/v1/mcp_auth_requirements",
            headers=write_headers,
            json=tool_requirement,
        )
        checks["mcp_auth_requirements.tool_id_unique"] = _is_unique_violation_response(
            duplicate_tool_response
        )

        return checks
    finally:
        with suppress(Exception):
            await client.delete(
                f"{base_url}/rest/v1/mcp_auth_requirements",
                headers=cleanup_headers,
                params={"server_id": f"eq.{server_id}"},
            )
        with suppress(Exception):
            await client.delete(
                f"{base_url}/rest/v1/mcp_tools",
                headers=cleanup_headers,
                params={"server_id": f"eq.{server_id}"},
            )
        with suppress(Exception):
            await client.delete(
                f"{base_url}/rest/v1/mcp_servers",
                headers=cleanup_headers,
                params={"server_id": f"eq.{server_id}"},
            )
        if owns_client:
            await client.aclose()


async def fetch_post_029_absent_column_state(
    base_url: str,
    service_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, bool]:
    """Check whether plaintext secret columns still exist (True = still present = bad)."""
    base_url = base_url.rstrip("/")
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)

    try:
        results: dict[str, bool] = {}
        for check_name, (relation, column) in _POST_029_ABSENT_REQUESTS.items():
            response = await client.get(
                f"{base_url}/rest/v1/{relation}",
                headers=_build_headers(service_key),
                params={"select": column, "limit": "1"},
            )
            # 200 → column still exists (bad); 400/404 → column absent (good)
            results[check_name] = _is_present_response(response)
        return results
    finally:
        if owns_client:
            await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify hosted runtime schema readiness.")
    parser.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL", ""))
    parser.add_argument("--service-key", default=os.environ.get("SUPABASE_SERVICE_KEY", ""))
    parser.add_argument(
        "--verify-mcp-auth-requirements-uniqueness",
        action="store_true",
        default=os.environ.get("VERIFY_MCP_AUTH_REQUIREMENTS_UNIQUENESS") == "1",
        help=(
            "Run an opt-in write probe that verifies migration 034 uniqueness "
            "for mcp_auth_requirements server-default and tool-level rows."
        ),
    )
    args = parser.parse_args()

    if not (args.supabase_url and args.service_key):
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")

    checks = asyncio.run(fetch_runtime_schema_state(args.supabase_url, args.service_key))
    summary = summarize_schema_checks(checks)
    ready = bool(summary["ready"])
    print(json.dumps(summary, indent=2))

    if os.environ.get("VERIFY_POST_029") == "1":
        absent_checks = asyncio.run(
            fetch_post_029_absent_column_state(args.supabase_url, args.service_key)
        )
        post_029_summary = summarize_post_029_checks(absent_checks)
        ready = ready and bool(post_029_summary["ready"])
        print(json.dumps({"post_029": post_029_summary}, indent=2))

    if args.verify_mcp_auth_requirements_uniqueness:
        uniqueness_checks = asyncio.run(
            fetch_mcp_auth_requirements_uniqueness_state(
                args.supabase_url,
                args.service_key,
            )
        )
        uniqueness_summary = summarize_mcp_auth_requirements_uniqueness_checks(uniqueness_checks)
        ready = ready and bool(uniqueness_summary["ready"])
        print(
            json.dumps(
                {"mcp_auth_requirements_uniqueness": uniqueness_summary},
                indent=2,
            )
        )
    if not ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
