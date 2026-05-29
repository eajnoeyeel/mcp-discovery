"""Unit tests for the IndexDLQ consumer Lambda handler (ADR-0024)."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _sqs_record(
    server_id: str = "test-server",
    message_id: str = "msg-001",
    receive_count: int = 1,
) -> dict:
    eb_event = {
        "version": "0",
        "source": "mcp-discovery",
        "detail-type": "server.registered",
        "detail": {"server_id": server_id},
    }
    return {
        "messageId": message_id,
        "body": json.dumps(eb_event),
        "attributes": {"ApproximateReceiveCount": str(receive_count)},
    }


def _sqs_event(*records: dict) -> dict:
    return {"Records": list(records)}


def _failed_tool(
    tool_id: str = "test-server::t1",
    retry_count: int = 0,
    updated_at: datetime | None = None,
) -> dict:
    return {
        "tool_id": tool_id,
        "retry_count": retry_count,
        "updated_at": (updated_at or datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    }


# ---------------------------------------------------------------------------
# _get_receive_count
# ---------------------------------------------------------------------------


def test_get_receive_count_normal():
    from service.lambdas.index_dlq_consumer.handler import _get_receive_count

    assert _get_receive_count({"attributes": {"ApproximateReceiveCount": "2"}}) == 2


def test_get_receive_count_missing():
    from service.lambdas.index_dlq_consumer.handler import _get_receive_count

    assert _get_receive_count({}) == 1
    assert _get_receive_count({"attributes": {}}) == 1


def test_get_receive_count_invalid():
    from service.lambdas.index_dlq_consumer.handler import _get_receive_count

    assert _get_receive_count({"attributes": {"ApproximateReceiveCount": "NaN"}}) == 1


# ---------------------------------------------------------------------------
# _parse_updated_at — Z and +00:00 variants
# ---------------------------------------------------------------------------


def test_parse_updated_at_accepts_z_suffix():
    from service.lambdas.index_dlq_consumer.handler import _parse_updated_at

    parsed = _parse_updated_at("2026-04-19T08:00:00Z")
    assert parsed.tzinfo is not None


def test_parse_updated_at_accepts_offset_suffix():
    from service.lambdas.index_dlq_consumer.handler import _parse_updated_at

    parsed = _parse_updated_at("2026-04-19T08:00:00+00:00")
    assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# Invalid payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_record_invalid_payload():
    from service.lambdas.index_dlq_consumer.handler import _process_record

    record = {
        "messageId": "msg-bad",
        "body": "not valid json {{{",
        "attributes": {"ApproximateReceiveCount": "1"},
    }
    result = await _process_record(record)
    assert result["status"] == "invalid_payload"


@pytest.mark.asyncio
async def test_process_record_missing_server_id():
    from service.lambdas.index_dlq_consumer.handler import _process_record

    record = {
        "messageId": "msg-no-sid",
        "body": json.dumps({"detail": {}}),
        "attributes": {"ApproximateReceiveCount": "1"},
    }
    result = await _process_record(record)
    assert result["status"] == "invalid_payload"


# ---------------------------------------------------------------------------
# SQS-level circuit breaker — terminal safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqs_circuit_breaker_flips_to_failed_permanent():
    """At MAX_RECEIVE_COUNT the message is dropped but failed tools must be
    flipped to failed_permanent so they surface in TerminalFailures metric
    instead of sitting forever in 'failed'."""
    from service.lambdas.index_dlq_consumer.handler import _process_record

    record = _sqs_record(receive_count=3)

    with (
        patch(
            "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
            new_callable=AsyncMock,
            return_value=[_failed_tool("test-server::t1"), _failed_tool("test-server::t2")],
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._mark_failed_permanent",
            new_callable=AsyncMock,
            return_value=2,
        ) as mock_permanent,
        patch("service.lambdas.index_dlq_consumer.handler._emit_emf_metric") as mock_emf,
    ):
        result = await _process_record(record)

    assert result["status"] == "terminal_sqs_exhausted"
    assert result["failed_permanent_count"] == 2
    mock_permanent.assert_awaited_once_with(["test-server::t1", "test-server::t2"])
    # EMF emitted with sqs_circuit_breaker reason
    emf_calls = [c.args + (c.kwargs,) for c in mock_emf.call_args_list]
    assert any("TerminalFailures" in str(c) and "sqs_circuit_breaker" in str(c) for c in emf_calls)


@pytest.mark.asyncio
async def test_sqs_circuit_breaker_no_failed_tools_still_completes():
    """Circuit-breaker branch is safe when no tools are in 'failed' state."""
    from service.lambdas.index_dlq_consumer.handler import _process_record

    record = _sqs_record(receive_count=5)

    with (
        patch(
            "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._mark_failed_permanent",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_permanent,
        patch("service.lambdas.index_dlq_consumer.handler._emit_emf_metric"),
    ):
        result = await _process_record(record)

    assert result["status"] == "terminal_sqs_exhausted"
    assert result["failed_permanent_count"] == 0
    mock_permanent.assert_not_awaited()


# ---------------------------------------------------------------------------
# Normal path — no failed tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_record_no_failed_tools():
    from service.lambdas.index_dlq_consumer.handler import _process_record

    record = _sqs_record(server_id="clean-server")
    with patch(
        "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await _process_record(record)
    assert result["status"] == "no_failed_tools"


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cooldown_skips_recent_updates():
    """If failed tools were updated <COOLDOWN_SECONDS ago, skip republish."""
    from service.lambdas.index_dlq_consumer.handler import _process_record

    recent_update = datetime.now(UTC) - timedelta(seconds=30)
    record = _sqs_record()

    with (
        patch(
            "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
            new_callable=AsyncMock,
            return_value=[_failed_tool(updated_at=recent_update)],
        ),
        patch("service.lambdas.index_dlq_consumer.handler._build_eventbridge_client") as mock_eb,
        patch(
            "service.lambdas.index_dlq_consumer.handler._increment_retry_and_reset",
            new_callable=AsyncMock,
        ) as mock_rpc,
        patch("service.lambdas.index_dlq_consumer.handler._emit_emf_metric"),
    ):
        result = await _process_record(record)

    assert result["status"] == "cooldown_skipped"
    mock_eb.assert_not_called()
    mock_rpc.assert_not_awaited()


@pytest.mark.asyncio
async def test_cooldown_passes_for_old_updates():
    """If failed tools were updated >COOLDOWN_SECONDS ago, republish proceeds."""
    from service.lambdas.index_dlq_consumer.handler import _process_record

    old_update = datetime.now(UTC) - timedelta(minutes=10)
    record = _sqs_record()

    eb_client = AsyncMock()
    eb_client.publish_server_registered = AsyncMock()

    with (
        patch(
            "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
            new_callable=AsyncMock,
            return_value=[_failed_tool(updated_at=old_update, retry_count=1)],
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._build_eventbridge_client",
            return_value=eb_client,
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._increment_retry_and_reset",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_rpc,
        patch("service.lambdas.index_dlq_consumer.handler._emit_emf_metric"),
    ):
        result = await _process_record(record)

    assert result["status"] == "redispatched"
    eb_client.publish_server_registered.assert_awaited_once()
    mock_rpc.assert_awaited_once()


# ---------------------------------------------------------------------------
# retry_count circuit breaker — DB-level
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_over_retry_limit_marks_failed_permanent_no_publish():
    """Tools at or over MAX_RETRY_COUNT flip to failed_permanent and do NOT
    trigger an EB republish."""
    from service.lambdas.index_dlq_consumer.handler import MAX_RETRY_COUNT, _process_record

    record = _sqs_record()
    old = datetime.now(UTC) - timedelta(hours=1)

    eb_client = AsyncMock()
    eb_client.publish_server_registered = AsyncMock()

    with (
        patch(
            "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
            new_callable=AsyncMock,
            return_value=[
                _failed_tool("s::t1", retry_count=MAX_RETRY_COUNT, updated_at=old),
                _failed_tool("s::t2", retry_count=MAX_RETRY_COUNT + 1, updated_at=old),
            ],
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._mark_failed_permanent",
            new_callable=AsyncMock,
            return_value=2,
        ) as mock_permanent,
        patch(
            "service.lambdas.index_dlq_consumer.handler._build_eventbridge_client",
            return_value=eb_client,
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._increment_retry_and_reset",
            new_callable=AsyncMock,
        ) as mock_rpc,
        patch("service.lambdas.index_dlq_consumer.handler._emit_emf_metric"),
    ):
        result = await _process_record(record)

    assert result["status"] == "all_terminal"
    assert result["terminal_count"] == 2
    assert result["republished_count"] == 0
    mock_permanent.assert_awaited_once_with(["s::t1", "s::t2"])
    eb_client.publish_server_registered.assert_not_awaited()
    mock_rpc.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_over_and_under_limit_splits_correctly():
    """Tools under the limit republish; tools at/over the limit terminal."""
    from service.lambdas.index_dlq_consumer.handler import MAX_RETRY_COUNT, _process_record

    record = _sqs_record()
    old = datetime.now(UTC) - timedelta(hours=1)

    eb_client = AsyncMock()
    eb_client.publish_server_registered = AsyncMock()

    with (
        patch(
            "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
            new_callable=AsyncMock,
            return_value=[
                _failed_tool("s::t1", retry_count=MAX_RETRY_COUNT, updated_at=old),
                _failed_tool("s::t2", retry_count=MAX_RETRY_COUNT - 1, updated_at=old),
            ],
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._mark_failed_permanent",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_permanent,
        patch(
            "service.lambdas.index_dlq_consumer.handler._build_eventbridge_client",
            return_value=eb_client,
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._increment_retry_and_reset",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_rpc,
        patch("service.lambdas.index_dlq_consumer.handler._emit_emf_metric"),
    ):
        result = await _process_record(record)

    assert result["status"] == "redispatched"
    assert result["terminal_count"] == 1
    assert result["republished_count"] == 1
    mock_permanent.assert_awaited_once_with(["s::t1"])
    mock_rpc.assert_awaited_once_with(["s::t2"])


@pytest.mark.asyncio
async def test_under_limit_republishes():
    from service.lambdas.index_dlq_consumer.handler import _process_record

    record = _sqs_record()
    old = datetime.now(UTC) - timedelta(hours=1)

    eb_client = AsyncMock()
    eb_client.publish_server_registered = AsyncMock()

    with (
        patch(
            "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
            new_callable=AsyncMock,
            return_value=[
                _failed_tool("s::t1", retry_count=0, updated_at=old),
                _failed_tool("s::t2", retry_count=2, updated_at=old),
            ],
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._build_eventbridge_client",
            return_value=eb_client,
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._increment_retry_and_reset",
            new_callable=AsyncMock,
            return_value=2,
        ) as mock_rpc,
        patch("service.lambdas.index_dlq_consumer.handler._emit_emf_metric"),
    ):
        result = await _process_record(record)

    assert result["status"] == "redispatched"
    assert result["republished_count"] == 2
    eb_client.publish_server_registered.assert_awaited_once_with("test-server")
    mock_rpc.assert_awaited_once_with(["s::t1", "s::t2"])


# ---------------------------------------------------------------------------
# Publish-first ordering — if publish fails, RPC MUST NOT run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_failure_aborts_before_rpc():
    """EB publish raising must propagate and the retry_count RPC must not run."""
    from service.lambdas.index_dlq_consumer.handler import _process_record

    record = _sqs_record()
    old = datetime.now(UTC) - timedelta(hours=1)

    eb_client = AsyncMock()
    eb_client.publish_server_registered = AsyncMock(side_effect=RuntimeError("EB throttled"))

    with (
        patch(
            "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
            new_callable=AsyncMock,
            return_value=[_failed_tool("s::t1", retry_count=0, updated_at=old)],
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._build_eventbridge_client",
            return_value=eb_client,
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._increment_retry_and_reset",
            new_callable=AsyncMock,
        ) as mock_rpc,
        patch("service.lambdas.index_dlq_consumer.handler._emit_emf_metric") as mock_emf,
    ):
        with pytest.raises(RuntimeError, match="EB throttled"):
            await _process_record(record)

    # RPC must NOT have run
    mock_rpc.assert_not_awaited()
    # Failure metric emitted in publish phase
    assert any(
        "RedispatchFailures" in str(c) and "publish" in str(c)
        for c in [str(call) for call in mock_emf.call_args_list]
    )


@pytest.mark.asyncio
async def test_rpc_failure_after_publish_raises_for_sqs_retry():
    """If RPC fails after publish succeeds, exception bubbles so SQS re-delivers.
    Duplicate EB publish on retry is safe via primary Lambda's claim lock."""
    from service.lambdas.index_dlq_consumer.handler import _process_record

    record = _sqs_record()
    old = datetime.now(UTC) - timedelta(hours=1)

    eb_client = AsyncMock()
    eb_client.publish_server_registered = AsyncMock()

    with (
        patch(
            "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
            new_callable=AsyncMock,
            return_value=[_failed_tool("s::t1", retry_count=0, updated_at=old)],
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._build_eventbridge_client",
            return_value=eb_client,
        ),
        patch(
            "service.lambdas.index_dlq_consumer.handler._increment_retry_and_reset",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Supabase 500"),
        ),
        patch("service.lambdas.index_dlq_consumer.handler._emit_emf_metric") as mock_emf,
    ):
        with pytest.raises(RuntimeError, match="Supabase 500"):
            await _process_record(record)

    eb_client.publish_server_registered.assert_awaited_once()
    assert any(
        "RedispatchFailures" in str(c) and "rpc_update" in str(c)
        for c in [str(call) for call in mock_emf.call_args_list]
    )


