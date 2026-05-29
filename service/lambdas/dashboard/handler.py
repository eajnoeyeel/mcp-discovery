"""Dashboard Lambda thin adapter for provider-scoped read APIs."""

from __future__ import annotations

import json as _json
import os
from typing import Any
from urllib.parse import unquote

import httpx
from loguru import logger

from service.adapters.supabase_auth import SupabaseAuthClient
from service.adapters.supabase_client import SupabaseClient
from service.services.dashboard_service import DashboardService
from service.services.insight_service import InsightService
from service.services.provider_service import ProviderService
from service.shared.http import error_response, json_response

_repo = SupabaseClient(
    url=os.environ.get("SUPABASE_URL", ""),
    service_key=os.environ.get("SUPABASE_SERVICE_KEY", ""),
)
dashboard_service = DashboardService(repo=_repo)
provider_service = ProviderService(repo=_repo)
insight_service = InsightService()
auth_client = SupabaseAuthClient(
    url=os.environ.get("SUPABASE_URL", ""),
    service_key=os.environ.get("SUPABASE_SERVICE_KEY", ""),
)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    from service.shared.event_loop import get_or_create_loop

    loop = get_or_create_loop()
    return loop.run_until_complete(_async_handler(event, context))


def _request_path(event: dict[str, Any]) -> str:
    request_context = event.get("requestContext", {})
    http_context = request_context.get("http", {})
    raw = event.get("rawPath") or http_context.get("path") or event.get("path") or ""
    stage = request_context.get("stage", "")
    if stage and stage != "$default" and raw.startswith(f"/{stage}"):
        raw = raw[len(f"/{stage}") :]
    return raw


def _extract_bearer_token(headers: dict[str, Any]) -> str | None:
    authorization = headers.get("authorization") or headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


async def _async_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    request_method = event.get("requestContext", {}).get("http", {}).get("method") or "GET"
    if request_method not in ("GET", "PUT", "POST"):
        return error_response(405, "Method not allowed")

    token = _extract_bearer_token(event.get("headers") or {})
    if token is None:
        return error_response(401, "Missing bearer token")

    try:
        user = await auth_client.get_user(token)
    except httpx.HTTPStatusError:
        return error_response(401, "Invalid bearer token")

    user_id = user["id"]
    path = _request_path(event)
    path_params = event.get("pathParameters") or {}

    # Resolve provider (creates on first visit)
    provider = await provider_service.get_or_create_provider(user_id)
    provider_id = provider["id"]

    try:
        # Provider profile routes
        if path == "/api/providers/profile":
            if request_method == "PUT":
                body = event.get("body")
                if isinstance(body, str):
                    body = _json.loads(body)
                updated = await provider_service.update_provider(user_id, body or {})
                return json_response(200, updated)
            return json_response(200, provider)

        # Dashboard overview
        if path == "/api/providers/dashboard":
            return json_response(
                200,
                await dashboard_service.get_provider_dashboard(provider_id, owner_user_id=user_id),
            )

        tool_id_param = path_params.get("tool_id")
        if tool_id_param:
            decoded_tool_id = unquote(tool_id_param)
            body = event.get("body")
            if isinstance(body, str):
                body = _json.loads(body or "{}")
            body = body or {}

            if request_method == "POST" and path.endswith("/metadata-refresh-preview"):
                preview = await dashboard_service.preview_provider_tool_refresh(
                    decoded_tool_id,
                    owner_user_id=user_id,
                    provider_id=provider_id,
                    payload=body,
                )
                return json_response(200, preview)

            if request_method == "POST" and path.endswith("/metadata-refresh-apply"):
                applied = await dashboard_service.apply_provider_tool_refresh(
                    decoded_tool_id,
                    owner_user_id=user_id,
                    provider_id=provider_id,
                    payload=body,
                )
                return json_response(200, applied)

            if request_method == "PUT" and not path.endswith(("/analytics", "/insights")):
                updated = await dashboard_service.update_provider_tool_metadata(
                    decoded_tool_id,
                    owner_user_id=user_id,
                    provider_id=provider_id,
                    payload=body,
                )
                return json_response(200, updated)

            # Insights route: /api/providers/tools/{tool_id}/insights
            if path.endswith("/insights"):
                detail = await dashboard_service.get_provider_tool_detail(
                    decoded_tool_id,
                    owner_user_id=user_id,
                    provider_id=provider_id,
                )
                tool_data = detail["tool"]
                try:
                    insights = await insight_service.get_tool_insights(tool_data, tool_data)
                except Exception as exc:
                    logger.warning(f"Insights unavailable: {exc}")
                    insights = []
                return json_response(200, {"tool_id": decoded_tool_id, "insights": insights})

            # Analytics route: /api/providers/tools/{tool_id}/analytics
            if path.endswith("/analytics"):
                analytics = await dashboard_service.get_tool_analytics(
                    decoded_tool_id,
                    owner_user_id=user_id,
                    provider_id=provider_id,
                )
                return json_response(200, analytics)

            # Tool detail route: /api/providers/tools/{tool_id}
            return json_response(
                200,
                await dashboard_service.get_provider_tool_detail(
                    decoded_tool_id,
                    owner_user_id=user_id,
                    provider_id=provider_id,
                ),
            )
    except LookupError as exc:
        return error_response(404, str(exc))
    except ValueError as exc:
        return error_response(400, str(exc))
    except RuntimeError as exc:
        return error_response(400, str(exc))
    except httpx.HTTPError:
        return error_response(502, "Failed to refresh provider metadata")

    return error_response(404, "Route not found")
