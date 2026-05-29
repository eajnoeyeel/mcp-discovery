"""Gateway health probe harness for local rehearsal and hosted rollout checks."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from statistics import mean
from typing import Any

import httpx

HEALTH_PATH = "/gateway/health"


async def probe_gateway_health(base_url: str, timeout_s: float = 5.0) -> dict[str, Any]:
    """Probe the gateway health endpoint and capture a single result payload."""
    path = HEALTH_PATH
    url = f"{base_url.rstrip('/')}{path}"
    started = time.perf_counter()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=timeout_s)
        payload = _response_payload(response)
        ok = response.is_success
        error = None if ok else f"HTTP {response.status_code}"
    except httpx.TimeoutException:
        payload = None
        ok = False
        error = "timeout"
    except httpx.HTTPError as exc:
        payload = None
        ok = False
        error = str(exc)

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "path": path,
        "ok": ok,
        "latency_ms": latency_ms,
        "payload": payload,
        "error": error,
    }


def summarize_gateway_health_runs(results: list[dict[str, Any]]) -> dict[str, float]:
    """Summarize success rate and latency percentiles across health probe runs."""
    if not results:
        return {
            "runs": 0,
            "success_rate": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "mean_latency_ms": 0.0,
        }

    latencies = sorted(float(item["latency_ms"]) for item in results)
    total = len(results)
    p50_index = min(total - 1, total // 2)
    p95_index = min(total - 1, int(total * 0.95))
    return {
        "runs": total,
        "success_rate": sum(1 for item in results if item.get("ok")) / total,
        "p50_latency_ms": latencies[p50_index],
        "p95_latency_ms": latencies[p95_index],
        "mean_latency_ms": mean(latencies),
    }


def run_sample() -> dict[str, Any]:
    """Return a deterministic sample payload for safe local rehearsal."""
    results = [
        {
            "path": HEALTH_PATH,
            "ok": True,
            "latency_ms": 42.0,
            "payload": {"status": "ok"},
            "error": None,
        },
        {
            "path": HEALTH_PATH,
            "ok": True,
            "latency_ms": 55.0,
            "payload": {"status": "ok"},
            "error": None,
        },
        {
            "path": HEALTH_PATH,
            "ok": False,
            "latency_ms": 2500.0,
            "payload": None,
            "error": "timeout",
        },
    ]
    return {
        "mode": "sample",
        "summary": summarize_gateway_health_runs(results),
        "results": results,
    }


def _response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Probe the gateway health endpoint.")
    parser.add_argument("--base-url", default=os.environ.get("GATEWAY_BASE_URL", ""))
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Print a deterministic local sample instead of probing a live target.",
    )
    args = parser.parse_args()

    if args.sample or not args.base_url:
        payload = run_sample()
    else:
        result = await probe_gateway_health(args.base_url, timeout_s=args.timeout_seconds)
        payload = {
            "mode": "live",
            "summary": summarize_gateway_health_runs([result]),
            "results": [result],
        }

    print(json.dumps(payload, indent=2))


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
