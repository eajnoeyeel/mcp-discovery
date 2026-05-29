"""RAG pipeline service — orchestrates search, fallback, merge, operability, confidence."""

import asyncio
import time
from pathlib import Path
from typing import Any

from loguru import logger

from mcp_discovery.description.variant_store import VariantStore
from mcp_discovery.models import FindBestToolResponse, SearchResult
from mcp_discovery.pipeline.confidence import compute_confidence
from mcp_discovery.pipeline.strategy import PipelineStrategy
from mcp_discovery.reranking.base import Reranker
from service.rag.cache import QueryCache
from service.rag.fallback import SupabaseFallback
from service.rag.merger import ResultMerger

BLOCKED_STATUSES = frozenset({"quarantined", "unreachable", "deprecated", "stale"})


class RAGSearchResult:
    """Wraps FindBestToolResponse and carries pipeline observability signals.

    Delegates all FindBestToolResponse attribute access transparently, so existing
    callers (resp.results, resp.confidence, etc.) require no changes. The extra
    fields carry stage-level telemetry that handlers can persist out-of-band
    without mutating the public API response model.
    """

    __slots__ = (
        "_response",
        "candidate_ms",
        "freshness_ms",
        "rerank_ms",
        "cold_cache",
        "fallback_used",
    )

    def __init__(
        self,
        response: FindBestToolResponse,
        *,
        candidate_ms: float,
        freshness_ms: float,
        rerank_ms: float,
        cold_cache: bool,
        fallback_used: bool,
    ) -> None:
        object.__setattr__(self, "_response", response)
        object.__setattr__(self, "candidate_ms", candidate_ms)
        object.__setattr__(self, "freshness_ms", freshness_ms)
        object.__setattr__(self, "rerank_ms", rerank_ms)
        object.__setattr__(self, "cold_cache", cold_cache)
        object.__setattr__(self, "fallback_used", fallback_used)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_response"), name)

    def model_dump(self, **kwargs: Any) -> dict:
        return object.__getattribute__(self, "_response").model_dump(**kwargs)


def _apply_selection_descriptions(
    results: list[SearchResult],
    client_id: str | None = None,
    variant_map: dict[str, dict[str, str]] | None = None,
) -> list[SearchResult]:
    """Shape response descriptions without changing retrieval inputs."""
    if client_id is None:
        return results

    out = []
    for result in results:
        if client_id and client_id.startswith("gemini"):
            description = result.tool.selection_description or result.tool.description
        elif client_id and variant_map:
            vendor_description = (variant_map.get(result.tool.tool_id) or {}).get(client_id)
            description = (
                vendor_description or result.tool.selection_description or result.tool.description
            )
        else:
            description = result.tool.selection_description or result.tool.description

        if description and description != result.tool.description:
            updated_tool = result.tool.model_copy(update={"description": description})
            out.append(result.model_copy(update={"tool": updated_tool}))
        else:
            out.append(result)
    return out


def _apply_hard_gate(
    results: list[SearchResult],
    snapshots: dict,
) -> list[SearchResult]:
    """Filter tools with blocked lifecycle status. Unknown tools pass through."""
    return [
        r
        for r in results
        if getattr(snapshots.get(r.tool.tool_id), "status", "active") not in BLOCKED_STATUSES
    ]


def _apply_score_merge(
    results: list[SearchResult],
    snapshots: dict,
    *,
    w_rel: float,
    w_op: float,
    min_boost_rel: float,
) -> list[SearchResult]:
    """Merge retrieval score with precomputed operability. Arithmetic only."""
    merged = []
    for r in results:
        snap = snapshots.get(r.tool.tool_id)
        retrieval = r.score
        if snap:
            op = getattr(snap, "operability_score", None) or 0.0
            boost = getattr(snap, "boost", None) or 0.0
            effective_boost = boost if retrieval >= min_boost_rel else 0.0
            composite = retrieval * w_rel + op * w_op + effective_boost
        else:
            composite = retrieval * w_rel
        merged.append(
            r.model_copy(
                update={
                    "score": round(composite, 4),
                    "retrieval_score": retrieval,
                }
            )
        )
    merged.sort(key=lambda r: r.score, reverse=True)
    for i, r in enumerate(merged):
        merged[i] = r.model_copy(update={"rank": i + 1})
    return merged


