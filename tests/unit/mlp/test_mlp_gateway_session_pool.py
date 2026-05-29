"""Tests for long-running MCP gateway session pool core and transport factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest


class FakeSession:
    def __init__(self, name: str):
        self.name = name
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_get_reuses_existing_active_session_for_same_key():
    from service.gateway.session_pool import SessionPool

    factory = AsyncMock(side_effect=[FakeSession("one")])
    pool = SessionPool(factory=factory, max_sessions=4)

    first = await pool.get("srv")
    second = await pool.get("srv")

    assert first is second
    factory.assert_awaited_once_with("srv")


@pytest.mark.asyncio
async def test_concurrent_gets_share_single_session_for_same_key():
    from service.gateway.session_pool import SessionPool

    calls = 0

    async def factory(key: str) -> FakeSession:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return FakeSession(key)

    pool = SessionPool(factory=factory, max_sessions=4)

    first, second = await asyncio.gather(pool.get("srv"), pool.get("srv"))

    assert first is second
    assert calls == 1


@pytest.mark.asyncio
async def test_cleanup_closes_and_removes_session():
    from service.gateway.session_pool import SessionPool

    session = FakeSession("one")
    pool = SessionPool(factory=AsyncMock(return_value=session), max_sessions=4)

    await pool.get("srv")
    await pool.close("srv")

    assert session.closed is True
    assert pool.status()["active"] == 0
    assert pool.status()["keys"] == []


@pytest.mark.asyncio
async def test_close_all_closes_all_sessions():
    from service.gateway.session_pool import SessionPool

    first = FakeSession("one")
    second = FakeSession("two")
    pool = SessionPool(factory=AsyncMock(side_effect=[first, second]), max_sessions=4)

    await pool.get("srv-1")
    await pool.get("srv-2")
    await pool.close_all()

    assert first.closed is True
    assert second.closed is True
    assert pool.status() == {"active": 0, "keys": []}


@pytest.mark.asyncio
async def test_max_sessions_prevents_unbounded_process_growth():
    from service.gateway.session_pool import SessionLimitError, SessionPool

    pool = SessionPool(factory=AsyncMock(side_effect=[FakeSession("one")]), max_sessions=1)

    await pool.get("srv-1")
    with pytest.raises(SessionLimitError, match="session limit reached"):
        await pool.get("srv-2")


def test_transport_config_rejects_stdio_without_command():
    from pydantic import ValidationError

    from service.gateway.mcp_clients import MCPTransportConfig

    with pytest.raises(ValidationError, match="command is required"):
        MCPTransportConfig(server_id="srv", transport_type="stdio")


def test_transport_config_rejects_remote_without_url():
    from pydantic import ValidationError

    from service.gateway.mcp_clients import MCPTransportConfig

    with pytest.raises(ValidationError, match="url is required"):
        MCPTransportConfig(server_id="srv", transport_type="streamable_http")


def test_transport_config_builds_pool_key_without_secrets():
    from service.gateway.mcp_clients import MCPTransportConfig

    config = MCPTransportConfig(
        server_id="srv",
        transport_type="streamable_http",
        url="https://provider.example/mcp",
        headers={"Authorization": "Bearer secret"},
    )

    assert config.pool_key() == "srv:streamable_http:https://provider.example/mcp"


@pytest.mark.asyncio
async def test_create_pooled_mcp_session_opens_stdio_transport(monkeypatch):
    from service.gateway import mcp_clients
    from service.gateway.mcp_clients import MCPTransportConfig, create_pooled_mcp_session

    calls: list[tuple[str, object]] = []

    @asynccontextmanager
    async def fake_stdio_client(params):
        calls.append(("stdio", params))
        yield "stdio-read", "stdio-write"

    class FakeClientSession:
        def __init__(self, read_stream, write_stream):
            calls.append(("session", (read_stream, write_stream)))
            self.initialized = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            calls.append(("session-close", None))

        async def initialize(self):
            self.initialized = True
            calls.append(("initialize", None))

        async def call_tool(self, tool_name, arguments):
            return {"tool_name": tool_name, "arguments": arguments}

    monkeypatch.setattr(mcp_clients, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(mcp_clients, "ClientSession", FakeClientSession)

    client = await create_pooled_mcp_session(
        MCPTransportConfig(
            server_id="srv",
            transport_type="stdio",
            command="uvx",
            args=["provider-mcp"],
            env={"API_KEY": "secret"},
        )
    )

    assert client.config.pool_key() == "srv:stdio:uvx:provider-mcp"
    assert ("session", ("stdio-read", "stdio-write")) in calls
    assert ("initialize", None) in calls
    assert calls[0][0] == "stdio"
    assert calls[0][1].command == "uvx"
    assert calls[0][1].args == ["provider-mcp"]
    assert calls[0][1].env == {"API_KEY": "secret"}
    assert await client.call_tool("lookup", {"q": "x"}) == {
        "tool_name": "lookup",
        "arguments": {"q": "x"},
    }

    await client.close()
    assert ("session-close", None) in calls


@pytest.mark.asyncio
async def test_gateway_client_session_skips_invalid_schema_runtime_error(monkeypatch):
    from service.gateway import mcp_clients

    async def fake_validate(self, name, result):
        raise RuntimeError(f"Invalid schema for tool {name}: broken schema")

    monkeypatch.setattr(
        mcp_clients._SDKClientSession,
        "_validate_tool_result",
        fake_validate,
    )

    session = object.__new__(mcp_clients.ClientSession)

    await mcp_clients.ClientSession._validate_tool_result(session, "lookup", object())


@pytest.mark.asyncio
async def test_gateway_client_session_preserves_non_schema_runtime_errors(monkeypatch):
    from service.gateway import mcp_clients

    async def fake_validate(self, name, result):
        raise RuntimeError("Invalid structured content returned by tool lookup")

    monkeypatch.setattr(
        mcp_clients._SDKClientSession,
        "_validate_tool_result",
        fake_validate,
    )

    session = object.__new__(mcp_clients.ClientSession)

    with pytest.raises(RuntimeError, match="Invalid structured content"):
        await mcp_clients.ClientSession._validate_tool_result(session, "lookup", object())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_type", "transport_attr", "expected_key"),
    [
        ("sse", "sse_client", "srv:sse:https://provider.example/sse"),
        (
            "streamable_http",
            "streamablehttp_client",
            "srv:streamable_http:https://provider.example/mcp",
        ),
    ],
)
async def test_create_pooled_mcp_session_opens_remote_transports(
    monkeypatch, transport_type, transport_attr, expected_key
):
    from service.gateway import mcp_clients
    from service.gateway.mcp_clients import MCPTransportConfig, create_pooled_mcp_session

    calls: list[tuple[str, object]] = []

    @asynccontextmanager
    async def fake_remote_client(url, *, headers=None):
        calls.append((transport_type, {"url": url, "headers": headers}))
        if transport_type == "streamable_http":
            yield "remote-read", "remote-write", lambda: "session-id"
        else:
            yield "remote-read", "remote-write"

    class FakeClientSession:
        def __init__(self, read_stream, write_stream):
            calls.append(("session", (read_stream, write_stream)))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            calls.append(("session-close", None))

        async def initialize(self):
            calls.append(("initialize", None))

        async def call_tool(self, tool_name, arguments):
            return {"ok": True, "tool_name": tool_name, "arguments": arguments}

    monkeypatch.setattr(mcp_clients, transport_attr, fake_remote_client)
    monkeypatch.setattr(mcp_clients, "ClientSession", FakeClientSession)

    url = (
        "https://provider.example/sse"
        if transport_type == "sse"
        else "https://provider.example/mcp"
    )
    client = await create_pooled_mcp_session(
        MCPTransportConfig(
            server_id="srv",
            transport_type=transport_type,
            url=url,
            headers={"Authorization": "Bearer secret"},
        )
    )

    assert client.config.pool_key() == expected_key
    assert calls[0] == (
        transport_type,
        {"url": url, "headers": {"Authorization": "Bearer secret"}},
    )
    assert ("session", ("remote-read", "remote-write")) in calls
    assert ("initialize", None) in calls
    assert await client.call_tool("lookup", {"q": "x"}) == {
        "ok": True,
        "tool_name": "lookup",
        "arguments": {"q": "x"},
    }

    await client.close()
    assert ("session-close", None) in calls
