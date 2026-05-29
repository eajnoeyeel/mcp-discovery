"""Unit tests for scripts/validate_pool_gt_alignment.py."""

import json
from pathlib import Path

import pytest


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


@pytest.fixture
def pool(tmp_path: Path) -> Path:
    p = tmp_path / "pool.jsonl"
    _write_jsonl(
        p,
        [
            {
                "server_id": "myserver",
                "name": "My Server",
                "description": "test",
                "tools": [
                    {
                        "server_id": "myserver",
                        "tool_name": "my_tool",
                        "tool_id": "myserver::my_tool",
                        "description": "d",
                    }
                ],
            }
        ],
    )
    return p


@pytest.fixture
def gt_aligned(tmp_path: Path) -> Path:
    p = tmp_path / "gt_aligned.jsonl"
    _write_jsonl(
        p,
        [
            {
                "query_id": "gt-test-0001",
                "correct_server_id": "myserver",
                "correct_tool_id": "myserver::my_tool",
            }
        ],
    )
    return p


@pytest.fixture
def gt_missing_tool(tmp_path: Path) -> Path:
    p = tmp_path / "gt_missing.jsonl"
    _write_jsonl(
        p,
        [
            {
                "query_id": "gt-test-0002",
                "correct_server_id": "myserver",
                "correct_tool_id": "myserver::nonexistent_tool",
            }
        ],
    )
    return p


@pytest.fixture
def gt_bad_separator(tmp_path: Path) -> Path:
    p = tmp_path / "gt_bad_sep.jsonl"
    _write_jsonl(
        p,
        [
            {
                "query_id": "gt-test-0003",
                "correct_server_id": "myserver",
                "correct_tool_id": "myserver/my_tool",
            }
        ],
    )
    return p


@pytest.fixture
def gt_missing_server(tmp_path: Path) -> Path:
    p = tmp_path / "gt_missing_server.jsonl"
    _write_jsonl(
        p,
        [
            {
                "query_id": "gt-test-0004",
                "correct_server_id": "ghost_server",
                "correct_tool_id": "ghost_server::some_tool",
            }
        ],
    )
    return p


def test_aligned_returns_no_errors(pool, gt_aligned):
    from scripts.validate_pool_gt_alignment import validate

    errors = validate(pool_path=pool, gt_paths=[gt_aligned])
    assert errors == []


def test_missing_tool_returns_error(pool, gt_missing_tool):
    from scripts.validate_pool_gt_alignment import validate

    errors = validate(pool_path=pool, gt_paths=[gt_missing_tool])
    assert any("nonexistent_tool" in e for e in errors)


def test_bad_separator_returns_error(pool, gt_bad_separator):
    from scripts.validate_pool_gt_alignment import validate

    errors = validate(pool_path=pool, gt_paths=[gt_bad_separator])
    assert any("separator" in e for e in errors)


def test_missing_server_returns_error(pool, gt_missing_server):
    from scripts.validate_pool_gt_alignment import validate

    errors = validate(pool_path=pool, gt_paths=[gt_missing_server])
    assert any("ghost_server" in e for e in errors)


def test_missing_gt_file_is_skipped(pool, tmp_path):
    from scripts.validate_pool_gt_alignment import validate

    nonexistent = tmp_path / "does_not_exist.jsonl"
    errors = validate(pool_path=pool, gt_paths=[nonexistent])
    assert errors == []