# ---------------------------------------------------------------------------
# EMF metric emission — structure assertion
# ---------------------------------------------------------------------------


def test_emit_emf_metric_writes_valid_emf_json(monkeypatch):
    """EMF lines must be pure JSON with an ``_aws`` block at the root."""
    from service.lambdas.index_dlq_consumer import handler

    buf = io.StringIO()
    monkeypatch.setattr(handler.sys, "stdout", buf)

    handler._emit_emf_metric("TestMetric", 3, unit="Count", dimensions={"Reason": "probe"})
    line = buf.getvalue().strip()
    payload = json.loads(line)
    assert "_aws" in payload
    assert payload["_aws"]["CloudWatchMetrics"][0]["Namespace"] == handler.EMF_NAMESPACE
    assert payload["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"] == "TestMetric"
    assert payload["TestMetric"] == 3
    assert payload["Reason"] == "probe"


def test_emit_emf_metric_handles_empty_dimensions(monkeypatch):
    from service.lambdas.index_dlq_consumer import handler

    buf = io.StringIO()
    monkeypatch.setattr(handler.sys, "stdout", buf)

    handler._emit_emf_metric("NoDimMetric", 1)
    payload = json.loads(buf.getvalue().strip())
    assert payload["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]]


# ---------------------------------------------------------------------------
# EventBridge client builder — local_direct vs AWS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_eventbridge_client_local_direct(monkeypatch):
    from service.lambdas.index_dlq_consumer import handler

    monkeypatch.setenv("MLP_EVENT_MODE", "local_direct")
    client = handler._build_eventbridge_client()
    # local_direct publisher should be wired — inspect internal
    assert isinstance(client._publisher, handler._LocalDirectDLQPublisher)


def test_build_eventbridge_client_aws(monkeypatch):
    from service.lambdas.index_dlq_consumer import handler

    monkeypatch.delenv("MLP_EVENT_MODE", raising=False)
    monkeypatch.setattr(handler, "_get_eventbridge", lambda: MagicMock())
    client = handler._build_eventbridge_client()
    # Should use boto3 publisher, not LocalDirect
    assert not isinstance(client._publisher, handler._LocalDirectDLQPublisher)


# ---------------------------------------------------------------------------
# Supabase helpers — httpx transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_failed_tools_selects_retry_fields():
    from service.lambdas.index_dlq_consumer.handler import _fetch_failed_tools

    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"tool_id": "s::t1", "retry_count": 0, "updated_at": "2026-04-19T00:00:00Z"}
    ]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "service.lambdas.index_dlq_consumer.handler.httpx.AsyncClient", return_value=mock_client
    ):
        result = await _fetch_failed_tools("srv-1")

    assert result[0]["retry_count"] == 0
    call_kwargs = str(mock_client.get.call_args)
    assert "retry_count" in call_kwargs
    assert "updated_at" in call_kwargs
    assert "eq.failed" in call_kwargs


