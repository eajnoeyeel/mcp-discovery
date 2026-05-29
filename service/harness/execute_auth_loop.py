"""Repeated upstream auth header generation harness for execute proxy safety."""

from __future__ import annotations

import argparse
import json
from typing import Any

from service.services.contracts import UpstreamAuthConfig
from service.services.upstream_auth import build_upstream_headers


def summarize_auth_runs(results: list[dict[str, Any]]) -> dict[str, float]:
    """Summarize repeated auth header generation runs."""
    if not results:
        return {"runs": 0, "success_rate": 0.0, "avg_header_count": 0.0}
    total = len(results)
    successes = sum(1 for result in results if result.get("ok"))
    header_count = sum(int(result.get("header_count", 0)) for result in results)
    return {
        "runs": total,
        "success_rate": successes / total,
        "avg_header_count": header_count / total,
    }


def run_sample(iterations: int) -> dict[str, Any]:
    """Run deterministic sample auth generation without printing secret values."""
    configs = [
        UpstreamAuthConfig(auth_type="none"),
        UpstreamAuthConfig(auth_type="bearer", bearer_token="sample-token"),
        UpstreamAuthConfig(
            auth_type="api_key_header",
            api_key_header_name="X-Provider-Key",
            api_key="sample-key",
        ),
        UpstreamAuthConfig(
            auth_type="custom_headers",
            headers={"X-Org-ID": "org-123", "X-API-Version": "v2"},
        ),
    ]
    results: list[dict[str, Any]] = []
    for index in range(iterations):
        headers = build_upstream_headers(configs[index % len(configs)])
        results.append({"ok": True, "header_count": len(headers)})
    return {"mode": "sample", "summary": summarize_auth_runs(results)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run execute upstream auth loop harness.")
    parser.add_argument("--iterations", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(run_sample(args.iterations), indent=2))


if __name__ == "__main__":
    main()
