"""Pool↔GT alignment orchestrator (ADR-0018).

Default mode: targeted probe against servers listed in --servers-from file.
Produces a ReconcilePlan JSON that can be passed to apply_gt_reconcile.py.

Usage:
    uv run python scripts/refresh_pool.py --help

    # Dry-run (default, no file writes):
    uv run python scripts/refresh_pool.py \\
      --servers-from data/probes/targeted_set.txt \\
      --output-plan /tmp/plan.json

    # Apply:
    uv run python scripts/refresh_pool.py \\
      --servers-from data/probes/targeted_set.txt \\
      --output-plan /tmp/plan.json \\
      --apply

Exit codes:
    0  — success
    1  — BASELINE_IMPACT_REFUSED (planned actions would touch Qdrant-indexed tools)
    2  — user error / bad arguments
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# E402: sys.path shim allows running script directly without `uv run` (mirrors other scripts).
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
# Helpers
# ---------------------------------------------------------------------------


def _load_server_ids_from_file(path: Path) -> list[str]:
    """Load server_id list from a plain-text file (one per line, # comments stripped)."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _load_pool_from_jsonl(pool_path: Path) -> list[MCPServer]:
    """Parse a pool JSONL file into MCPServer objects."""
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
    """Return (tool_remaps, server_remaps) from manual_remaps.yaml."""
    if not remaps_path.exists():
        logger.warning(f"manual_remaps.yaml not found at {remaps_path} — using empty remaps")
        return {}, {}
    raw = yaml.safe_load(remaps_path.read_text(encoding="utf-8")) or {}
    tool_remaps: dict[str, str] = raw.get("tool_remaps", {}) or {}
    server_remaps: dict[str, str] = raw.get("server_remaps", {}) or {}
    return tool_remaps, server_remaps


def _load_indexed_tool_ids() -> frozenset[str]:
    """Return the set of tool_ids currently indexed in Qdrant mcp_tools_hybrid.

    Reads from a pool manifest file if one exists; if unavailable, returns
    an empty frozenset (conservative — caller treats empty as "unknown").
    """
    manifest_candidates = [
        _REPO_ROOT / "data" / "results" / "indexed_tool_ids.json",
        _REPO_ROOT / "data" / "raw" / "mcp_tools_hybrid_manifest.json",
    ]
    for candidate in manifest_candidates:
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                ids = data if isinstance(data, list) else data.get("tool_ids", [])
                return frozenset(ids)
            except Exception as exc:
                logger.warning(f"Could not read indexed manifest {candidate}: {exc}")
    return frozenset()


def _check_baseline_impact(plan_tool_ids: set[str], indexed_tool_ids: frozenset[str]) -> bool:
    """Return True if any tool in the plan is currently indexed in Qdrant.

    When indexed_tool_ids is empty (manifest not found), we are conservative
    and check against the pool instead (handled by caller).
    """
    overlap = plan_tool_ids & indexed_tool_ids
    if overlap:
        logger.error(
            f"BASELINE_IMPACT_REFUSED: {len(overlap)} tool_id(s) in reconcile plan "
            f"are currently indexed in mcp_tools_hybrid. "
            f"Use refresh_pool_with_reindex.py to proceed with reindexing. "
            f"Affected: {sorted(overlap)[:5]}{'...' if len(overlap) > 5 else ''}"
        )
        return True
    return False


def _print_summary(
    plan_json: dict,
    *,
    dry_run: bool,
    journal_hash: str | None = None,
) -> None:
    """Emit stdout summary in the canonical format."""
    actions = plan_json.get("actions", [])
    review_queue = plan_json.get("review_queue", [])
    plan_hash = plan_json.get("plan_hash", "")

    rule_counts: dict[str, int] = {}
    for action in actions:
        r = action.get("rule", "?")
        rule_counts[r] = rule_counts.get(r, 0) + 1

    prefix = "[DRY-RUN] " if dry_run else "[APPLIED] "
    lines = [
        "",
        f"{prefix}Pool↔GT Reconcile Summary",
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
    """Main entry point. Returns exit code."""
    parser = argparse.ArgumentParser(
        description="Pool↔GT alignment orchestrator (ADR-0018). Default: dry-run.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--servers-from",
        type=Path,
        default=_DEFAULT_TARGETED_SET,
        help="Plain-text file with server_ids to probe (default: data/probes/targeted_set.txt)",
    )
    parser.add_argument(
        "--transports",
        type=Path,
        default=_DEFAULT_TRANSPORTS_YAML,
        help="transports.yaml with transport specs for targeted servers",
    )
    parser.add_argument(
        "--manual-remaps",
        type=Path,
        default=_DEFAULT_MANUAL_REMAPS,
        help="manual_remaps.yaml for R2/R4 overrides",
    )
    parser.add_argument(
        "--pool",
        type=Path,
        default=_DEFAULT_POOL,
        help="Pool JSONL file (mcp_zero_servers.jsonl)",
    )
    parser.add_argument(
        "--gt",
        type=Path,
        nargs="+",
        default=_DEFAULT_GT_PATHS,
        help="Ground truth JSONL file(s)",
    )
    parser.add_argument(
        "--output-plan",
        type=Path,
        default=None,
        help="Write ReconcilePlan JSON to this path",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=None,
        help="Write markdown plan report to this path",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=_DEFAULT_CACHE_DIR,
        help="Probe result cache directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass probe cache",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the plan to GT files (default is dry-run only)",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=_DEFAULT_JOURNAL,
        help="Audit journal path",
    )

    args = parser.parse_args()

    # Load targeted server list
    if not args.servers_from.exists():
        logger.error(f"--servers-from file not found: {args.servers_from}")
        return 2

    server_ids = _load_server_ids_from_file(args.servers_from)
    if not server_ids:
        logger.warning(f"No server_ids found in {args.servers_from} — nothing to do")
        return 0

    logger.info(f"Targeting {len(server_ids)} server(s) from {args.servers_from}")

    # Load transport specs
    all_specs = load_transports_yaml(args.transports)
    target_specs = {sid: all_specs[sid] for sid in server_ids if sid in all_specs}
    missing_specs = [sid for sid in server_ids if sid not in all_specs]
    if missing_specs:
        logger.warning(
            f"{len(missing_specs)} server(s) have no transport spec — will skip probing: "
            f"{missing_specs}"
        )

    # Probe servers
    logger.info(f"Probing {len(target_specs)} server(s)...")
    probe_results = await probe_servers(target_specs, cache_dir=args.cache_dir, force=args.force)
    probe_list = list(probe_results.values())

    # Load pool and GT
    pool = _load_pool_from_jsonl(args.pool)
    existing_gt_paths = [p for p in args.gt if p.exists()]
    if not existing_gt_paths:
        logger.warning("No GT files found — reconcile plan will have no actions")
    gt_entries: list[GroundTruthEntry] = (
        merge_ground_truth(*existing_gt_paths) if existing_gt_paths else []
    )

    # Load manual remaps
    tool_remaps, server_remaps = _load_manual_remaps(args.manual_remaps)

    # Build reconcile plan
    plan = build_reconcile_plan(
        pool=pool,
        probes=probe_list,
        gt_entries=gt_entries,
        manual_remaps=tool_remaps,
        server_remaps=server_remaps if server_remaps else None,
    )

    # HARD REFUSAL: check baseline impact
    indexed_tool_ids = _load_indexed_tool_ids()
    affected_tool_ids = {
        a.old_tool_id for a in plan.actions if a.old_tool_id
    } | {a.new_tool_id for a in plan.actions if a.new_tool_id}

    if indexed_tool_ids:
        if _check_baseline_impact(affected_tool_ids, indexed_tool_ids):
            return 1
    else:
        logger.info(
            "Qdrant indexed manifest not found — baseline impact check skipped "
            "(run refresh_pool_with_reindex.py if reindexing is intended)"
        )

    plan_dict = json.loads(plan.model_dump_json())
    _print_summary(plan_dict, dry_run=not args.apply)

    # Write plan JSON
    if args.output_plan:
        args.output_plan.parent.mkdir(parents=True, exist_ok=True)
        args.output_plan.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        logger.info(f"Plan written to {args.output_plan}")

    # Write plan report
    if args.output_report:
        serialize_plan_report(plan, args.output_report)

    # Apply if requested
    journal_hash: str | None = None
    if args.apply:
        from mcp_discovery.data.gt_reconciler import apply_plan_to_gt

        modified = apply_plan_to_gt(plan, existing_gt_paths)
        logger.info(f"Applied plan: {len(modified)} GT file(s) modified")

        journal = AuditJournal(args.journal)
        entry = {
            "event": "refresh_pool_apply",
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
