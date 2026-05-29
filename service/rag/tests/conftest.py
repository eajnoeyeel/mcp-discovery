from mcp_discovery.models import MCPTool, SearchResult


def make_tool(server_id: str = "srv1", tool_name: str = "tool_a") -> MCPTool:
    return MCPTool(
        server_id=server_id,
        tool_name=tool_name,
        tool_id=f"{server_id}::{tool_name}",
        description=f"Description for {tool_name}",
    )


def make_result(
    server_id: str = "srv1",
    tool_name: str = "tool_a",
    score: float = 0.9,
    rank: int = 1,
) -> SearchResult:
    return SearchResult(
        tool=make_tool(server_id, tool_name),
        score=score,
        rank=rank,
    )
