"""데이터 모델 테스트 (TDD RED → GREEN)"""

import pytest
from src.models import BackendServerConfig, ProxyConfig, ToolMapping


class TestBackendServerConfig:
    def test_create_minimal(self) -> None:
        """최소 필드로 생성."""
        config = BackendServerConfig(
            server_id="echo",
            command="python",
            args=["-m", "src.echo_server"],
        )
        assert config.server_id == "echo"
        assert config.command == "python"
        assert config.args == ["-m", "src.echo_server"]
        assert config.env == {}

    def test_create_with_env(self) -> None:
        """환경 변수 포함 생성."""
        config = BackendServerConfig(
            server_id="test",
            command="npx",
            args=["-y", "some-package"],
            env={"NODE_ENV": "test"},
        )
        assert config.env == {"NODE_ENV": "test"}

    def test_missing_required_field(self) -> None:
        """필수 필드 누락 시 ValidationError."""
        with pytest.raises(Exception):
            BackendServerConfig(server_id="echo")  # type: ignore


class TestProxyConfig:
    def test_create_with_backends(self) -> None:
        """백엔드 리스트로 생성."""
        config = ProxyConfig(
            backends=[
                BackendServerConfig(
                    server_id="echo",
                    command="python",
                    args=["-m", "src.echo_server"],
                ),
            ]
        )
        assert len(config.backends) == 1
        assert config.backends[0].server_id == "echo"

    def test_empty_backends(self) -> None:
        """빈 백엔드 리스트."""
        config = ProxyConfig(backends=[])
        assert len(config.backends) == 0


class TestToolMapping:
    def test_create(self) -> None:
        """ToolMapping 생성."""
        mapping = ToolMapping(
            tool_id="echo__echo",
            server_id="echo",
            original_tool_name="echo",
            description="Echo back the input message.",
            input_schema={"type": "object", "properties": {"message": {"type": "string"}}},
        )
        assert mapping.tool_id == "echo__echo"
        assert mapping.server_id == "echo"
        assert mapping.original_tool_name == "echo"

    def test_namespace_format(self) -> None:
        """tool_id가 {server_id}__{tool_name} 형식인지 검증."""
        mapping = ToolMapping(
            tool_id="filesystem__read_file",
            server_id="filesystem",
            original_tool_name="read_file",
            description="Read a file.",
            input_schema={},
        )
        parts = mapping.tool_id.split("__", 1)
        assert len(parts) == 2
        assert parts[0] == mapping.server_id
        assert parts[1] == mapping.original_tool_name
