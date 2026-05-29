"""Catalog Lambda thin adapter for public frontend read APIs."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from service.adapters.supabase_client import SupabaseClient
from service.services.catalog_service import CatalogService
from service.shared.http import error_response, json_response

catalog_service = CatalogService(
    repo=SupabaseClient(
        url="http://localhost" if False else __import__("os").environ.get("SUPABASE_URL", ""),
        service_key=__import__("os").environ.get("SUPABASE_SERVICE_KEY", ""),
    )
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


async def _async_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    if (event.get("requestContext", {}).get("http", {}).get("method") or "GET") != "GET":
        return error_response(405, "Method not allowed")

    path = _request_path(event)
    path_params = event.get("pathParameters") or {}
    query = event.get("queryStringParameters") or {}

    try:
        if path == "/api/platform/stats":
            return json_response(200, await catalog_service.get_platform_stats())
        if path == "/api/servers":
            limit = int(query.get("limit", 50))
            offset = int(query.get("offset", 0))
            payload = await catalog_service.list_servers(limit=limit, offset=offset)
            return json_response(200, payload)
        if path.endswith("/tools") and path_params.get("server_id"):
            payload = await catalog_service.get_server_tools(path_params["server_id"])
            return json_response(200, payload)
        if path.endswith("/quality") and path_params.get("server_id"):
            payload = await catalog_service.get_server_quality(path_params["server_id"])
            return json_response(200, payload)
        if path_params.get("server_id"):
            payload = await catalog_service.get_server_detail(path_params["server_id"])
            return json_response(200, payload)
        if path.endswith("/stats") and path_params.get("tool_id"):
            stats = await catalog_service.get_tool_public_stats(unquote(path_params["tool_id"]))
            return json_response(200, {"stats": stats})
        if path_params.get("tool_id"):
            payload = await catalog_service.get_tool_detail(unquote(path_params["tool_id"]))
            return json_response(200, payload)
    except LookupError as exc:
        return error_response(404, str(exc))
    except ValueError as exc:
        return error_response(400, str(exc))

    return error_response(404, "Route not found")
