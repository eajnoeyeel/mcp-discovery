"""Minimal local mock provider MCP app for compose/dev runtime."""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

LOOKUP_TOOL_NAME = "lookup"


def create_app() -> FastAPI:
    app = FastAPI(title="MLP Mock Provider MCP")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/mcp")
    async def mcp(request: Request) -> JSONResponse:
        payload = await request.json()
        req_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params", {})

        if method == "initialize":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mock-provider", "version": "1.0.0"},
                    },
                }
            )

        if method == "tools/list":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": LOOKUP_TOOL_NAME,
                                "description": "Lookup mock provider records by query.",
                                "inputSchema": {
                                    "type": "object",
                                    "required": ["query"],
                                    "properties": {
                                        "query": {
                                            "type": "string",
                                            "description": "Query text to look up",
                                        }
                                    },
                                },
                            }
                        ]
                    },
                }
            )

        if method == "tools/call" and params.get("name") == LOOKUP_TOOL_NAME:
            query = params.get("arguments", {}).get("query", "")
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "lookup_query": query,
                                        "server": "mock_provider",
                                        "ok": True,
                                    }
                                ),
                            }
                        ]
                    },
                }
            )

        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Method not found"},
            }
        )

    return app


app = create_app()
