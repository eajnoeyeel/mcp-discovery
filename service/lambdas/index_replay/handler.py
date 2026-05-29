"""IndexReplay Lambda — scans for stuck tools and re-emits EventBridge events.

Tools can get stuck in 'event_failed' (EventBridge publish failed during
registration) or 'pending' (indexing never triggered). This scheduled Lambda
finds those tools, resets them to 'pending', and re-publishes the
server.registered event to trigger IndexFunction.

Runs on a 30-minute schedule. Self-limiting: processes at most 20 servers
per invocation to avoid overwhelming the indexing pipeline.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger

from service.adapters.eventbridge_client import EventBridgeClient, ServerRegisteredPublisher
from service.local_runtime.eventbridge_relay import LocalEventBridgeRelay

_SUPABASE_URL = os.getenv("SUPABASE_URL", "")
_SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
_MAX_SERVERS_PER_RUN = 20
_STUCK_THRESHOLD_MINUTES = 30

_eventbridge_client = None


class _LocalDirectReplayPublisher(ServerRegisteredPublisher):
    """Replay publisher that routes server.registered events directly to the local relay."""

    async def publish_server_registered(self, server_id: str) -> None:
        from service.lambdas.index.handler import _async_handler as index_handler

        relay = LocalEventBridgeRelay(index_handler=index_handler)
        await relay.start()
        try:
            await relay.publish_server_registered(server_id)
            await relay.drain()
        finally:
            await relay.stop()


def _supabase_headers() -> dict[str, str]:
    return {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


async def _fetch_stuck_servers() -> list[dict]:
    """Find servers with tools stuck in event_failed or pending for >threshold."""
    url = f"{_SUPABASE_URL}/rest/v1/mcp_tools"
    # PostgREST horizontal filters do not evaluate SQL expressions; passing
    # `now()-interval'30 minutes'` as a literal string produces a timestamptz
    # cast error (22007) and returns 400. Compute the threshold client-side.
    threshold_iso = (
        datetime.now(UTC) - timedelta(minutes=_STUCK_THRESHOLD_MINUTES)
    ).isoformat()
    stuck_filter = (
        f"(index_status.eq.event_failed,"
        f"and(index_status.eq.pending,"
        f"created_at.lt.{threshold_iso}))"
    )
    params = {
        "select": "server_id",
        "or": stuck_filter,
        "limit": "200",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=_supabase_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()

    server_counts: dict[str, int] = {}
    for row in rows:
        sid = row["server_id"]
        server_counts[sid] = server_counts.get(sid, 0) + 1

    result = [{"server_id": sid, "stuck_count": count} for sid, count in server_counts.items()]
    return result[:_MAX_SERVERS_PER_RUN]


async def _reset_tools_to_pending(server_id: str) -> None:
    """Reset event_failed/stuck-pending tools back to 'pending' for re-indexing."""
    url = f"{_SUPABASE_URL}/rest/v1/mcp_tools"
    params = {
        "server_id": f"eq.{server_id}",
        "or": "(index_status.eq.event_failed,index_status.eq.pending)",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            url,
            headers=_supabase_headers(),
            params=params,
            json={"index_status": "pending"},
        )
        resp.raise_for_status()


def _get_eventbridge():
    """Lazy-initialize the raw boto3 EventBridge client when replay runs in AWS."""
    global _eventbridge_client  # noqa: PLW0603
    if _eventbridge_client is None:
        import boto3

        _eventbridge_client = boto3.client("events")
    return _eventbridge_client


def _build_eventbridge_client() -> EventBridgeClient:
    """Build the shared EventBridge publisher abstraction for replay flows."""
    if os.getenv("MLP_EVENT_MODE") == "local_direct":
        return EventBridgeClient(publisher=_LocalDirectReplayPublisher())
    return EventBridgeClient(eb_client=_get_eventbridge())


async def _publish_server_registered(server_id: str) -> bool:
    """Re-publish server.registered event to trigger IndexFunction."""
    try:
        await _build_eventbridge_client().publish_server_registered(server_id)
        return True
    except Exception as e:
        logger.error(f"EventBridge replay failed for server_id={server_id}: {e}")
        return False


async def _async_handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    stuck_servers = await _fetch_stuck_servers()
    if not stuck_servers:
        logger.info("IndexReplay: no stuck tools found")
        return {
            "statusCode": 200,
            "body": json.dumps({"replayed_count": 0, "failed_count": 0}),
        }

    replayed = 0
    failed = 0

    for entry in stuck_servers:
        server_id = entry["server_id"]
        stuck_count = entry["stuck_count"]
        try:
            await _reset_tools_to_pending(server_id)
            success = await _publish_server_registered(server_id)
            if success:
                replayed += 1
                logger.info(f"IndexReplay: replayed server_id={server_id} ({stuck_count} tools)")
            else:
                failed += 1
        except Exception as e:
            logger.error(f"IndexReplay: failed for server_id={server_id}: {e}")
            failed += 1

    logger.info(f"IndexReplay complete: replayed={replayed}, failed={failed}")
    return {
        "statusCode": 200,
        "body": json.dumps({"replayed_count": replayed, "failed_count": failed}),
    }


def lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """AWS Lambda entry point."""
    from service.shared.event_loop import get_or_create_loop

    loop = get_or_create_loop()
    return loop.run_until_complete(_async_handler(event, context))
