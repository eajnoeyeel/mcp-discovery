from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_discovery.analytics.logger import QueryLogEntry


@pytest.fixture
def logger():
    from service.services.query_logger import QueryLogger

    return QueryLogger(supabase_url="http://fake.supabase.co", supabase_key="test-key")


def test_build_payload_matches_ddl(logger):
    """Payload must match query_logs DDL columns exactly."""
    payload = logger._build_payload(
        event_id="req-123",
        query="search GitHub repos",
        results=[{"tool_id": "github::search", "score": 0.8, "rank": 1}],
        confidence=0.8,
        strategy="sequential",
        latency_ms=120.0,
        stage_metrics={"ann_latency_ms": 50.0, "cache_hit": True},
    )
    assert payload["event_id"] == "req-123"
    assert payload["query"] == "search GitHub repos"
    assert payload["recommended_tool_id"] == "github::search"
    assert "selected_tool_id" not in payload
    assert payload["confidence"] == 0.8
    assert payload["latency_ms"] == 120.0
    assert payload["strategy"] == "sequential"
    assert isinstance(payload["alternatives"], list)
    assert payload["stage_metrics"] == {"ann_latency_ms": 50.0, "cache_hit": True}
    assert "selected_score" not in payload
    assert "result_count" not in payload
    assert "results_json" not in payload


def test_build_payload_empty_results(logger):
    payload = logger._build_payload(
        event_id="req-456",
        query="nonexistent tool",
        results=[],
        confidence=0.0,
        strategy="sequential",
        latency_ms=50.0,
    )
    assert payload["recommended_tool_id"] is None
    assert "selected_tool_id" not in payload
    assert payload["alternatives"] == []


@pytest.mark.asyncio
async def test_log_query_fire_and_forget(logger):
    """Must not raise even if POST fails; returns None on failure."""
    with patch.object(logger, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("network error")
        mock_get.return_value = mock_client

        result = await logger.log_query(
            event_id="req-789",
            query="test",
            results=[],
            confidence=0.0,
            strategy="flat",
            latency_ms=10.0,
        )
        assert result is None


@pytest.mark.asyncio
async def test_log_query_sends_correct_url(logger):
    with patch.object(logger, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"id": 42}]
        mock_client.post.return_value = mock_resp
        mock_get.return_value = mock_client

        await logger.log_query(
            event_id="req-101",
            query="test",
            results=[],
            confidence=0.0,
            strategy="flat",
            latency_ms=10.0,
        )

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/rest/v1/query_logs" in call_args[0][0]


@pytest.mark.asyncio
async def test_log_query_returns_inserted_id(logger):
    """On successful INSERT, log_query returns the inserted row id as int."""
    with patch.object(logger, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"id": 42, "event_id": "req-200"}]
        mock_client.post.return_value = mock_resp
        mock_get.return_value = mock_client

        result = await logger.log_query(
            event_id="req-200",
            query="test query",
            results=[{"tool_id": "github::search", "score": 0.9, "rank": 1}],
            confidence=0.9,
            strategy="flat",
            latency_ms=120.0,
        )

        assert result == 42
        assert isinstance(result, int)


@pytest.mark.asyncio
async def test_log_query_returns_none_on_empty_response(logger):
    """When Supabase returns an empty list, log_query returns None."""
    with patch.object(logger, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = []
        mock_client.post.return_value = mock_resp
        mock_get.return_value = mock_client

        result = await logger.log_query(
            event_id="req-300",
            query="test",
            results=[],
            confidence=0.0,
            strategy="flat",
            latency_ms=10.0,
        )

        assert result is None


@pytest.mark.asyncio
async def test_log_query_uses_return_representation_header(logger):
    """Prefer header must be return=representation so Supabase returns the row."""
    with patch.object(logger, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"id": 7}]
        mock_client.post.return_value = mock_resp
        mock_get.return_value = mock_client

        await logger.log_query(
            event_id="req-400",
            query="test",
            results=[],
            confidence=0.0,
            strategy="flat",
            latency_ms=10.0,
        )

        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["headers"]["Prefer"] == "return=representation"


# ---------------------------------------------------------------------------
# T3 — QueryLogEntry Pydantic alias round-trip tests
# ---------------------------------------------------------------------------

_ENTRY_BASE = {
    "query": "q",
    "server_id": "s",
    "confidence": 0.9,
    "disambiguation_needed": False,
    "strategy": "flat",
    "latency_ms": 50.0,
}


def test_query_log_entry_accepts_legacy_field_name() -> None:
    """Legacy input with selected_tool_id (alias) must parse successfully."""
    entry = QueryLogEntry.model_validate({**_ENTRY_BASE, "selected_tool_id": "x::y"})
    assert entry.recommended_tool_id == "x::y"


def test_query_log_entry_accepts_new_field_name() -> None:
    """New input with recommended_tool_id (field name) must parse successfully."""
    entry = QueryLogEntry.model_validate({**_ENTRY_BASE, "recommended_tool_id": "x::y"})
    assert entry.recommended_tool_id == "x::y"


def test_query_log_entry_model_dump_uses_new_field_name() -> None:
    """model_dump() must produce recommended_tool_id (new canonical name)."""
    entry = QueryLogEntry.model_validate({**_ENTRY_BASE, "selected_tool_id": "x::y"})
    dumped = entry.model_dump()
    assert "recommended_tool_id" in dumped
    assert dumped["recommended_tool_id"] == "x::y"
    assert "selected_tool_id" not in dumped


def test_query_log_entry_model_dump_by_alias_uses_legacy_field_name() -> None:
    """model_dump(by_alias=True) must produce selected_tool_id for backward compat."""
    entry = QueryLogEntry.model_validate({**_ENTRY_BASE, "selected_tool_id": "x::y"})
    dumped = entry.model_dump(by_alias=True)
    assert "selected_tool_id" in dumped
    assert dumped["selected_tool_id"] == "x::y"
    assert "recommended_tool_id" not in dumped
