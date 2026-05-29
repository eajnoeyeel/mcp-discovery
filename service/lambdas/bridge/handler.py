"""Bridge MCP Server — library path plus fallback JSON-RPC dispatch."""

from __future__ import annotations

import json
import os
import time
import uuid
from contextvars import ContextVar
from typing import Any

import httpx
from loguru import logger

from service.adapters.execution import SupabaseExecutionLogger, SupabaseToolRegistry
from service.adapters.mcp_http_client import MCPHTTPClient
from service.adapters.supabase_auth import SupabaseAuthClient
from service.analytics.stage_metrics import StageMetrics
from service.rag.factory import RAGServiceFactory
from service.services.auth_probe import build_auth_probe_result
from service.services.bridge_service import BridgeService
from service.services.contracts import ExecuteRequest, SearchRequest
from service.services.execute_service import ExecuteService
from service.services.query_logger import QueryLogger
from service.services.search_service import SearchService
from service.shared.event_loop import get_or_create_loop
from service.shared.runtime import build_search_runtime

_BRIDGE_USER_ID: ContextVar[str | None] = ContextVar("_BRIDGE_USER_ID", default=None)
_BRIDGE_AUTH_SOURCE: ContextVar[str] = ContextVar(
    "_BRIDGE_AUTH_SOURCE",
    default="bridge_authorizer",
)
_BRIDGE_ISSUER: ContextVar[str | None] = ContextVar("_BRIDGE_ISSUER", default=None)
_BRIDGE_AUTH_STATUS: ContextVar[str | None] = ContextVar("_BRIDGE_AUTH_STATUS", default=None)
_BRIDGE_AUTH_ERROR: ContextVar[str | None] = ContextVar("_BRIDGE_AUTH_ERROR", default=None)

_FIND_BEST_TOOL_DESCRIPTION = """\
Search the MCP tool registry by natural language and return top-ranked candidate tools.

## When to use
- The user needs a capability but the exact tool_id is unknown
  (e.g. "search Airbnb listings", "send a Slack message", "look up a GitHub repo").
- Before `execute_tool` whenever the tool_id has not yet been resolved.
- To discover what MCP tools are available for a given task.

## Parameters
- `query` (string, required): Natural-language description of the desired capability.
- `top_k` (integer, optional, default 3, range 1-10): Number of candidates to return.

## Returns
Object with three fields:
- `results`: list of `{tool_id, description, score (0.0-1.0), input_schema}`
  ranked by match quality.
- `confidence`: float score-gap between rank-1 and rank-2 (higher = less ambiguous).
- `query_log_id`: integer or null. Echo it back to `execute_tool` to link the
  execution to this search for conversion analytics.

## Next step
Pick a result, then call `execute_tool` with its `tool_id` plus `params` shaped
to the returned `input_schema`.
"""


_EXECUTE_TOOL_DESCRIPTION = """\
Invoke a registered MCP tool by tool_id with the given params and return its response.

## When to use
- After `find_best_tool` selected a candidate you want to run.
- When the tool_id (`"{server_id}::{tool_name}"`) is already known.
- Not for discovery - call `find_best_tool` first if the tool_id is unknown.

## Parameters
- `tool_id` (string, required): Fully qualified identifier,
  e.g. `"github::search_repositories"`.
- `params` (object, optional, default `{}`): JSON matching the target tool's
  `input_schema` (from `find_best_tool`).
- `query_log_id` (integer | null, optional): Echo the `query_log_id` from
  `find_best_tool` to link this execution to the search. Omit or pass null
  for direct calls.

## Returns
The upstream tool's native response on success. On failure, an object with
`error` and `details` fields (unknown tool_id, schema mismatch, upstream timeout).
"""

_AUTH_PROBE_DESCRIPTION = "Verify whether the current MCP request is authenticated."
_RESUME_PENDING_EXECUTION_DESCRIPTION = "Resume an OAuth-blocked pending execution by resume token."


runtime = build_search_runtime()
mlp_settings = runtime.mlp_settings
rag_service = RAGServiceFactory.create(
    strategy=runtime.strategy,
    supabase_url=os.getenv("SUPABASE_URL", ""),
    supabase_key=os.getenv("SUPABASE_SERVICE_KEY", ""),
    cache_ttl=mlp_settings.cache_ttl_seconds,
    confidence_gap_threshold=runtime.settings.confidence_gap_threshold,
    reranker=None,  # reranker removed per architecture pivot
    enable_pending_freshness=mlp_settings.enable_pending_freshness,
    enable_per_client_routing=mlp_settings.enable_per_client_routing,
    rerank_candidate_pool_size=mlp_settings.rerank_candidate_pool_size,
    pending_freshness_limit=mlp_settings.pending_freshness_limit,
    pending_freshness_timeout_ms=mlp_settings.pending_freshness_timeout_ms,
    operability_cache=runtime.operability_cache,
)
search_service = SearchService(rag_service=rag_service)

