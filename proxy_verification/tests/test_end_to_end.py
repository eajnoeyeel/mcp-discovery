"""E2E 통합 테스트 (TDD RED → GREEN)

프록시 MCP 서버를 subprocess로 실행하고, MCP 클라이언트로 연결하여
도구 목록 확인 + 도구 호출 라우팅을 검증.
"""

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


PROXY_SERVER_PARAMS = StdioServerParameters(
    command="uv",
    args=["run", "python", "-m", "src.proxy_server"],
)


async def _run_with_proxy(fn):
    """프록시 서버에 연결된 세션으로 fn을 실행하는 헬퍼."""
    async with stdio_client(PROXY_SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


async def test_proxy_list_tools() -> None:
    """프록시가 echo 백엔드의 도구를 네임스페이스화하여 노출하는지 검증."""

    async def check(session: ClientSession):
        result = await session.list_tools()
        tool_names = {tool.name for tool in result.tools}
        assert "echo__echo" in tool_names
        assert "echo__reverse" in tool_names

    await _run_with_proxy(check)


async def test_proxy_call_echo() -> None:
    """프록시를 통해 echo__echo 도구 호출 → 입력 그대로 반환."""

    async def check(session: ClientSession):
        result = await session.call_tool("echo__echo", {"message": "hello"})
        assert len(result.content) == 1
        assert result.content[0].text == "hello"

    await _run_with_proxy(check)


async def test_proxy_call_reverse() -> None:
    """프록시를 통해 echo__reverse 도구 호출 → 뒤집어서 반환."""

    async def check(session: ClientSession):
        result = await session.call_tool("echo__reverse", {"text": "hello"})
        assert result.content[0].text == "olleh"

    await _run_with_proxy(check)


async def test_proxy_call_korean() -> None:
    """프록시를 통해 한국어 메시지 echo → 그대로 반환."""

    async def check(session: ClientSession):
        result = await session.call_tool("echo__echo", {"message": "프록시 테스트"})
        assert result.content[0].text == "프록시 테스트"

    await _run_with_proxy(check)


async def test_proxy_unknown_tool() -> None:
    """존재하지 않는 네임스페이스 도구 호출 시 에러 결과 반환."""

    async def check(session: ClientSession):
        result = await session.call_tool("nonexistent__tool", {})
        # MCP SDK는 서버 에러를 isError=True로 전달
        assert result.isError is True

    await _run_with_proxy(check)
