"""Direct MCP connector — interface only for Phase 1. Full implementation in Phase 4+."""

from loguru import logger

from mcp_discovery.models import TOOL_ID_SEPARATOR, MCPTool


class MCPDirectConnector:
    """Connects directly to MCP servers via JSON-RPC tools/list.

    Phase 1: only parse_tools is implemented.
    Phase 4+: fetch_tools will make actual JSON-RPC calls.
    """

    async def fetch_tools(self, server_id: str, endpoint_url: str) -> list[MCPTool]:
        raise NotImplementedError("Direct MCP connection is planned for Phase 4+")

    @staticmethod
    def parse_tools(server_id: str, response: dict) -> list[MCPTool]:
        raw_tools = response.get("tools", [])
        tools = []
        for t in raw_tools:
            name = t.get("name")
            if not name:
                logger.warning(f"Skipping tool with missing name in server '{server_id}'")
                continue
            tools.append(
                MCPTool(
                    server_id=server_id,
                    tool_name=name,
                    tool_id=f"{server_id}{TOOL_ID_SEPARATOR}{name}",
                    description=t.get("description"),
                    input_schema=t.get("inputSchema"),
                )
            )
        return tools
