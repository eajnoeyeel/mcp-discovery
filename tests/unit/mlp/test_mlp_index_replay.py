"""Tests for IndexReplay Lambda — rescues stuck event_failed/pending tools."""

import json
import re
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


class TestIndexReplay:
    async def test_no_stuck_tools_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from service.lambdas.index_replay import handler

        async def mock_fetch_stuck() -> list[dict]:
            return []

        monkeypatch.setattr(handler, "_fetch_stuck_servers", mock_fetch_stuck)

        result = await handler._async_handler({}, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["replayed_count"] == 0

    async def test_stuck_servers_get_replayed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from service.lambdas.index_replay import handler

        async def mock_fetch_stuck() -> list[dict]:
            return [
                {"server_id": "srv-1", "stuck_count": 3},
                {"server_id": "srv-2", "stuck_count": 1},
            ]

        published_events: list[str] = []

        async def mock_reset(server_id: str) -> None:
            pass

        async def mock_publish(server_id: str) -> bool:
            published_events.append(server_id)
            return True

        monkeypatch.setattr(handler, "_fetch_stuck_servers", mock_fetch_stuck)
        monkeypatch.setattr(handler, "_reset_tools_to_pending", mock_reset)
        monkeypatch.setattr(handler, "_publish_server_registered", mock_publish)

        result = await handler._async_handler({}, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["replayed_count"] == 2
        assert set(published_events) == {"srv-1", "srv-2"}

    async def test_publish_failure_does_not_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from service.lambdas.index_replay import handler

        async def mock_fetch_stuck() -> list[dict]:
            return [{"server_id": "srv-fail", "stuck_count": 1}]

        async def mock_reset(server_id: str) -> None:
            pass

        async def mock_publish_fail(server_id: str) -> bool:
            return False

        monkeypatch.setattr(handler, "_fetch_stuck_servers", mock_fetch_stuck)
        monkeypatch.setattr(handler, "_reset_tools_to_pending", mock_reset)
        monkeypatch.setattr(handler, "_publish_server_registered", mock_publish_fail)

        result = await handler._async_handler({}, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["replayed_count"] == 0
        assert body["failed_count"] == 1

    async def test_resets_status_before_replay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from service.lambdas.index_replay import handler

        reset_calls: list[str] = []

        async def mock_fetch_stuck() -> list[dict]:
            return [{"server_id": "srv-1", "stuck_count": 2}]

        async def mock_reset(server_id: str) -> None:
            reset_calls.append(server_id)

        async def mock_publish(server_id: str) -> bool:
            return True

        monkeypatch.setattr(handler, "_fetch_stuck_servers", mock_fetch_stuck)
        monkeypatch.setattr(handler, "_reset_tools_to_pending", mock_reset)
        monkeypatch.setattr(handler, "_publish_server_registered", mock_publish)

        await handler._async_handler({}, None)
        assert "srv-1" in reset_calls


@pytest.mark.asyncio
async def test_fetch_stuck_servers_uses_iso_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: threshold must be computed client-side as an ISO-8601 timestamp.

    PostgREST horizontal filters do not evaluate SQL expressions. If the filter
    passes a string like `now()-interval'30 minutes'`, PostgreSQL tries to cast
    it to `timestamptz` and raises error 22007, causing Supabase to return 400
    and the Lambda to crash on every invocation.
    """
    from service.lambdas.index_replay import handler

    captured_params: dict = {}

    class _MockResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> list:
            return []

    class _MockClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self) -> "_MockClient":
            return self

        async def __aexit__(self, *_args) -> None:
            pass

        async def get(self, url: str, headers=None, params=None) -> _MockResponse:
            if params is not None:
                captured_params.update(params)
            return _MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    monkeypatch.setattr(handler, "_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(handler, "_SUPABASE_KEY", "test-key")

    await handler._fetch_stuck_servers()

    or_filter = captured_params.get("or", "")
    # Regression guards: must not leak SQL expressions into a literal filter value.
    assert "now()" not in or_filter, f"SQL now() leaked into filter: {or_filter}"
    assert "interval" not in or_filter, f"SQL interval leaked into filter: {or_filter}"
    # Must include an ISO-8601 timestamp following `created_at.lt.`.
    match = re.search(
        r"created_at\.lt\.(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+\d{2}:\d{2})?)",
        or_filter,
    )
    assert match is not None, f"Expected ISO-8601 timestamp in filter, got: {or_filter}"


@pytest.mark.asyncio
async def test_publish_server_registered_uses_shared_publisher_abstraction() -> None:
    from service.lambdas.index_replay import handler

    publisher = AsyncMock()
    with patch.object(handler, "_build_eventbridge_client", return_value=publisher):
        ok = await handler._publish_server_registered("srv-123")

    assert ok is True
    publisher.publish_server_registered.assert_awaited_once_with("srv-123")


@pytest.mark.asyncio
async def test_publish_server_registered_uses_local_direct_relay_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from service.lambdas.index_replay import handler

    monkeypatch.setenv("MLP_EVENT_MODE", "local_direct")
    relay = MagicMock()
    relay.start = AsyncMock()
    relay.publish_server_registered = AsyncMock()
    relay.drain = AsyncMock()
    relay.stop = AsyncMock()

    fake_index_handler = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    fake_index_module = types.ModuleType("service.lambdas.index.handler")
    fake_index_module._async_handler = fake_index_handler

    with (
        patch.dict(sys.modules, {"service.lambdas.index.handler": fake_index_module}),
        patch.object(handler, "LocalEventBridgeRelay", return_value=relay),
        patch.object(handler, "_get_eventbridge", side_effect=AssertionError("boto3 path unused")),
    ):
        ok = await handler._publish_server_registered("srv-local")

    assert ok is True
    relay.start.assert_awaited_once()
    relay.publish_server_registered.assert_awaited_once_with("srv-local")
    relay.drain.assert_awaited_once()
    relay.stop.assert_awaited_once()
