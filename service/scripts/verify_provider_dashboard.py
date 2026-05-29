"""Live API-level verification for provider-owned dashboard behavior."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any

import httpx


def _headers(api_key: str, bearer_token: str | None = None) -> dict[str, str]:
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    if bearer_token:
        headers["authorization"] = f"Bearer {bearer_token}"
    return headers


def _build_payload(server_id: str) -> dict[str, Any]:
    return {
        "server_id": server_id,
        "name": "Provider Owned Verification Server",
        "description": "Verification payload for provider-owned dashboard E2E checks.",
        "url": f"https://example.invalid/{server_id}",
        "tags": ["verification", "plan05"],
        "tools": [
            {
                "tool_name": "lookup",
                "description": "Lookup verification records by query.",
                "input_schema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
            }
        ],
    }


async def verify_provider_dashboard(
    *,
    base_url: str,
    api_key: str,
    bearer_token: str,
    server_id: str,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 2.0,
) -> dict[str, Any]:
    """Register a provider-owned server and poll for dashboard visibility."""
    base_url = base_url.rstrip("/")
    tool_id = f"{server_id}::lookup"
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=10.0) as client:
        register_response = await client.post(
            f"{base_url}/api/servers",
            headers=_headers(api_key, bearer_token),
            json=_build_payload(server_id),
        )
        register_response.raise_for_status()

        negative_unauthorized = await client.get(
            f"{base_url}/api/providers/dashboard",
            headers=_headers(api_key),
        )

        deadline = time.perf_counter() + timeout_seconds
        dashboard_snapshots: list[dict[str, Any]] = []
        while True:
            dashboard_response = await client.get(
                f"{base_url}/api/providers/dashboard",
                headers=_headers(api_key, bearer_token),
            )
            dashboard_response.raise_for_status()
            dashboard_payload = dashboard_response.json()
            dashboard_snapshots.append(dashboard_payload)

            tools = dashboard_payload.get("tools", [])
            owned_tool = next((tool for tool in tools if tool.get("tool_id") == tool_id), None)
            if owned_tool is not None:
                break

            if time.perf_counter() >= deadline:
                raise TimeoutError(
                    f"Provider-owned tool '{tool_id}' did not appear in dashboard "
                    f"within {timeout_seconds}s"
                )
            await asyncio.sleep(poll_interval_seconds)

        detail_response = await client.get(
            f"{base_url}/api/providers/tools/{tool_id}",
            headers=_headers(api_key, bearer_token),
        )
        detail_response.raise_for_status()

        missing_tool_response = await client.get(
            f"{base_url}/api/providers/tools/__nonexistent__",
            headers=_headers(api_key, bearer_token),
        )

    return {
        "server_id": server_id,
        "tool_id": tool_id,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "register_status": register_response.status_code,
        "unauthorized_status": negative_unauthorized.status_code,
        "detail_status": detail_response.status_code,
        "missing_tool_status": missing_tool_response.status_code,
        "dashboard_snapshots_seen": len(dashboard_snapshots),
    }


async def _async_main() -> None:
    parser = argparse.ArgumentParser(
        description=("Verify provider-owned dashboard behavior against a live MLP stage.")
    )
    parser.add_argument("--base-url", default=os.environ.get("MLP_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("MLP_API_KEY", ""))
    parser.add_argument("--bearer-token", default=os.environ.get("MLP_BEARER_TOKEN", ""))
    parser.add_argument(
        "--server-id",
        default=f"verify-provider-{int(time.time())}",
        help="Unique server_id to register for the verification run.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    args = parser.parse_args()

    if not (args.base_url and args.api_key and args.bearer_token):
        raise SystemExit(
            "Missing required live verification inputs. Set "
            "MLP_BASE_URL, MLP_API_KEY, and MLP_BEARER_TOKEN "
            "or pass --base-url/--api-key/--bearer-token."
        )

    result = await verify_provider_dashboard(
        base_url=args.base_url,
        api_key=args.api_key,
        bearer_token=args.bearer_token,
        server_id=args.server_id,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    print(json.dumps(result, indent=2))


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
