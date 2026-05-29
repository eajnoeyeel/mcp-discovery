"""Build Query Set for Per-Client Description A/B Experiment.

Selects GT queries per target tool from confusion clusters and constructs
candidate sets for the offline selection experiment.

Usage:
    # Dry run (prints summary, does not write output)
    PYTHONPATH=src uv run python scripts/build_experiment_queries.py --dry-run

    # Full run with defaults (5 queries, seed=42)
    PYTHONPATH=src uv run python scripts/build_experiment_queries.py

    # Custom
    PYTHONPATH=src uv run python scripts/build_experiment_queries.py --n-queries 3 --seed 0
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
GT_ATLAS_PATH = Path("data/ground_truth/mcp_atlas.jsonl")
RAW_SERVERS_PATH = Path("data/raw/mcp_zero_servers.jsonl")
OUTPUT_PATH = Path("data/experiment/selection_queries.json")

# ---------------------------------------------------------------------------
# Experiment configuration
# ---------------------------------------------------------------------------
CONFUSION_CLUSTERS: dict[str, list[str]] = {
    "airtable": [
        "airtable::search_records",
        "airtable::list_records",
        "airtable::list_bases",
        "airtable::list_tables",
    ],
    "web_search": [
        "exa::web_search_exa",
        "ddg-search::search",
        "brave-search::brave_web_search",
    ],
}

TARGET_TOOLS: dict[str, str] = {
    "airtable::search_records": "airtable",
    "airtable::list_records": "airtable",
    "airtable::list_bases": "airtable",
    "airtable::list_tables": "airtable",
    "exa::web_search_exa": "web_search",
}


# ---------------------------------------------------------------------------
# Pure helper functions (tested in unit tests)
# ---------------------------------------------------------------------------


def load_gt_entries(path: Path) -> list[dict]:
    """Load all GT entries from a JSONL file."""
    entries: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def load_tool_descriptions(path: Path) -> dict[str, str]:
    """Build tool_id -> description map from raw servers JSONL."""
    descriptions: dict[str, str] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            server = json.loads(line)
            for tool in server.get("tools", []):
                tool_id = tool.get("tool_id", "")
                description = tool.get("description", "")
                if tool_id:
                    descriptions[tool_id] = description
    return descriptions


def build_candidate_set(
    cluster: str,
    confusion_clusters: dict[str, list[str]],
    tool_descriptions: dict[str, str],
) -> list[dict]:
    """Return candidate list for a cluster with tool_id and description fields.

    Missing descriptions default to empty string.
    """
    return [
        {
            "tool_id": tool_id,
            "description": tool_descriptions.get(tool_id, ""),
        }
        for tool_id in confusion_clusters[cluster]
    ]


def select_queries_for_tool(
    tool_id: str,
    gt_entries: list[dict],
    n: int,
    seed: int,
) -> list[dict]:
    """Select up to n GT entries where correct_tool_id matches tool_id.

    Deterministic: uses random.Random(seed) to shuffle before slicing.
    """
    matching = [e for e in gt_entries if e.get("correct_tool_id") == tool_id]
    rng = random.Random(seed)
    rng.shuffle(matching)
    return matching[:n]


# ---------------------------------------------------------------------------
# Main build logic
# ---------------------------------------------------------------------------


def build_experiment_queries(
    n_queries: int,
    seed: int,
    gt_path: Path,
    servers_path: Path,
) -> list[dict]:
    """Build the full query set for all target tools.

    Returns a list of query records with query, query_id, target_tool_id,
    cluster, and candidates fields.
    """
    logger.info(f"Loading GT entries from {gt_path}")
    gt_entries = load_gt_entries(gt_path)
    logger.info(f"Loaded {len(gt_entries)} GT entries")

    logger.info(f"Loading tool descriptions from {servers_path}")
    tool_descriptions = load_tool_descriptions(servers_path)
    logger.info(f"Loaded descriptions for {len(tool_descriptions)} tools")

    records: list[dict] = []
    for tool_id, cluster in TARGET_TOOLS.items():
        candidates = build_candidate_set(cluster, CONFUSION_CLUSTERS, tool_descriptions)
        queries = select_queries_for_tool(tool_id, gt_entries, n=n_queries, seed=seed)
        logger.info(
            f"Tool {tool_id}: {len(queries)} queries selected from cluster '{cluster}'"
            f" ({len(candidates)} candidates)"
        )
        for entry in queries:
            records.append(
                {
                    "query": entry["query"],
                    "query_id": entry["query_id"],
                    "target_tool_id": tool_id,
                    "cluster": cluster,
                    "candidates": candidates,
                }
            )

    return records


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build GT query set for per-client description A/B experiment."
    )
    parser.add_argument(
        "--n-queries",
        type=int,
        default=5,
        help="Max GT queries to select per target tool (default: 5)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic selection (default: 42)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary without writing output file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    records = build_experiment_queries(
        n_queries=args.n_queries,
        seed=args.seed,
        gt_path=GT_ATLAS_PATH,
        servers_path=RAW_SERVERS_PATH,
    )

    logger.info(f"Total query records built: {len(records)}")

    if args.dry_run:
        logger.info("Dry run — skipping file write")
        for rec in records[:3]:
            logger.info(
                f"  query_id={rec['query_id']} tool={rec['target_tool_id']}"
                f" cluster={rec['cluster']} n_candidates={len(rec['candidates'])}"
            )
        if len(records) > 3:
            logger.info(f"  ... and {len(records) - 3} more")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    logger.info(f"Wrote {len(records)} records to {OUTPUT_PATH}")


if __name__ == "__main__":
    main(sys.argv[1:])