@pytest.mark.asyncio
async def test_mark_failed_permanent_sends_correct_patch():
    from service.lambdas.index_dlq_consumer.handler import _mark_failed_permanent

    mock_response = MagicMock()
    mock_response.json.return_value = [{"tool_id": "t1"}, {"tool_id": "t2"}]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.patch.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "service.lambdas.index_dlq_consumer.handler.httpx.AsyncClient", return_value=mock_client
    ):
        count = await _mark_failed_permanent(["t1", "t2"])

    assert count == 2
    call_kwargs = str(mock_client.patch.call_args)
    assert "failed_permanent" in call_kwargs


@pytest.mark.asyncio
async def test_mark_failed_permanent_empty_noop():
    from service.lambdas.index_dlq_consumer.handler import _mark_failed_permanent

    count = await _mark_failed_permanent([])
    assert count == 0


@pytest.mark.asyncio
async def test_increment_retry_and_reset_calls_rpc():
    from service.lambdas.index_dlq_consumer.handler import _increment_retry_and_reset

    mock_response = MagicMock()
    mock_response.json.return_value = [{"tool_id": "t1", "retry_count": 3}]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "service.lambdas.index_dlq_consumer.handler.httpx.AsyncClient", return_value=mock_client
    ):
        count = await _increment_retry_and_reset(["t1"])

    assert count == 1
    call_kwargs = str(mock_client.post.call_args)
    assert "increment_retry_and_reset_to_pending" in call_kwargs
    assert "p_tool_ids" in call_kwargs


