"""Repeated indexing loop harness — summary statistics for indexing stability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

DEFAULT_SAMPLE_RUNS: list[dict[str, Any]] = [
    {"ok": True, "indexed_count": 2, "skipped_count": 0},
    {"ok": True, "indexed_count": 0, "skipped_count": 2},
    {"ok": True, "indexed_count": 1, "skipped_count": 1},
]


def summarize_index_runs(results: list[dict[str, Any]]) -> dict[str, float]:
    """Compute aggregate stats for repeated indexing runs."""
    if not results:
        return {
            "runs": 0,
            "success_rate": 0.0,
            "failure_rate": 0.0,
            "indexed_total": 0.0,
            "skipped_total": 0.0,
            "skip_rate": 0.0,
            "average_batch_size": 0.0,
        }

    total = len(results)
    indexed_counts = [float(item.get("indexed_count", 0)) for item in results]
    skipped_counts = [float(item.get("skipped_count", 0)) for item in results]
    indexed_total = float(sum(indexed_counts))
    skipped_total = float(sum(skipped_counts))
    processed_total = indexed_total + skipped_total
    success_rate = sum(1 for item in results if item.get("ok")) / total
    failure_rate = sum(1 for item in results if not item.get("ok")) / total
    skip_rate = skipped_total / processed_total if processed_total else 0.0
    return {
        "runs": float(total),
        "success_rate": success_rate,
        "failure_rate": failure_rate,
        "indexed_total": indexed_total,
        "skipped_total": skipped_total,
        "skip_rate": skip_rate,
        "average_batch_size": mean(indexed_counts),
    }


def _load_results(results_file: str | None) -> list[dict[str, Any]]:
    if not results_file:
        return DEFAULT_SAMPLE_RUNS

    payload = json.loads(Path(results_file).read_text())
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON array of run result objects")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize repeated index loop runs.")
    parser.add_argument(
        "--results-file",
        help="Path to a JSON file containing an array of indexing run result objects.",
    )
    args = parser.parse_args()

    results = _load_results(args.results_file)
    mode = "results_file" if args.results_file else "sample"
    print(json.dumps({"mode": mode, "summary": summarize_index_runs(results)}, indent=2))


if __name__ == "__main__":
    main()
