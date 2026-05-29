"""Health check Lambda — verifies external service connectivity."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

_MV_FRESHNESS_THRESHOLD_SECONDS = 15 * 60  # 15 minutes


async def _check_mv_freshness() -> dict[str, Any]:
    """Check materialized view freshness via tool_operational_stats."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url:
        return {"status": "skip", "reason": "SUPABASE_URL not set"}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/tool_operational_stats"
                "?select=last_called_at&order=last_called_at.desc&limit=1",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                return {"status": "ok", "reason": "mv_empty"}
            last_called_at_str = rows[0].get("last_called_at")
            if not last_called_at_str:
                return {"status": "ok", "reason": "no_timestamp"}
            last_called_at = datetime.fromisoformat(last_called_at_str.replace("Z", "+00:00"))
            age_seconds = (datetime.now(tz=timezone.utc) - last_called_at).total_seconds()
            if age_seconds > _MV_FRESHNESS_THRESHOLD_SECONDS:
                return {
                    "status": "degraded",
                    "reason": "mv_stale",
                    "age_seconds": round(age_seconds),
                }
            return {"status": "ok", "age_seconds": round(age_seconds)}
    except Exception as exc:
        logger.warning(f"MV freshness check failed (non-critical): {exc}")
        return {"status": "skip", "reason": f"check_failed: {exc}"}


async def _check_qdrant() -> dict[str, Any]:
    url = os.getenv("QDRANT_URL", "")
    api_key = os.getenv("QDRANT_API_KEY", "")
    if not url:
        return {"status": "skip", "reason": "QDRANT_URL not set"}
    headers = {"api-key": api_key} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{url}/healthz", headers=headers)
            status = "ok" if resp.status_code == 200 else "degraded"
            return {"status": status, "code": resp.status_code}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_supabase() -> dict[str, Any]:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url:
        return {"status": "skip", "reason": "SUPABASE_URL not set"}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            status = "ok" if resp.status_code == 200 else "degraded"
            return {"status": status, "code": resp.status_code}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _async_handler() -> dict[str, Any]:
    t0 = time.perf_counter()
    qdrant = await _check_qdrant()
    supabase = await _check_supabase()
    mv_freshness = await _check_mv_freshness()
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    overall = "healthy"
    for check in (qdrant, supabase):
        if check["status"] == "error":
            overall = "unhealthy"
            break
        if check["status"] == "degraded":
            overall = "degraded"
    # mv_freshness is non-critical: degraded only downgrades to degraded, never unhealthy
    if overall == "healthy" and mv_freshness.get("status") == "degraded":
        overall = "degraded"

    body = json.dumps(
        {
            "status": overall,
            "checks": {"qdrant": qdrant, "supabase": supabase, "mv_freshness": mv_freshness},
            "latency_ms": elapsed_ms,
        }
    )

    status_code = 200 if overall == "healthy" else 503
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": body,
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda entry point."""
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(_async_handler())
