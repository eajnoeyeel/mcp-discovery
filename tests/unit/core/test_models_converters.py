"""Tests for data contract converters."""

from mcp_discovery.models.canonical import EntityStatus
from mcp_discovery.models.converters import (
    registry_to_canonical_server,
    registry_to_canonical_tools,
)
from mcp_discovery.models.registry import RegistryRecord, RegistryToolEntry


def test_registry_to_canonical_tools():
    record = RegistryRecord(
        server_id="github",
        name="GitHub MCP",
        tools=[
            RegistryToolEntry(tool_name="search_repos", description="Search GitHub repositories"),
            RegistryToolEntry(tool_name="create_issue", description="Create a GitHub issue"),
        ],
    )
    tools = registry_to_canonical_tools(record)
    assert len(tools) == 2
    assert tools[0].tool_id == "github::search_repos"
    assert tools[0].server_id == "github"
    assert tools[0].entity_status == EntityStatus.ACTIVE
    assert tools[0].content_hash is not None
    assert tools[1].tool_id == "github::create_issue"


def test_content_hash_populated():
    record = RegistryRecord(
        server_id="s1",
        name="Server",
        tools=[RegistryToolEntry(tool_name="t1", description="desc")],
    )
    tools = registry_to_canonical_tools(record)
    assert tools[0].content_hash is not None
    assert len(tools[0].content_hash) == 64


def test_registry_to_canonical_server():
    record = RegistryRecord(
        server_id="github",
        name="GitHub MCP",
        description="GitHub integration tools",
        url="https://github.mcp.example.com",
        tags=["code", "search"],
        registered_by="user-123",
    )
    server = registry_to_canonical_server(record)
    assert server.server_id == "github"
    assert server.name == "GitHub MCP"
    assert server.description == "GitHub integration tools"
    assert server.url == "https://github.mcp.example.com"
    assert server.tags == ["code", "search"]


def test_registry_to_canonical_server_empty_strings_become_none():
    record = RegistryRecord(
        server_id="s1",
        name="Server",
        description="",
        url="",
    )
    server = registry_to_canonical_server(record)
    assert server.description is None
    assert server.url is None


def test_registry_to_canonical_tools_empty_description_becomes_none():
    record = RegistryRecord(
        server_id="s1",
        name="Server",
        tools=[RegistryToolEntry(tool_name="t1", description="")],
    )
    tools = registry_to_canonical_tools(record)
    assert tools[0].description is None
