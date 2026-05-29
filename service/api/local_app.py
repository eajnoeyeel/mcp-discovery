"""Dev-only FastAPI adapter that wraps Lambda handlers as local HTTP routes.

This shim replicates the API Gateway v2 → Lambda → response cycle locally.
It is NOT for production use.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:
    from loguru import logger
except ModuleNotFoundError:  # pragma: no cover - local dev/test fallback
    logger = logging.getLogger(__name__)

from service.adapters.eventbridge_client import EventBridgeClient
from service.adapters.execution import AuthRequirementLookupError, SupabaseToolRegistry
from service.adapters.supabase_auth import SupabaseAuthClient
from service.lambdas.oauth_start.handler import _async_handler as oauth_start_handler
from service.local_runtime.eventbridge_relay import LocalEventBridgeRelay
from service.services.auth_probe import build_auth_probe_result

_EXPECTED_API_KEY: str = os.environ.get("MLP_API_KEY", "")
_LEGACY_HOSTED_CONNECT_REQUIRED_SCOPES = ["full_api_access"]


def _check_api_key(headers: dict[str, str]) -> bool:
    """Replicate authorizer logic: validate x-api-key header."""
    if not _EXPECTED_API_KEY:
        # Dev fallback: if no key configured, allow all requests locally.
        return True
    provided = headers.get("x-api-key", "")
    return provided == _EXPECTED_API_KEY


def _extract_bearer_token(headers: dict[str, str] | None) -> str | None:
    headers = headers or {}
    authorization = headers.get("authorization") or headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


def _build_event(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    query_params: dict[str, str],
    body: bytes,
    path_parameters: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a minimal API Gateway v2 (HTTP) event dict."""
    return {
        "version": "2.0",
        "rawPath": path,
        "requestContext": {
            "http": {
                "method": method.upper(),
                "path": path,
            },
            "requestId": "local-dev",
        },
        "headers": headers,
        "queryStringParameters": query_params or None,
        "pathParameters": path_parameters or None,
        "body": body.decode("utf-8") if body else None,
        "isBase64Encoded": False,
    }


def _lambda_response(result: dict[str, Any]) -> JSONResponse:
    """Convert a Lambda response dict to a FastAPI JSONResponse."""
    status_code: int = result.get("statusCode", 200)
    raw_body = result.get("body", "{}")
    try:
        content = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
    except json.JSONDecodeError:
        content = {"raw": raw_body}
    return JSONResponse(status_code=status_code, content=content)


def _normalize_required_scopes(scopes: Any) -> list[str]:
    if not isinstance(scopes, list):
        return []

    normalized: list[str] = []
    for scope in scopes:
        scope_value = str(scope).strip()
        if scope_value and scope_value not in normalized:
            normalized.append(scope_value)
    return normalized


async def _resolve_hosted_connect_auth_requirement(
    *, tool_id: str, fallback_provider: str
) -> tuple[str, list[str]]:
    try:
        contract = await SupabaseToolRegistry().fetch_tool_contract(tool_id)
    except AuthRequirementLookupError:
        raise
    except Exception as exc:  # pragma: no cover - defensive fail-closed path
        logger.warning(
            "local hosted connect failed to load auth requirement "
            f"tool_id={tool_id} fallback_provider={fallback_provider} error={exc}"
        )
        raise AuthRequirementLookupError(
            "Failed to load delegated auth metadata for hosted connect"
        ) from exc

    auth_requirement = getattr(contract, "auth_requirement", None)
    if auth_requirement is None:
        return fallback_provider, list(_LEGACY_HOSTED_CONNECT_REQUIRED_SCOPES)

    provider = str(getattr(auth_requirement, "provider", "") or "").strip() or fallback_provider
    required_scopes = _normalize_required_scopes(
        getattr(auth_requirement, "required_scopes", None)
    )
    return provider, required_scopes


