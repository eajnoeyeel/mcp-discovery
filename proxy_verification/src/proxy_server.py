"""프록시 MCP 서버 — Claude Code가 연결하는 단일 진입점.

여러 백엔드 MCP 서버의 도구를 네임스페이스화하여 노출하고,
도구 호출을 해당 백엔드로 라우팅한다.

MetaMCP의 mcp-proxy.ts 패턴을 Python으로 구현.
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.models import BackendServerConfig, ProxyConfig, ToolMapping
from src.proxy_client import call_backend_tool
from src.registry import discover_tools


# 전역 상태 (MetaMCP의 toolToClient 패턴)
_tool_registry: dict[str, ToolMapping] = {}
_backend_configs: dict[str, BackendServerConfig] = {}

server = Server("proxy-mcp-verifier")


def _load_config() -> ProxyConfig:
    """config.json에서 백엔드 설정 로드."""
    config_path = Path(__file__).parent.parent / "config.json"
    if not config_path.exists():
        print(f"Warning: {config_path} not found, using empty config", file=sys.stderr)
        return ProxyConfig(backends=[])

    with open(config_path) as f:
        data = json.load(f)
    return ProxyConfig(**data)


async def _init_registry() -> None:
    """서버 시작 시 모든 백엔드에서 도구를 발견하고 레지스트리 구성."""
    config = _load_config()

    # 백엔드 설정을 server_id로 인덱싱
    for backend in config.backends:
        _backend_configs[backend.server_id] = backend

    # 도구 발견
    mappings = await discover_tools(config)
    _tool_registry.update(mappings)

    print(
        f"Discovered {len(_tool_registry)} tools from {len(config.backends)} backends",
        file=sys.stderr,
    )


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """네임스페이스된 도구 목록 반환."""
    return [
        Tool(
            name=mapping.tool_id,
            description=f"[{mapping.server_id}] {mapping.description}",
            inputSchema=mapping.input_schema,
        )
        for mapping in _tool_registry.values()
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """도구 호출을 해당 백엔드로 라우팅."""
    mapping = _tool_registry.get(name)
    if not mapping:
        raise ValueError(f"Unknown tool: {name}")

    backend = _backend_configs.get(mapping.server_id)
    if not backend:
        raise ValueError(f"Unknown backend: {mapping.server_id}")

    result = await call_backend_tool(backend, mapping.original_tool_name, arguments)
    return [TextContent(type="text", text=item["text"]) for item in result]


async def main() -> None:
    """프록시 MCP 서버 메인 엔트리포인트."""
    # Echo 백엔드만으로 먼저 시작 (Node.js 백엔드는 별도 설정)
    await _init_registry()

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
