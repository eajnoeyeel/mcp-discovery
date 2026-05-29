"""Proxy MCP 검증용 데이터 모델."""

from pydantic import BaseModel


class BackendServerConfig(BaseModel):
    """백엔드 MCP 서버 연결 설정."""

    server_id: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}


class ProxyConfig(BaseModel):
    """프록시 전체 설정 — 백엔드 서버 목록."""

    backends: list[BackendServerConfig]


class ToolMapping(BaseModel):
    """네임스페이스된 도구 매핑 정보."""

    tool_id: str  # "{server_id}__{tool_name}"
    server_id: str
    original_tool_name: str
    description: str
    input_schema: dict