_supabase_url = os.getenv("SUPABASE_URL", "")
_supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "")
_query_logger = (
    QueryLogger(supabase_url=_supabase_url, supabase_key=_supabase_key)
    if _supabase_url and _supabase_key
    else None
)
try:
    _execute_service: ExecuteService = ExecuteService(
        registry=SupabaseToolRegistry(),
        mcp_client=MCPHTTPClient(timeout=25.0),
        execution_logger=SupabaseExecutionLogger(),
    )
except ImportError as exc:
    logger.error(f"ExecuteService dependencies missing in bridge artifact: {exc}")
    raise

bridge_service = BridgeService(
    search_service=search_service,
    execute_service=_execute_service,
)


async def _find_best_tool(query: str, top_k: int = 3) -> dict[str, Any]:
    """Search for the best MCP tool matching a natural-language query."""
    request = SearchRequest(query=query, top_k=top_k, client_id=None)
    started_at = time.perf_counter()
    result = await bridge_service.find_best_tool(request)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)

    query_log_id: int | None = None
    if _query_logger is not None:
        event_id = f"bridge-{uuid.uuid4().hex[:12]}"
        tools = payload.get("results", [])
        raw_candidate_ms = getattr(result, "candidate_ms", None)
        raw_freshness_ms = getattr(result, "freshness_ms", None)
        raw_rerank_ms = getattr(result, "rerank_ms", None)
        raw_fallback_used = getattr(result, "fallback_used", False)
        raw_cold_cache = getattr(result, "cold_cache", False)
        query_log_id = await _query_logger.log_query(
            event_id=event_id,
            query=query,
            results=[
                {
                    "tool_id": t.get("tool_id", t.get("tool", {}).get("tool_id", "")),
                    "score": t.get("score", 0),
                    "rank": t.get("rank", 0),
                }
                for t in tools[:5]
            ],
            confidence=payload.get("confidence", 0.0),
            strategy=payload.get("strategy_used", "bridge"),
            latency_ms=elapsed_ms,
            stage_metrics=StageMetrics(
                source_path=payload.get("source_path"),
                candidate_ms=(
                    raw_candidate_ms if isinstance(raw_candidate_ms, (float, int)) else None
                ),
                freshness_ms=(
                    raw_freshness_ms if isinstance(raw_freshness_ms, (float, int)) else None
                ),
                rerank_ms=raw_rerank_ms if isinstance(raw_rerank_ms, (float, int)) else None,
                fallback_used=raw_fallback_used if isinstance(raw_fallback_used, bool) else False,
                cold_cache=raw_cold_cache if isinstance(raw_cold_cache, bool) else False,
            ).model_dump(exclude_none=True),
        )

    return {**payload, "latency_ms": round(elapsed_ms, 1), "query_log_id": query_log_id}


async def _execute_tool(
    tool_id: str,
    params: dict | None = None,
    query_log_id: int | None = None,
) -> dict[str, Any]:
    """Proxy execution to the dedicated execute path."""
    request = ExecuteRequest(tool_id=tool_id, params=params or {})
    return await bridge_service.execute_tool(
        request,
        user_id=_BRIDGE_USER_ID.get(),
        query_log_id=query_log_id,
    )


async def _auth_probe() -> dict[str, object]:
    user_id = _BRIDGE_USER_ID.get()
    return build_auth_probe_result(
        user_id=user_id,
        auth_source=_BRIDGE_AUTH_SOURCE.get(),
        issuer=_BRIDGE_ISSUER.get(),
        status=_BRIDGE_AUTH_STATUS.get(),
        error=_BRIDGE_AUTH_ERROR.get(),
    )


async def _resume_pending_execution(resume_token: str) -> dict[str, Any]:
    user_id = _BRIDGE_USER_ID.get()
    if not user_id:
        return {
            "status": "auth_required",
            "error": "Authenticated MCP session required",
        }
    response = await _execute_service.resume_pending_execution(resume_token, user_id=user_id)
    if not response.success:
        return {
            "status": response.status,
            "tool_id": response.tool_id,
            "error": response.error,
        }
    return {
        "status": response.status,
        "tool_id": response.tool_id,
        "server_id": response.server_id,
        "result": response.result,
        "latency_ms": response.latency_ms,
    }


