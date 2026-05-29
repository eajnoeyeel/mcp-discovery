"""Deployable App Runner entrypoint for the MLP gateway."""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI

from service.gateway.app import create_app
from service.gateway.mcp_clients import MCPTransportConfig, create_pooled_mcp_session
from service.gateway.session_pool import SessionPool

from .settings import get_gateway_settings


async def create_session_from_pool_key(key: str):
    """Create a pooled MCP session from a serialized transport config key."""
    server_id, transport_type, url = key.split(":", 2)
    return await create_pooled_mcp_session(
        MCPTransportConfig(
            server_id=server_id,
            transport_type=transport_type,
            url=url,
        )
    )


async def load_gateway_config(server_id: str) -> dict[str, str]:
    """Load gateway transport config for a registered MCP server from Supabase."""
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not supabase_url or not service_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{supabase_url}/rest/v1/mcp_servers",
            headers=headers,
            params={
                "server_id": f"eq.{server_id}",
                "select": "server_id,transport_type,url",
                "limit": "1",
            },
        )
        response.raise_for_status()
        rows = response.json()
    if not rows:
        raise RuntimeError(f"Gateway config not found for server '{server_id}'")

    row = rows[0]
    config = MCPTransportConfig(
        server_id=row["server_id"],
        transport_type=row.get("transport_type") or "streamable_http",
        url=row["url"],
    )
    return {
        "server_id": config.server_id,
        "transport_type": config.transport_type,
        "url": config.url or "",
        "pool_key": config.pool_key(),
    }


settings = get_gateway_settings()
session_pool = SessionPool(
    factory=create_session_from_pool_key,
    max_sessions=settings.session_pool_max_size,
)
app: FastAPI = create_app(session_pool=session_pool, config_loader=load_gateway_config)
