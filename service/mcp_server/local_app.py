"""Dev-only HTTP MCP app wrapping the bridge Lambda handler.

This is the compose/dev counterpart to the deployed bridge Lambda.
It exposes `/mcp` over HTTP so nginx and local CLI clients can talk to
the same bridge logic used by `service/lambdas/bridge/handler.py`.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from loguru import logger

from service.adapters.supabase_auth import SupabaseAuthClient

_BACKEND_URL = os.environ.get("MLP_BACKEND_URL", "http://backend:3000").rstrip("/")
_API_KEY = os.environ.get("MLP_API_KEY", "")
_MCP_BASE_URL = os.environ.get("MLP_MCP_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
_FRONTEND_URL = os.environ.get("MLP_FRONTEND_URL", "http://127.0.0.1:3001").rstrip("/")
_AUTH_CODES: dict[str, str] = {}

_LOCAL_MCP_SEARCH_TIMEOUT_DEFAULT_SECONDS = 20.0
_LOCAL_MCP_DOWNSTREAM_EXECUTE_BUDGET_SECONDS = 30.0
_LOCAL_MCP_EXECUTE_TIMEOUT_MIN_SECONDS = _LOCAL_MCP_DOWNSTREAM_EXECUTE_BUDGET_SECONDS + 1.0
_LOCAL_MCP_EXECUTE_TIMEOUT_DEFAULT_SECONDS = _LOCAL_MCP_DOWNSTREAM_EXECUTE_BUDGET_SECONDS + 5.0


def _read_timeout_seconds(name: str, *, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        value = float(raw_value)
    except ValueError:
        logger.warning(f"Invalid {name}={raw_value!r}; using default {default}s")
        return default
    if value <= 0:
        logger.warning(f"Non-positive {name}={raw_value!r}; using default {default}s")
        return default
    return value


_LOCAL_MCP_SEARCH_TIMEOUT_SECONDS = _read_timeout_seconds(
    "MLP_MCP_LOCAL_SEARCH_TIMEOUT_SECONDS",
    default=_LOCAL_MCP_SEARCH_TIMEOUT_DEFAULT_SECONDS,
)
_LOCAL_MCP_EXECUTE_TIMEOUT_SECONDS = max(
    _read_timeout_seconds(
        "MLP_MCP_LOCAL_EXECUTE_TIMEOUT_SECONDS",
        default=_LOCAL_MCP_EXECUTE_TIMEOUT_DEFAULT_SECONDS,
    ),
    _LOCAL_MCP_EXECUTE_TIMEOUT_MIN_SECONDS,
)


def _build_event(*, headers: dict[str, str], body: bytes) -> dict[str, Any]:
    """Build a minimal API Gateway v2 event for the bridge handler."""
    return {
        "version": "2.0",
        "rawPath": "/mcp",
        "requestContext": {
            "http": {
                "method": "POST",
                "path": "/mcp",
            },
            "requestId": "local-mcp-dev",
        },
        "headers": headers,
        "queryStringParameters": None,
        "pathParameters": None,
        "body": body.decode("utf-8") if body else None,
        "isBase64Encoded": False,
    }


def _extract_bearer_token(headers: dict[str, str]) -> str | None:
    authorization = headers.get("authorization") or headers.get("Authorization") or ""
    if not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


async def _resolve_mcp_user(headers: dict[str, str]) -> tuple[str | None, JSONResponse | None]:
    token = _extract_bearer_token(headers)
    if token is None:
        return None, JSONResponse(status_code=401, content={"error": "Missing bearer token"})

    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not supabase_url or not supabase_key:
        return None, JSONResponse(
            status_code=503,
            content={"error": "Supabase validation unavailable"},
        )

    auth_client = SupabaseAuthClient(url=supabase_url, service_key=supabase_key)
    try:
        user = await auth_client.get_user(token)
    except httpx.HTTPStatusError:
        return None, JSONResponse(status_code=401, content={"error": "Invalid bearer token"})
    except httpx.HTTPError:
        return None, JSONResponse(
            status_code=503,
            content={"error": "Supabase validation unavailable"},
        )

    user_id = str(user.get("id") or "").strip()
    if not user_id:
        return None, JSONResponse(status_code=401, content={"error": "Invalid bearer token"})
    return user_id, None


def _extract_auth_forward_headers(headers: dict[str, str]) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in {"authorization", "x-authorization"}:
            forwarded["Authorization"] = value
        elif lowered.startswith("mcp-authorization"):
            forwarded["Authorization"] = value
    return forwarded


def _jsonrpc_ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _execution_failed_payload(error: str, *, status_code: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "execution_failed", "error": error}
    if status_code is not None:
        payload["status_code"] = status_code
    return payload


async def _mock_async_handler(event: dict[str, Any]) -> dict[str, Any]:
    """Lightweight local MCP handler used by compose smoke runs."""
    body = json.loads(event.get("body") or "{}")
    method = body.get("method", "")
    req_id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mcp-discovery-bridge-local", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "find_best_tool",
                    "description": "Find the best MCP tool for a given natural language query.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer", "default": 3},
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "execute_tool",
                    "description": "Execute an MCP tool by tool_id.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "tool_id": {"type": "string"},
                            "params": {"type": "object", "default": {}},
                            "query_log_id": {"type": ["integer", "null"]},
                        },
                        "required": ["tool_id"],
                    },
                },
            ]
        }
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "find_best_tool":
            async with httpx.AsyncClient(timeout=_LOCAL_MCP_SEARCH_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{_BACKEND_URL}/api/search",
                    headers={
                        "x-api-key": _API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": args.get("query", ""),
                        "top_k": int(args.get("top_k", 3)),
                    },
                )
                response.raise_for_status()
                search_payload = response.json()
                if search_payload.get("query_log_id") is None:
                    search_payload["query_log_id"] = int(time.time() * 1000)
                result = {
                    "content": [{"type": "text", "text": json.dumps(search_payload)}],
                }
        elif name == "execute_tool":
            backend_headers = {
                "x-api-key": _API_KEY,
                "Content-Type": "application/json",
            }
            query_log_id = args.get("query_log_id")
            if query_log_id is not None:
                try:
                    query_log_id = int(query_log_id)
                except (TypeError, ValueError):
                    return {
                        "statusCode": 200,
                        "headers": {
                            "Content-Type": "application/json",
                            "MCP-Version": "2025-03-26",
                        },
                        "body": json.dumps(
                            _jsonrpc_error(req_id, -32602, "query_log_id must be an integer")
                        ),
                    }
            backend_headers.update(_extract_auth_forward_headers(event.get("headers") or {}))
            try:
                async with httpx.AsyncClient(timeout=_LOCAL_MCP_EXECUTE_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{_BACKEND_URL}/api/execute",
                        headers=backend_headers,
                        json={
                            "tool_id": args.get("tool_id", ""),
                            "params": args.get("params") or {},
                            "query_log_id": query_log_id,
                        },
                    )
            except httpx.TimeoutException:
                logger.warning(
                    "local MCP mock backend execute timed out "
                    f"tool_id={args.get('tool_id', '')} "
                    f"timeout_seconds={_LOCAL_MCP_EXECUTE_TIMEOUT_SECONDS}"
                )
                payload = _execution_failed_payload(
                    "Backend execute timed out",
                    status_code=504,
                )
            else:
                if response.status_code == 401:
                    payload = _execution_failed_payload(
                        "Missing or invalid MCP user bearer token for backend execute"
                    )
                else:
                    try:
                        payload = response.json()
                    except json.JSONDecodeError:
                        payload = _execution_failed_payload(
                            "Backend returned non-JSON response",
                            status_code=response.status_code,
                        )
            result = {
                "content": [{"type": "text", "text": json.dumps(payload)}],
            }
        else:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json", "MCP-Version": "2025-03-26"},
                "body": json.dumps(_jsonrpc_error(req_id, -32601, f"Unknown tool: {name}")),
            }
    else:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", "MCP-Version": "2025-03-26"},
            "body": json.dumps(_jsonrpc_error(req_id, -32601, f"Method not found: {method}")),
        }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json", "MCP-Version": "2025-03-26"},
        "body": json.dumps(_jsonrpc_ok(req_id, result)),
    }


if os.getenv("MLP_MCP_LOCAL_MOCK") == "1":
    _async_handler = _mock_async_handler
else:
    from service.lambdas.bridge.handler import _async_handler


def _lambda_response(result: dict[str, Any]) -> Response:
    """Convert a Lambda-style response into a FastAPI response."""
    status_code = result.get("statusCode", 200)
    headers = result.get("headers") or {}
    raw_body = result.get("body")

    if raw_body is None or raw_body == "":
        return Response(status_code=status_code, headers=headers)

    try:
        content = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
    except json.JSONDecodeError:
        content = {"raw": raw_body}

    return JSONResponse(status_code=status_code, content=content, headers=headers)


def create_app() -> FastAPI:
    app = FastAPI(title="MLP MCP Discovery Bridge (local dev)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3001", "http://localhost:3001"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/.well-known/oauth-authorization-server")
    @app.get("/.well-known/oauth-authorization-server/mcp")
    @app.get("/mcp/.well-known/oauth-authorization-server")
    async def oauth_metadata() -> Response:
        return JSONResponse(
            status_code=200,
            content={
                "issuer": _MCP_BASE_URL,
                "authorization_endpoint": f"{_MCP_BASE_URL}/oauth/authorize",
                "token_endpoint": f"{_MCP_BASE_URL}/oauth/token",
                "registration_endpoint": f"{_MCP_BASE_URL}/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
            },
        )

    @app.get("/.well-known/oauth-protected-resource")
    @app.get("/.well-known/oauth-protected-resource/mcp")
    async def protected_resource_metadata() -> Response:
        return JSONResponse(
            status_code=200,
            content={
                "resource": f"{_MCP_BASE_URL}/mcp",
                "authorization_servers": [_MCP_BASE_URL],
            },
        )

    @app.get("/oauth/authorize")
    async def oauth_authorize(redirect_uri: str, state: str) -> Response:
        callback_url = (
            f"/oauth/complete?redirect_uri={quote(redirect_uri, safe='')}"
            f"&state={quote(state, safe='')}"
        )
        return RedirectResponse(
            url=f"{_FRONTEND_URL}/login?redirect={quote(callback_url, safe='')}",
            status_code=302,
        )

    @app.post("/oauth/issue-code")
    async def oauth_issue_code(request: Request) -> JSONResponse:
        headers = dict(request.headers)
        access_token = _extract_bearer_token(headers)
        if access_token is None:
            return JSONResponse(status_code=401, content={"error": "Missing bearer token"})

        _user_id, error_response = await _resolve_mcp_user(headers)
        if error_response is not None:
            return error_response

        code = f"local-dev-code-{int(time.time() * 1000)}"
        _AUTH_CODES[code] = access_token
        return JSONResponse(status_code=200, content={"code": code})

    @app.post("/oauth/register")
    async def oauth_register(request: Request) -> JSONResponse:
        payload = await request.json()
        redirect_uris = payload.get("redirect_uris") or []
        client_name = payload.get("client_name") or "Claude"
        grant_types = payload.get("grant_types") or ["authorization_code"]
        response_types = payload.get("response_types") or ["code"]
        token_endpoint_auth_method = payload.get("token_endpoint_auth_method") or "none"
        return JSONResponse(
            status_code=201,
            content={
                "client_id": "local-dev-claude-client",
                "client_id_issued_at": int(time.time()),
                "client_name": client_name,
                "redirect_uris": redirect_uris,
                "grant_types": grant_types,
                "response_types": response_types,
                "token_endpoint_auth_method": token_endpoint_auth_method,
            },
        )

    @app.post("/oauth/token")
    async def oauth_token(request: Request) -> JSONResponse:
        form = await request.form()
        code = str(form.get("code") or "").strip()
        if code and code in _AUTH_CODES:
            access_token = _AUTH_CODES.pop(code)
        elif code:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_grant",
                    "error_description": "Unknown authorization code",
                },
            )
        else:
            access_token = "local-dev-access-token"
        return JSONResponse(
            status_code=200,
            content={
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    @app.get("/mcp")
    async def get_mcp() -> JSONResponse:
        return JSONResponse(
            status_code=405,
            content={"error": "Method Not Allowed. Use POST."},
        )

    @app.post("/mcp")
    async def post_mcp(request: Request) -> Response:
        headers = dict(request.headers)
        user_id, error_response = await _resolve_mcp_user(headers)
        if error_response is not None:
            return error_response

        body = await request.body()
        if not body:
            return Response(status_code=204)

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"error": "invalid json"})

        # Client notifications do not expect a response body.
        if payload.get("id") is None:
            return Response(status_code=204)

        logger.info(f"local POST /mcp method={payload.get('method')}")
        event = _build_event(headers=headers, body=body)
        event["requestContext"]["authorizer"] = {"lambda": {"user_id": user_id}}
        result = await _async_handler(event)
        return _lambda_response(result)

    return app


app = create_app()
