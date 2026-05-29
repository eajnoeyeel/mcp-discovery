"""HTTP MCP metadata discovery service."""

from __future__ import annotations

from typing import Any

import httpx

from service.services.contracts import DiscoveredTool, MetadataDiscoveryResponse, UpstreamAuthConfig
from service.services.parameter_metadata import extract_parameter_metadata
from service.services.upstream_auth import build_upstream_headers


class MetadataDiscoveryService:
    """Fetch and normalize upstream MCP tool metadata via ``tools/list``."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._timeout = timeout

    async def discover(
        self,
        *,
        url: str,
        auth: UpstreamAuthConfig,
    ) -> MetadataDiscoveryResponse:
        payload = await self._call_tools_list(url, auth)
        tools: list[DiscoveredTool] = []

        for item in payload.get("tools", []):
            tool_name = item.get("name") or item.get("tool_name")
            if not tool_name:
                continue
            raw_schema = item.get("inputSchema", item.get("input_schema"))
            tools.append(
                DiscoveredTool(
                    tool_name=tool_name,
                    upstream_description=item.get("description")
                    or item.get("upstream_description")
                    or "",
                    input_schema=raw_schema,
                    parameter_metadata=extract_parameter_metadata(raw_schema),
                )
            )

        return MetadataDiscoveryResponse(url=url, tools=tools)

    async def _call_tools_list(self, url: str, auth: UpstreamAuthConfig) -> dict[str, Any]:
        headers = build_upstream_headers(auth) or {}
        headers.setdefault("Accept", "application/json, text/event-stream")
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url.rstrip("/"), json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()

        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            message = body["error"].get("message") or "Unknown upstream MCP error"
            raise RuntimeError(f"tools/list failed: {message}")

        result = body.get("result") if isinstance(body, dict) else None
        if isinstance(result, dict):
            return result
        if isinstance(body, dict):
            return body
        raise RuntimeError("tools/list returned an invalid response payload")
