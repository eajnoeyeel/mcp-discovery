from unittest.mock import AsyncMock, call

import pytest
from loguru import logger


@pytest.mark.asyncio
async def test_local_relay_invokes_index_handler_with_eventbridge_shape():
    from service.local_runtime.eventbridge_relay import LocalEventBridgeRelay

    handler = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    relay = LocalEventBridgeRelay(index_handler=handler)
    await relay.start()

    await relay.publish_server_registered("srv-123")
    await relay.drain()

    handler.assert_awaited_once_with(
        {
            "source": "mcp-discovery",
            "detail-type": "server.registered",
            "detail": {"server_id": "srv-123"},
        },
        None,
    )

    await relay.stop()


@pytest.mark.asyncio
async def test_local_relay_drain_once_processes_one_event_without_background_loop():
    from service.local_runtime.eventbridge_relay import LocalEventBridgeRelay

    handler = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    relay = LocalEventBridgeRelay(index_handler=handler)

    await relay.publish_server_registered("srv-123")

    assert await relay.drain_once() is True
    handler.assert_awaited_once_with(
        {
            "source": "mcp-discovery",
            "detail-type": "server.registered",
            "detail": {"server_id": "srv-123"},
        },
        None,
    )


@pytest.mark.asyncio
async def test_local_relay_keeps_running_after_handler_failure():
    from service.local_runtime.eventbridge_relay import LocalEventBridgeRelay

    handler = AsyncMock(side_effect=[RuntimeError("boom"), {"statusCode": 200, "body": "{}"}])
    relay = LocalEventBridgeRelay(index_handler=handler)
    log_messages: list[str] = []
    sink_id = logger.add(log_messages.append, format="{message}")
    await relay.start()

    try:
        await relay.publish_server_registered("srv-a")
        await relay.publish_server_registered("srv-b")
        await relay.drain()
    finally:
        logger.remove(sink_id)
        await relay.stop()

    assert handler.await_count == 2
    assert handler.await_args_list == [
        call(
            {
                "source": "mcp-discovery",
                "detail-type": "server.registered",
                "detail": {"server_id": "srv-a"},
            },
            None,
        ),
        call(
            {
                "source": "mcp-discovery",
                "detail-type": "server.registered",
                "detail": {"server_id": "srv-b"},
            },
            None,
        ),
    ]
    assert any("srv-a" in message and "boom" in message for message in log_messages)


@pytest.mark.asyncio
async def test_local_relay_rejects_publish_after_stop():
    from service.local_runtime.eventbridge_relay import LocalEventBridgeRelay

    relay = LocalEventBridgeRelay(index_handler=AsyncMock())

    await relay.start()
    await relay.stop()

    with pytest.raises(RuntimeError, match="not accepting new events"):
        await relay.publish_server_registered("srv-after-stop")


@pytest.mark.asyncio
async def test_local_relay_double_stop_is_safe():
    from service.local_runtime.eventbridge_relay import LocalEventBridgeRelay

    handler = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    relay = LocalEventBridgeRelay(index_handler=handler)

    await relay.start()
    await relay.publish_server_registered("srv-123")
    await relay.stop()
    await relay.stop()

    handler.assert_awaited_once_with(
        {
            "source": "mcp-discovery",
            "detail-type": "server.registered",
            "detail": {"server_id": "srv-123"},
        },
        None,
    )


@pytest.mark.asyncio
async def test_local_relay_restart_after_stop_processes_new_events_cleanly():
    from service.local_runtime.eventbridge_relay import LocalEventBridgeRelay

    handler = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    relay = LocalEventBridgeRelay(index_handler=handler)

    await relay.start()
    await relay.stop()

    await relay.start()
    await relay.publish_server_registered("srv-restarted")
    await relay.stop()

    handler.assert_awaited_once_with(
        {
            "source": "mcp-discovery",
            "detail-type": "server.registered",
            "detail": {"server_id": "srv-restarted"},
        },
        None,
    )
