"""Verify the integrity of the audit journal hash chain (ADR-0018).

Wraps ``AuditJournal.verify_chain()`` as a CLI tool.

Usage:
    uv run python scripts/verify_audit_trail.py

    # Limit to entries after a git ref (informational — chain is always verified in full):
    uv run python scripts/verify_audit_trail.py --since HEAD~3

Exit codes:
    0  — chain is valid (or journal is empty)
    1  — chain is broken; first-break index printed to stderr
    2  — user error
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger

from mcp_discovery.data.audit_trail import AuditJournal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_JOURNAL = _REPO_ROOT / "data" / "probes" / "journal.jsonl"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify AuditJournal hash chain integrity (ADR-0018).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=_DEFAULT_JOURNAL,
        help="Audit journal JSONL file to verify",
    )
    parser.add_argument(
        "--since",
        metavar="GIT-REF",
        default=None,
        help=(
            "Advisory: show git log since this ref for context. "
            "The hash chain is ALWAYS verified in full regardless of this flag."
        ),
    )

    args = parser.parse_args()

    if not args.journal.exists():
        logger.info(f"Journal does not exist yet: {args.journal} — chain trivially valid")
        return 0

    journal = AuditJournal(args.journal)
    entry_count = len(journal)
    logger.info(f"Verifying chain of {entry_count} entry(ies) in {args.journal}...")

    if args.since:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"{args.since}..HEAD"],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(_REPO_ROOT),
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.info(f"Git commits since {args.since}:\n{result.stdout.strip()}")
            elif result.returncode != 0:
                logger.warning(f"git log --since={args.since} failed: {result.stderr.strip()}")
        except FileNotFoundError:
            logger.warning("git not found in PATH — skipping --since git log")

    valid, break_idx = journal.verify_chain()

    if valid:
        logger.info(f"Chain OK: {entry_count} entries verified successfully")
        return 0

    logger.error(
        f"Chain BROKEN at index {break_idx} "
        f"(0-based, out of {entry_count} entries)"
    )
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
