"""Repeated search loop harness — summary statistics for SLA verification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

DEFAULT_SAMPLE_RUNS = [
    {"query": "search github repositories", "ok": True, "latency_ms": 412.4},
    {"query": "find postgres database tool", "ok": True, "latency_ms": 438.9},
    {"query": "look up arxiv papers", "ok": True, "latency_ms": 471.2},
]


def summarize_runs(results: list[dict[str, Any]]) -> dict[str, float]:
    """Compute aggregate stats from a list of run results."""
    if not results:
        return {
            "runs": 0.0,
            "success_rate": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "mean_latency_ms": 0.0,
        }

    latencies = sorted(float(item["latency_ms"]) for item in results)
    total = len(results)
    success_rate = sum(1 for item in results if item.get("ok")) / total
    p50_index = min(total - 1, total // 2)
    p95_index = min(total - 1, int(total * 0.95))
    return {
        "runs": float(total),
        "success_rate": success_rate,
        "p50_latency_ms": latencies[p50_index],
        "p95_latency_ms": latencies[p95_index],
        "mean_latency_ms": mean(latencies),
    }


def _load_runs(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return DEFAULT_SAMPLE_RUNS
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError("search loop input must be a JSON list")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize repeated MLP search runs.")
    parser.add_argument(
        "--input",
        help="Path to a JSON file containing repeated search-run results. Defaults to sample data.",
    )
    args = parser.parse_args()

    runs = _load_runs(args.input)
    payload = {
        "mode": "file" if args.input else "sample",
        "note": (
            "Provide --input with recorded search runs to capture a live baseline "
            "before enabling pending freshness."
            if not args.input
            else f"Summarized search runs from {args.input}."
        ),
        "summary": summarize_runs(runs),
        "results": runs,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
