"""Delegated OAuth execute loop harness.

Sample mode proves the expected auth/retry accounting shape. Live mode can call
the local API sequence once the local app and controlled OAuth provider stubs
are available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx


def summarize_delegated_oauth_runs(results: list[dict[str, Any]]) -> dict[str, float]:
    """Summarize auth-required, callback, and retry outcomes."""
    if not results:
        return {
            "runs": 0.0,
            "auth_required_rate": 0.0,
            "callback_success_rate": 0.0,
            "retry_success_rate": 0.0,
        }

    total = len(results)
    return {
        "runs": float(total),
        "auth_required_rate": sum(1 for item in results if item.get("auth_required")) / total,
        "callback_success_rate": sum(1 for item in results if item.get("callback_ok")) / total,
        "retry_success_rate": sum(1 for item in results if item.get("retry_ok")) / total,
    }


async def run_live_loop(
    *,
    base_url: str,
    api_key: str,
    bearer_token: str,
    provider: str,
    tool_id: str,
    params: dict[str, Any],
    required_scopes: list[str],
    callback_code: str,
) -> list[dict[str, Any]]:
    """Run a single live local proof through execute, OAuth start/callback, and retry."""
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers) as client:
        first = await client.post("/api/execute", json={"tool_id": tool_id, "params": params})
        first_body = first.json()

        start = await client.post(
            f"/api/oauth/providers/{provider}/start",
            json={
                "provider": provider,
                "tool_id": tool_id,
                "required_scopes": required_scopes,
            },
        )
        start_body = start.json()

        callback = await client.get(
            f"/api/oauth/providers/{provider}/callback",
            params={"code": callback_code, "state": start_body.get("state", "")},
        )

        second = await client.post("/api/execute", json={"tool_id": tool_id, "params": params})
        return [
            {
                "auth_required": first_body.get("status") == "auth_required",
                "callback_ok": callback.status_code == 200,
                "retry_ok": 200 <= second.status_code < 300,
                "first_status_code": first.status_code,
                "callback_status_code": callback.status_code,
                "retry_status_code": second.status_code,
            }
        ]


def _sample_results() -> list[dict[str, Any]]:
    return [
        {"auth_required": True, "callback_ok": True, "retry_ok": True},
        {"auth_required": True, "callback_ok": True, "retry_ok": True},
    ]


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Run delegated OAuth execute loop verification.")
    parser.add_argument("--results-file")
    parser.add_argument("--base-url", default=os.environ.get("MLP_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("MLP_API_KEY", ""))
    parser.add_argument("--bearer-token", default=os.environ.get("MLP_BEARER_TOKEN", ""))
    parser.add_argument("--provider", default="github")
    parser.add_argument("--tool-id", default="github::create_issue")
    parser.add_argument("--params-json", default='{"title":"bug"}')
    parser.add_argument("--required-scopes", default="repo,issues:write")
    parser.add_argument("--callback-code", default="fake-code")
    args = parser.parse_args()

    if args.results_file:
        results = json.loads(Path(args.results_file).read_text())
        mode = "file"
        note = "Loaded delegated OAuth run results from file."
    elif args.base_url and args.api_key and args.bearer_token:
        results = await run_live_loop(
            base_url=args.base_url,
            api_key=args.api_key,
            bearer_token=args.bearer_token,
            provider=args.provider,
            tool_id=args.tool_id,
            params=json.loads(args.params_json),
            required_scopes=[scope.strip() for scope in args.required_scopes.split(",")],
            callback_code=args.callback_code,
        )
        mode = "live"
        note = "Live delegated OAuth loop completed."
    else:
        results = _sample_results()
        mode = "sample"
        note = (
            "Set MLP_BASE_URL, MLP_API_KEY, and MLP_BEARER_TOKEN for a live local API run."
        )

    print(
        json.dumps(
            {
                "mode": mode,
                "note": note,
                "summary": summarize_delegated_oauth_runs(results),
                "results": results,
            },
            indent=2,
        )
    )


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
