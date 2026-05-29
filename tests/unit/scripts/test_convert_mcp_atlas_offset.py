"""Tests for incremental GT generation support in convert_mcp_atlas.py."""

from convert_mcp_atlas import build_ground_truth_entry


def test_build_ground_truth_entry_with_high_task_index():
    """task_index=81 should produce query_id 'gt-atlas-081-s00'."""
    entry = build_ground_truth_entry(
        task_id="test",
        task_index=81,
        step_index=0,
        tool_call_name="github_search_repositories",
        query="test query",
        prompt="test prompt",
    )
    assert entry["query_id"] == "gt-atlas-081-s00"


def test_build_ground_truth_entry_step_continuity():
    """task_index=81, step_index=5 should produce query_id 'gt-atlas-081-s05'."""
    entry = build_ground_truth_entry(
        task_id="test",
        task_index=81,
        step_index=5,
        tool_call_name="github_create_issue",
        query="test query",
        prompt="test prompt",
    )
    assert entry["query_id"] == "gt-atlas-081-s05"


def test_build_ground_truth_entry_remap():
    """Remapped tool should use actual server tool name."""
    entry = build_ground_truth_entry(
        task_id="test",
        task_index=1,
        step_index=0,
        tool_call_name="filesystem_read_text_file",
        query="read a file",
        prompt="test prompt",
    )
    assert entry is not None
    assert entry["correct_tool_id"] == "filesystem::read_file"


def test_build_ground_truth_entry_unmappable_returns_none():
    """Unmappable tool (no match in server) should return None."""
    entry = build_ground_truth_entry(
        task_id="test",
        task_index=1,
        step_index=0,
        tool_call_name="github_get_repository",
        query="get repo info",
        prompt="test prompt",
    )
    assert entry is None
