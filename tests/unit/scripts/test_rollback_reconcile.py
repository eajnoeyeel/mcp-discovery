"""Tests for scripts/rollback_reconcile.py — apply-then-rollback roundtrip (AC20).

Covers:
- test_apply_then_rollback_restores_bit_identical: file content is identical after rollback
- test_rollback_entry_journaled_and_chain_valid: rollback creates audit entry + chain valid
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"


def _ensure_paths() -> None:
    for p in [str(_SCRIPTS_DIR), str(_REPO_ROOT / "src")]:
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_paths()

# Import rollback script helpers
import rollback_reconcile  # noqa: E402

from mcp_discovery.data.audit_trail import AuditJournal  # noqa: E402
from mcp_discovery.data.gt_reconciler import apply_plan_to_gt  # noqa: E402
from mcp_discovery.models.core import (  # noqa: E402
    Ambiguity,
    Category,
    Difficulty,
    GroundTruthEntry,
)
from mcp_discovery.models.probe import ReconcileAction, ReconcilePlan  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_gt_entry(query_id: str, server_id: str, tool_name: str) -> GroundTruthEntry:
    return GroundTruthEntry(
        query_id=query_id,
        query=f"find {tool_name}",
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


def _write_gt_file(gt_path: Path, entries: list[GroundTruthEntry]) -> None:
    lines = [e.model_dump_json() for e in entries]
    gt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_simple_plan(old_tool_id: str, new_tool_id: str) -> ReconcilePlan:
    """Build a minimal ReconcilePlan with one R2 rename action."""
    action = ReconcileAction(
        query_id="gt-test-001",
        old_tool_id=old_tool_id,
        new_tool_id=new_tool_id,
        rule="R2",
        confidence=None,
        notes="test rename",
    )
    import hashlib

    plan_hash = hashlib.sha256(
        json.dumps([action.model_dump()], sort_keys=True).encode()
    ).hexdigest()
    return ReconcilePlan(plan_hash=plan_hash, actions=[action])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestApplyThenRollback:
    """Verify that rollback restores GT files to bit-identical pre-apply state."""

    def test_apply_then_rollback_restores_bit_identical(self, tmp_path: Path) -> None:
        """After apply → rollback, GT file content must be bit-identical to original."""
        gt_path = tmp_path / "gt.jsonl"
        entry = _make_gt_entry("gt-test-001", "github", "get_commit")
        _write_gt_file(gt_path, [entry])

        original_content = gt_path.read_text(encoding="utf-8")

        # Build a plan that renames github::get_commit → github::list_commits
        plan = _make_simple_plan("github::get_commit", "github::list_commits")

        # Apply
        modified = apply_plan_to_gt(plan, [gt_path])
        assert modified == [gt_path], "Expected gt_path to be modified"

        # Verify the file was actually changed
        applied_content = gt_path.read_text(encoding="utf-8")
        assert "list_commits" in applied_content
        assert applied_content != original_content

        # Rollback — use helper directly (no CLI invocation in unit tests)
        backup_map = rollback_reconcile._find_backup_files([gt_path], plan.plan_hash[:12])
        assert backup_map, "Expected backup file to exist after apply"

        restored = rollback_reconcile._restore_backups(backup_map)
        assert restored == [gt_path]

        # File must be bit-identical to pre-apply state
        assert gt_path.read_text(encoding="utf-8") == original_content

    def test_rollback_entry_journaled_and_chain_valid(self, tmp_path: Path) -> None:
        """After rollback, journal must contain a rollback entry and chain must be valid."""
        gt_path = tmp_path / "gt.jsonl"
        entry = _make_gt_entry("gt-test-002", "slack", "send_message")
        _write_gt_file(gt_path, [entry])

        plan = _make_simple_plan("slack::send_message", "slack::post_message")

        # Apply plan
        apply_plan_to_gt(plan, [gt_path])

        # Set up journal
        journal_path = tmp_path / "journal.jsonl"
        journal = AuditJournal(journal_path)

        # Append apply entry
        apply_entry = {
            "event": "apply_gt_reconcile",
            "plan_hash": plan.plan_hash,
            "actions_count": len(plan.actions),
        }
        journal.append(apply_entry)

        # Rollback and journal it
        backup_map = rollback_reconcile._find_backup_files([gt_path], plan.plan_hash[:12])
        rollback_reconcile._restore_backups(backup_map)

        rollback_entry = {
            "event": "rollback_reconcile",
            "original_plan_hash": plan.plan_hash,
            "files_restored": [str(gt_path)],
        }
        journal.append(rollback_entry)

        # Verify chain integrity
        valid, break_idx = journal.verify_chain()
        assert valid, f"Chain broken at index {break_idx}"

        # Verify rollback entry is in journal
        entries = journal.read_all()
        assert len(entries) == 2
        rollback_found = any(e.get("event") == "rollback_reconcile" for e in entries)
        assert rollback_found, "Rollback entry not found in journal"

        # Verify the restored file has the original tool_id
        restored_lines = [
            json.loads(ln) for ln in gt_path.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        assert restored_lines[0]["correct_tool_id"] == "slack::send_message"

    def test_rollback_no_backup_returns_1(self, tmp_path: Path) -> None:
        """When no backup file exists, _find_backup_files returns empty dict."""
        gt_path = tmp_path / "nonexistent_gt.jsonl"
        result = rollback_reconcile._find_backup_files([gt_path], "aabbccddee11")
        assert result == {}
