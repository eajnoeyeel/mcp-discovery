"""레지스트리 — 백엔드 MCP 서버 도구 발견 + 네임스페이스 매핑.

MetaMCP 패턴 차용:
- sanitize_name(): 영숫자, _, -만 허용
- 네임스페이스: {sanitized_server_id}__{tool_name}
- 병렬 발견: asyncio.gather(return_exceptions=True)
"""

import asyncio
import re
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from src.models import BackendServerConfig, ProxyConfig, ToolMapping


def sanitize_name(name: str) -> str:
    """서버 이름에서 영숫자, _, -만 남기고 나머지 제거.

    MetaMCP의 sanitizeName() 동등 구현.
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "", name)


async def _discover_backend_tools(
    backend: BackendServerConfig,
) -> list[ToolMapping]:
    """단일 백엔드 MCP 서버에서 도구 목록을 발견."""
    server_params = StdioServerParameters(
        command=backend.command,
        args=backend.args,
        env=backend.env if backend.env else None,
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

            mappings: list[ToolMapping] = []
            for tool in result.tools:
                tool_id = f"{sanitize_name(backend.server_id)}__{tool.name}"
                mappings.append(
                    ToolMapping(
                        tool_id=tool_id,
                        server_id=backend.server_id,
                        original_tool_name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.inputSchema,
                    )
                )
            return mappings


async def discover_tools(config: ProxyConfig) -> dict[str, ToolMapping]:
    """모든 백엔드 MCP 서버에서 도구를 병렬로 발견하고 네임스페이스 매핑을 반환.

    실패한 백엔드는 경고만 출력하고 나머지 결과를 반환.
    (MetaMCP의 Promise.allSettled 패턴)
    """
    tasks = [_discover_backend_tools(backend) for backend in config.backends]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_mappings: dict[str, ToolMapping] = {}
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            backend = config.backends[i]
            print(
                f"Warning: Failed to discover tools from {backend.server_id}: {result}",
                file=sys.stderr,
            )
            continue
        for mapping in result:
            all_mappings[mapping.tool_id] = mapping

    return all_mappings