def _extract_user_id_from_event(event: dict) -> str | None:
    """Extract authenticated platform user id from common API Gateway authorizer shapes."""
    authorizer = event.get("requestContext", {}).get("authorizer") or {}
    jwt_claims = authorizer.get("jwt", {}).get("claims") or {}
    lambda_context = authorizer.get("lambda") or {}
    return (
        lambda_context.get("user_id")
        or lambda_context.get("sub")
        or jwt_claims.get("sub")
        or authorizer.get("user_id")
        or authorizer.get("principalId")
    )


def _extract_bearer_token(headers: dict | None) -> str | None:
    headers = headers or {}
    authorization = headers.get("authorization") or headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


async def _resolve_bridge_auth(
    event: dict,
) -> tuple[str | None, str, str | None, str | None, str | None]:
    user_id = _extract_user_id_from_event(event)
    if user_id:
        return user_id, "bridge_authorizer", "supabase", None, None

    token = _extract_bearer_token(event.get("headers"))
    if token is None:
        return None, "bridge_authorizer", None, None, None

    if not _supabase_url or not _supabase_key:
        logger.warning("Bridge auth resolution skipped: Supabase auth credentials are unavailable")
        return (
            None,
            "supabase_bearer",
            None,
            "validation_unavailable",
            "supabase_validation_unavailable",
        )

    auth_client = SupabaseAuthClient(url=_supabase_url, service_key=_supabase_key)
    try:
        user = await auth_client.get_user(token)
    except httpx.HTTPStatusError:
        return None, "supabase_bearer", None, None, None
    except httpx.HTTPError as exc:
        logger.warning(f"Bridge auth resolution failed during bearer validation: {exc}")
        return (
            None,
            "supabase_bearer",
            None,
            "validation_unavailable",
            "supabase_validation_unavailable",
        )

    resolved_user_id = user.get("id")
    return resolved_user_id, "supabase_bearer", "supabase" if resolved_user_id else None, None, None


try:
    from awslabs.mcp_lambda_handler import MCPLambdaHandler  # type: ignore[import-untyped]

    mcp = MCPLambdaHandler(name="mcp-discovery-bridge", version="1.0.0")

    @mcp.tool()
    def find_best_tool(query: str, top_k: int = 3) -> dict:
        loop = get_or_create_loop()
        return loop.run_until_complete(_find_best_tool(query, top_k))

    find_best_tool.__doc__ = _FIND_BEST_TOOL_DESCRIPTION

    @mcp.tool()
    def execute_tool(tool_id: str, params: str = "{}", query_log_id: int | None = None) -> dict:
        parsed = json.loads(params) if isinstance(params, str) else params
        loop = get_or_create_loop()
        return loop.run_until_complete(_execute_tool(tool_id, parsed, query_log_id))

    execute_tool.__doc__ = _EXECUTE_TOOL_DESCRIPTION

    @mcp.tool()
    def auth_probe() -> dict:
        loop = get_or_create_loop()
        return loop.run_until_complete(_auth_probe())

    auth_probe.__doc__ = _AUTH_PROBE_DESCRIPTION

    @mcp.tool()
    def resume_pending_execution(resume_token: str) -> dict:
        loop = get_or_create_loop()
        return loop.run_until_complete(_resume_pending_execution(resume_token))

    resume_pending_execution.__doc__ = _RESUME_PENDING_EXECUTION_DESCRIPTION

    def lambda_handler(event: dict, context: Any) -> dict:
        """AWS Lambda entry-point (library path)."""
        loop = get_or_create_loop()
        user_id, auth_source, issuer, auth_status, auth_error = loop.run_until_complete(
            _resolve_bridge_auth(event)
        )
        user_token = _BRIDGE_USER_ID.set(user_id)
        source_token = _BRIDGE_AUTH_SOURCE.set(auth_source)
        issuer_token = _BRIDGE_ISSUER.set(issuer)
        status_token = _BRIDGE_AUTH_STATUS.set(auth_status)
        error_token = _BRIDGE_AUTH_ERROR.set(auth_error)
        try:
            return mcp.handle_request(event, context)
        finally:
            _BRIDGE_AUTH_ERROR.reset(error_token)
            _BRIDGE_AUTH_STATUS.reset(status_token)
            _BRIDGE_ISSUER.reset(issuer_token)
            _BRIDGE_AUTH_SOURCE.reset(source_token)
            _BRIDGE_USER_ID.reset(user_token)

    logger.info("Bridge MCP handler: using awslabs.mcp-lambda-handler")