@asynccontextmanager
async def _lifespan(app: FastAPI):
    relay = None
    register_handler = None

    if os.environ.get("MLP_EVENT_MODE", "local_direct") == "local_direct":
        from service.lambdas.index.handler import _async_handler as index_handler  # noqa: PLC0415
        from service.lambdas.register import handler as register_handler  # noqa: PLC0415

        relay = LocalEventBridgeRelay(index_handler=index_handler)
        await relay.start()
        app.state.eventbridge_relay = relay
        app.state.eventbridge_client = EventBridgeClient(publisher=relay)
        register_handler.set_eventbridge_client_for_local_runtime(app.state.eventbridge_client)

    try:
        yield
    finally:
        if register_handler is not None:
            register_handler.set_eventbridge_client_for_local_runtime(None)
        if relay is not None:
            await relay.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="MCP Discovery Backend API (local dev)", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ health

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # ------------------------------------------------------------------ search

    @app.post("/api/search")
    async def search(request: Request) -> JSONResponse:
        from service.lambdas.search.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = await request.body()
        query_params = dict(request.query_params)
        event = _build_event(
            method="POST",
            path="/api/search",
            headers=headers,
            query_params=query_params,
            body=body,
        )
        logger.info("local POST /api/search")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    # ------------------------------------------------------------------ catalog

    @app.get("/api/platform/stats")
    async def platform_stats(request: Request) -> JSONResponse:
        from service.lambdas.catalog.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        event = _build_event(
            method="GET",
            path="/api/platform/stats",
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
        )
        logger.info("local GET /api/platform/stats")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.get("/api/servers")
    async def list_servers(request: Request) -> JSONResponse:
        from service.lambdas.catalog.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        event = _build_event(
            method="GET",
            path="/api/servers",
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
        )
        logger.info("local GET /api/servers")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.get("/api/servers/{server_id}")
    async def get_server(server_id: str, request: Request) -> JSONResponse:
        from service.lambdas.catalog.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        path = f"/api/servers/{server_id}"
        event = _build_event(
            method="GET",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
            path_parameters={"server_id": server_id},
        )
        logger.info(f"local GET {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.get("/api/servers/{server_id}/tools")
    async def get_server_tools(server_id: str, request: Request) -> JSONResponse:
        from service.lambdas.catalog.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        path = f"/api/servers/{server_id}/tools"
        event = _build_event(
            method="GET",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
            path_parameters={"server_id": server_id},
        )
        logger.info(f"local GET {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.get("/api/tools/{tool_id:path}")
    async def get_tool(tool_id: str, request: Request) -> JSONResponse:
        from service.lambdas.catalog.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        path = f"/api/tools/{tool_id}"
        event = _build_event(
            method="GET",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
            path_parameters={"tool_id": tool_id},
        )
        logger.info(f"local GET {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.get("/api/servers/{server_id}/quality")
    async def get_server_quality(server_id: str, request: Request) -> JSONResponse:
        from service.lambdas.catalog.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        path = f"/api/servers/{server_id}/quality"
        event = _build_event(
            method="GET",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
            path_parameters={"server_id": server_id},
        )
        logger.info(f"local GET {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    # ---------------------------------------------------------------- dashboard

    @app.get("/api/providers/dashboard")
    async def provider_dashboard(request: Request) -> JSONResponse:
        from service.lambdas.dashboard.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        event = _build_event(
            method="GET",
            path="/api/providers/dashboard",
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
        )
        logger.info("local GET /api/providers/dashboard")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.get("/api/providers/profile")
    async def get_provider_profile(request: Request) -> JSONResponse:
        from service.lambdas.dashboard.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        event = _build_event(
            method="GET",
            path="/api/providers/profile",
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
        )
        logger.info("local GET /api/providers/profile")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.put("/api/providers/profile")
    async def put_provider_profile(request: Request) -> JSONResponse:
        from service.lambdas.dashboard.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = await request.body()
        event = _build_event(
            method="PUT",
            path="/api/providers/profile",
            headers=headers,
            query_params=dict(request.query_params),
            body=body,
        )
        logger.info("local PUT /api/providers/profile")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.get("/api/providers/tools/{tool_id:path}/analytics")
    async def get_tool_analytics(tool_id: str, request: Request) -> JSONResponse:
        from service.lambdas.dashboard.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        path = f"/api/providers/tools/{tool_id}/analytics"
        event = _build_event(
            method="GET",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
            path_parameters={"tool_id": tool_id},
        )
        logger.info(f"local GET {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.get("/api/providers/tools/{tool_id:path}/insights")
    async def get_tool_insights(tool_id: str, request: Request) -> JSONResponse:
        from service.lambdas.dashboard.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        path = f"/api/providers/tools/{tool_id}/insights"
        event = _build_event(
            method="GET",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
            path_parameters={"tool_id": tool_id},
        )
        logger.info(f"local GET {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.get("/api/providers/tools/{tool_id:path}")
    async def get_provider_tool(tool_id: str, request: Request) -> JSONResponse:
        from service.lambdas.dashboard.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        path = f"/api/providers/tools/{tool_id}"
        event = _build_event(
            method="GET",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
            path_parameters={"tool_id": tool_id},
        )
        logger.info(f"local GET {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.put("/api/providers/tools/{tool_id:path}")
    async def put_provider_tool(tool_id: str, request: Request) -> JSONResponse:
        from service.lambdas.dashboard.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = await request.body()
        path = f"/api/providers/tools/{tool_id}"
        event = _build_event(
            method="PUT",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=body,
            path_parameters={"tool_id": tool_id},
        )
        logger.info(f"local PUT {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.post("/api/providers/tools/{tool_id:path}/metadata-refresh-preview")
    async def preview_provider_tool_refresh(tool_id: str, request: Request) -> JSONResponse:
        from service.lambdas.dashboard.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = await request.body()
        path = f"/api/providers/tools/{tool_id}/metadata-refresh-preview"
        event = _build_event(
            method="POST",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=body,
            path_parameters={"tool_id": tool_id},
        )
        logger.info(f"local POST {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.post("/api/providers/tools/{tool_id:path}/metadata-refresh-apply")
    async def apply_provider_tool_refresh(tool_id: str, request: Request) -> JSONResponse:
        from service.lambdas.dashboard.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = await request.body()
        path = f"/api/providers/tools/{tool_id}/metadata-refresh-apply"
        event = _build_event(
            method="POST",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=body,
            path_parameters={"tool_id": tool_id},
        )
        logger.info(f"local POST {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    # ---------------------------------------------------------------- register

    @app.post("/api/providers/servers/discovery")
    async def register_server_discovery(request: Request) -> JSONResponse:
        from service.lambdas.register.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = await request.body()
        event = _build_event(
            method="POST",
            path="/api/providers/servers/discovery",
            headers=headers,
            query_params=dict(request.query_params),
            body=body,
        )
        logger.info("local POST /api/providers/servers/discovery")
        result = await _async_handler(event, None)
        return _lambda_response(result)


    async def _forward_register_post(request: Request, path: str) -> JSONResponse:
        from service.lambdas.register.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = await request.body()
        event = _build_event(
            method="POST",
            path=path,
            headers=headers,
            query_params=dict(request.query_params),
            body=body,
        )
        logger.info(f"local POST {path}")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.post("/api/oauth/providers/bootstrap/discover")
    async def oauth_provider_bootstrap_discover(request: Request) -> JSONResponse:
        return await _forward_register_post(request, "/api/oauth/providers/bootstrap/discover")

    @app.post("/api/oauth/providers/bootstrap/dcr")
    async def oauth_provider_bootstrap_dcr(request: Request) -> JSONResponse:
        return await _forward_register_post(request, "/api/oauth/providers/bootstrap/dcr")

    @app.post("/api/oauth/providers/bootstrap/manual")
    async def oauth_provider_bootstrap_manual(request: Request) -> JSONResponse:
        return await _forward_register_post(request, "/api/oauth/providers/bootstrap/manual")

    @app.post("/api/oauth/providers/{provider_key}/enable")
    async def oauth_provider_bootstrap_enable(provider_key: str, request: Request) -> JSONResponse:
        return await _forward_register_post(request, f"/api/oauth/providers/{provider_key}/enable")

    @app.post("/api/providers/connect/discover")
    async def provider_connect_discover(request: Request) -> JSONResponse:
        """Local no-auth shortcut for the hosted-connect discovery handshake."""
        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = json.loads((await request.body()).decode("utf-8") or "{}")
        server_id = str(body.get("server_id") or "").strip()
        url = str(body.get("url") or "").strip()
        if not server_id or not url:
            return JSONResponse(
                status_code=400,
                content={"error": "server_id and url are required"},
            )

        return JSONResponse(
            status_code=200,
            content={
                "connect_session_id": f"local-{server_id}",
                "provider_user_id": "local-provider",
                "server_id": server_id,
                "url": url,
                "auth_type": "none",
                "status": "connected",
            },
        )

    @app.post("/api/servers")
    async def register_server(request: Request) -> JSONResponse:
        from service.lambdas.register.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = await request.body()
        event = _build_event(
            method="POST",
            path="/api/servers",
            headers=headers,
            query_params=dict(request.query_params),
            body=body,
        )
        logger.info("local POST /api/servers (register)")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    # ----------------------------------------------------------------- execute

    @app.post("/api/execute")
    async def execute_tool(request: Request) -> JSONResponse:
        from service.lambdas.execute.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = await request.body()
        try:
            preview = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            preview = {"_raw": body.decode("utf-8", errors="ignore")[:200]}
        param_keys = (
            sorted((preview.get("params") or {}).keys())
            if isinstance(preview.get("params"), dict)
            else "<non-dict>"
        )
        event = _build_event(
            method="POST",
            path="/api/execute",
            headers=headers,
            query_params=dict(request.query_params),
            body=body,
        )
        logger.info(
            "local POST /api/execute "
            f"tool_id={preview.get('tool_id')} "
            f"query_log_id={preview.get('query_log_id')} "
            f"param_keys={param_keys}"
        )
        # execute handler takes only one param (no context)
        result = await _async_handler(event)
        logger.info(
            "local POST /api/execute result "
            f"statusCode={result.get('statusCode')} body={str(result.get('body'))[:300]}"
        )
        return _lambda_response(result)

    @app.post("/api/auth/probe")
    async def auth_probe(request: Request) -> JSONResponse:
        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        token = _extract_bearer_token(headers)
        if token is None:
            return JSONResponse(status_code=401, content={"error": "Missing bearer token"})

        supabase_url = os.environ.get("SUPABASE_URL", "")
        supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not supabase_url or not supabase_key:
            return JSONResponse(
                status_code=503,
                content=build_auth_probe_result(
                    user_id=None,
                    auth_source="supabase_bearer",
                    issuer=None,
                    status="validation_unavailable",
                    error="supabase_validation_unavailable",
                ),
            )

        auth_client = SupabaseAuthClient(
            url=supabase_url,
            service_key=supabase_key,
        )
        try:
            user = await auth_client.get_user(token)
        except httpx.HTTPStatusError:
            return JSONResponse(status_code=401, content={"error": "Invalid bearer token"})
        except httpx.HTTPError:
            return JSONResponse(
                status_code=503,
                content=build_auth_probe_result(
                    user_id=None,
                    auth_source="supabase_bearer",
                    issuer=None,
                    status="validation_unavailable",
                    error="supabase_validation_unavailable",
                ),
            )

        user_id = user.get("id")
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Invalid bearer token"})

        return JSONResponse(
            status_code=200,
            content=build_auth_probe_result(
                user_id=user_id,
                auth_source="supabase_bearer",
                issuer="supabase",
            ),
        )

    @app.post("/api/client-connections/session")
    async def create_client_connect_session(request: Request) -> JSONResponse:
        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        token = _extract_bearer_token(headers)
        if token is None:
            return JSONResponse(status_code=401, content={"error": "Missing bearer token"})

        supabase_url = os.environ.get("SUPABASE_URL", "")
        supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not supabase_url or not supabase_key:
            return JSONResponse(
                status_code=503,
                content={"error": "Supabase validation unavailable"},
            )

        auth_client = SupabaseAuthClient(url=supabase_url, service_key=supabase_key)
        try:
            user = await auth_client.get_user(token)
        except httpx.HTTPStatusError:
            return JSONResponse(status_code=401, content={"error": "Invalid bearer token"})
        except httpx.HTTPError:
            return JSONResponse(
                status_code=503,
                content={"error": "Supabase validation unavailable"},
            )

        body = json.loads((await request.body()).decode("utf-8") or "{}")
        server_id = str(body.get("server_id") or "").strip()
        provider_key = str(body.get("provider_key") or "").strip() or None
        tool_name = str(body.get("tool_name") or "").strip() or None
        tool_id = str(body.get("tool_id") or "").strip() or None
        auth_type = str(body.get("auth_type") or "").strip() or "oauth"
        client_app_id = str(body.get("client_app_id") or "").strip() or None
        pending_execution_id = str(body.get("pending_execution_id") or "").strip() or None

        if not server_id:
            return JSONResponse(status_code=400, content={"error": "server_id is required"})
        if auth_type != "oauth":
            return JSONResponse(
                status_code=400,
                content={"error": "Only oauth hosted connect is supported"},
            )

        resolved_tool_id = tool_id or (
            f"{server_id}::{tool_name}" if tool_name else None
        )
        if not resolved_tool_id:
            return JSONResponse(
                status_code=400,
                content={"error": "tool_id or tool_name is required for oauth hosted connect"},
            )

        fallback_provider = provider_key or server_id.removesuffix("-oauth")
        try:
            resolved_provider, required_scopes = await _resolve_hosted_connect_auth_requirement(
                tool_id=resolved_tool_id,
                fallback_provider=fallback_provider,
            )
        except AuthRequirementLookupError:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Unable to resolve delegated auth metadata for hosted connect"
                },
            )

        oauth_start_event = _build_event(
            method="POST",
            path=f"/api/oauth/providers/{resolved_provider}/start",
            headers=headers,
            query_params={},
            body=json.dumps(
                {
                    "provider": resolved_provider,
                    "tool_id": resolved_tool_id,
                    "required_scopes": required_scopes,
                    "pending_execution_id": pending_execution_id,
                }
            ).encode("utf-8"),
            path_parameters={"provider": resolved_provider},
        )
        oauth_start_result = await oauth_start_handler(oauth_start_event, None)
        oauth_start_body = json.loads(oauth_start_result.get("body") or "{}")
        if oauth_start_result.get("statusCode") != 200:
            return JSONResponse(
                status_code=oauth_start_result.get("statusCode", 400),
                content=oauth_start_body,
            )

        connect_session_id = pending_execution_id or f"connect-{server_id}-{user['id']}"
        return JSONResponse(
            status_code=200,
            content={
                "connect_session_id": connect_session_id,
                "actor_type": "client",
                "end_user_id": user["id"],
                "client_app_id": client_app_id,
                "server_id": server_id,
                "tool_name": tool_name,
                "auth_type": "oauth",
                "status": "awaiting_user_approval",
                "scope": {
                    "reuse_scope": "client_app" if client_app_id else "user",
                    "client_app_id": client_app_id,
                },
                "start_url": oauth_start_body.get("oauth_url"),
            },
        )

    @app.post("/api/pending-executions/{resume_token}/resume")
    async def resume_pending_execution(resume_token: str, request: Request) -> JSONResponse:
        from service.lambdas.execute.handler import _get_execute_service  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        token = _extract_bearer_token(headers)
        if token is None:
            return JSONResponse(status_code=401, content={"error": "Missing bearer token"})

        supabase_url = os.environ.get("SUPABASE_URL", "")
        supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not supabase_url or not supabase_key:
            return JSONResponse(
                status_code=503,
                content={"error": "Supabase validation unavailable"},
            )

        auth_client = SupabaseAuthClient(url=supabase_url, service_key=supabase_key)
        try:
            user = await auth_client.get_user(token)
        except httpx.HTTPStatusError:
            return JSONResponse(status_code=401, content={"error": "Invalid bearer token"})
        except httpx.HTTPError:
            return JSONResponse(
                status_code=503,
                content={"error": "Supabase validation unavailable"},
            )

        user_id = user.get("id")
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Invalid bearer token"})

        response = await _get_execute_service().resume_pending_execution(
            resume_token,
            user_id=user_id,
        )
        if not response.success:
            return JSONResponse(status_code=400, content={"error": response.error})
        return JSONResponse(
            status_code=200,
            content={
                "status": "resumed",
                "tool_id": response.tool_id,
                "server_id": response.server_id,
                "result": response.result,
            },
        )

    # ----------------------------------------------------------- provider OAuth

    @app.post("/api/oauth/providers/{provider}/start")
    async def oauth_start(provider: str, request: Request) -> JSONResponse:
        from service.lambdas.oauth_start.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        if not _check_api_key(headers):
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        body = await request.body()
        event = _build_event(
            method="POST",
            path=f"/api/oauth/providers/{provider}/start",
            headers=headers,
            query_params=dict(request.query_params),
            body=body,
            path_parameters={"provider": provider},
        )
        logger.info(f"local POST /api/oauth/providers/{provider}/start")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    @app.get("/api/oauth/providers/{provider}/callback")
    async def oauth_callback(provider: str, request: Request) -> JSONResponse:
        from service.lambdas.oauth_callback.handler import _async_handler  # noqa: PLC0415

        headers = dict(request.headers)
        event = _build_event(
            method="GET",
            path=f"/api/oauth/providers/{provider}/callback",
            headers=headers,
            query_params=dict(request.query_params),
            body=b"",
            path_parameters={"provider": provider},
        )
        logger.info(f"local GET /api/oauth/providers/{provider}/callback")
        result = await _async_handler(event, None)
        return _lambda_response(result)

    return app


app = create_app()
