from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_provider_dashboard_summary_call_count_tracks_execution_count() -> None:
    from service.services.dashboard_service import DashboardService

    repo = AsyncMock()
    repo.fetch_provider_dashboard_tools.return_value = [
        {
            "tool_id": "srv::lookup",
            "tool_name": "lookup",
            "server_id": "srv",
            "server_name": "Server",
            "geo_score": {"total": 0.5},
            "index_status": "indexed",
            "times_exposed": 10,
            "times_selected": 3,
            "call_count": 5,
            "success_rate": 0.9,
            "avg_latency_ms": 150.0,
            "p95_latency_ms": 300.0,
        }
    ]
    repo.fetch_tool_exposure_count.return_value = 10
    repo.fetch_tool_conversion_stats.return_value = {
        "recommendation_count": 3,
        "converted_count": 2,
    }

    service = DashboardService(repo=repo)
    result = await service.get_provider_dashboard("prov-456", owner_user_id="user-123")

    assert result["summary"]["recommendation_count"] == 3
    assert result["summary"]["execution_count"] == 5
    assert result["summary"]["call_count"] == 5
