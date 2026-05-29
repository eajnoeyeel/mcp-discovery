"""Repeated execute loop harness — success and timeout summary stats."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def summarize_execute_runs(results: list[dict[str, Any]]) -> dict[str, float]:
    """Compute aggregate stats for repeated execute runs."""
    if not results:
        return {"runs": 0, "success_rate": 0.0, "timeout_rate": 0.0, "error_rate": 0.0}

    total = len(results)
    success_rate = sum(1 for item in results if item.get("ok")) / total
    timeout_rate = sum(1 for item in results if item.get("timed_out")) / total
    return {
        "runs": float(total),
        "success_rate": success_rate,
        "timeout_rate": timeout_rate,
        "error_rate": 1.0 - success_rate,
    }


def _load_results(results_file: str | None) -> list[dict[str, Any]]:
    if not results_file:
        return [
            {"ok": True, "timed_out": False},
            {"ok": True, "timed_out": False},
            {"ok": False, "timed_out": True},
        ]

    payload = json.loads(Path(results_file).read_text())
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON array of run result objects")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize repeated execute loop runs.")
    parser.add_argument(
        "--results-file",
        help="Path to a JSON file containing an array of execute run result objects.",
    )
    args = parser.parse_args()

    results = _load_results(args.results_file)
    mode = "live" if args.results_file else "sample"
    print(json.dumps({"mode": mode, "summary": summarize_execute_runs(results)}, indent=2))


if __name__ == "__main__":
    main()
