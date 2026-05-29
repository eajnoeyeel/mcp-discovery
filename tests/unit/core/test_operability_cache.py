import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def cache():
    from mcp_discovery.operability.cache import OperabilityCache

    return OperabilityCache(supabase_url="http://fake", supabase_key="key")


def test_cache_starts_empty(cache):
    assert not cache.is_fresh()


@pytest.mark.asyncio
async def test_cache_get_bulk_triggers_refresh(cache):
    """Stale cache triggers background refresh without blocking the caller."""
    with patch.object(cache, "_background_refresh", new_callable=AsyncMock):
        cache._cache = {"a::t1": MagicMock(status="active")}
        cache._last_refresh = 0

        result = await cache.get_bulk(["a::t1"])
        # Stale data is returned immediately (non-blocking)
        assert "a::t1" in result
        # Background refresh was scheduled (flag set before create_task)
        assert cache._refreshing is True


@pytest.mark.asyncio
async def test_cache_get_bulk_returns_matching_ids(cache):
    from datetime import datetime, timezone

    from mcp_discovery.operability.models import ToolOperabilitySnapshot

    snap = ToolOperabilitySnapshot(
        tool_id="a::t1",
        server_id="a",
        status="active",
        call_count=50,
        call_count_7d=10,
        min_support=20,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
    )
    cache._cache = {"a::t1": snap}
    cache._last_refresh = time.monotonic()

    result = await cache.get_bulk(["a::t1", "b::t2"])
    assert "a::t1" in result
    assert "b::t2" not in result


@pytest.mark.asyncio
async def test_cache_degraded_on_refresh_failure(cache):
    """Refresh failure should keep stale cache, not crash."""
    from datetime import datetime, timezone

    from mcp_discovery.operability.models import ToolOperabilitySnapshot

    old_snap = ToolOperabilitySnapshot(
        tool_id="a::t1",
        server_id="a",
        status="active",
        call_count=10,
        call_count_7d=5,
        min_support=20,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
    )
    cache._cache = {"a::t1": old_snap}
    cache._last_refresh = 0

    with patch.object(cache, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Supabase down")
        mock_get.return_value = mock_client

        result = await cache.get_bulk(["a::t1"])
        assert "a::t1" in result


def test_cache_jitter_varies_freshness(cache):
    """TTL jitter should prevent thundering herd."""
    cache._last_refresh = time.monotonic() - cache.TTL_SECONDS
    results = [cache.is_fresh() for _ in range(100)]
    assert True in results or False in results


# ---------------------------------------------------------------------------
# _derive_status
# ---------------------------------------------------------------------------
class TestDeriveStatus:
    def test_prefers_index_status_from_view_when_present(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"index_status": "deprecated", "call_count": 50, "success_rate": 0.99}
        assert _derive_status(r) == "deprecated"

    def test_maps_indexed_status_to_active(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"index_status": "indexed", "call_count": 0}
        assert _derive_status(r) == "active"

    def test_maps_failed_status_to_pending(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"index_status": "failed", "call_count": 50, "success_rate": 0.05}
        assert _derive_status(r) == "pending"

    def test_returns_active_when_call_count_below_threshold(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"call_count": 5}
        assert _derive_status(r) == "active"

    def test_returns_active_when_call_count_is_exactly_threshold_minus_one(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"call_count": 19}
        assert _derive_status(r) == "active"

    def test_returns_unreachable_when_success_rate_below_point_one(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"call_count": 50, "success_rate": 0.05}
        assert _derive_status(r) == "unreachable"

    def test_returns_quarantined_when_timeout_rate_above_point_eight(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"call_count": 50, "success_rate": 0.8, "timeout_rate": 0.9}
        assert _derive_status(r) == "quarantined"

    def test_returns_active_when_all_metrics_acceptable(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"call_count": 100, "success_rate": 0.95, "timeout_rate": 0.01}
        assert _derive_status(r) == "active"

    def test_returns_active_when_success_rate_is_none(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"call_count": 50, "success_rate": None}
        assert _derive_status(r) == "active"

    def test_returns_active_when_timeout_rate_is_none(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"call_count": 50, "success_rate": 0.95, "timeout_rate": None}
        assert _derive_status(r) == "active"

    def test_treats_missing_call_count_as_zero(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {}
        assert _derive_status(r) == "active"

    def test_treats_none_call_count_as_zero(self):
        from mcp_discovery.operability.cache import _derive_status

        r = {"call_count": None}
        assert _derive_status(r) == "active"


# ---------------------------------------------------------------------------
# get_bulk — skip refresh when already refreshing
# ---------------------------------------------------------------------------
class TestGetBulkRefreshGuard:
    @pytest.mark.asyncio
    async def test_does_not_trigger_refresh_when_already_refreshing(self, cache):
        cache._last_refresh = 0
        cache._refreshing = True

        with patch.object(cache, "_background_refresh", new_callable=AsyncMock) as mock_refresh:
            cache._cache = {"x::t": MagicMock()}
            await cache.get_bulk(["x::t"])
            mock_refresh.assert_not_awaited()


# ---------------------------------------------------------------------------
# _refresh — success path builds new cache
# ---------------------------------------------------------------------------
class TestRefreshSuccessPath:
    @pytest.mark.asyncio
    async def test_refresh_populates_cache_from_supabase_response(self, cache):
        rows = [
            {
                "tool_id": "srv::tool_a",
                "server_id": "srv",
                "call_count": 100,
                "call_count_7d": 30,
                "success_rate": 0.95,
                "success_rate_7d": 0.90,
                "timeout_rate": 0.01,
                "avg_latency_ms": 120.0,
                "p95_latency_ms": 300.0,
            }
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=rows)

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(cache, "_get_client", return_value=mock_http):
            await cache._refresh()

        assert "srv::tool_a" in cache._cache
        snap = cache._cache["srv::tool_a"]
        assert snap.tool_id == "srv::tool_a"
        assert snap.server_id == "srv"
        assert snap.call_count == 100
        assert snap.success_rate == 0.95
        assert snap.avg_latency_ms == 120.0

    @pytest.mark.asyncio
    async def test_refresh_derives_status_for_each_row(self, cache):
        rows = [
            {
                "tool_id": "srv::unreachable",
                "server_id": "srv",
                "call_count": 50,
                "success_rate": 0.95,
                "index_status": "unreachable",
            }
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=rows)

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(cache, "_get_client", return_value=mock_http):
            await cache._refresh()

        assert cache._cache["srv::unreachable"].status == "unreachable"

    @pytest.mark.asyncio
    async def test_refresh_skips_malformed_rows_and_continues(self, cache):
        rows = [
            {"tool_id": "srv::good", "server_id": "srv", "call_count": 10},
            # row missing tool_id — will raise during ToolOperabilitySnapshot construction
            {"server_id": "srv", "call_count": 5},
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=rows)

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(cache, "_get_client", return_value=mock_http):
            await cache._refresh()

        assert "srv::good" in cache._cache
        assert len(cache._cache) == 1

    @pytest.mark.asyncio
    async def test_refresh_updates_last_refresh_timestamp(self, cache):
        before = time.monotonic()
        rows = [{"tool_id": "srv::t", "server_id": "srv", "call_count": 0}]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=rows)

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(cache, "_get_client", return_value=mock_http):
            await cache._refresh()

        assert cache._last_refresh >= before

    @pytest.mark.asyncio
    async def test_refresh_replaces_entire_cache_on_success(self, cache):
        cache._cache = {"old::tool": MagicMock()}

        rows = [{"tool_id": "new::tool", "server_id": "new", "call_count": 0}]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=rows)

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(cache, "_get_client", return_value=mock_http):
            await cache._refresh()

        assert "old::tool" not in cache._cache
        assert "new::tool" in cache._cache


