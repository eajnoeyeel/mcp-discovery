"""Bridge handler end-to-end integration with ExecuteService.

These tests verify that after the #64 fix:
- ``BridgeService`` is constructed with a *real* (non-None) ``ExecuteService``
  at cold-start time, because the execution adapters live under
  ``service.adapters.execution`` and are shipped in the bridge Lambda
  artifact.
- ``_execute_tool()`` in the bridge handler reaches the real
  ``ExecuteService.execute()`` path (not a stub), invoking
  ``SupabaseToolRegistry.fetch_tool_contract`` and ``MCPHTTPClient.call_tool``.

Unit layer only — live MCP round-trip + ``execution_logs.query_log_id``
population are covered by integration/E2E smoke tests post-deploy.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_discovery.models import MCPTool, SearchResult
from service.services.contracts import ToolContract, UpstreamAuthConfig


def _mock_settings(**overrides) -> MagicMock:
    s = MagicMock()
    defaults = dict(
        openai_api_key="fake",
        embedding_model="text-embedding-3-small",
        embedding_dimension=1536,
        qdrant_url="http://localhost:6333",
        qdrant_api_key=None,
        enable_reranker=False,
        rerank_provider="none",
        rerank_model="none",
        confidence_gap_threshold=0.15,
        qdrant_collection_name="mcp_tools",
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _mock_mlp_settings(**overrides) -> MagicMock:
    s = MagicMock()
    defaults = dict(
        cache_ttl_seconds=300,
        enable_pending_freshness=False,
        rerank_candidate_pool_size=10,
        pending_freshness_limit=2,
        pending_freshness_timeout_ms=150,
        server_collection_name="mcp_servers",
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _bridge_event(body: dict, method: str = "POST") -> dict:
    return {
        "requestContext": {"http": {"method": method}},
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


class TestBridgeExecuteIntegration:
    @pytest.fixture(autouse=True)
    def _setup(self):
        sys.modules.pop("service.lambdas.bridge.handler", None)
        sys.modules.pop("service.adapters.execution", None)
        sys.modules.pop("awslabs.mcp_lambda_handler", None)
        sys.modules["awslabs"] = None  # force manual JSON-RPC fallback

        runtime = MagicMock()
        runtime.settings = _mock_settings()
        runtime.mlp_settings = _mock_mlp_settings()
        runtime.reranker = MagicMock(name="reranker")
        runtime.strategy = MagicMock()
        runtime.operability_cache = MagicMock()

        search_response = MagicMock()
        search_response.model_dump = MagicMock(
            return_value={
                "results": [
                    {
                        "tool_id": "srv::lookup",
                        "score": 0.9,
                        "rank": 1,
                    }
                ],
                "confidence": 0.9,
                "strategy_used": "flat",
            }
        )
        self.search_service = MagicMock()
        self.search_service.search = AsyncMock(return_value=search_response)

        with (
            patch("service.shared.runtime.build_search_runtime", return_value=runtime),
            patch(
                "service.services.search_service.SearchService",
                return_value=self.search_service,
            ),
        ):
            import service.lambdas.bridge.handler as bridge_mod

        self.bridge_mod = bridge_mod
        yield
        sys.modules.pop("service.lambdas.bridge.handler", None)
        sys.modules.pop("service.adapters.execution", None)
        sys.modules.pop("awslabs", None)

    def test_bridge_constructs_real_execute_service(self) -> None:
        """After #64, the bridge cold-start produces a real ExecuteService."""
        from service.services.execute_service import ExecuteService

        assert isinstance(self.bridge_mod._execute_service, ExecuteService)
        assert self.bridge_mod.bridge_service._execute_service is not None

    async def test_bridge_execute_tool_reaches_execute_service(self) -> None:
        """_execute_tool() must hit the real ExecuteService.execute() path."""
        mock_contract = ToolContract(
            tool_id="srv::lookup",
            server_id="srv",
            tool_name="lookup",
            url="https://srv.example",
            upstream_auth=UpstreamAuthConfig(),
            transport_type="stateless_http",
            requires_gateway=False,
        )
        registry_mock = AsyncMock(return_value=mock_contract)
        call_tool_mock = AsyncMock(
            return_value={"jsonrpc": "2.0", "id": 1, "result": {"content": []}}
        )

        with (
            patch(
                "service.adapters.execution.SupabaseToolRegistry.fetch_tool_contract",
                registry_mock,
            ),
            patch(
                "service.adapters.mcp_http_client.MCPHTTPClient.call_tool",
                call_tool_mock,
            ),
        ):
            result = await self.bridge_mod._execute_tool(
                tool_id="srv::lookup", params={"q": "x"}, query_log_id=None
            )

        # Verify the mocked path was reached (not the stub BridgeService branch).
        registry_mock.assert_awaited_once_with("srv::lookup")
        call_tool_mock.assert_awaited_once()
        assert result["tool_id"] == "srv::lookup"
        assert result["server_id"] == "srv"
        assert result["result"] == {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}

    async def test_bridge_execute_tool_threads_query_log_id(self) -> None:
        """query_log_id is threaded through BridgeService → ExecuteService → logger."""
        mock_contract = ToolContract(
            tool_id="srv::lookup",
            server_id="srv",
            tool_name="lookup",
            url="https://srv.example",
            upstream_auth=UpstreamAuthConfig(),
            transport_type="stateless_http",
            requires_gateway=False,
        )

        with (
            patch(
                "service.adapters.execution.SupabaseToolRegistry.fetch_tool_contract",
                AsyncMock(return_value=mock_contract),
            ),
            patch(
                "service.adapters.mcp_http_client.MCPHTTPClient.call_tool",
                AsyncMock(return_value={"jsonrpc": "2.0", "id": 1, "result": {}}),
            ),
            patch(
                "service.adapters.execution.SupabaseExecutionLogger.log",
                new_callable=AsyncMock,
            ) as log_mock,
        ):
            await self.bridge_mod._execute_tool(
                tool_id="srv::lookup", params={"q": "x"}, query_log_id=42
            )

        log_mock.assert_awaited_once()
        assert log_mock.await_args.kwargs.get("query_log_id") == 42


def _sr(tool_id: str = "srv::lookup", score: float = 0.9, rank: int = 1) -> SearchResult:
    sid, tname = tool_id.split("::", 1)
    return SearchResult(
        tool=MCPTool(server_id=sid, tool_name=tname, tool_id=tool_id, description="A tool"),
        score=score,
        rank=rank,
    )
