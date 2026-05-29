"""Optimizer MCP 서버 E2E 테스트 (TDD RED → GREEN)

프로덕션 구조 검증: find_best_tool + execute_tool 2개 도구만 노출.
모든 백엔드 도구를 직접 노출하지 않고, 추천→실행 2단계 흐름을 검증한다.
"""

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


OPTIMIZER_SERVER_PARAMS = StdioServerParameters(
    command="uv",
    args=["run", "python", "-m", "src.optimizer_server"],
)


async def _run_with_optimizer(fn):
    """Optimizer 서버에 연결된 세션으로 fn을 실행하는 헬퍼."""
    async with stdio_client(OPTIMIZER_SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


# ── 도구 목록 검증 ──────────────────────────────────────────


async def test_exposes_only_two_tools() -> None:
    """정확히 find_best_tool, execute_tool 2개만 노출되는지 검증."""

    async def check(session: ClientSession):
        result = await session.list_tools()
        tool_names = {tool.name for tool in result.tools}
        assert tool_names == {"find_best_tool", "execute_tool"}

    await _run_with_optimizer(check)


async def test_no_backend_tools_exposed() -> None:
    """백엔드 도구(echo__echo 등)가 직접 노출되지 않는지 검증."""

    async def check(session: ClientSession):
        result = await session.list_tools()
        tool_names = {tool.name for tool in result.tools}
        # 네임스페이스된 백엔드 도구가 없어야 함
        assert not any("__" in name for name in tool_names)

    await _run_with_optimizer(check)


# ── find_best_tool 검증 ─────────────────────────────────────


async def test_find_best_tool_returns_recommendations() -> None:
    """find_best_tool이 쿼리에 대해 추천 결과를 반환하는지 검증."""

    async def check(session: ClientSession):
        result = await session.call_tool(
            "find_best_tool",
            {"query": "echo a message back to me"},
        )
        assert len(result.content) >= 1
        # 결과에 tool_id가 포함되어야 함
        text = result.content[0].text
        assert "echo__echo" in text

    await _run_with_optimizer(check)


async def test_find_best_tool_returns_json() -> None:
    """find_best_tool 결과가 구조화된 JSON인지 검증."""
    import json

    async def check(session: ClientSession):
        result = await session.call_tool(
            "find_best_tool",
            {"query": "reverse some text"},
        )
        data = json.loads(result.content[0].text)
        # JSON 구조: recommendations 배열
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)
        assert len(data["recommendations"]) > 0
        # 각 추천에 필수 필드
        rec = data["recommendations"][0]
        assert "tool_id" in rec
        assert "score" in rec
        assert "description" in rec

    await _run_with_optimizer(check)


async def test_find_best_tool_no_match() -> None:
    """매칭 도구가 없을 때도 정상 응답 (빈 recommendations)."""
    import json

    async def check(session: ClientSession):
        result = await session.call_tool(
            "find_best_tool",
            {"query": "xyzzy_absolutely_no_match_possible_12345"},
        )
        data = json.loads(result.content[0].text)
        assert "recommendations" in data
        assert len(data["recommendations"]) == 0

    await _run_with_optimizer(check)


# ── execute_tool 검증 ────────────────────────────────────────


async def test_execute_tool_echo() -> None:
    """execute_tool로 echo 백엔드 호출 → 결과 반환."""

    async def check(session: ClientSession):
        result = await session.call_tool(
            "execute_tool",
            {
                "tool_id": "echo__echo",
                "arguments": {"message": "production-style"},
            },
        )
        assert result.content[0].text == "production-style"

    await _run_with_optimizer(check)


async def test_execute_tool_reverse() -> None:
    """execute_tool로 reverse 백엔드 호출 → 뒤집힌 결과 반환."""

    async def check(session: ClientSession):
        result = await session.call_tool(
            "execute_tool",
            {
                "tool_id": "echo__reverse",
                "arguments": {"text": "production"},
            },
        )
        assert result.content[0].text == "noitcudorp"

    await _run_with_optimizer(check)


async def test_execute_tool_unknown() -> None:
    """존재하지 않는 tool_id로 execute_tool 호출 시 에러."""

    async def check(session: ClientSession):
        result = await session.call_tool(
            "execute_tool",
            {
                "tool_id": "nonexistent__tool",
                "arguments": {},
            },
        )
        assert result.isError is True

    await _run_with_optimizer(check)


# ── 전체 흐름 검증 (find → execute) ──────────────────────────


async def test_find_then_execute_flow() -> None:
    """find_best_tool → execute_tool 2단계 흐름 검증."""
    import json

    async def check(session: ClientSession):
        # Step 1: 추천 받기
        find_result = await session.call_tool(
            "find_best_tool",
            {"query": "echo a message"},
        )
        recommendations = json.loads(find_result.content[0].text)["recommendations"]
        assert len(recommendations) > 0

        # Step 2: 추천된 도구로 실행
        best_tool_id = recommendations[0]["tool_id"]
        exec_result = await session.call_tool(
            "execute_tool",
            {
                "tool_id": best_tool_id,
                "arguments": {"message": "end-to-end"},
            },
        )
        assert exec_result.content[0].text == "end-to-end"

    await _run_with_optimizer(check)