def _load_variant_map() -> dict[str, dict[str, str]]:
    """Load per-client variants from JSONL into a tool_id -> client_id map."""
    variants_path = (
        Path(__file__).resolve().parents[2] / "data" / "enriched" / "per_client_variants.jsonl"
    )
    if not variants_path.exists():
        logger.warning(f"Per-client variant file not found: {variants_path}")
        return {}

    store = VariantStore(path=variants_path)
    variants = store.load_all()
    result: dict[str, dict[str, str]] = {}
    for variant in variants:
        result.setdefault(variant.tool_id, {})[variant.vendor] = variant.description
    logger.info(f"Loaded {len(variants)} per-client variants for {len(result)} tools")
    return result


async def _recover_dense_only(
    strategy: PipelineStrategy,
    *,
    query: str,
    top_k: int,
) -> list[SearchResult]:
    """Best-effort dense-only recovery when the hybrid path fails.

    This intentionally relies on FlatStrategy's live attributes rather than
    changing the public strategy ABC: only the live service path uses this
    recovery branch, and only after the primary strategy call has already failed.
    """
    strategy_state = getattr(strategy, "__dict__", {})
    embedder = strategy_state.get("embedder")
    tool_store = strategy_state.get("tool_store")
    if embedder is None or tool_store is None:
        return []

    query_vector = await embedder.embed_one(query)
    return await tool_store.search(
        query_vector=query_vector,
        top_k=top_k,
        server_id_filter=None,
    )


