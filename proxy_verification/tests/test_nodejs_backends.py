"""Node.js 백엔드 통합 테스트 (TDD)

프록시를 통해 filesystem, memory MCP 서버 호출 검증.
Node.js(npx) 미설치 환경에서는 skip.
"""

import os
import shutil
import tempfile

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# npx 사용 가능 여부 확인
HAS_NPX = shutil.which("npx") is not None

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


@pytest.mark.skipif(not HAS_NPX, reason="npx not available")
async def test_proxy_filesystem_list() -> None:
    """프록시를 통해 filesystem 백엔드의 도구 목록 확인."""

    async def check(session: ClientSession):
        result = await session.list_tools()
        tool_names = {tool.name for tool in result.tools}
        # filesystem 서버는 read_file, write_file 등 제공
        assert any(name.startswith("filesystem__") for name in tool_names)

    await _run_with_proxy(check)


@pytest.mark.skipif(not HAS_NPX, reason="npx not available")
async def test_proxy_filesystem_read() -> None:
    """프록시를 통해 filesystem__read_file로 파일 읽기 검증."""
    # /tmp/mcp-test/test.txt에 테스트 파일 준비
    test_dir = "/tmp/mcp-test"
    os.makedirs(test_dir, exist_ok=True)
    test_file = os.path.join(test_dir, "test.txt")
    test_content = "proxy verification test content"
    with open(test_file, "w") as f:
        f.write(test_content)

    async def check(session: ClientSession):
        result = await session.call_tool(
            "filesystem__read_file",
            {"path": test_file},
        )
        assert len(result.content) >= 1
        assert test_content in result.content[0].text

    await _run_with_proxy(check)


@pytest.mark.skipif(not HAS_NPX, reason="npx not available")
async def test_proxy_memory_roundtrip() -> None:
    """프록시를 통해 memory 백엔드로 entity 생성→조회 검증."""

    async def check(session: ClientSession):
        # entity 생성
        await session.call_tool(
            "memory__create_entities",
            {
                "entities": [
                    {
                        "name": "TestEntity",
                        "entityType": "test",
                        "observations": ["This is a test entity for proxy verification"],
                    }
                ]
            },
        )

        # entity 검색
        result = await session.call_tool(
            "memory__search_nodes",
            {"query": "TestEntity"},
        )
        assert len(result.content) >= 1
        # 검색 결과에 TestEntity가 포함되어야 함
        result_text = result.content[0].text
        assert "TestEntity" in result_text

    await _run_with_proxy(check)
