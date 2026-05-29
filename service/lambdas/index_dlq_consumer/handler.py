"""IndexDLQ consumer — event-driven retry of failed indexing via primary Lambda.

When primary IndexFunction fails, Lambda routes the original EventBridge event
to IndexDLQ (SQS). This consumer:

  1. Fetches failed tools for the server_id (with retry_count).
  2. Partitions by DB-level retry_count (substrate-independent circuit breaker,
     because SQS ApproximateReceiveCount resets on EventBridge republish).
  3. Flips over-limit tools to the terminal `failed_permanent` state.
  4. For under-limit tools:
     a. Publishes `server.registered` to EventBridge (publish-first order).
     b. Atomically increments retry_count + flips `failed → pending` via RPC.
     c. Primary IndexFunction picks up the EB event and retries on the hybrid
        path (sparse + LLM enrichment).

The DLQ consumer never runs IndexService directly, so it cannot write dense-only
points and break the hybrid retrieval invariant.

Safety nets:
  - SQS MAX_RECEIVE_COUNT=3: message-level circuit breaker; on trip, tools are
    flipped to failed_permanent before the message is dropped.
  - MAX_RETRY_COUNT=5 (DB-level): primary poison-pill protection against SQS
    receive-count reset on republish.
  - COOLDOWN_SECONDS=120: per-server de-dup — skip republish if the server's
    failed tools were updated in the last 2 minutes (likely another retry
    already in flight).
  - IndexReplayFunction (30-min cron): catches pending tools whose DLQ
    republish path itself failed (defence in depth).

Observability (CloudWatch EMF, namespace `McpDiscovery/IndexDLQ`):
  - RedispatchSuccess: count of tools republished to primary.
  - RedispatchFailures: count of publish or RPC failures.
  - TerminalFailures: count of tools flipped to failed_permanent (Reason dim).
  - CooldownSkipped: count of records skipped due to per-server cooldown.
"""

import json
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

from service.adapters.eventbridge_client import EventBridgeClient, ServerRegisteredPublisher
from service.services.contracts import IndexRequest

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}

MAX_RECEIVE_COUNT = 3  # SQS-level circuit breaker (secondary)
MAX_RETRY_COUNT = 5  # DB-level circuit breaker (authoritative)
COOLDOWN_SECONDS = 120  # Per-server thundering-herd suppression

EMF_NAMESPACE = "McpDiscovery/IndexDLQ"

_eventbridge_client = None


# ---------------------------------------------------------------------------
# EventBridge publish (shared pattern with index_replay/handler.py)
# ---------------------------------------------------------------------------


class _LocalDirectDLQPublisher(ServerRegisteredPublisher):
    """Route DLQ republishes through the local relay in local_direct mode."""

    async def publish_server_registered(self, server_id: str) -> None:
        from service.lambdas.index.handler import _async_handler as index_handler
        from service.local_runtime.eventbridge_relay import LocalEventBridgeRelay

        relay = LocalEventBridgeRelay(index_handler=index_handler)
        await relay.start()
        try:
            await relay.publish_server_registered(server_id)
            await relay.drain()
        finally:
            await relay.stop()


def _get_eventbridge():
    """Lazy-initialise the raw boto3 EventBridge client (only for AWS mode)."""
    global _eventbridge_client  # noqa: PLW0603
    if _eventbridge_client is None:
        import boto3

        _eventbridge_client = boto3.client("events")
    return _eventbridge_client


def _build_eventbridge_client() -> EventBridgeClient:
    if os.getenv("MLP_EVENT_MODE") == "local_direct":
        return EventBridgeClient(publisher=_LocalDirectDLQPublisher())
    return EventBridgeClient(eb_client=_get_eventbridge())


# ---------------------------------------------------------------------------
# EMF metric emission (stdout JSON → CloudWatch Logs → Metrics)
# ---------------------------------------------------------------------------


