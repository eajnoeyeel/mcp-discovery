"""Thin bridge service wrapper around search and execute services."""

from __future__ import annotations

from service.services.contracts import ExecuteRequest, SearchRequest


class BridgeService:
    def __init__(self, search_service, execute_service=None):
        self._search_service = search_service
        self._execute_service = execute_service

    async def find_best_tool(self, request: SearchRequest):
        return await self._search_service.search(request)

    async def execute_tool(
        self,
        request: ExecuteRequest,
        *,
        user_id: str | None = None,
        query_log_id: int | None = None,
    ) -> dict:
        if self._execute_service is None:
            return {
                "error": (
                    "Direct execution via Bridge is not yet supported. "
                    "Use the /api/execute REST endpoint instead."
                ),
                "tool_id": request.tool_id,
            }

        execute_kwargs = {"tool_id": request.tool_id, "params": request.params}
        if user_id is not None:
            execute_kwargs["user_id"] = user_id
        execute_kwargs["query_log_id"] = query_log_id
        response = await self._execute_service.execute(**execute_kwargs)

        if response.status == "auth_required" and response.auth is not None:
            return {
                "status": response.status,
                "tool_id": response.tool_id,
                "server_id": response.server_id,
                "auth": response.auth.model_dump(),
            }

        if not response.success:
            result: dict = {"error": response.error, "tool_id": response.tool_id}
            if response.latency_ms > 0:
                result["latency_ms"] = response.latency_ms
            return result

        return {
            "tool_id": response.tool_id,
            "server_id": response.server_id,
            "result": response.result,
            "latency_ms": response.latency_ms,
        }
