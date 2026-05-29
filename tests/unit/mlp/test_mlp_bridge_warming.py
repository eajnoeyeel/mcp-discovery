"""Test BridgeFunction warming short-circuit."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def warming_event() -> dict:
    return {"source": "warming"}


@pytest.fixture()
def normal_mcp_event() -> dict:
    return {
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}),
    }


@pytest.fixture()
def bridge_handler_module():
    runtime = MagicMock()
    runtime.settings = MagicMock(confidence_gap_threshold=0.2)
    runtime.mlp_settings = MagicMock(
        cache_ttl_seconds=300,
        enable_pending_freshness=False,
        enable_per_client_routing=False,
        rerank_candidate_pool_size=10,
        pending_freshness_limit=2,
        pending_freshness_timeout_ms=150,
    )
    runtime.strategy = MagicMock()
    runtime.operability_cache = None

    sys.modules.pop("service.lambdas.bridge.handler", None)
    sys.modules.pop("awslabs.mcp_lambda_handler", None)
    sys.modules["awslabs"] = None
    with (
        patch("service.shared.runtime.build_search_runtime", return_value=runtime),
        patch("service.rag.factory.RAGServiceFactory.create", return_value=MagicMock()),
        patch("service.services.search_service.SearchService", return_value=MagicMock()),
        patch("service.services.execute_service.ExecuteService", return_value=MagicMock()),
        patch("service.services.bridge_service.BridgeService", return_value=MagicMock()),
    ):
        import service.lambdas.bridge.handler as mod

    yield mod
    sys.modules.pop("service.lambdas.bridge.handler", None)
    sys.modules.pop("awslabs", None)


class TestBridgeWarming:
    async def test_warming_event_short_circuits(
        self, warming_event: dict, bridge_handler_module
    ) -> None:
        result = await bridge_handler_module._async_handler(warming_event)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "warm"

    async def test_normal_event_not_affected(
        self, normal_mcp_event: dict, bridge_handler_module
    ) -> None:
        result = await bridge_handler_module._async_handler(normal_mcp_event)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "status" not in body or body.get("status") != "warm"
