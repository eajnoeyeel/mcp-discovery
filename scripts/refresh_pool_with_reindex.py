"""Escape hatch: refresh pool AND allow Qdrant reindexing (ADR-0018).

This script is identical to refresh_pool.py EXCEPT it bypasses the
BASELINE_IMPACT_REFUSED guard.  It REQUIRES an explicit
`--confirm-baseline-resuperseded ADR-NNNN` argument whose value must:

  1. Match regex ^ADR-\\d{4}$
  2. Correspond to an existing file at docs/adr/{arg}.md

Both checks enforce that a proper ADR exists and has been committed before
baseline invalidation is permitted.  Never bypass with --no-verify.

Usage:
    uv run python scripts/refresh_pool_with_reindex.py \\
      --confirm-baseline-resuperseded ADR-0019 \\
      --servers-from data/probes/targeted_set.txt \\
      --output-plan /tmp/plan.json

Exit codes:
    0  — success
    1  — guard rejected (missing/malformed ADR arg or ADR file not found)
    2  — user error / bad arguments
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import yaml
from loguru import logger

from mcp_discovery.data.audit_trail import AuditJournal
from mcp_discovery.data.ground_truth import merge_ground_truth
from mcp_discovery.data.gt_reconciler import build_reconcile_plan, serialize_plan_report
from mcp_discovery.data.pool_prober import probe_servers
from mcp_discovery.data.transport_spec import load_transports_yaml
from mcp_discovery.models.core import GroundTruthEntry, MCPServer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_ADR_ARG_RE = re.compile(r"^ADR-\d{4}$")

_DEFAULT_TRANSPORTS_YAML = _REPO_ROOT / "src" / "mcp_discovery" / "data" / "transports.yaml"
_DEFAULT_MANUAL_REMAPS = _REPO_ROOT / "data" / "probes" / "manual_remaps.yaml"
_DEFAULT_TARGETED_SET = _REPO_ROOT / "data" / "probes" / "targeted_set.txt"
_DEFAULT_JOURNAL = _REPO_ROOT / "data" / "probes" / "journal.jsonl"
_DEFAULT_POOL = _REPO_ROOT / "data" / "raw" / "mcp_zero_servers.jsonl"
_DEFAULT_GT_PATHS = [
    _REPO_ROOT / "data" / "ground_truth" / "synthetic.jsonl",
    _REPO_ROOT / "data" / "ground_truth" / "mcp_atlas.jsonl",
]
_DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "probes" / ".cache"

# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


def _validate_adr_arg(arg: str) -> Path:
    """Validate --confirm-baseline-resuperseded value.

    Returns the resolved ADR file Path if valid.
    Raises SystemExit(1) on any failure.
    """
    if not _ADR_ARG_RE.match(arg):
        logger.error(
            f"--confirm-baseline-resuperseded value '{arg}' does not match ^ADR-\\d{{4}}$. "
            "Example valid value: ADR-0019"
        )
        sys.exit(1)

    adr_path = _REPO_ROOT / "docs" / "adr" / f"{arg}.md"
    if not adr_path.exists():
        logger.error(
            f"ADR file not found: {adr_path}. "
            "The ADR must be committed before baseline invalidation is permitted."
        )
        sys.exit(1)

    logger.info(f"ADR guard passed: {adr_path} exists")
    return adr_path


# ---------------------------------------------------------------------------
# Helpers (duplicated minimally from refresh_pool.py — intentionally self-contained)
# ---------------------------------------------------------------------------


def _load_server_ids_from_file(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _load_pool_from_jsonl(pool_path: Path) -> list[MCPServer]:
    servers: list[MCPServer] = []
    if not pool_path.exists():
        logger.warning(f"Pool file not found: {pool_path} — using empty pool")
        return servers
    for line in pool_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            servers.append(MCPServer.model_validate_json(line))
        except Exception as exc:
            logger.warning(f"Skipping malformed pool line: {exc}")
    return servers


def _load_manual_remaps(remaps_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    if not remaps_path.exists():
        logger.warning(f"manual_remaps.yaml not found at {remaps_path} — using empty remaps")
        return {}, {}
    raw = yaml.safe_load(remaps_path.read_text(encoding="utf-8")) or {}
    tool_remaps: dict[str, str] = raw.get("tool_remaps", {}) or {}
    server_remaps: dict[str, str] = raw.get("server_remaps", {}) or {}
    return tool_remaps, server_remaps


def _print_summary(plan_dict: dict, *, dry_run: bool, journal_hash: str | None = None) -> None:
    actions = plan_dict.get("actions", [])
    review_queue = plan_dict.get("review_queue", [])
    plan_hash = plan_dict.get("plan_hash", "")
    rule_counts: dict[str, int] = {}
    for action in actions:
        r = action.get("rule", "?")
        rule_counts[r] = rule_counts.get(r, 0) + 1
    prefix = "[DRY-RUN] " if dry_run else "[APPLIED] "
    lines = [
        "",
        f"{prefix}Pool↔GT Reconcile Summary (WITH REINDEX)",
        "=" * 50,
        f"  Added (R1 preserve, R2 manual):  {rule_counts.get('R1', 0) + rule_counts.get('R2', 0)}",
        f"  Renamed (R3 fuzzy):              {rule_counts.get('R3', 0)}",
        f"  Server-renamed (R4):             {rule_counts.get('R4', 0)}",
        f"  Dropped (R5):                    {rule_counts.get('R5', 0)}",
        f"  Total actions:                   {len(actions)}",
        f"  Review queue (manual required):  {len(review_queue)}",
        f"  Plan hash:                       {plan_hash[:16]}...",
    ]
    if journal_hash:
        lines.append(f"  Journal entry hash:              {journal_hash[:16]}...")
    lines.append("")
    for line in lines:
        logger.info(line)


# ---------------------------------------------------------------------------
# Main async logic
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Escape-hatch refresh that permits Qdrant reindexing. "
            "Requires --confirm-baseline-resuperseded ADR-NNNN "
            "and an existing docs/adr/ADR-NNNN.md. (ADR-0018 FC3)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--confirm-baseline-resuperseded",
        required=True,
        metavar="ADR-NNNN",
        help=(
            "ADR identifier that supersedes the baseline "
            "(must match ^ADR-\\d{4}$ and exist as docs/adr/<value>.md)"
        ),
    )
    parser.add_argument("--servers-from", type=Path, default=_DEFAULT_TARGETED_SET)
    parser.add_argument("--transports", type=Path, default=_DEFAULT_TRANSPORTS_YAML)
    parser.add_argument("--manual-remaps", type=Path, default=_DEFAULT_MANUAL_REMAPS)
    parser.add_argument("--pool", type=Path, default=_DEFAULT_POOL)
    parser.add_argument("--gt", type=Path, nargs="+", default=_DEFAULT_GT_PATHS)
    parser.add_argument("--output-plan", type=Path, default=None)
    parser.add_argument("--output-report", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=_DEFAULT_CACHE_DIR)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--journal", type=Path, default=_DEFAULT_JOURNAL)

    args = parser.parse_args()

    # === ADR Guard (Architect FC3) ===
    adr_path = _validate_adr_arg(args.confirm_baseline_resuperseded)
    logger.info(
        f"Baseline resuperseded by {args.confirm_baseline_resuperseded} "
        f"({adr_path}) — BASELINE_IMPACT_REFUSED check bypassed"
    )

    if not args.servers_from.exists():
        logger.error(f"--servers-from file not found: {args.servers_from}")
        return 2

    server_ids = _load_server_ids_from_file(args.servers_from)
    if not server_ids:
        logger.warning("No server_ids found — nothing to do")
        return 0

    all_specs = load_transports_yaml(args.transports)
    target_specs = {sid: all_specs[sid] for sid in server_ids if sid in all_specs}
    missing_specs = [sid for sid in server_ids if sid not in all_specs]
    if missing_specs:
        logger.warning(f"{len(missing_specs)} server(s) missing transport spec: {missing_specs}")

    probe_results = await probe_servers(target_specs, cache_dir=args.cache_dir, force=args.force)
    probe_list = list(probe_results.values())

    pool = _load_pool_from_jsonl(args.pool)
    existing_gt_paths = [p for p in args.gt if p.exists()]
    gt_entries: list[GroundTruthEntry] = (
        merge_ground_truth(*existing_gt_paths) if existing_gt_paths else []
    )

    tool_remaps, server_remaps = _load_manual_remaps(args.manual_remaps)

    plan = build_reconcile_plan(
        pool=pool,
        probes=probe_list,
        gt_entries=gt_entries,
        manual_remaps=tool_remaps,
        server_remaps=server_remaps if server_remaps else None,
    )

    plan_dict = json.loads(plan.model_dump_json())
    _print_summary(plan_dict, dry_run=not args.apply)

    if args.output_plan:
        args.output_plan.parent.mkdir(parents=True, exist_ok=True)
        args.output_plan.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        logger.info(f"Plan written to {args.output_plan}")

    if args.output_report:
        serialize_plan_report(plan, args.output_report)

    journal_hash: str | None = None
    if args.apply:
        from mcp_discovery.data.gt_reconciler import apply_plan_to_gt

        modified = apply_plan_to_gt(plan, existing_gt_paths)
        logger.info(f"Applied plan: {len(modified)} GT file(s) modified")

        journal = AuditJournal(args.journal)
        entry = {
            "event": "refresh_pool_with_reindex_apply",
            "adr_confirmed": args.confirm_baseline_resuperseded,
            "plan_hash": plan.plan_hash,
            "servers_targeted": server_ids,
            "actions_count": len(plan.actions),
            "review_queue_count": len(plan.review_queue),
            "gt_files_modified": [str(p) for p in modified],
        }
        journal_hash = journal.append(entry)
        _print_summary(plan_dict, dry_run=False, journal_hash=journal_hash)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
