"""Execute service — schema validation, proxy call, and execution logging."""

from __future__ import annotations

import time
from typing import Any, Protocol

from loguru import logger

from service.adapters.mcp_http_client import MCPHTTPClient
from service.services.contracts import ExecuteResponse, ToolContract
from service.services.delegated_oauth import build_auth_required_payload
from service.services.pending_execution import build_pending_execution, validate_resume_request
from service.services.upstream_auth import UpstreamAuthError, resolve_upstream_headers


class ToolRegistry(Protocol):
    """Protocol for fetching tool metadata from a data store."""

    async def fetch_tool_contract(self, tool_id: str) -> ToolContract | None: ...

    async def create_pending_execution(
        self,
        *,
        user_id: str,
        tool_id: str,
        params_json: dict[str, Any],
        provider_key: str,
        required_scopes: list[str],
        resume_token: str,
        expires_at: str,
    ) -> dict | list: ...

    async def fetch_pending_execution_by_resume_token(self, resume_token: str) -> dict | None: ...

    async def update_pending_execution(
        self,
        pending_execution_id: str,
        payload: dict[str, Any],
    ) -> dict | list: ...

    async def resolve_user_provider_headers(self, connection_id: str) -> dict[str, str]: ...


class ExecutionLogger(Protocol):
    """Protocol for logging execution results (e.g. to Supabase).

    ``client_id`` is the originating MCP client tag used by per-client
    analytics (migration 012). Concrete loggers must accept it to match the
    ``SupabaseExecutionLogger`` signature; end-to-end plumbing from the
    bridge still pending (see progress.txt Follow-up #F3b).
    """

    async def log(
        self,
        tool_id: str,
        server_id: str,
        success: bool,
        latency_ms: float,
        error_message: str | None = None,
        client_id: str | None = None,
        event_id: str | None = None,
        query_log_id: int | None = None,
    ) -> None: ...


class GatewayExecutor(Protocol):
    """Protocol for delegating pooled MCP transport execution to the gateway."""

    async def __call__(self, contract: ToolContract, params: dict[str, Any]) -> dict[str, Any]: ...


def validate_against_schema(schema: dict[str, Any] | None, params: dict[str, Any]) -> None:
    """Validate params against the tool's input_schema.

    Currently checks ``required`` fields only.  Full JSON-Schema validation
    can be added later without changing the public interface.

    Raises
    ------
    ValueError
        If any required parameter is missing.
    """
    if not schema:
        return
    required = schema.get("required", [])
    missing = [field for field in required if field not in params]
    if missing:
        raise ValueError(f"Missing required params: {', '.join(missing)}")


