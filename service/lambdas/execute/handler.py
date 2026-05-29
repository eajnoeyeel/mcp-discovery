"""Execute Lambda — Proxy tool execution to hosted MCP servers.

MLP supports 3-5 pre-registered servers only.  This handler:
1. Parses the request body for tool_id + params
2. Delegates to ExecuteService for validation, proxy, and logging
3. Returns the result (or a structured error)

Supabase-backed ``ToolRegistry`` / ``ExecutionLogger`` implementations and
their helpers live in :mod:`service.adapters.execution` so the bridge
Lambda can reuse them without adding ``lambdas`` to
``MLP_RUNTIME_PACKAGES``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from loguru import logger

from mcp_discovery.config import Settings
from service.adapters import execution as _execution_adapters
from service.adapters.execution import (
    ALLOWED_EXECUTION_SERVERS,
    SupabaseExecutionLogger,
    SupabaseToolRegistry,
    _call_gateway,
    # Re-exports below are test-compat only. PR #65 moved these helpers from
    # service.lambdas.execute.handler to service.adapters.execution. Existing
    # TestExecuteHandler* tests access them as `self.m.<name>` where
    # `self.m = service.lambdas.execute.handler`; the re-export keeps that
    # attribute lookup working without rewriting ~25 test patches.
    _fetch_gateway_url,  # noqa: F401
    _fetch_server,  # noqa: F401
    _fetch_server_auth,  # noqa: F401
    _fetch_tool_schema,  # noqa: F401
    _is_missing_auth_table_error,  # noqa: F401
    _is_missing_gateway_routes_error,  # noqa: F401
    _log_execution,  # noqa: F401
)
from service.adapters.mcp_http_client import MCPHTTPClient
from service.adapters.supabase_auth import SupabaseAuthClient
from service.adapters.supabase_oauth_tokens import SupabaseOAuthTokenRepository
from service.services.execute_service import ExecuteService
from service.services.oauth_tokens import OAuthTokenService

# Global initialisation

settings = Settings()


# Service-layer singleton (lazy init)

_execute_service: ExecuteService | None = None


def _get_execute_service() -> ExecuteService:
    global _execute_service
    if _execute_service is None:
        oauth_token_service = None
        supabase_url = _execution_adapters._SUPABASE_URL
        supabase_key = _execution_adapters._SUPABASE_KEY
        if supabase_url and supabase_key:
            oauth_token_service = OAuthTokenService(
                repo=SupabaseOAuthTokenRepository(
                    url=supabase_url,
                    service_key=supabase_key,
                )
            )
        _execute_service = ExecuteService(
            registry=SupabaseToolRegistry(),
            mcp_client=MCPHTTPClient(timeout=25.0),
            execution_logger=SupabaseExecutionLogger(),
            allowed_servers=ALLOWED_EXECUTION_SERVERS or None,
            oauth_token_service=oauth_token_service,
            gateway_executor=_call_gateway,
        )
    return _execute_service


def _extract_bearer_token(headers: dict | None) -> str | None:
    headers = headers or {}
    authorization = headers.get("authorization") or headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


# Lambda handler


async def _async_handler(event: dict) -> dict[str, Any]:
    """Parse the API Gateway event and proxy execution."""
    raw_body = event.get("body", "{}")
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode()

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Invalid JSON in request body"}),
        }

    tool_id: str = body.get("tool_id", "")
    params: dict = body.get("params", {})
    query_log_id: int | None = body.get("query_log_id")
    if query_log_id is not None:
        try:
            query_log_id = int(query_log_id)
        except (TypeError, ValueError):
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "query_log_id must be an integer"}),
            }

    if not tool_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Missing required field: tool_id"}),
        }

    token = _extract_bearer_token(event.get("headers"))
    if token is None:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Missing bearer token"}),
        }

    auth_client = SupabaseAuthClient(
        url=_execution_adapters._SUPABASE_URL,
        service_key=_execution_adapters._SUPABASE_KEY,
    )
    try:
        user = await auth_client.get_user(token)
    except httpx.HTTPStatusError:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Invalid bearer token"}),
        }

    logger.info(
        "execute handler request "
        f"tool_id={tool_id} "
        f"user_id={user.get('id')} "
        f"query_log_id={query_log_id} "
        f"param_keys={sorted(params.keys()) if isinstance(params, dict) else '<non-dict>'}"
    )

    service = _get_execute_service()

    request_id = event.get("requestContext", {}).get("requestId") or uuid.uuid4().hex[:12]
    event_id = f"exec-{request_id}"

    try:
        response = await service.execute(
            tool_id,
            params,
            user_id=user["id"],
            event_id=event_id,
            query_log_id=query_log_id,
        )
    except ValueError as exc:
        logger.warning(f"execute handler validation error tool_id={tool_id}: {exc}")
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(exc)}),
        }

    if response.status == "auth_required" and response.auth is not None:
        logger.info(
            "execute handler auth_required "
            f"tool_id={response.tool_id} "
            f"server_id={response.server_id} "
            f"provider={response.auth.provider} "
            f"pending_execution_id={response.auth.pending_execution_id} "
            f"resume_token={response.auth.resume_token}"
        )
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "status": response.status,
                    "tool_id": response.tool_id,
                    "server_id": response.server_id,
                    "auth": response.auth.model_dump(),
                }
            ),
        }

    if not response.success:
        err_msg = response.error or ""
        logger.warning(
            "execute handler execution_failed "
            f"tool_id={response.tool_id} "
            f"server_id={response.server_id} "
            f"status={response.status} "
            f"error={err_msg}"
        )
        if "not found" in err_msg.lower():
            status = 404
        elif err_msg == "Failed to load tool contract":
            status = 503
        elif "not in the allowed" in err_msg:
            status = 400
        elif "timed out" in err_msg.lower():
            status = 504
        elif "Upstream error" in err_msg or "Upstream MCP error" in err_msg:
            status = 502
        else:
            status = 400
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": err_msg}),
        }

    logger.info(
        "execute handler success "
        f"tool_id={response.tool_id} "
        f"server_id={response.server_id} "
        f"latency_ms={response.latency_ms:.1f}"
    )
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response.result),
    }


def lambda_handler(event: dict, context: Any) -> dict:
    """AWS Lambda entry-point."""
    from service.shared.event_loop import get_or_create_loop

    loop = get_or_create_loop()
    return loop.run_until_complete(_async_handler(event))
