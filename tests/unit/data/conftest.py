"""Shared fixtures for tests/unit/data/."""

from __future__ import annotations

from mcp_discovery.models.core import Ambiguity, Category, Difficulty, GroundTruthEntry, MCPTool


def make_gt_entry(
    query_id: str,
    server_id: str,
    tool_name: str,
    query: str = "test query",
) -> GroundTruthEntry:
    """Helper to build a minimal valid GroundTruthEntry for tests."""
    return GroundTruthEntry(
        query_id=query_id,
        query=query,
        correct_server_id=server_id,
        correct_tool_id=f"{server_id}::{tool_name}",
        difficulty=Difficulty.EASY,
        category=Category.GENERAL,
        ambiguity=Ambiguity.LOW,
        source="llm_synthetic",
        manually_verified=False,
        author="test",
        created_at="2026-04-19",
    )


def make_tool(server_id: str, tool_name: str) -> MCPTool:
    """Helper to build a minimal MCPTool."""
    return MCPTool(
        server_id=server_id,
        tool_name=tool_name,
        tool_id=f"{server_id}::{tool_name}",
        description=f"Tool {tool_name} on {server_id}",
    )
