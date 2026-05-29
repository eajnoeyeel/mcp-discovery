"""Loop harness helpers for MetaMCP-class runtime behavior."""

from __future__ import annotations

import argparse
import json
from typing import Any


def summarize_runtime_runs(results: list[dict[str, Any]]) -> dict[str, float]:
    """Summarize OAuth refresh and pooled-session reuse across runtime runs."""
    if not results:
        return {
            "runs": 0,
            "success_rate": 0.0,
            "refresh_rate": 0.0,
            "session_reuse_rate": 0.0,
        }
    total = len(results)
    successes = sum(1 for item in results if item.get("ok"))
    refreshes = sum(1 for item in results if item.get("refreshed"))
    reused = sum(1 for item in results if item.get("reused_session"))
    return {
        "runs": total,
        "success_rate": successes / total,
        "refresh_rate": refreshes / total,
        "session_reuse_rate": reused / total,
    }


def run_sample(iterations: int) -> dict[str, Any]:
    """Run a deterministic sample loop without network or subprocess side effects."""
    results = []
    for index in range(iterations):
        results.append(
            {
                "ok": True,
                "refreshed": index == 0,
                "reused_session": index > 0,
            }
        )
    return {"mode": "sample", "summary": summarize_runtime_runs(results)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MetaMCP runtime parity sample loop.")
    parser.add_argument("--iterations", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(run_sample(args.iterations), indent=2))


if __name__ == "__main__":
    main()