except ImportError:
    logger.warning("awslabs.mcp-lambda-handler not installed — using manual JSON-RPC fallback")

    _TOOL_SCHEMAS: list[dict[str, Any]] = [
        {
            "name": "find_best_tool",
            "description": _FIND_BEST_TOOL_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of what you need",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "execute_tool",
            "description": _EXECUTE_TOOL_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tool_id": {
                        "type": "string",
                        "description": "Tool ID in format 'server_id::tool_name'",
                    },
                    "params": {
                        "type": "object",
                        "description": "Parameters to pass to the tool",
                        "default": {},
                    },
                    "query_log_id": {
                        "type": ["integer", "null"],
                        "description": (
                            "Optional. Echo back the query_log_id returned from find_best_tool "
                            "to correlate this execution with that search for conversion "
                            "analytics. Omit or pass null for direct executions."
                        ),
                    },
                },
                "required": ["tool_id"],
            },
        },
        {
            "name": "auth_probe",
            "description": _AUTH_PROBE_DESCRIPTION,
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "resume_pending_execution",
            "description": _RESUME_PENDING_EXECUTION_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "resume_token": {
                        "type": "string",
                        "description": "Resume token returned by execute_tool auth_required.",
                    },
                },
                "required": ["resume_token"],
            },
        },
    ]

    async def _dispatch_jsonrpc(body: dict) -> dict[str, Any]:
        method = body.get("method", "")
        req_id = body.get("id")
        params = body.get("params", {})

        if method == "initialize":
            return _jsonrpc_ok(
                req_id,
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mcp-discovery-bridge", "version": "1.0.0"},
                },
            )

        if method == "tools/list":
            return _jsonrpc_ok(req_id, {"tools": _TOOL_SCHEMAS})

        if method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments", {})
            if name == "find_best_tool":
                result = await _find_best_tool(
                    query=args.get("query", ""),
                    top_k=args.get("top_k", 3),
                )
            elif name == "execute_tool":
                raw_qli = args.get("query_log_id")
                if raw_qli is not None:
                    try:
                        raw_qli = int(raw_qli)
                    except (TypeError, ValueError):
                        return _jsonrpc_error(req_id, -32602, "query_log_id must be an integer")
                result = await _execute_tool(
                    tool_id=args.get("tool_id", ""),
                    params=args.get("params"),
                    query_log_id=raw_qli,
                )
            elif name == "auth_probe":
                result = await _auth_probe()
            elif name == "resume_pending_execution":
                result = await _resume_pending_execution(
                    resume_token=str(args.get("resume_token") or "")
                )
            else:
                return _jsonrpc_error(req_id, -32601, f"Unknown tool: {name}")
            return _jsonrpc_ok(
                req_id,
                {"content": [{"type": "text", "text": json.dumps(result)}]},
            )

        if method == "ping":
            return _jsonrpc_ok(req_id, {})

        return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")

    def _jsonrpc_ok(req_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    async def _async_handler(event: dict) -> dict[str, Any]:
        # Warming short-circuit: EventBridge sends {"source": "warming"} every 5 min
        if event.get("source") == "warming":
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"status": "warm"}),
            }

        http_method = event.get("requestContext", {}).get("http", {}).get("method", "POST")

        if http_method == "GET":
            return {
                "statusCode": 405,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Method Not Allowed. Use POST."}),
            }

        raw_body = event.get("body", "{}")
        if event.get("isBase64Encoded"):
            import base64

            raw_body = base64.b64decode(raw_body).decode()

        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(_jsonrpc_error(None, -32700, "Parse error")),
            }

        user_id, auth_source, issuer, auth_status, auth_error = await _resolve_bridge_auth(event)
        user_token = _BRIDGE_USER_ID.set(user_id)
        source_token = _BRIDGE_AUTH_SOURCE.set(auth_source)
        issuer_token = _BRIDGE_ISSUER.set(issuer)
        status_token = _BRIDGE_AUTH_STATUS.set(auth_status)
        error_token = _BRIDGE_AUTH_ERROR.set(auth_error)
        try:
            result = await _dispatch_jsonrpc(body)
        finally:
            _BRIDGE_AUTH_ERROR.reset(error_token)
            _BRIDGE_AUTH_STATUS.reset(status_token)
            _BRIDGE_ISSUER.reset(issuer_token)
            _BRIDGE_AUTH_SOURCE.reset(source_token)
            _BRIDGE_USER_ID.reset(user_token)
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "MCP-Version": "2025-03-26",
            },
            "body": json.dumps(result),
        }

    def lambda_handler(event: dict, context: Any) -> dict:
        """AWS Lambda entry-point (fallback JSON-RPC path)."""
        loop = get_or_create_loop()
        return loop.run_until_complete(_async_handler(event))