def _emit_emf_metric(
    metric_name: str,
    value: float,
    *,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
) -> None:
    """Emit a CloudWatch EMF metric. Lambda auto-extracts metrics from any log
    line whose JSON root contains an ``_aws`` block; we bypass the Loguru
    formatter by writing directly to stdout.
    """
    dims = dimensions or {}
    emf = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": EMF_NAMESPACE,
                    "Dimensions": [list(dims.keys())] if dims else [[]],
                    "Metrics": [{"Name": metric_name, "Unit": unit}],
                }
            ],
        },
        metric_name: value,
        **dims,
    }
    sys.stdout.write(json.dumps(emf) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# SQS record parsing
# ---------------------------------------------------------------------------


def _get_receive_count(record: dict) -> int:
    """Extract ApproximateReceiveCount from SQS record attributes."""
    attributes = record.get("attributes", {})
    try:
        return int(attributes.get("ApproximateReceiveCount", "1"))
    except (ValueError, TypeError):
        return 1


def _parse_updated_at(value: str) -> datetime:
    """Parse PostgREST ISO timestamp (may end with Z or +00:00)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Supabase REST / RPC helpers
# ---------------------------------------------------------------------------


async def _fetch_failed_tools(server_id: str) -> list[dict]:
    """Fetch tools in 'failed' state for this server incl. retry_count, updated_at."""
    url = f"{SUPABASE_URL}/rest/v1/mcp_tools"
    params = {
        "server_id": f"eq.{server_id}",
        "index_status": "eq.failed",
        "select": "tool_id,retry_count,updated_at",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=SUPABASE_HEADERS, params=params, timeout=10.0)
        resp.raise_for_status()
        return resp.json()


async def _mark_failed_permanent(tool_ids: list[str]) -> int:
    """Flip the given tools to the terminal 'failed_permanent' state."""
    if not tool_ids:
        return 0
    url = f"{SUPABASE_URL}/rest/v1/mcp_tools"
    params = {"tool_id": f"in.({','.join(tool_ids)})"}
    headers = {**SUPABASE_HEADERS, "Prefer": "return=representation"}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            url,
            headers=headers,
            params=params,
            json={"index_status": "failed_permanent"},
            timeout=10.0,
        )
        resp.raise_for_status()
        return len(resp.json())


async def _increment_retry_and_reset(tool_ids: list[str]) -> int:
    """Atomic increment retry_count + flip failed→pending via Postgres RPC.

    Guarded by ``index_status=failed`` inside the RPC so concurrent DLQ messages
    for the same tool cannot double-increment.
    """
    if not tool_ids:
        return 0
    url = f"{SUPABASE_URL}/rest/v1/rpc/increment_retry_and_reset_to_pending"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers=SUPABASE_HEADERS,
            json={"p_tool_ids": tool_ids},
            timeout=10.0,
        )
        resp.raise_for_status()
        return len(resp.json())


# ---------------------------------------------------------------------------
# Main record processor
# ---------------------------------------------------------------------------


async def _process_record(record: dict) -> dict:
    """Process a single SQS DLQ record.

    Invariants:
      - EventBridge publish MUST happen before the retry_count increment so that
        if publish fails we do not orphan tools in 'pending' with a bumped
        counter.
      - Over-limit tools (retry_count >= MAX_RETRY_COUNT) bypass republish and
        transition to the terminal failed_permanent state.
      - SQS MAX_RECEIVE_COUNT trip is a terminal safety net that also marks
        failed_permanent (prevents silent drop of poisoned messages).
    """
    body_str = record.get("body", "{}")
    receive_count = _get_receive_count(record)
    message_id = record.get("messageId", "unknown")

    # Parse EventBridge envelope from SQS body first so we know the server_id
    # even in the circuit-breaker branch.
    try:
        eb_event = json.loads(body_str) if isinstance(body_str, str) else body_str
        detail = eb_event.get("detail", {})
        if isinstance(detail, str):
            detail = json.loads(detail)
        request = IndexRequest.model_validate(detail)
    except Exception as exc:
        logger.error(f"DLQ {message_id}: invalid event payload: {exc}")
        return {"messageId": message_id, "status": "invalid_payload", "error": str(exc)}

    server_id = request.server_id

    # SQS-level circuit breaker (terminal safety):
    # If the message has bounced back MAX_RECEIVE_COUNT times, flip the
    # server's failed tools to failed_permanent and drop the message. Without
    # this, the message would be silently dropped while tools stay stuck in
    # 'failed' forever without an alarm surface.
    if receive_count >= MAX_RECEIVE_COUNT:
        logger.warning(
            f"DLQ {message_id} exceeded SQS receive count "
            f"({receive_count}/{MAX_RECEIVE_COUNT}); "
            f"flipping server={server_id} failed tools to failed_permanent"
        )
        failed_tools = await _fetch_failed_tools(server_id)
        tool_ids = [t["tool_id"] for t in failed_tools]
        marked = await _mark_failed_permanent(tool_ids) if tool_ids else 0
        _emit_emf_metric(
            "TerminalFailures", marked, dimensions={"Reason": "sqs_circuit_breaker"}
        )
        return {
            "messageId": message_id,
            "server_id": server_id,
            "status": "terminal_sqs_exhausted",
            "failed_permanent_count": marked,
        }

    # Normal path
    failed_tools = await _fetch_failed_tools(server_id)
    if not failed_tools:
        logger.info(
            f"DLQ {message_id}: no failed tools for server={server_id} "
            f"(race or already handled)"
        )
        return {
            "messageId": message_id,
            "server_id": server_id,
            "status": "no_failed_tools",
        }

    # Per-server cooldown: if the most recent update is within COOLDOWN_SECONDS,
    # another republish is likely in flight. Skip to avoid thundering herd.
    now = datetime.now(UTC)
    most_recent = max(_parse_updated_at(t["updated_at"]) for t in failed_tools)
    if (now - most_recent).total_seconds() < COOLDOWN_SECONDS:
        logger.info(
            f"DLQ {message_id}: cooldown active for server={server_id} "
            f"(most_recent={most_recent.isoformat()}); skipping republish"
        )
        _emit_emf_metric("CooldownSkipped", 1)
        return {
            "messageId": message_id,
            "server_id": server_id,
            "status": "cooldown_skipped",
        }

    # Partition by DB-level retry_count (authoritative circuit breaker)
    over_limit_ids = [
        t["tool_id"] for t in failed_tools if int(t.get("retry_count", 0)) >= MAX_RETRY_COUNT
    ]
    under_limit_ids = [
        t["tool_id"] for t in failed_tools if int(t.get("retry_count", 0)) < MAX_RETRY_COUNT
    ]

    terminal_count = 0
    if over_limit_ids:
        terminal_count = await _mark_failed_permanent(over_limit_ids)
        _emit_emf_metric(
            "TerminalFailures",
            terminal_count,
            dimensions={"Reason": "retry_count_exhausted"},
        )
        logger.warning(
            f"DLQ {message_id}: server={server_id} terminal={terminal_count} "
            f"(retry_count >= {MAX_RETRY_COUNT})"
        )

    republished_count = 0
    if under_limit_ids:
        # Publish-first: if publish fails we raise, SQS re-delivers, and the
        # tools stay in 'failed' without an orphaned retry_count bump.
        try:
            await _build_eventbridge_client().publish_server_registered(server_id)
        except Exception as exc:
            logger.error(
                f"DLQ {message_id}: EB publish failed for server={server_id}: {exc}"
            )
            _emit_emf_metric(
                "RedispatchFailures", 1, dimensions={"Phase": "publish"}
            )
            raise

        # Publish succeeded → atomic RPC increment + flip to pending.
        # If the RPC fails here, SQS re-delivers and we may publish a duplicate
        # EB event. Primary IndexFunction's optimistic claim lock
        # (index_status=eq.pending) makes this safe.
        try:
            republished_count = await _increment_retry_and_reset(under_limit_ids)
        except Exception as exc:
            logger.error(
                f"DLQ {message_id}: RPC failed after successful EB publish "
                f"for server={server_id}: {exc}"
            )
            _emit_emf_metric(
                "RedispatchFailures", 1, dimensions={"Phase": "rpc_update"}
            )
            raise

        _emit_emf_metric("RedispatchSuccess", republished_count)
        logger.info(
            f"DLQ {message_id}: server={server_id} republished={republished_count} "
            f"terminal={terminal_count} (receive_count={receive_count})"
        )

    if republished_count > 0:
        status = "redispatched"
    elif terminal_count > 0:
        status = "all_terminal"
    else:
        # Should not happen: we had failed_tools but neither bucket; defensive.
        status = "no_action"

    return {
        "messageId": message_id,
        "server_id": server_id,
        "status": status,
        "republished_count": republished_count,
        "terminal_count": terminal_count,
    }


async def _async_handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    """Process SQS batch with ReportBatchItemFailures semantics."""
    records = event.get("Records", [])
    if not records:
        return {"batchItemFailures": []}

    batch_item_failures: list[dict] = []
    for record in records:
        try:
            await _process_record(record)
        except Exception:
            batch_item_failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": batch_item_failures}


def lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """AWS Lambda entry point."""
    from service.shared.event_loop import get_or_create_loop

    loop = get_or_create_loop()
    return loop.run_until_complete(_async_handler(event, context))
