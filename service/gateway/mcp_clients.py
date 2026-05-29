"""Python MCP SDK-backed client sessions for the long-running gateway."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any, Literal

from loguru import logger
from mcp import ClientSession as _SDKClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field, model_validator

GatewayTransportType = Literal["stdio", "sse", "streamable_http"]


class ClientSession(_SDKClientSession):
    """MCP SDK session with lenient handling for invalid remote output schemas.

    Some third-party MCP servers publish malformed output schemas that fail JSON
    Schema metaschema validation even when the actual tool result is usable.
    In that narrow case, keep the tool result and log the schema problem instead
    of turning the whole call into a 500.
    """

    async def _validate_tool_result(self, name: str, result: Any) -> None:
        try:
            await super()._validate_tool_result(name, result)
        except RuntimeError as exc:
            if str(exc).startswith("Invalid schema for tool "):
                logger.warning(f"Skipping invalid upstream output schema for tool {name}: {exc}")
                return
            raise


class MCPTransportConfig(BaseModel):
    """Connection settings for one upstream MCP server transport."""

    server_id: str
    transport_type: GatewayTransportType
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transport_fields(self) -> MCPTransportConfig:
        """Require only the fields needed by the selected transport."""
        if self.transport_type == "stdio" and not self.command:
            raise ValueError("command is required for stdio transport")
        if self.transport_type in {"sse", "streamable_http"} and not self.url:
            raise ValueError("url is required for remote MCP transport")
        return self

    def pool_key(self) -> str:
        """Build a stable non-secret key for session reuse."""
        if self.transport_type == "stdio":
            return f"{self.server_id}:stdio:{self.command}:{' '.join(self.args)}"
        return f"{self.server_id}:{self.transport_type}:{self.url}"


class PooledMCPClientSession:
    """Owns one initialized MCP ClientSession and its transport resources."""

    def __init__(
        self, *, config: MCPTransportConfig, session: ClientSession, stack: AsyncExitStack
    ) -> None:
        self.config = config
        self.session = session
        self._stack = stack

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an upstream MCP tool and normalize SDK model results to dictionaries."""
        result = await self.session.call_tool(tool_name, arguments)
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return dict(result)

    async def close(self) -> None:
        """Close SDK session and transport resources."""
        await self._stack.aclose()


async def create_pooled_mcp_session(config: MCPTransportConfig) -> PooledMCPClientSession:
    """Open and initialize a pooled MCP SDK session for config."""
    stack = AsyncExitStack()
    try:
        if config.transport_type == "stdio":
            params = StdioServerParameters(
                command=config.command or "",
                args=config.args,
                env=config.env or None,
            )
            read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        elif config.transport_type == "sse":
            read_stream, write_stream = await stack.enter_async_context(
                sse_client(config.url or "", headers=config.headers or None)
            )
        else:
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamablehttp_client(config.url or "", headers=config.headers or None)
            )

        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        return PooledMCPClientSession(config=config, session=session, stack=stack)
    except Exception:
        await stack.aclose()
        raise
