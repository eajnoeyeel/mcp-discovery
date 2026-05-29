"""레지스트리 테스트 (TDD RED → GREEN)

Echo 서버를 백엔드로 사용하여 도구 발견 + 네임스페이스 매핑 검증.
"""

from src.models import BackendServerConfig, ProxyConfig
from src.registry import discover_tools, sanitize_name


ECHO_BACKEND = BackendServerConfig(
    server_id="echo",
    command="uv",
    args=["run", "python", "-m", "src.echo_server"],
)


async def test_discover_echo_tools() -> None:
    """Echo 백엔드에서 2개 도구를 발견하는지 검증."""
    config = ProxyConfig(backends=[ECHO_BACKEND])
    mappings = await discover_tools(config)
    assert len(mappings) == 2
    assert "echo__echo" in mappings
    assert "echo__reverse" in mappings


async def test_namespace_format() -> None:
    """tool_id가 {server_id}__{tool_name} 형식인지 검증."""
    config = ProxyConfig(backends=[ECHO_BACKEND])
    mappings = await discover_tools(config)

    for tool_id, mapping in mappings.items():
        parts = tool_id.split("__", 1)
        assert len(parts) == 2
        assert parts[0] == mapping.server_id
        assert parts[1] == mapping.original_tool_name


async def test_tool_mapping_has_description() -> None:
    """ToolMapping에 description이 포함되어 있는지 검증."""
    config = ProxyConfig(backends=[ECHO_BACKEND])
    mappings = await discover_tools(config)

    for mapping in mappings.values():
        assert mapping.description != ""


async def test_tool_mapping_has_input_schema() -> None:
    """ToolMapping에 input_schema가 포함되어 있는지 검증."""
    config = ProxyConfig(backends=[ECHO_BACKEND])
    mappings = await discover_tools(config)

    echo_mapping = mappings["echo__echo"]
    assert "properties" in echo_mapping.input_schema
    assert "message" in echo_mapping.input_schema["properties"]


def test_sanitize_name() -> None:
    """sanitize_name이 영숫자, _, -만 허용하는지 검증."""
    assert sanitize_name("hello-world") == "hello-world"
    assert sanitize_name("hello world") == "helloworld"
    assert sanitize_name("hello@world!") == "helloworld"
    assert sanitize_name("서버_1") == "_1"
    assert sanitize_name("my_server-2") == "my_server-2"
