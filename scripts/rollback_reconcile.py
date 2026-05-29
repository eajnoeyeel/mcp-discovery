"""Rollback a previously applied ReconcilePlan (ADR-0018).

Reads a plan JSON (or finds the latest journal entry) and inverts the
applied actions by restoring `*.bak-pre-reconcile-<plan_hash[:12]>` backup
files.  The rollback itself is appended to the audit journal as a new entry
so the rollback is itself auditable.

Usage:
    # Rollback via plan file:
    uv run python scripts/rollback_reconcile.py --plan /tmp/plan.json

    # Rollback the most recent journal entry (requires --plan or --journal-index):
    uv run python scripts/rollback_reconcile.py \\
      --journal-index -1 \\
      --gt data/ground_truth/seed_set.jsonl data/ground_truth/mcp_atlas.jsonl

Exit codes:
    0  — success
    1  — rollback failed (backup files missing, plan invalid)
    2  — user error
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger

from mcp_discovery.data.audit_trail import AuditJournal
from mcp_discovery.models.probe import ReconcilePlan

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_JOURNAL = _REPO_ROOT / "data" / "probes" / "journal.jsonl"
_DEFAULT_GT_PATHS = [
    _REPO_ROOT / "data" / "ground_truth" / "synthetic.jsonl",
    _REPO_ROOT / "data" / "ground_truth" / "mcp_atlas.jsonl",
]

# ---------------------------------------------------------------------------
# Core rollback logic
# ---------------------------------------------------------------------------


def _find_backup_files(gt_paths: list[Path], plan_hash_prefix: str) -> dict[Path, Path]:
    """Map gt_path → backup_path for every backup matching the plan hash prefix.

    Returns an empty dict if no backups are found.
    """
    result: dict[Path, Path] = {}
    for gt_path in gt_paths:
        backup_path = gt_path.with_name(
            f"{gt_path.name}.bak-pre-reconcile-{plan_hash_prefix}"
        )
        if backup_path.exists():
            result[gt_path] = backup_path
    return result


def _restore_backups(backup_map: dict[Path, Path]) -> list[Path]:
    """Restore backup files to their original paths. Returns list of restored paths."""
    restored: list[Path] = []
    for original, backup in backup_map.items():
        content = backup.read_text(encoding="utf-8")
        original.write_text(content, encoding="utf-8")
        logger.info(f"Restored {original} from {backup}")
        restored.append(original)
    return restored


def _load_plan(plan_path: Path) -> ReconcilePlan:
    if not plan_path.exists():
        logger.error(f"Plan file not found: {plan_path}")
        sys.exit(1)
    try:
        return ReconcilePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error(f"Invalid plan file {plan_path}: {exc}")
        sys.exit(1)


def _plan_hash_from_journal_index(journal: AuditJournal, index: int) -> str:
    """Extract plan_hash from a journal entry at position ``index``."""
    entries = journal.read_all()
    if not entries:
        logger.error("Journal is empty — no entries to roll back")
        sys.exit(1)
    try:
        entry = entries[index]
    except IndexError:
        logger.error(
            f"Journal index {index} out of range (journal has {len(entries)} entries)"
        )
        sys.exit(1)
    plan_hash = entry.get("plan_hash")
    if not plan_hash:
        logger.error(f"Journal entry at index {index} has no 'plan_hash' field: {entry}")
        sys.exit(1)
    return plan_hash


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rollback a previously applied ReconcilePlan (ADR-0018).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="ReconcilePlan JSON file whose application should be rolled back",
    )
    source_group.add_argument(
        "--journal-index",
        type=int,
        default=None,
        help="0-based index into the journal (use -1 for the most recent entry)",
    )

    parser.add_argument(
        "--gt",
        type=Path,
        nargs="+",
        default=_DEFAULT_GT_PATHS,
        help="GT JSONL files to restore (must match files from original apply run)",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=_DEFAULT_JOURNAL,
        help="Audit journal path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be restored without writing files",
    )

    args = parser.parse_args()

    # Determine plan_hash
    if args.plan is not None:
        plan = _load_plan(args.plan)
        plan_hash = plan.plan_hash
        plan_info = {
            "plan_hash": plan.plan_hash,
            "created_at": plan.created_at.isoformat(),
            "actions_count": len(plan.actions),
        }
    else:
        journal = AuditJournal(args.journal)
        plan_hash = _plan_hash_from_journal_index(journal, args.journal_index)
        plan_info = {"plan_hash": plan_hash, "source": f"journal_index={args.journal_index}"}

    plan_hash_prefix = plan_hash[:12]
    logger.info(f"Rolling back plan {plan_hash_prefix}...")

    # Find backup files
    existing_gt_paths = [p for p in args.gt if p.exists()]
    backup_map = _find_backup_files(existing_gt_paths, plan_hash_prefix)

    if not backup_map:
        logger.error(
            f"No backup files found matching pattern "
            f"*.bak-pre-reconcile-{plan_hash_prefix} "
            f"for GT paths: {[str(p) for p in existing_gt_paths]}"
        )
        return 1

    logger.info(f"Found {len(backup_map)} backup file(s) to restore:")
    for original, backup in backup_map.items():
        logger.info(f"  {backup} → {original}")

    if args.dry_run:
        logger.info("[DRY-RUN] No files restored")
        return 0

    restored = _restore_backups(backup_map)

    # Append rollback entry to journal (rollback is itself auditable)
    journal = AuditJournal(args.journal)
    rollback_entry = {
        "event": "rollback_reconcile",
        "original_plan_hash": plan_hash,
        "files_restored": [str(p) for p in restored],
        **{k: v for k, v in plan_info.items() if k != "plan_hash"},
    }
    journal_hash = journal.append(rollback_entry)

    logger.info(
        f"Rollback complete: {len(restored)} file(s) restored. "
        f"Journal entry hash: {journal_hash[:16]}..."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
