"""Data contract types for MCP Discovery Platform.

Backward compatibility: all existing types are re-exported from core.
"""

from mcp_discovery.models.core import (
    TOOL_ID_SEPARATOR,
    Ambiguity,
    Category,
    Difficulty,
    FindBestToolRequest,
    FindBestToolResponse,
    GroundTruthEntry,
    MCPServer,
    MCPServerSummary,
    MCPTool,
    ScoreBreakdown,
    SearchResult,
)

__all__ = [
    "TOOL_ID_SEPARATOR",
    "Ambiguity",
    "Category",
    "Difficulty",
    "FindBestToolRequest",
    "FindBestToolResponse",
    "GroundTruthEntry",
    "MCPServer",
    "MCPServerSummary",
    "MCPTool",
    "ScoreBreakdown",
    "SearchResult",
]