class RAGService:
    """Orchestrates the full RAG search pipeline."""

    def __init__(
        self,
        strategy: PipelineStrategy,
        fallback: SupabaseFallback | None,
        cache: QueryCache | None,
        confidence_gap_threshold: float = 0.15,
        reranker: Reranker | None = None,
        enable_pending_freshness: bool = False,
        rerank_candidate_pool_size: int = 10,
        pending_freshness_limit: int = 2,
        pending_freshness_timeout_ms: int = 150,
        operability_cache: object | None = None,
        w_relevance: float = 0.75,
        w_operability: float = 0.25,
        min_boost_relevance: float = 0.3,
        enable_per_client_routing: bool = False,
    ) -> None:
        self._strategy = strategy
        self._fallback = fallback
        self._cache = cache
        self._gap_threshold = confidence_gap_threshold
        self._reranker = reranker
        self._enable_pending_freshness = enable_pending_freshness
        self._rerank_candidate_pool_size = rerank_candidate_pool_size
        self._pending_freshness_limit = pending_freshness_limit
        self._pending_freshness_timeout_ms = pending_freshness_timeout_ms
        self._operability_cache = operability_cache
        self._w_relevance = w_relevance
        self._w_operability = w_operability
        self._min_boost_relevance = min_boost_relevance
        self._variant_map: dict[str, dict[str, str]] = {}
        if enable_per_client_routing:
            try:
                self._variant_map = _load_variant_map()
            except Exception as exc:
                logger.warning(f"Failed to load per-client variant map: {exc}")

    @staticmethod
    def _cache_key(
        query: str,
        top_k: int,
        freshness_enabled: bool,
        client_id: str | None = None,
    ) -> str:
        base = f"{query}\x1f{top_k}\x1f{int(freshness_enabled)}"
        return base if not client_id else f"{base}\x1f{client_id}"

    def _can_use_cache(self) -> bool:
        return self._cache is not None and not self._enable_pending_freshness

    async def search(
        self,
        query: str,
        top_k: int = 3,
        client_id: str | None = None,
    ) -> RAGSearchResult:
        if top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")
        t_start = time.time()
        cache_key = self._cache_key(query, top_k, self._enable_pending_freshness, client_id)
        sparse_active = getattr(self._strategy, "__dict__", {}).get("sparse_embedder") is not None

        if self._can_use_cache():
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info(f"Cache hit: query='{query[:40]}' top_k={top_k}")
                return cached

        candidate_k = max(top_k, self._rerank_candidate_pool_size)
        primary: list[SearchResult] = []
        degraded = False
        dense_recovered = False
        t_candidate = time.time()
        try:
            primary = await self._strategy.search(query, candidate_k)
        except Exception as exc:
            logger.warning(f"Strategy search failed, using fallback: {exc}")
            degraded = True
            if sparse_active:
                try:
                    primary = await _recover_dense_only(
                        self._strategy,
                        query=query,
                        top_k=candidate_k,
                    )
                    dense_recovered = bool(primary)
                except Exception as recovery_exc:
                    logger.warning(f"Dense-only recovery failed (non-critical): {recovery_exc}")
        candidate_ms = (time.time() - t_candidate) * 1000

        t_freshness = time.time()
        freshness_results: list[SearchResult] = []
        if (
            not degraded
            and self._enable_pending_freshness
            and self._fallback is not None
            and self._fallback.is_configured
        ):
            try:
                timeout_s = self._pending_freshness_timeout_ms / 1000
                freshness_results = await asyncio.wait_for(
                    self._fallback.search_pending_freshness(
                        query,
                        limit=self._pending_freshness_limit,
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Pending freshness search timed out after "
                    f"{self._pending_freshness_timeout_ms}ms"
                )
            except Exception as exc:
                logger.warning(f"Pending freshness search failed (non-critical): {exc}")

        fallback_results: list[SearchResult] = []
        if degraded and self._fallback is not None and self._fallback.is_configured:
            try:
                fallback_results = await self._fallback.search_full_catalog(
                    query,
                    limit=candidate_k,
                )
            except Exception as exc:
                logger.warning(f"Fallback search failed: {exc}")
        freshness_ms = (time.time() - t_freshness) * 1000

        candidates = ResultMerger.merge_candidates(primary, freshness_results, fallback_results)

        strategy_used = "rag"
        final_results = ResultMerger.truncate_and_reassign(candidates, top_k)
        t_rerank = time.time()
        if self._reranker is not None and candidates:
            try:
                final_results = await self._reranker.rerank(query, candidates, top_k)
                strategy_used = "rag+rerank"
            except Exception as exc:
                logger.warning(f"Reranker failed, using unranked results: {exc}")
        rerank_ms = (time.time() - t_rerank) * 1000

        # Gate + Score merge + Enrichment (after reranking, before response)
        cold_cache = False
        if self._operability_cache is not None:
            try:
                tool_ids = [r.tool.tool_id for r in final_results]
                snapshots = await self._operability_cache.get_bulk(tool_ids)
            except Exception:
                snapshots = {}
            cold_cache = not snapshots
            final_results = _apply_hard_gate(final_results, snapshots)
            final_results = _apply_score_merge(
                final_results,
                snapshots,
                w_rel=self._w_relevance,
                w_op=self._w_operability,
                min_boost_rel=self._min_boost_relevance,
            )
            # Enrichment
            from mcp_discovery.operability.models import build_enrichment

            for i, r in enumerate(final_results[:top_k]):
                snap = snapshots.get(r.tool.tool_id)
                final_results[i] = r.model_copy(update={"operability": build_enrichment(snap)})

        final_results = _apply_selection_descriptions(final_results, client_id, self._variant_map)

        if sparse_active and not degraded:
            gap_threshold = getattr(
                self._gap_threshold,
                "__hybrid__",
                min(self._gap_threshold, 0.005),
            )
            strategy_hint = "hybrid"
        else:
            gap_threshold = self._gap_threshold
            strategy_hint = "dense"

        confidence, disambiguation_needed = compute_confidence(
            final_results, gap_threshold=gap_threshold, strategy_hint=strategy_hint
        )

        # Determine response-level source_path
        has_freshness = len(freshness_results) > 0
        fallback_used = bool(fallback_results)
        if fallback_used:
            response_source_path = "lexical_fallback"
        elif degraded and dense_recovered:
            response_source_path = "dense_only_degraded"
        elif sparse_active:
            response_source_path = "hybrid_semantic"
        elif has_freshness:
            response_source_path = "mixed"
        else:
            response_source_path = "semantic"

        total_ms = (time.time() - t_start) * 1000
        response = FindBestToolResponse(
            query=query,
            results=final_results,
            confidence=confidence,
            disambiguation_needed=disambiguation_needed,
            strategy_used=strategy_used,
            latency_ms=round(total_ms, 1),
            degraded=degraded,
            source_path=response_source_path,
        )

        result = RAGSearchResult(
            response,
            candidate_ms=round(candidate_ms, 1),
            freshness_ms=round(freshness_ms, 1),
            rerank_ms=round(rerank_ms, 1),
            cold_cache=cold_cache,
            fallback_used=fallback_used,
        )

        if self._can_use_cache():
            self._cache.put(cache_key, result)

        stage_breakdown = (
            f"[candidate={candidate_ms:.1f}ms"
            f" freshness={freshness_ms:.1f}ms"
            f" rerank={rerank_ms:.1f}ms]"
        )
        logger.info(
            f"RAG search: query='{query[:60]}' candidates={len(candidates)} "
            f"results={len(final_results)} confidence={confidence:.3f} degraded={degraded} "
            f"freshness={len(freshness_results)} reranked={strategy_used == 'rag+rerank'} "
            f"latency={total_ms:.1f}ms {stage_breakdown}"
        )
        return result
