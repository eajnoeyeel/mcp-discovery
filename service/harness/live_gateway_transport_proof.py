"""Summarize live MCP transport proof runs for gateway rollout evidence."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "stdio_echo_server.py"


def fixture_script_path() -> Path:
    """Return the local STDIO fixture path used for controlled transport proofing."""
    return FIXTURE_PATH


def summarize_transport_runs(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute overall and per-transport success rates."""
    if not results:
        return {"runs": 0, "success_rate": 0.0, "per_transport": {}}

    buckets: dict[str, list[bool]] = defaultdict(list)
    for item in results:
        buckets[item["transport"]].append(bool(item.get("ok")))

    total = len(results)
    successes = sum(1 for item in results if item.get("ok"))
    return {
        "runs": total,
        "success_rate": successes / total,
        "per_transport": {
            transport: sum(values) / len(values) for transport, values in buckets.items()
        },
    }


def run_sample() -> dict[str, Any]:
    """Return a deterministic, no-network sample artifact for docs and tests."""
    results = [
        {"transport": "streamable_http", "ok": True},
        {"transport": "sse", "ok": True},
        {"transport": "stdio", "ok": True},
    ]
    return {
        "mode": "sample",
        "fixture": str(fixture_script_path()),
        "summary": summarize_transport_runs(results),
    }


def _load_results(results_file: str | None) -> list[dict[str, Any]]:
    if not results_file:
        return []
    payload = json.loads(Path(results_file).read_text())
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON array of transport proof result objects")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize live gateway transport proof runs.")
    parser.add_argument(
        "--results-file",
        help="Optional JSON file containing an array of transport proof result objects.",
    )
    args = parser.parse_args()

    if args.results_file:
        payload = {
            "mode": "live",
            "fixture": str(fixture_script_path()),
            "summary": summarize_transport_runs(_load_results(args.results_file)),
        }
    else:
        payload = run_sample()
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