class ExecuteService:
    """Orchestrates tool execution: lookup, validation, proxy, and logging.

    Parameters
    ----------
    registry:
        Fetches ``ToolContract`` for a given ``tool_id``.
    mcp_client:
        Sends the actual ``tools/call`` to the hosted MCP server.
    execution_logger:
        Optional logger for recording execution results.
    allowed_servers:
        Optional allow-list of server IDs.  When non-empty, only servers
        in this set may be executed.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        mcp_client: MCPHTTPClient,
        execution_logger: ExecutionLogger | None = None,
        allowed_servers: set[str] | None = None,
        oauth_token_service=None,
        gateway_executor: GatewayExecutor | None = None,
    ) -> None:
        self._registry = registry
        self._mcp_client = mcp_client
        self._execution_logger = execution_logger
        self._allowed_servers: set[str] = allowed_servers or set()
        self._oauth_token_service = oauth_token_service
        self._gateway_executor = gateway_executor

    async def execute(
        self,
        tool_id: str,
        params: dict[str, Any],
        *,
        user_id: str | None = None,
        event_id: str | None = None,
        query_log_id: int | None = None,
    ) -> ExecuteResponse:
        """Execute a tool by proxying to its hosted MCP server.

        Returns an ``ExecuteResponse`` with either the result or a
        structured error description.
        """
        import httpx

        # 1. Look up tool contract (platform error — not logged as operational signal)
        try:
            contract = await self._registry.fetch_tool_contract(tool_id)
        except Exception:
            return ExecuteResponse(
                tool_id=tool_id,
                server_id="",
                success=False,
                error="Failed to load tool contract",
            )
        if contract is None:
            return ExecuteResponse(
                tool_id=tool_id,
                server_id="",
                success=False,
                error=f"Tool '{tool_id}' not found",
            )

        server_id = contract.server_id
        auth_requirement = (
            contract.auth_requirement.model_dump() if contract.auth_requirement else None
        )
        logger.info(
            "execute service contract "
            f"tool_id={tool_id} server_id={server_id} tool_name={contract.tool_name} "
            f"url={contract.url} auth_requirement={auth_requirement}"
        )

        # 2. Allowed-list check (platform error — not logged)
        if self._allowed_servers and server_id not in self._allowed_servers:
            return ExecuteResponse(
                tool_id=tool_id,
                server_id=server_id,
                success=False,
                error=f"Server '{server_id}' is not in the allowed execution list",
            )

        # 3. Validate params against input_schema (client error — not logged)
        try:
            validate_against_schema(contract.input_schema, params)
        except ValueError:
            required_fields = (
                contract.input_schema.get("required", []) if contract.input_schema else []
            )
            logger.warning(
                "execute service schema validation failed "
                f"tool_id={tool_id} required={required_fields} "
                f"param_keys={sorted(params.keys()) if isinstance(params, dict) else '<non-dict>'}"
            )
            raise

        # 4. Resolve delegated provider auth before contacting upstream.
        if contract.auth_requirement is not None:
            requirement = contract.auth_requirement
            if not user_id:
                return ExecuteResponse(
                    tool_id=tool_id,
                    server_id=server_id,
                    status="execution_failed",
                    error="Missing authenticated user context",
                )

            connection = await self._registry.find_user_provider_connection(
                user_id=user_id,
                provider_key=requirement.provider,
                required_scopes=requirement.required_scopes,
            )
            logger.info(
                "execute service delegated auth lookup "
                f"tool_id={tool_id} provider={requirement.provider} "
                f"user_id={user_id} connection_id={getattr(connection, 'id', None)}"
            )
            if connection is None:
                pending_execution_id: str | None = None
                resume_token: str | None = None
                create_pending_execution = getattr(self._registry, "create_pending_execution", None)
                if callable(create_pending_execution):
                    pending = build_pending_execution(
                        user_id=user_id,
                        tool_id=tool_id,
                        params=params,
                        provider_key=requirement.provider,
                        required_scopes=requirement.required_scopes,
                    )
                    created = await create_pending_execution(
                        user_id=pending["user_id"],
                        tool_id=pending["tool_id"],
                        params_json=pending["params_json"],
                        provider_key=pending["provider_key"],
                        required_scopes=pending["required_scopes"],
                        resume_token=pending["resume_token"],
                        expires_at=pending["expires_at"],
                    )
                    resume_token = pending["resume_token"]
                    if isinstance(created, list) and created:
                        pending_execution_id = str(created[0].get("id") or "")
                    elif isinstance(created, dict):
                        pending_execution_id = str(created.get("id") or "")
                    pending_execution_id = pending_execution_id or None
                    logger.info(
                        "execute service pending execution created "
                        f"tool_id={tool_id} provider={requirement.provider} "
                        f"pending_execution_id={pending_execution_id} resume_token={resume_token}"
                    )

                build_oauth_url = getattr(self._registry, "build_provider_oauth_url", None)
                if build_oauth_url is None:
                    oauth_url = f"/api/oauth/providers/{requirement.provider}/start"
                else:
                    oauth_url = await build_oauth_url(
                        user_id=user_id,
                        tool_id=tool_id,
                        provider=requirement.provider,
                        required_scopes=requirement.required_scopes,
                        params=params,
                        pending_execution_id=pending_execution_id,
                        resume_token=resume_token,
                    )
                return ExecuteResponse(
                    tool_id=tool_id,
                    server_id=server_id,
                    status="auth_required",
                    auth=build_auth_required_payload(
                        provider=requirement.provider,
                        required_scopes=requirement.required_scopes,
                        oauth_url=oauth_url,
                        pending_execution_id=pending_execution_id,
                        resume_token=resume_token,
                    ),
                )

        delegated_headers: dict[str, str] = {}
        if contract.auth_requirement is not None and connection is not None:
            delegated_headers = await self._registry.resolve_user_provider_headers(connection.id)
            logger.info(
                "execute service delegated headers "
                f"tool_id={tool_id} "
                f"connection_id={connection.id} "
                f"header_keys={sorted(delegated_headers.keys())}"
            )
            if not delegated_headers.get("Authorization"):
                return ExecuteResponse(
                    tool_id=tool_id,
                    server_id=server_id,
                    status="auth_revoked",
                    error="Delegated OAuth connection is missing, expired, or revoked",
                )

        # 5. Route stateful transports to the long-running gateway
        if contract.requires_gateway:
            if self._gateway_executor is None:
                return ExecuteResponse(
                    tool_id=tool_id,
                    server_id=server_id,
                    success=False,
                    error="Pooled MCP transport requires execution gateway",
                )
            upstream_start = time.monotonic()
            result = await self._gateway_executor(contract, params, headers=delegated_headers)
            latency = (time.monotonic() - upstream_start) * 1000
            await self._log(
                tool_id,
                server_id,
                True,
                latency,
                event_id=event_id,
                query_log_id=query_log_id,
            )
            return ExecuteResponse(
                tool_id=tool_id,
                server_id=server_id,
                success=True,
                result=result,
                latency_ms=latency,
            )

        # 6. Build provider upstream auth headers (platform error — not logged)
        try:
            upstream_headers = await resolve_upstream_headers(
                server_id,
                contract.upstream_auth,
                oauth_token_service=self._oauth_token_service,
            )
        except UpstreamAuthError:
            return ExecuteResponse(
                tool_id=tool_id,
                server_id=server_id,
                success=False,
                error="Invalid upstream auth configuration",
            )
        headers = {**upstream_headers, **delegated_headers}
        logger.info(
            "execute service upstream call "
            f"tool_id={tool_id} server_url={contract.url} header_keys={sorted(headers.keys())}"
        )

        # 7. Proxy the call — timer starts here (pure upstream latency)
        upstream_start = time.monotonic()
        try:
            result = await self._mcp_client.call_tool(
                server_url=contract.url,
                tool_name=contract.tool_name,
                arguments=params,
                headers=headers,
            )
        except httpx.TimeoutException:
            latency = (time.monotonic() - upstream_start) * 1000
            await self._log(
                tool_id,
                server_id,
                False,
                latency,
                "Proxy timeout",
                event_id=event_id,
                query_log_id=query_log_id,
            )
            return ExecuteResponse(
                tool_id=tool_id,
                server_id=server_id,
                success=False,
                error="Upstream MCP server timed out",
                latency_ms=latency,
            )
        except httpx.HTTPStatusError as exc:
            response_text = (exc.response.text or "")[:500]
            logger.warning(
                "execute service upstream HTTPStatusError "
                f"tool_id={tool_id} server_id={server_id} "
                f"status={exc.response.status_code} body={response_text!r}"
            )
            latency = (time.monotonic() - upstream_start) * 1000
            await self._log(
                tool_id,
                server_id,
                False,
                latency,
                str(exc),
                event_id=event_id,
                query_log_id=query_log_id,
            )
            return ExecuteResponse(
                tool_id=tool_id,
                server_id=server_id,
                success=False,
                error=f"Upstream error: HTTP {exc.response.status_code}",
                latency_ms=latency,
            )
        except RuntimeError as exc:
            logger.warning(
                f"execute service runtime error tool_id={tool_id} server_id={server_id} error={exc}"
            )
            latency = (time.monotonic() - upstream_start) * 1000
            await self._log(
                tool_id,
                server_id,
                False,
                latency,
                str(exc),
                event_id=event_id,
                query_log_id=query_log_id,
            )
            return ExecuteResponse(
                tool_id=tool_id,
                server_id=server_id,
                success=False,
                error="Failed to reach upstream MCP server",
                latency_ms=latency,
            )

        upstream_error = self._extract_upstream_error(result)
        if upstream_error is not None:
            logger.warning(
                "execute service upstream error payload "
                f"tool_id={tool_id} server_id={server_id} error={upstream_error}"
            )
            latency = (time.monotonic() - upstream_start) * 1000
            await self._log(
                tool_id,
                server_id,
                False,
                latency,
                upstream_error,
                event_id=event_id,
                query_log_id=query_log_id,
            )
            return ExecuteResponse(
                tool_id=tool_id,
                server_id=server_id,
                success=False,
                error=upstream_error,
                latency_ms=latency,
            )

        latency = (time.monotonic() - upstream_start) * 1000
        await self._log(
            tool_id,
            server_id,
            True,
            latency,
            event_id=event_id,
            query_log_id=query_log_id,
        )

        return ExecuteResponse(
            tool_id=tool_id,
            server_id=server_id,
            success=True,
            result=result,
            latency_ms=latency,
        )

    async def resume_pending_execution(
        self,
        resume_token: str,
        *,
        user_id: str,
    ) -> ExecuteResponse:
        """Resume a ready OAuth-blocked pending execution."""
        pending = await self._registry.fetch_pending_execution_by_resume_token(resume_token)
        if pending is None:
            return ExecuteResponse(
                tool_id="",
                server_id="",
                status="execution_failed",
                error="Pending execution not found",
            )

        error = validate_resume_request(pending, requester_user_id=user_id)
        if error is not None:
            if error == "Pending execution has expired" and pending.get("id"):
                await self._registry.update_pending_execution(
                    str(pending["id"]),
                    {"status": "expired", "error_message": error},
                )
            return ExecuteResponse(
                tool_id=str(pending.get("tool_id") or ""),
                server_id=str(pending.get("server_id") or ""),
                status="execution_failed",
                error=error,
            )

        pending_id = str(pending["id"])
        await self._registry.update_pending_execution(pending_id, {"status": "resuming"})
        response = await self.execute(
            str(pending["tool_id"]),
            pending.get("params_json") or {},
            user_id=user_id,
        )
        await self._registry.update_pending_execution(
            pending_id,
            {
                "status": "resumed" if response.success else "failed",
                "result_json": response.result,
                "error_message": response.error,
            },
        )
        return response

    @staticmethod
    def _extract_upstream_error(result: dict[str, Any]) -> str | None:
        """Translate JSON-RPC error payloads into proxy failures."""
        if not isinstance(result, dict):
            return None

        error = result.get("error")
        if error is None:
            return None

        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message", "Unknown upstream MCP error")
            if code is not None:
                return f"Upstream MCP error {code}: {message}"
            return f"Upstream MCP error: {message}"

        return f"Upstream MCP error: {error}"

    async def _log(
        self,
        tool_id: str,
        server_id: str,
        success: bool,
        latency_ms: float,
        error_message: str | None = None,
        client_id: str | None = None,
        event_id: str | None = None,
        query_log_id: int | None = None,
    ) -> None:
        """Best-effort execution logging."""
        if self._execution_logger is None:
            return
        try:
            await self._execution_logger.log(
                tool_id=tool_id,
                server_id=server_id,
                success=success,
                latency_ms=latency_ms,
                error_message=error_message,
                client_id=client_id,
                event_id=event_id,
                query_log_id=query_log_id,
            )
        except Exception as exc:
            logger.warning(f"Failed to log execution: {exc}")
