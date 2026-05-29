"""Tests for registry data contract types."""

from mcp_discovery.models.registry import RegistryRecord, RegistryToolEntry


def test_registry_record_round_trip():
    tool = RegistryToolEntry(
        tool_name="search_repos",
        description="Search GitHub repositories",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    record = RegistryRecord(
        server_id="github",
        name="GitHub MCP",
        description="GitHub integration tools",
        url="https://github.mcp.example.com",
        tags=["code", "search"],
        tools=[tool],
        registered_by="user-123",
    )
    assert record.server_id == "github"
    assert len(record.tools) == 1
    assert record.tools[0].tool_name == "search_repos"
    assert record.registered_by == "user-123"


def test_registry_tool_entry_optional_fields():
    tool = RegistryToolEntry(tool_name="my_tool")
    assert tool.description == ""
    assert tool.input_schema is None
