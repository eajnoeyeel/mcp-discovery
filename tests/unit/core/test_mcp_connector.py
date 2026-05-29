"""Tests for MCPDirectConnector — interface only for Phase 1."""

import pytest

from mcp_discovery.data.mcp_connector import MCPDirectConnector
from mcp_discovery.models import TOOL_ID_SEPARATOR

SAMPLE_TOOLS_RESPONSE = {
    "tools": [
        {
            "name": "search",
            "description": "Search for items",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
        {
            "name": "create",
            "description": "Create an item",
            "inputSchema": None,
        },
    ]
}


class TestParseTools:
    def test_parse_tools(self):
        tools = MCPDirectConnector.parse_tools("@test/server", SAMPLE_TOOLS_RESPONSE)
        assert len(tools) == 2
        assert tools[0].tool_id == f"@test/server{TOOL_ID_SEPARATOR}search"
        assert tools[0].tool_name == "search"
        assert tools[0].server_id == "@test/server"
        assert tools[0].description == "Search for items"

    def test_tool_id_format(self):
        tools = MCPDirectConnector.parse_tools("@my/srv", SAMPLE_TOOLS_RESPONSE)
        for tool in tools:
            assert TOOL_ID_SEPARATOR in tool.tool_id

    def test_empty_response(self):
        tools = MCPDirectConnector.parse_tools("@test/server", {"tools": []})
        assert tools == []

    def test_missing_tools_key(self):
        tools = MCPDirectConnector.parse_tools("@test/server", {})
        assert tools == []

    def test_skips_tool_with_missing_name(self):
        response = {
            "tools": [
                {"name": "valid_tool", "description": "ok"},
                {"description": "no name field here"},
                {"name": "", "description": "empty name"},
            ]
        }
        tools = MCPDirectConnector.parse_tools("@test/server", response)
        # Only "valid_tool" should remain — empty string is falsy
        assert len(tools) == 1
        assert tools[0].tool_name == "valid_tool"

    async def test_fetch_tools_raises_not_implemented(self):
        connector = MCPDirectConnector()
        with pytest.raises(NotImplementedError):
            await connector.fetch_tools("@test/server", "http://example.com")
