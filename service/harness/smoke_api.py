"""HTTP API smoke harness for MLP stage verification."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from statistics import mean
from typing import Any

import httpx

DEFAULT_QUERIES = [
    "search github repositories",
    "find postgres database tool",
    "look up arxiv papers",
]


def classify_status(status_code: int) -> str:
    """Classify an HTTP status code into ok/timeout/error buckets."""
    if 200 <= status_code < 300:
        return "ok"
    if status_code == 504:
        return "timeout"
    return "error"


def summarize_smoke_runs(results: list[dict[str, Any]]) -> dict[str, float]:
    """Summarize smoke harness runs with SLA-oriented metrics."""
    if not results:
        return {
            "runs": 0,
            "success_rate": 0.0,
            "timeout_rate": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "mean_latency_ms": 0.0,
        }

    latencies = sorted(float(item["latency_ms"]) for item in results)
    total = len(results)
    success_rate = (
        sum(1 for item in results if classify_status(int(item["status_code"])) == "ok") / total
    )
    timeout_rate = (
        sum(1 for item in results if classify_status(int(item["status_code"])) == "timeout") / total
    )
    p50_index = min(len(latencies) - 1, len(latencies) // 2)
    p95_index = min(len(latencies) - 1, int(len(latencies) * 0.95))
    return {
        "runs": float(total),
        "success_rate": success_rate,
        "timeout_rate": timeout_rate,
        "p50_latency_ms": latencies[p50_index],
        "p95_latency_ms": latencies[p95_index],
        "mean_latency_ms": mean(latencies),
    }


async def _probe_search(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    query: str,
    top_k: int,
    timeout_s: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{base_url.rstrip('/')}/api/search",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": query, "top_k": top_k},
            timeout=timeout_s,
        )
        status_code = response.status_code
        response.raise_for_status()
        error = None
    except httpx.TimeoutException:
        status_code = 504
        error = "timeout"
    except httpx.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", 500)
        error = str(exc)

    latency_ms = (time.perf_counter() - started) * 1000
    return {
        "query": query,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "classification": classify_status(status_code),
        "error": error,
    }


async def run_smoke_checks(
    *,
    base_url: str,
    api_key: str,
    queries: list[str],
    top_k: int = 5,
    timeout_s: float = 10.0,
) -> list[dict[str, Any]]:
    """Run repeated API smoke checks against the deployed MLP search API."""
    async with httpx.AsyncClient() as client:
        return [
            await _probe_search(
                client,
                base_url=base_url,
                api_key=api_key,
                query=query,
                top_k=top_k,
                timeout_s=timeout_s,
            )
            for query in queries
        ]


def _sample_results() -> list[dict[str, Any]]:
    return [
        {"query": DEFAULT_QUERIES[0], "status_code": 200, "latency_ms": 180.0},
        {"query": DEFAULT_QUERIES[1], "status_code": 200, "latency_ms": 225.0},
        {"query": DEFAULT_QUERIES[2], "status_code": 504, "latency_ms": 5000.0},
    ]


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Run or summarize MLP API smoke checks.")
    parser.add_argument("--base-url", default=os.environ.get("MLP_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("MLP_API_KEY", ""))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Use bundled sample results instead of calling a live stage.",
    )
    args = parser.parse_args()

    if args.sample or not (args.base_url and args.api_key):
        results = _sample_results()
        mode = "sample"
        note = (
            "Set MLP_BASE_URL and MLP_API_KEY (or pass --base-url/--api-key) for a live stage run."
        )
    else:
        results = await run_smoke_checks(
            base_url=args.base_url,
            api_key=args.api_key,
            queries=DEFAULT_QUERIES,
            top_k=args.top_k,
            timeout_s=args.timeout_seconds,
        )
        mode = "live"
        note = "Live stage smoke run completed."

    print(
        json.dumps(
            {
                "mode": mode,
                "note": note,
                "summary": summarize_smoke_runs(results),
                "results": results,
            },
            indent=2,
        )
    )


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
