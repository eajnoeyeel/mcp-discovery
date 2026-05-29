"""Local stdio MCP server wrapping BridgeService for Claude Code connection.

Constructs its own runtime — NEVER imports singletons from handler.py.
The Lambda handler uses get_or_create_loop() (sync-to-async bridge) which
conflicts with the stdio server's own event loop.

Usage:
    uv run python mlp/harness/local_bridge_mcp.py

Claude Code config (.claude/settings.json):
    {
      "mcpServers": {
        "mcp-discovery-bridge": {
          "command": "uv",
          "args": ["run", "python", "mlp/harness/local_bridge_mcp.py"],
          "cwd": "/path/to/mcp-discovery"
        }
        }
    }
"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import mcp.types as types
from dotenv import load_dotenv
from loguru import logger
from mcp.server import Server
from mcp.server.stdio import stdio_server

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"


def _bootstrap_import_paths() -> None:
    """Ensure local MCP launches can import both service/ and src/ packages."""
    for path in (PROJECT_ROOT, SRC_ROOT):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)


_bootstrap_import_paths()
load_dotenv(PROJECT_ROOT / ".env")

app = Server("mcp-discovery-bridge-local")

# Lazy-initialized bridge service (constructed inside async context)
_bridge_service = None


async def _get_bridge():
    """Construct BridgeService with full runtime on first call.

    Mirrors mlp/lambdas/bridge/handler.py lines 21-55 but constructs
    everything inside the running event loop to avoid loop conflicts.
    """
    global _bridge_service
    if _bridge_service is not None:
        return _bridge_service

    from service.rag.factory import RAGServiceFactory
    from service.services.bridge_service import BridgeService
    from service.services.search_service import SearchService
    from service.shared.runtime import build_search_runtime

    runtime = build_search_runtime()
    mlp_settings = runtime.mlp_settings

    rag_service = RAGServiceFactory.create(
        strategy=runtime.strategy,
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_key=os.getenv("SUPABASE_SERVICE_KEY", ""),
        cache_ttl=mlp_settings.cache_ttl_seconds,
        confidence_gap_threshold=runtime.settings.confidence_gap_threshold,
        reranker=None,
        operability_cache=runtime.operability_cache,
        enable_pending_freshness=mlp_settings.enable_pending_freshness,
        enable_per_client_routing=mlp_settings.enable_per_client_routing,
        rerank_candidate_pool_size=mlp_settings.rerank_candidate_pool_size,
        pending_freshness_limit=mlp_settings.pending_freshness_limit,
        pending_freshness_timeout_ms=mlp_settings.pending_freshness_timeout_ms,
    )
    search_service = SearchService(rag_service=rag_service)

    # Wire ExecuteService for execute_tool support
    execute_service = None
    try:
        from service.adapters.mcp_http_client import MCPHTTPClient
        from service.lambdas.execute.handler import (
            SupabaseExecutionLogger,
            SupabaseToolRegistry,
        )
        from service.services.execute_service import ExecuteService

        execute_service = ExecuteService(
            registry=SupabaseToolRegistry(),
            mcp_client=MCPHTTPClient(timeout=25.0),
            execution_logger=SupabaseExecutionLogger(),
        )
        logger.info("ExecuteService wired for local bridge")
    except Exception as exc:
        logger.warning(f"ExecuteService unavailable in local bridge: {exc}")

    _bridge_service = BridgeService(
        search_service=search_service,
        execute_service=execute_service,
    )
    logger.info("Local bridge service initialized")
    return _bridge_service


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Return the list of tools exposed by this bridge."""
    return [
        types.Tool(
            name="find_best_tool",
            description="Find the best MCP tool for a natural language query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of what you need",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="execute_tool",
            description="Execute an MCP tool by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_id": {
                        "type": "string",
                        "description": "Tool ID in format 'server_id::tool_name'",
                    },
                    "params": {
                        "type": "string",
                        "description": "JSON string of parameters to pass to the tool",
                        "default": "{}",
                    },
                },
                "required": ["tool_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
    """Dispatch a tool call to the bridge service."""
    args = arguments or {}
    bridge = await _get_bridge()

    if name == "find_best_tool":
        from service.services.contracts import SearchRequest

        query = args.get("query", "")
        top_k = int(args.get("top_k", 3))
        result = await bridge.find_best_tool(SearchRequest(query=query, top_k=top_k))
        return [
            types.TextContent(
                type="text",
                text=json.dumps(result.model_dump(), indent=2, default=str),
            )
        ]

    if name == "execute_tool":
        from service.services.contracts import ExecuteRequest

        tool_id = args.get("tool_id", "")
        params_raw = args.get("params", "{}")
        parsed: dict[str, Any] = (
            json.loads(params_raw) if isinstance(params_raw, str) else params_raw
        )
        result = await bridge.execute_tool(ExecuteRequest(tool_id=tool_id, params=parsed))
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    """Run the stdio MCP server."""
    logger.info("Starting local bridge MCP server (stdio transport)")
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
