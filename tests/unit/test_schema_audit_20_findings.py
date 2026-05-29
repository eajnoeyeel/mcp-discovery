"""Unit tests for 2026-04-20 Codex audit fixes (F5, F7).

F5 — public catalog must filter on is_published.
F7 — tool_conversion_funnel count must dedupe per query_log_id.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from service.adapters.supabase_client import SupabaseClient


def _mock_http(response_data):
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()
    mock_http = MagicMock()
    mock_http.request = AsyncMock(return_value=mock_resp)
    return mock_http


@pytest.mark.asyncio
class TestF5PublicCatalogFilter:
    async def test_fetch_servers_defaults_to_public_only(self):
        """F5: public list must filter is_published=true by default."""
        client = SupabaseClient(url="http://fake", service_key="k")
        client._client = _mock_http([])
        client.fetch_server_tool_counts = AsyncMock(return_value={})

        await client.fetch_servers()

        params = client._client.request.call_args.kwargs["params"]
        assert params["is_published"] == "eq.true"

    async def test_fetch_servers_can_opt_in_to_unpublished(self):
        """Explicit public_only=False returns all rows (owner/admin path)."""
        client = SupabaseClient(url="http://fake", service_key="k")
        client._client = _mock_http([])
        client.fetch_server_tool_counts = AsyncMock(return_value={})

        await client.fetch_servers(public_only=False)

        params = client._client.request.call_args.kwargs["params"]
        assert "is_published" not in params

    async def test_fetch_server_defaults_to_public_only(self):
        """F5: single-server fetch filters is_published=true by default."""
        client = SupabaseClient(url="http://fake", service_key="k")
        client._client = _mock_http([])

        await client.fetch_server("srv-1")

        params = client._client.request.call_args.kwargs["params"]
        assert params["is_published"] == "eq.true"

    async def test_fetch_server_opt_in_returns_unpublished(self):
        client = SupabaseClient(url="http://fake", service_key="k")
        client._client = _mock_http([])

        await client.fetch_server("srv-1", public_only=False)

        params = client._client.request.call_args.kwargs["params"]
        assert "is_published" not in params


@pytest.mark.asyncio
class TestF7ConversionStatsDedup:
    async def test_recommendation_count_dedupes_multi_execution_rows(self):
        """F7: one query_log_id producing 3 execution rows counts as ONE recommendation."""
        client = SupabaseClient(url="http://fake", service_key="k")
        # Two recommendations: qid=1 has 3 executions (one converted, two diverged);
        # qid=2 has 1 execution (diverged).
        client._client = _mock_http(
            [
                {"query_log_id": 1, "funnel_outcome": "diverged"},
                {"query_log_id": 1, "funnel_outcome": "converted"},
                {"query_log_id": 1, "funnel_outcome": "diverged"},
                {"query_log_id": 2, "funnel_outcome": "diverged"},
            ]
        )

        result = await client.fetch_tool_conversion_stats("srv::t")

        assert result["recommendation_count"] == 2, "each query_log_id counts once"
        assert result["converted_count"] == 1, "qid=1 converted (any execution matching wins)"

    async def test_converted_wins_over_diverged_for_same_qid(self):
        """If a qid has both 'converted' and 'diverged' rows, it counts as converted."""
        client = SupabaseClient(url="http://fake", service_key="k")
        client._client = _mock_http(
            [
                {"query_log_id": 7, "funnel_outcome": "diverged"},
                {"query_log_id": 7, "funnel_outcome": "converted"},
            ]
        )

        result = await client.fetch_tool_conversion_stats("srv::t")

        assert result["recommendation_count"] == 1
        assert result["converted_count"] == 1

    async def test_no_execution_counts_as_unconverted(self):
        client = SupabaseClient(url="http://fake", service_key="k")
        client._client = _mock_http(
            [
                {"query_log_id": 1, "funnel_outcome": "no_execution"},
                {"query_log_id": 2, "funnel_outcome": "converted"},
            ]
        )

        result = await client.fetch_tool_conversion_stats("srv::t")

        assert result["recommendation_count"] == 2
        assert result["converted_count"] == 1

    async def test_empty_rows_returns_zeros(self):
        client = SupabaseClient(url="http://fake", service_key="k")
        client._client = _mock_http([])

        result = await client.fetch_tool_conversion_stats("srv::t")

        assert result == {"recommendation_count": 0, "converted_count": 0}

    async def test_selects_query_log_id_for_dedup(self):
        """Regression: must SELECT query_log_id (not just funnel_outcome)."""
        client = SupabaseClient(url="http://fake", service_key="k")
        client._client = _mock_http([])

        await client.fetch_tool_conversion_stats("srv::t")

        params = client._client.request.call_args.kwargs["params"]
        assert "query_log_id" in params["select"]
