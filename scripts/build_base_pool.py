"""Build GT-first ordered pool for experiment reproducibility.

Ordering rule:
  1. GT-covered servers (overlap between MCP-Atlas GT and MCP-Zero) — sorted by
     GT entry count descending (most-covered first → maximizes Precision@1 reliability
     at small pool sizes).
  2. Remaining MCP-Zero servers — sorted alphabetically.

This ensures pool[:N] always maximizes GT coverage for any N, making the E5 pool-scale
sweep valid (GT set doesn't change for pool_size >= number of overlapping servers, 11).

Usage:
    uv run python scripts/build_base_pool.py
    uv run python scripts/build_base_pool.py --output data/tool-pools/base_pool.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from loguru import logger

_GT_PATHS = [
    Path("data/ground_truth/seed_set.jsonl"),
    Path("data/ground_truth/mcp_atlas.jsonl"),
]
_POOL_PATH = Path("data/raw/mcp_zero_servers.jsonl")
_OUTPUT_PATH = Path("data/tool-pools/base_pool.json")


def build_ordered_pool(
    gt_paths: list[Path],
    pool_path: Path,
) -> list[str]:
    """Return GT-first ordered list of all server_ids from pool_path.

    GT-covered servers appear first (sorted by descending GT entry count),
    followed by remaining pool servers in alphabetical order.
    """
    gt_counts: Counter[str] = Counter()
    for path in gt_paths:
        if not path.exists():
            logger.warning(f"GT file not found, skipping: {path}")
            continue
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                server_id = entry.get("correct_server_id")
                if server_id:
                    gt_counts[server_id] += 1
            except json.JSONDecodeError:
                continue

    pool_server_ids: set[str] = set()
    for raw_line in pool_path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            pool_server_ids.add(json.loads(line)["server_id"])
        except (json.JSONDecodeError, KeyError):
            continue

    gt_covered = {sid for sid in gt_counts if sid in pool_server_ids}
    remaining = pool_server_ids - gt_covered

    ordered_gt = sorted(gt_covered, key=lambda s: (-gt_counts[s], s))
    ordered_remaining = sorted(remaining)

    result = ordered_gt + ordered_remaining
    logger.info(
        f"Pool ordering: {len(ordered_gt)} GT-covered servers first "
        f"({len(gt_counts)} GT servers total, {len(gt_covered)} overlap with pool), "
        f"then {len(ordered_remaining)} MCP-Zero-only servers"
    )
    return result


def compute_coverage(server_ids: list[str], gt_paths: list[Path]) -> int:
    """Return count of GT entries whose correct_server_id is in server_ids."""
    pool_set = set(server_ids)
    count = 0
    for path in gt_paths:
        if not path.exists():
            continue
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("correct_server_id") in pool_set:
                    count += 1
            except json.JSONDecodeError:
                continue
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Build GT-first ordered pool")
    parser.add_argument(
        "--output", type=Path, default=_OUTPUT_PATH,
        help="Output JSON path for base_pool.json",
    )
    args = parser.parse_args()

    ordered = build_ordered_pool(gt_paths=_GT_PATHS, pool_path=_POOL_PATH)

    for n in [5, 11, 20, 50, 100, 200, len(ordered)]:
        if n > len(ordered):
            continue
        cov = compute_coverage(ordered[:n], gt_paths=_GT_PATHS)
        logger.info(f"  pool[:{n:3d}] → {cov} GT entries covered")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ordered, indent=2, ensure_ascii=False))
    logger.info(f"Saved {len(ordered)}-server ordered pool to {args.output}")


if __name__ == "__main__":
    main()
