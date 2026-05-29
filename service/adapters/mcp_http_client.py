"""MCP HTTP client — proxies tools/call to hosted MCP servers via JSON-RPC 2.0."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from loguru import logger


class MCPHTTPClient:
    """Sends JSON-RPC 2.0 ``tools/call`` requests to hosted MCP servers.

    Parameters
    ----------
    timeout:
        HTTP timeout in seconds for the upstream call.
    """

    def __init__(self, *, timeout: float = 25.0) -> None:
        self._timeout = timeout

    async def call_tool(
        self,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Forward a ``tools/call`` request to the hosted MCP server.

        Returns the full JSON-RPC response body on success.

        Raises
        ------
        httpx.TimeoutException
            If the upstream server does not respond within the timeout.
        httpx.HTTPStatusError
            If the upstream server returns a non-2xx status.
        RuntimeError
            For any other connectivity failure.
        """
        parts = urlsplit(server_url)
        path = (parts.path or "").rstrip("/")
        if not path:
            path = "" if parts.query else "/mcp"
        elif path != "/mcp":
            path = f"{path}/mcp"
        url = urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": 1,
        }
        argument_keys = sorted(arguments.keys()) if isinstance(arguments, dict) else "<non-dict>"
        header_keys = sorted((headers or {}).keys())
        logger.info(
            "MCP upstream request "
            f"url={url} tool={tool_name} argument_keys={argument_keys} header_keys={header_keys}"
        )

        request_headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **(headers or {}),
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=request_headers)
                resp.raise_for_status()
                try:
                    return resp.json()
                except json.JSONDecodeError as exc:
                    snippet = (resp.text or "")[:200]
                    logger.warning(
                        f"MCP upstream non-JSON response: {url} tool={tool_name} body={snippet!r}"
                    )
                    raise RuntimeError(
                        f"Upstream response parsing failed: {exc}"
                    ) from exc
        except httpx.TimeoutException:
            logger.warning(f"MCP upstream timeout: {url} tool={tool_name}")
            raise
        except httpx.HTTPStatusError as exc:
            response = exc.response
            snippet = (response.text or "")[:500]
            logger.warning(
                "MCP upstream HTTP error "
                f"url={url} tool={tool_name} status={response.status_code} "
                f"content_type={response.headers.get('content-type')} body={snippet!r}"
            )
            raise
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error(f"MCP upstream connection error: {url} tool={tool_name}: {exc}")
            raise RuntimeError(f"Failed to reach upstream MCP server: {exc}") from exc
