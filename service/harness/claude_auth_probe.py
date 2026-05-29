"""Claude/Codex auth probe harness for clear and re-auth verification."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

import httpx


def summarize_auth_probe_runs(results: list[dict[str, Any]]) -> dict[str, float]:
    """Summarize protected auth probe outcomes across clear/re-auth checks."""
    if not results:
        return {
            "runs": 0.0,
            "authenticated_rate": 0.0,
            "auth_required_rate": 0.0,
            "validation_unavailable_rate": 0.0,
        }

    total = len(results)
    return {
        "runs": float(total),
        "authenticated_rate": sum(
            1 for item in results if item.get("authenticated") is True
        )
        / total,
        "auth_required_rate": sum(
            1 for item in results if item.get("status") == "auth_required"
        )
        / total,
        "validation_unavailable_rate": sum(
            1 for item in results if item.get("status") == "validation_unavailable"
        )
        / total,
    }


async def run_probe(
    *,
    base_url: str,
    api_key: str,
    bearer_token: str | None,
    label: str,
) -> dict[str, Any]:
    """Call the local protected auth probe with optional bearer auth."""
    headers = {"x-api-key": api_key}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{base_url.rstrip('/')}/api/auth/probe", headers=headers)
    payload = response.json()
    return {
        "label": label,
        "status_code": response.status_code,
        "authenticated": payload.get("authenticated", False),
        "status": payload.get("status")
        or ("http_error" if response.status_code >= 400 else "unknown"),
        "body": payload,
    }


def _sample_results() -> list[dict[str, Any]]:
    return [
        {"label": "cleared", "status_code": 401, "authenticated": False, "status": "auth_required"},
        {
            "label": "reauthenticated",
            "status_code": 200,
            "authenticated": True,
            "status": "authenticated",
        },
    ]


async def _async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Run protected auth probe checks for clear and re-auth states."
    )
    parser.add_argument("--base-url", default=os.environ.get("MLP_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("MLP_API_KEY", ""))
    parser.add_argument("--bearer-token", default=os.environ.get("MLP_BEARER_TOKEN", ""))
    args = parser.parse_args()

    if args.base_url and args.api_key:
        results = [
            await run_probe(
                base_url=args.base_url,
                api_key=args.api_key,
                bearer_token=None,
                label="cleared",
            )
        ]
        if args.bearer_token:
            results.append(
                await run_probe(
                    base_url=args.base_url,
                    api_key=args.api_key,
                    bearer_token=args.bearer_token,
                    label="reauthenticated",
                )
            )
        mode = "live"
        note = "Live auth probe completed against the configured backend."
    else:
        results = _sample_results()
        mode = "sample"
        note = "Set MLP_BASE_URL, MLP_API_KEY, and MLP_BEARER_TOKEN for live probing."

    print(
        json.dumps(
            {
                "mode": mode,
                "note": note,
                "summary": summarize_auth_probe_runs(results),
                "results": results,
            },
            indent=2,
        )
    )


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
