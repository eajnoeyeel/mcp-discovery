"""Pool-GT Coverage Alignment Validator (ADR-0013).

Usage:
    uv run python scripts/validate_pool_gt_alignment.py \
      --pool data/raw/mcp_zero_servers.jsonl \
      --gt data/ground_truth/seed_set.jsonl data/ground_truth/mcp_atlas.jsonl \
      --pool-sizes 5 20 50 100 200 292 \
      --json-out data/results/alignment_report.json

Exit codes:
    0 — OK
    1 — coverage below --min-coverage threshold
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass
class CoverageAtSize:
    pool_size: int
    n_gt_servers: int
    n_gt_queries: int
    pct_queries: float
    gt_servers_included: list[str]


@dataclass
class AlignmentReport:
    total_gt_servers: int
    covered_servers: list[str]
    missing_servers: list[str]
    query_distribution: dict[str, int]
    coverage_by_pool_size: dict[int, CoverageAtSize]
    total_gt_queries: int


TOOL_ID_SEPARATOR = "::"

_DEFAULT_POOL = Path("data/raw/mcp_zero_servers.jsonl")
_DEFAULT_GT = [
    Path("data/ground_truth/synthetic.jsonl"),
    Path("data/ground_truth/mcp_atlas.jsonl"),
]


def load_pool_server_ids_from_jsonl(pool_path: Path) -> set[str]:
    ids: set[str] = set()
    for line in pool_path.read_text().splitlines():
        line = line.strip()
        if line:
            ids.add(json.loads(line)["server_id"])
    return ids


def load_pool_tool_ids_from_jsonl(pool_path: Path) -> set[str]:
    """Return all tool_ids from the pool JSONL (server tool list)."""
    ids: set[str] = set()
    for line in pool_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        for tool in record.get("tools", []):
            tid = tool.get("tool_id", "")
            if tid:
                ids.add(tid)
    return ids


def validate(pool_path: Path, gt_paths: list[Path]) -> list[str]:
    """Alias for validate_tool_ids — used by tests and CI."""
    return validate_tool_ids(pool_path=pool_path, gt_paths=gt_paths)


def validate_tool_ids(pool_path: Path, gt_paths: list[Path]) -> list[str]:
    """Return error strings for GT entries with missing or malformed tool_ids.

    Checks:
    - tool_id uses '::' separator (TOOL_ID_SEPARATOR)
    - tool_id exists in the pool
    - correct_server_id exists in the pool

    Returns an empty list when all GT entries are aligned.
    """
    pool_server_ids = load_pool_server_ids_from_jsonl(pool_path)
    pool_tool_ids = load_pool_tool_ids_from_jsonl(pool_path)

    errors: list[str] = []
    for path in gt_paths:
        if not path.exists():
            logger.warning(f"GT path not found, skipping: {path}")
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            qid = entry.get("query_id", f"{path}:{lineno}")
            server_id = entry.get("correct_server_id", "")
            tool_id = entry.get("correct_tool_id", "")

            if tool_id and TOOL_ID_SEPARATOR not in tool_id:
                errors.append(
                    f"{qid}: tool_id '{tool_id}' missing '{TOOL_ID_SEPARATOR}' separator"
                )
            if server_id and server_id not in pool_server_ids:
                errors.append(f"{qid}: server_id '{server_id}' not found in pool")
            if tool_id and tool_id not in pool_tool_ids:
                errors.append(f"{qid}: tool_id '{tool_id}' not found in pool")

    return errors


def load_gt_server_ids(gt_paths: list[Path]) -> dict[str, int]:
    """Returns {server_id: query_count}."""
    counts: dict[str, int] = {}
    for path in gt_paths:
        if not path.exists():
            logger.warning(f"GT path not found, skipping: {path}")
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                sid = json.loads(line)["correct_server_id"]
                counts[sid] = counts.get(sid, 0) + 1
    return counts


def _gt_first_ordering(pool_ids: set[str], gt_servers: set[str]) -> list[str]:
    gt_in_pool = sorted(s for s in pool_ids if s in gt_servers)
    rest = sorted(s for s in pool_ids if s not in gt_servers)
    return gt_in_pool + rest


def compute_alignment(
    pool_path: Path,
    gt_paths: list[Path],
    pool_sizes: list[int] | None = None,
) -> AlignmentReport:
    pool_ids = load_pool_server_ids_from_jsonl(pool_path)
    query_dist = load_gt_server_ids(gt_paths)
    gt_servers = set(query_dist.keys())

    covered = sorted(gt_servers & pool_ids)
    missing = sorted(gt_servers - pool_ids)
    total_queries = sum(query_dist.values())

    ordered_pool = _gt_first_ordering(pool_ids, gt_servers)

    coverage: dict[int, CoverageAtSize] = {}
    if pool_sizes:
        for size in pool_sizes:
            subset = set(ordered_pool[:size])
            included_gt = sorted(subset & gt_servers)
            n_queries = sum(query_dist.get(s, 0) for s in included_gt)
            pct = n_queries / total_queries * 100 if total_queries else 0.0
            coverage[size] = CoverageAtSize(
                pool_size=size,
                n_gt_servers=len(included_gt),
                n_gt_queries=n_queries,
                pct_queries=pct,
                gt_servers_included=included_gt,
            )

    return AlignmentReport(
        total_gt_servers=len(gt_servers),
        covered_servers=covered,
        missing_servers=missing,
        query_distribution=query_dist,
        coverage_by_pool_size=coverage,
        total_gt_queries=total_queries,
    )


def format_alignment_report(report: AlignmentReport) -> str:
    total_gt = report.total_gt_servers or 1
    covered_pct = len(report.covered_servers) / total_gt * 100
    missing_pct = len(report.missing_servers) / total_gt * 100

    lines = [
        "POOL-GT ALIGNMENT REPORT",
        "=" * 45,
        f"GT servers total:    {report.total_gt_servers}",
        f"Covered in pool:     {len(report.covered_servers)} ({covered_pct:.1f}%)",
        f"Missing from pool:   {len(report.missing_servers)} ({missing_pct:.1f}%)",
        "",
        f"Missing: {', '.join(report.missing_servers)}",
        "",
        f"Query distribution (covered, {report.total_gt_queries} total queries):",
    ]
    total_q = report.total_gt_queries or 1
    for sid in report.covered_servers:
        count = report.query_distribution.get(sid, 0)
        flag = "  *** HIGH SKEW ***" if count / total_q > 0.25 else ""
        lines.append(f"  {sid:<30} {count:>4} ({count / total_q * 100:.1f}%){flag}")

    if report.coverage_by_pool_size:
        lines += ["", "Coverage by pool_size (GT-first ordering):"]
        for size, cov in sorted(report.coverage_by_pool_size.items()):
            lines.append(
                f"  pool={size:<5} {cov.n_gt_servers:>2} GT servers, "
                f"{cov.n_gt_queries:>4} queries ({cov.pct_queries:.1f}%)"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Pool-GT alignment (ADR-0013)")
    parser.add_argument("--pool", type=Path, default=_DEFAULT_POOL)
    parser.add_argument("--gt", type=Path, nargs="+", default=_DEFAULT_GT)
    parser.add_argument("--pool-sizes", type=int, nargs="*", default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.0,
        help="Exit 1 if covered_pct < this value (0.0 = warn only)",
    )
    args = parser.parse_args()

    report = compute_alignment(args.pool, args.gt, pool_sizes=args.pool_sizes)
    logger.info(format_alignment_report(report))

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "total_gt_servers": report.total_gt_servers,
            "covered_servers": report.covered_servers,
            "missing_servers": report.missing_servers,
            "total_gt_queries": report.total_gt_queries,
            "query_distribution": report.query_distribution,
            "coverage_by_pool_size": {
                str(k): {
                    "n_gt_servers": v.n_gt_servers,
                    "n_gt_queries": v.n_gt_queries,
                    "pct_queries": v.pct_queries,
                    "gt_servers_included": v.gt_servers_included,
                }
                for k, v in report.coverage_by_pool_size.items()
            },
        }
        args.json_out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info(f"JSON report saved to {args.json_out}")

    # Tool-id alignment gate (always enforced)
    tool_errors = validate_tool_ids(args.pool, args.gt)
    if tool_errors:
        for err in tool_errors:
            logger.error(err)
        logger.error(f"{len(tool_errors)} tool-id alignment error(s) found.")
        sys.exit(1)
    logger.info("Tool-id alignment OK.")

    covered_pct = len(report.covered_servers) / (report.total_gt_servers or 1) * 100
    if args.min_coverage > 0 and covered_pct < args.min_coverage:
        logger.error(
            f"Coverage gate FAILED: {covered_pct:.1f}% < required {args.min_coverage:.1f}%"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
