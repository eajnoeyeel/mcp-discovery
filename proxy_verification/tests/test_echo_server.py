"""Echo MCP 서버 독립 테스트 (TDD RED → GREEN)"""

import pytest
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession


ECHO_SERVER_PARAMS = StdioServerParameters(
    command="uv",
    args=["run", "python", "-m", "src.echo_server"],
)


async def _run_with_session(fn):
    """Echo 서버에 연결된 세션으로 fn을 실행하는 헬퍼.

    anyio task group과 pytest-asyncio 간 cancel scope 충돌을
    방지하기 위해 fixture 대신 헬퍼로 세션 관리.
    """
    async with stdio_client(ECHO_SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


async def test_echo_list_tools() -> None:
    """Echo 서버가 2개 도구(echo, reverse)를 반환하는지 검증."""

    async def check(session: ClientSession):
        result = await session.list_tools()
        tool_names = {tool.name for tool in result.tools}
        assert "echo" in tool_names
        assert "reverse" in tool_names
        assert len(result.tools) == 2

    await _run_with_session(check)


async def test_echo_tool() -> None:
    """echo 도구가 입력 메시지를 그대로 반환하는지 검증."""

    async def check(session: ClientSession):
        result = await session.call_tool("echo", {"message": "hello"})
        assert len(result.content) == 1
        assert result.content[0].text == "hello"

    await _run_with_session(check)


async def test_echo_tool_korean() -> None:
    """echo 도구가 한국어 메시지를 그대로 반환하는지 검증."""

    async def check(session: ClientSession):
        result = await session.call_tool("echo", {"message": "안녕하세요"})
        assert result.content[0].text == "안녕하세요"

    await _run_with_session(check)


async def test_reverse_tool() -> None:
    """reverse 도구가 텍스트를 뒤집어서 반환하는지 검증."""

    async def check(session: ClientSession):
        result = await session.call_tool("reverse", {"text": "hello"})
        assert result.content[0].text == "olleh"

    await _run_with_session(check)


async def test_reverse_tool_korean() -> None:
    """reverse 도구가 한국어 텍스트를 뒤집어서 반환하는지 검증."""

    async def check(session: ClientSession):
        result = await session.call_tool("reverse", {"text": "가나다"})
        assert result.content[0].text == "다나가"

    await _run_with_session(check)