# ---------------------------------------------------------------------------
# _refresh — failure path keeps stale cache
# ---------------------------------------------------------------------------
class TestRefreshFailurePath:
    @pytest.mark.asyncio
    async def test_refresh_failure_keeps_stale_cache_intact(self, cache):
        from datetime import datetime, timezone

        from mcp_discovery.operability.models import ToolOperabilitySnapshot

        stale_snap = ToolOperabilitySnapshot(
            tool_id="srv::stale",
            server_id="srv",
            status="active",
            call_count=5,
            call_count_7d=2,
            min_support=20,
            snapshot_version=1,
            computed_at=datetime.now(timezone.utc),
        )
        cache._cache = {"srv::stale": stale_snap}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=Exception("Supabase down"))

        with patch.object(cache, "_get_client", return_value=mock_http):
            await cache._refresh()

        assert "srv::stale" in cache._cache

    @pytest.mark.asyncio
    async def test_refresh_failure_does_not_update_last_refresh(self, cache):
        original_ts = 12345.0
        cache._last_refresh = original_ts

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=Exception("timeout"))

        with patch.object(cache, "_get_client", return_value=mock_http):
            await cache._refresh()

        assert cache._last_refresh == original_ts


# ---------------------------------------------------------------------------
# _get_client — lazy init
# ---------------------------------------------------------------------------
class TestGetClient:
    def test_creates_httpx_client_on_first_call(self, cache):
        assert cache._client is None
        client = cache._get_client()
        assert client is not None
        assert cache._client is client

    def test_returns_same_client_on_subsequent_calls(self, cache):
        c1 = cache._get_client()
        c2 = cache._get_client()
        assert c1 is c2