@pytest.mark.asyncio
async def test_increment_retry_and_reset_empty_noop():
    from service.lambdas.index_dlq_consumer.handler import _increment_retry_and_reset

    count = await _increment_retry_and_reset([])
    assert count == 0


# ---------------------------------------------------------------------------
# _async_handler batch processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_handler_empty_records():
    from service.lambdas.index_dlq_consumer.handler import _async_handler

    assert await _async_handler({"Records": []}, None) == {"batchItemFailures": []}


@pytest.mark.asyncio
async def test_async_handler_no_records_key():
    from service.lambdas.index_dlq_consumer.handler import _async_handler

    assert await _async_handler({}, None) == {"batchItemFailures": []}


@pytest.mark.asyncio
async def test_async_handler_reports_batch_item_failures():
    from service.lambdas.index_dlq_consumer.handler import _async_handler

    event = _sqs_event(
        _sqs_record(server_id="good", message_id="msg-good"),
        _sqs_record(server_id="bad", message_id="msg-bad"),
    )

    async def fake_process(record):
        if record["messageId"] == "msg-bad":
            raise RuntimeError("fail")
        return {"status": "redispatched"}

    with patch(
        "service.lambdas.index_dlq_consumer.handler._process_record", side_effect=fake_process
    ):
        result = await _async_handler(event, None)

    assert result["batchItemFailures"] == [{"itemIdentifier": "msg-bad"}]


# ---------------------------------------------------------------------------
# SQS envelope parsing still works with stringified detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_record_stringified_detail():
    from service.lambdas.index_dlq_consumer.handler import _process_record

    eb_event = {
        "source": "mcp-discovery",
        "detail-type": "server.registered",
        "detail": json.dumps({"server_id": "str-detail-server"}),
    }
    record = {
        "messageId": "msg-str",
        "body": json.dumps(eb_event),
        "attributes": {"ApproximateReceiveCount": "1"},
    }

    with patch(
        "service.lambdas.index_dlq_consumer.handler._fetch_failed_tools",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_fetch:
        result = await _process_record(record)

    assert result["server_id"] == "str-detail-server"
    mock_fetch.assert_awaited_once_with("str-detail-server")


# ---------------------------------------------------------------------------
# lambda_handler — sync entry point
# ---------------------------------------------------------------------------


def test_lambda_handler_sync_wrapper():
    from service.lambdas.index_dlq_consumer.handler import lambda_handler

    with patch(
        "service.lambdas.index_dlq_consumer.handler._async_handler",
        new_callable=AsyncMock,
        return_value={"batchItemFailures": []},
    ):
        result = lambda_handler({"Records": []}, None)

    assert result == {"batchItemFailures": []}
