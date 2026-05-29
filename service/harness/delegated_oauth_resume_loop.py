"""Delegated OAuth resume loop harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def summarize_results(results: list[dict]) -> dict[str, float | int]:
    """Summarize auth probe, auth-required, ready-to-resume, and resume outcomes."""
    total = len(results)
    return {
        "total": total,
        "auth_probe_rate": sum(1 for item in results if item.get("auth_probe_ok")) / total
        if total
        else 0.0,
        "auth_required_rate": sum(1 for item in results if item.get("auth_required")) / total
        if total
        else 0.0,
        "ready_to_resume_rate": sum(1 for item in results if item.get("ready_to_resume")) / total
        if total
        else 0.0,
        "resume_success_rate": sum(1 for item in results if item.get("resume_ok")) / total
        if total
        else 0.0,
    }


def _load_results(results_file: str | None) -> list[dict]:
    if results_file:
        payload = json.loads(Path(results_file).read_text())
        if not isinstance(payload, list):
            raise ValueError("Expected a JSON array of resume proof results")
        return payload
    return [
        {
            "auth_probe_ok": True,
            "auth_required": True,
            "ready_to_resume": True,
            "resume_ok": True,
        }
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize delegated OAuth resume proof runs.")
    parser.add_argument("--results-file")
    args = parser.parse_args()

    results = _load_results(args.results_file)
    print(json.dumps({"summary": summarize_results(results), "results": results}, indent=2))


if __name__ == "__main__":
    main()
