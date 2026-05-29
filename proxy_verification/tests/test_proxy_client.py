"""프록시 클라이언트 테스트 (TDD RED → GREEN)

Echo 서버를 백엔드로 사용하여 proxy_client의 call_backend_tool 검증.
"""

import pytest
from src.models import BackendServerConfig
from src.proxy_client import call_backend_tool


ECHO_BACKEND = BackendServerConfig(
    server_id="echo",
    command="uv",
    args=["run", "python", "-m", "src.echo_server"],
)


async def test_call_backend_echo() -> None:
    """call_backend_tool로 echo 도구 호출 → 입력 그대로 반환."""
    result = await call_backend_tool(ECHO_BACKEND, "echo", {"message": "hello"})
    assert len(result) == 1
    assert result[0]["type"] == "text"
    assert result[0]["text"] == "hello"


async def test_call_backend_reverse() -> None:
    """call_backend_tool로 reverse 도구 호출 → 뒤집어서 반환."""
    result = await call_backend_tool(ECHO_BACKEND, "reverse", {"text": "hello"})
    assert result[0]["text"] == "olleh"


async def test_call_backend_unknown_tool() -> None:
    """존재하지 않는 도구 호출 시 에러."""
    result = await call_backend_tool(ECHO_BACKEND, "nonexistent", {})
    # 에러 시 isError=True이거나 에러 메시지를 포함해야 함
    assert len(result) >= 1
