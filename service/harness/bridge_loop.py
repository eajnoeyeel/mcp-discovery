"""Repeated bridge loop harness — combined search/execute summary stats."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

DEFAULT_SAMPLE_RUNS = [
    {
        "query": "search GitHub repositories and run the best tool",
        "search_ok": True,
        "execute_ok": True,
        "search_latency_ms": 412.4,
        "execute_latency_ms": 118.8,
    },
    {
        "query": "find a Postgres tool and inspect it",
        "search_ok": True,
        "execute_ok": True,
        "search_latency_ms": 438.9,
        "execute_latency_ms": 126.7,
    },
    {
        "query": "look up an arXiv tool and call it",
        "search_ok": True,
        "execute_ok": False,
        "search_latency_ms": 471.2,
        "execute_latency_ms": 2500.0,
    },
]


def summarize_bridge_runs(results: list[dict[str, Any]]) -> dict[str, float]:
    """Compute combined bridge search/execute summary stats."""
    if not results:
        return {
            "runs": 0.0,
            "search_success_rate": 0.0,
            "execute_success_rate": 0.0,
            "roundtrip_success_rate": 0.0,
            "p50_total_latency_ms": 0.0,
            "p95_total_latency_ms": 0.0,
            "mean_total_latency_ms": 0.0,
        }

    total = len(results)
    total_latencies = sorted(
        float(item.get("search_latency_ms", 0.0)) + float(item.get("execute_latency_ms", 0.0))
        for item in results
    )
    p50_index = min(total - 1, total // 2)
    p95_index = min(total - 1, int(total * 0.95))
    search_success_rate = sum(1 for item in results if item.get("search_ok")) / total
    execute_success_rate = sum(1 for item in results if item.get("execute_ok")) / total
    roundtrip_success_rate = (
        sum(1 for item in results if item.get("search_ok") and item.get("execute_ok")) / total
    )
    return {
        "runs": float(total),
        "search_success_rate": search_success_rate,
        "execute_success_rate": execute_success_rate,
        "roundtrip_success_rate": roundtrip_success_rate,
        "p50_total_latency_ms": total_latencies[p50_index],
        "p95_total_latency_ms": total_latencies[p95_index],
        "mean_total_latency_ms": mean(total_latencies),
    }


def _load_runs(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return DEFAULT_SAMPLE_RUNS
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError("bridge loop input must be a JSON list")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize repeated bridge search/execute runs.")
    parser.add_argument(
        "--input",
        help="Path to a JSON file containing repeated bridge run results. Defaults to sample data.",
    )
    args = parser.parse_args()

    runs = _load_runs(args.input)
    payload = {
        "mode": "file" if args.input else "sample",
        "note": (
            "Provide --input with recorded bridge runs to capture a root-vision "
            "baseline for combined search+execute behavior."
            if not args.input
            else f"Summarized bridge runs from {args.input}."
        ),
        "summary": summarize_bridge_runs(runs),
        "results": runs,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
