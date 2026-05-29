"""Search Lambda thin adapter around the shared search runtime/service."""

import os

os.environ.setdefault("HF_HOME", "/var/task/.cache/fastembed")

import asyncio
import time
import uuid
from typing import Any

from service.analytics.stage_metrics import StageMetrics
from service.rag.factory import RAGServiceFactory
from service.services.contracts import SearchRequest
from service.services.query_logger import QueryLogger
from service.services.search_service import SearchService
from service.shared.events import build_request_context, parse_event_body
from service.shared.http import error_response, json_response
from service.shared.logging import log_info
from service.shared.runtime import build_search_runtime

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
query_logger = (
    QueryLogger(supabase_url=_supabase_url, supabase_key=_supabase_key)
    if _supabase_url and _supabase_key
    else None
)
_pending_tasks: set[asyncio.Task] = set()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda entry point."""
    from service.shared.event_loop import get_or_create_loop

    loop = get_or_create_loop()
    return loop.run_until_complete(_async_handler(event, context))


async def _async_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if event.get("source") == "warming":
        return json_response(200, {"status": "warm"})

    request_context = build_request_context(event, context)
    started_at = time.perf_counter()

    headers = event.get("headers") or {}
    raw_client_id = headers.get("x-client-id") or headers.get("X-Client-Id")
    client_id = raw_client_id.strip().lower() if raw_client_id else None

    try:
        body = parse_event_body(event)
        query_params = event.get("queryStringParameters") or {}
        request = SearchRequest(
            query=body.get("query") or query_params.get("query"),
            top_k=body.get("top_k", query_params.get("top_k", 3)),
            client_id=client_id,
        )
    except Exception as exc:
        return error_response(400, str(exc))

    result = await search_service.search(request)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    response_model = result.model_copy(update={"latency_ms": round(elapsed_ms, 1)})
    response = response_model.model_dump()
    log_info(
        "search",
        request_context.request_id,
        query=request.query,
        top_k=request.top_k,
        latency_ms=response["latency_ms"],
        result_count=len(response["results"]),
    )

    # Fire-and-forget query logging
    if query_logger is not None:
        event_id = f"search-{request_context.request_id or uuid.uuid4().hex[:12]}"
        raw_source_path = response.get("source_path")
        raw_candidate_ms = getattr(result, "candidate_ms", None)
        raw_freshness_ms = getattr(result, "freshness_ms", None)
        raw_rerank_ms = getattr(result, "rerank_ms", None)
        raw_fallback_used = getattr(result, "fallback_used", False)
        raw_cold_cache = getattr(result, "cold_cache", False)
        stage_metrics_payload = StageMetrics(
            source_path=raw_source_path if isinstance(raw_source_path, str) else None,
            candidate_ms=raw_candidate_ms if isinstance(raw_candidate_ms, (float, int)) else None,
            freshness_ms=(
                raw_freshness_ms if isinstance(raw_freshness_ms, (float, int)) else None
            ),
            rerank_ms=raw_rerank_ms if isinstance(raw_rerank_ms, (float, int)) else None,
            fallback_used=raw_fallback_used if isinstance(raw_fallback_used, bool) else False,
            cold_cache=raw_cold_cache if isinstance(raw_cold_cache, bool) else False,
        ).model_dump(exclude_none=True)
        task = asyncio.create_task(
            query_logger.log_query(
                event_id=event_id,
                query=request.query,
                results=[
                    {"tool_id": r["tool"]["tool_id"], "score": r["score"], "rank": r["rank"]}
                    for r in response["results"]
                ],
                confidence=response["confidence"],
                strategy=response.get("strategy_used") or "rag",
                latency_ms=response["latency_ms"] or elapsed_ms,
                client_id=client_id,
                stage_metrics=stage_metrics_payload,
            )
        )
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)

    return json_response(200, response)
