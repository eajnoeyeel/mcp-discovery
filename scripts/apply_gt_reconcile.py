"""Apply a saved ReconcilePlan to GT JSONL files (ADR-0018).

Reads a plan JSON produced by refresh_pool.py, writes
``*.bak-pre-reconcile-<plan_hash[:12]>`` backups BEFORE modifying each GT
file, then applies the plan in-place.

Usage:
    uv run python scripts/apply_gt_reconcile.py --plan /tmp/plan.json

    # Override GT paths:
    uv run python scripts/apply_gt_reconcile.py \\
      --plan /tmp/plan.json \\
      --gt data/ground_truth/seed_set.jsonl data/ground_truth/mcp_atlas.jsonl

Exit codes:
    0  — success
    1  — plan file not found or invalid
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
from mcp_discovery.data.gt_reconciler import apply_plan_to_gt, serialize_plan_report
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
# Helpers
# ---------------------------------------------------------------------------


def _load_plan(plan_path: Path) -> ReconcilePlan:
    """Load and validate a ReconcilePlan from JSON. Exits on failure."""
    if not plan_path.exists():
        logger.error(f"Plan file not found: {plan_path}")
        sys.exit(1)
    try:
        return ReconcilePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error(f"Invalid plan file {plan_path}: {exc}")
        sys.exit(1)


def _print_summary(
    plan: ReconcilePlan,
    modified_paths: list[Path],
    *,
    dry_run: bool,
    journal_hash: str | None = None,
) -> None:
    rule_counts: dict[str, int] = {}
    for action in plan.actions:
        rule_counts[action.rule] = rule_counts.get(action.rule, 0) + 1

    prefix = "[DRY-RUN] " if dry_run else "[APPLIED] "
    lines = [
        "",
        f"{prefix}apply_gt_reconcile Summary",
        "=" * 50,
        f"  Plan hash:                       {plan.plan_hash[:16]}...",
        f"  Added (R1 preserve, R2 manual):  {rule_counts.get('R1', 0) + rule_counts.get('R2', 0)}",
        f"  Renamed (R3 fuzzy):              {rule_counts.get('R3', 0)}",
        f"  Server-renamed (R4):             {rule_counts.get('R4', 0)}",
        f"  Dropped (R5):                    {rule_counts.get('R5', 0)}",
        f"  Total actions:                   {len(plan.actions)}",
        f"  Review queue (manual required):  {len(plan.review_queue)}",
        f"  GT files modified:               {len(modified_paths)}",
    ]
    if journal_hash:
        lines.append(f"  Journal entry hash:              {journal_hash[:16]}...")
    lines.append("")
    for line in lines:
        logger.info(line)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply a saved ReconcilePlan JSON to GT JSONL files (ADR-0018).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--plan",
        type=Path,
        required=True,
        help="Path to ReconcilePlan JSON file (produced by refresh_pool.py)",
    )
    parser.add_argument(
        "--gt",
        type=Path,
        nargs="+",
        default=_DEFAULT_GT_PATHS,
        help="GT JSONL files to apply the plan to",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without writing files (default: apply)",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=_DEFAULT_JOURNAL,
        help="Audit journal path",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=None,
        help="Write markdown plan report to this path",
    )

    args = parser.parse_args()

    plan = _load_plan(args.plan)
    logger.info(
        f"Loaded plan {plan.plan_hash[:12]} "
        f"with {len(plan.actions)} action(s), "
        f"{len(plan.review_queue)} review_queue item(s)"
    )

    existing_gt_paths = [p for p in args.gt if p.exists()]
    if not existing_gt_paths:
        logger.warning("No GT files found at specified paths — nothing to apply")
        return 0

    if args.output_report:
        serialize_plan_report(plan, args.output_report)

    if args.dry_run:
        _print_summary(plan, [], dry_run=True)
        logger.info("Dry-run complete — no files modified")
        return 0

    modified = apply_plan_to_gt(plan, existing_gt_paths)
    logger.info(f"Plan applied: {len(modified)} GT file(s) modified")

    journal = AuditJournal(args.journal)
    entry = {
        "event": "apply_gt_reconcile",
        "plan_hash": plan.plan_hash,
        "plan_created_at": plan.created_at.isoformat(),
        "actions_count": len(plan.actions),
        "review_queue_count": len(plan.review_queue),
        "gt_files_modified": [str(p) for p in modified],
    }
    journal_hash = journal.append(entry)

    _print_summary(plan, modified, dry_run=False, journal_hash=journal_hash)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
