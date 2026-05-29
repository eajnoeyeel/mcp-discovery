"""Internal long-running MCP execution gateway API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, Protocol

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from service.gateway.internal_auth import verify_internal_auth
from service.gateway.mcp_clients import MCPTransportConfig, create_pooled_mcp_session
from service.gateway.settings import GatewaySettings, get_gateway_settings


class GatewaySession(Protocol):
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on a pooled upstream MCP session."""


class GatewaySessionPool(Protocol):
    async def get(self, key: str) -> GatewaySession:
        """Return the pooled session for the given key."""

    def status(self) -> dict[str, Any]:
        """Return session pool status for health checks."""

    async def close_all(self) -> None:
        """Close all pooled sessions during app shutdown."""


class GatewayExecuteRequest(BaseModel):
    server_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)


class GatewayExecuteResponse(BaseModel):
    server_id: str
    tool_name: str
    result: dict[str, Any]


ConfigLoader = Callable[[str], Awaitable[dict[str, Any]]]


def create_app(
    *,
    session_pool: GatewaySessionPool,
    config_loader: ConfigLoader,
    settings: GatewaySettings | None = None,
) -> FastAPI:
    """Create the internal MCP execution gateway FastAPI app."""

    gateway_settings = settings or get_gateway_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await session_pool.close_all()

    app = FastAPI(title="MLP MCP Execution Gateway", lifespan=lifespan)

    @app.get("/gateway/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "sessions": session_pool.status()}

    @app.post("/gateway/execute")
    async def execute(request: Request, payload: GatewayExecuteRequest) -> dict[str, Any]:
        body = await request.body()
        if not verify_internal_auth(
            secret=gateway_settings.internal_auth_secret,
            method=request.method,
            path=request.url.path,
            body=body,
            headers=request.headers,
            max_age_seconds=gateway_settings.internal_auth_max_age_seconds,
        ):
            raise HTTPException(status_code=401, detail="Invalid internal gateway auth")

        config = await config_loader(payload.server_id)
        if payload.headers:
            session = await create_pooled_mcp_session(
                MCPTransportConfig(
                    server_id=config["server_id"],
                    transport_type=config["transport_type"],
                    url=config["url"],
                    headers=payload.headers,
                )
            )
            try:
                result = await session.call_tool(payload.tool_name, payload.arguments)
            finally:
                await session.close()
        else:
            session = await session_pool.get(config["pool_key"])
            result = await session.call_tool(payload.tool_name, payload.arguments)
        return GatewayExecuteResponse(
            server_id=payload.server_id,
            tool_name=payload.tool_name,
            result=result,
        ).model_dump()

    return app
