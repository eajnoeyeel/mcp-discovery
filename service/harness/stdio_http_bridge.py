"""HTTP-to-stdio bridge — exposes a stdio MCP server as HTTP for testing.

Wraps any stdio-based MCP server (like n8n-mcp) with a minimal HTTP endpoint
so that MCPHTTPClient can call it through the normal execute proxy path.

The bridge:
  1. Accepts POST /mcp with JSON-RPC 2.0 payload
  2. Spawns the stdio MCP server process
  3. Sends initialize + the incoming request via stdin
  4. Returns the tools/call response as HTTP JSON

Usage:
  uv run python mlp/harness/stdio_http_bridge.py --command /opt/homebrew/bin/n8n-mcp --port 9800

Then MCPHTTPClient can call: http://localhost:9800/mcp

Security note: command path is from CLI args only (not user input).
Uses create_subprocess_exec (no shell) for safe process spawning.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import uvicorn
from loguru import logger
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def _call_stdio_mcp(
    command: str,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    """Spawn stdio MCP process, send initialize + request, return response.

    Uses asyncio.create_subprocess_exec (no shell) for safe process spawning.
    The command path is validated at startup, not from user input.
    """
    init_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "stdio-http-bridge", "version": "1.0"},
            },
        }
    )

    req_id = request_payload.get("id", 1)
    call_msg = json.dumps(request_payload)
    input_data = init_msg + "\n" + call_msg + "\n"

    proc = await asyncio.create_subprocess_exec(
        command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input_data.encode()),
        timeout=30.0,
    )

    for line in stdout.decode().splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            resp = json.loads(line)
            if resp.get("id") == req_id:
                return resp
        except json.JSONDecodeError:
            continue

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32603, "message": "No response from stdio MCP server"},
    }


def create_app(command: str) -> Starlette:
    """Create the Starlette app with the /mcp endpoint."""

    async def mcp_endpoint(request: Request) -> JSONResponse:
        body = await request.json()
        tool_name = body.get("params", {}).get("name", "?")
        logger.info(f"Bridge request: method={body.get('method')} tool={tool_name}")
        result = await _call_stdio_mcp(command, body)
        return JSONResponse(result)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "command": command})

    return Starlette(
        routes=[
            Route("/mcp", mcp_endpoint, methods=["POST"]),
            Route("/health", health, methods=["GET"]),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP-to-stdio MCP bridge")
    parser.add_argument("--command", required=True, help="Path to stdio MCP server binary")
    parser.add_argument("--port", type=int, default=9800, help="HTTP port (default: 9800)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    args = parser.parse_args()

    logger.info(f"Starting HTTP-to-stdio bridge: {args.command} on {args.host}:{args.port}")
    app = create_app(args.command)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
