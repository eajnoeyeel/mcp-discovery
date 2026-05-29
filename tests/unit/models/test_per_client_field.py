"""Tests that per-client variants stay outside canonical MCPTool state."""

from mcp_discovery.models.core import MCPTool


class TestMCPToolPerClientVariants:
    def test_variants_are_not_a_canonical_tool_field(self) -> None:
        tool = MCPTool(
            server_id="github",
            tool_name="search",
            tool_id="github::search",
            description="Search repos",
        )
        assert "per_client_variants" not in MCPTool.model_fields
        assert not hasattr(tool, "per_client_variants")
