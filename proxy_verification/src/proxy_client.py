"""프록시 클라이언트 — 백엔드 MCP 서버에 연결하여 도구 호출.

Connect-per-call 방식: 매 호출마다 새 프로세스 생성.
프로토타입용 — Phase 13에서 persistent connection으로 전환 필요.
"""

from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from src.models import BackendServerConfig


async def call_backend_tool(
    backend: BackendServerConfig,
    tool_name: str,
    arguments: dict[str, Any],
) -> list[dict[str, Any]]:
    """백엔드 MCP 서버에 연결하여 도구를 호출하고 결과를 반환.

    Args:
        backend: 백엔드 서버 연결 설정
        tool_name: 호출할 도구의 원래 이름 (네임스페이스 없음)
        arguments: 도구에 전달할 인자

    Returns:
        도구 호출 결과 content 리스트 (각 항목은 {"type": ..., "text": ...})
    """
    server_params = StdioServerParameters(
        command=backend.command,
        args=backend.args,
        env=backend.env if backend.env else None,
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return [
                {
                    "type": content.type,
                    "text": content.text if hasattr(content, "text") else str(content),
                }
                for content in result.content
            ]
