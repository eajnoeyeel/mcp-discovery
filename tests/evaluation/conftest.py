"""Shared test fixtures for evaluation tests."""

from __future__ import annotations

import pytest

from mcp_discovery.evaluation.metrics import PerQueryResult
from mcp_discovery.models import GroundTruthEntry, MCPTool, SearchResult


@pytest.fixture()
def make_tool_fn():
    """Factory for MCPTool instances."""
    return _make_tool


@pytest.fixture()
def make_result_fn():
    """Factory for SearchResult instances."""
    return _make_result


@pytest.fixture()
def make_gt_fn():
    """Factory for GroundTruthEntry instances."""
    return _make_gt


@pytest.fixture()
def make_pq_fn():
    """Factory for PerQueryResult instances."""
    return _make_pq


@pytest.fixture()
def make_entry_fn():
    """Factory for GroundTruthEntry instances (harness-style)."""
    return _make_entry


# ── Plain helpers (usable without fixtures) ──────────────────────────────────


def _make_tool(tool_id: str) -> MCPTool:
    server_id, tool_name = tool_id.split("::", 1)
    return MCPTool(
        tool_id=tool_id,
        server_id=server_id,
        tool_name=tool_name,
        description=f"Description for {tool_name}",
    )


def _make_result(tool_id: str, score: float, rank: int) -> SearchResult:
    return SearchResult(tool=_make_tool(tool_id), score=score, rank=rank)


def _make_gt(
    correct_tool_id: str,
    alternative_tools: list[str] | None = None,
) -> GroundTruthEntry:
    server_id = correct_tool_id.split("::")[0]
    return GroundTruthEntry(
        query_id="gt-test-001",
        query="test query",
        correct_server_id=server_id,
        correct_tool_id=correct_tool_id,
        difficulty="easy",
        category="general",
        ambiguity="low",
        source="manual_seed",
        manually_verified=True,
        author="test",
        created_at="2026-03-26",
        alternative_tools=alternative_tools,
    )


def _make_pq(
    query_id: str = "q1",
    top_1_correct: bool = True,
    in_top_k: bool = True,
    rank_of_correct: int | None = 1,
    confidence: float = 0.9,
    retrieved_tool_ids: tuple[str, ...] | None = None,
    correct_server_in_top_k: bool = False,
) -> PerQueryResult:
    return PerQueryResult(
        query_id=query_id,
        top_1_correct=top_1_correct,
        in_top_k=in_top_k,
        rank_of_correct=rank_of_correct,
        confidence=confidence,
        latency_ms=10.0,
        retrieved_tool_ids=retrieved_tool_ids or ("srv::a",),
        correct_server_in_top_k=correct_server_in_top_k,
    )


def _make_entry(
    query_id: str = "gt-test-001",
    correct_tool_id: str = "srv1::tool_a",
    query: str = "find tool a",
) -> GroundTruthEntry:
    server_id = correct_tool_id.split("::")[0]
    return GroundTruthEntry(
        query_id=query_id,
        query=query,
        correct_server_id=server_id,
        correct_tool_id=correct_tool_id,
        difficulty="easy",
        category="general",
        ambiguity="low",
        source="manual_seed",
        manually_verified=True,
        author="test",
        created_at="2026-03-26",
        alternative_tools=None,
    )
