"""Evaluation harness: runs a pipeline strategy against ground truth queries."""

from __future__ import annotations

import time

from loguru import logger

from mcp_discovery.evaluation.evaluator import Evaluator
from mcp_discovery.evaluation.metrics import (
    EvalResult,
    PerQueryResult,
    compute_confusion_rate,
    compute_ece,
    compute_latency_stats,
    compute_mrr,
    compute_ndcg_at_5,
    compute_precision_at_1,
    compute_recall_at_k,
    compute_server_recall_at_k,
)
from mcp_discovery.models import GroundTruthEntry
from mcp_discovery.pipeline.confidence import compute_confidence
from mcp_discovery.pipeline.strategy import PipelineStrategy


class DefaultEvaluator(Evaluator):
    """Default evaluation strategy: sequential query execution with per-query isolation.

    Each query is executed independently — a single query failure (network timeout,
    rate-limit, etc.) is logged and skipped rather than aborting the full eval run.
    """

    def __init__(self, gap_threshold: float = 0.15) -> None:
        self._gap_threshold = gap_threshold

    async def evaluate(
        self,
        strategy: PipelineStrategy,
        queries: list[GroundTruthEntry],
        top_k: int = 10,
    ) -> EvalResult:
        """Run strategy on all queries and compute all evaluation metrics."""
        name_attr = getattr(strategy, "name", None)
        strategy_name = name_attr if isinstance(name_attr, str) else type(strategy).__name__
        logger.info(f"evaluate: strategy={strategy_name}, n_queries={len(queries)}, top_k={top_k}")

        per_query: list[PerQueryResult] = []
        ndcg_scores: list[float] = []
        confidences: list[float] = []
        correct_flags: list[bool] = []
        latencies_ms: list[float] = []
        n_failed = 0

        for entry in queries:
            t_start = time.perf_counter()
            try:
                results = await strategy.search(entry.query, top_k=top_k)
            except Exception as e:
                latency_ms = (time.perf_counter() - t_start) * 1000.0
                logger.warning(
                    f"evaluate: query_id={entry.query_id} failed — {e}. Counting as zero-result."
                )
                n_failed += 1
                # Failed queries count as zero-result (no correct answer found)
                per_query.append(
                    PerQueryResult(
                        query_id=entry.query_id,
                        top_1_correct=False,
                        in_top_k=False,
                        rank_of_correct=None,
                        confidence=0.0,
                        latency_ms=latency_ms,
                        retrieved_tool_ids=(),
                    )
                )
                ndcg_scores.append(0.0)
                latencies_ms.append(latency_ms)
                continue
            latency_ms = (time.perf_counter() - t_start) * 1000.0

            confidence, _ = compute_confidence(results, self._gap_threshold)
            retrieved_ids = tuple(r.tool.tool_id for r in results)

            top_1_correct = bool(results and results[0].tool.tool_id == entry.correct_tool_id)
            in_top_k = entry.correct_tool_id in retrieved_ids
            correct_server_in_top_k = any(
                r.tool.server_id == entry.correct_server_id for r in results
            )

            rank_of_correct: int | None = None
            for i, r in enumerate(results):
                if r.tool.tool_id == entry.correct_tool_id:
                    rank_of_correct = i + 1
                    break

            per_query.append(
                PerQueryResult(
                    query_id=entry.query_id,
                    top_1_correct=top_1_correct,
                    in_top_k=in_top_k,
                    rank_of_correct=rank_of_correct,
                    confidence=confidence,
                    latency_ms=latency_ms,
                    retrieved_tool_ids=retrieved_ids,
                    correct_server_in_top_k=correct_server_in_top_k,
                )
            )
            ndcg_scores.append(compute_ndcg_at_5(results, entry))
            confidences.append(confidence)
            correct_flags.append(top_1_correct)
            latencies_ms.append(latency_ms)

        p50, p95, p99, mean_lat = compute_latency_stats(latencies_ms)
        confusion = compute_confusion_rate(per_query)
        server_recall = compute_server_recall_at_k(per_query)
        result = EvalResult(
            strategy_name=strategy_name,
            n_queries=len(queries),
            n_failed=n_failed,
            k_used=top_k,
            precision_at_1=compute_precision_at_1(per_query),
            recall_at_k=compute_recall_at_k(per_query),
            mrr=compute_mrr(per_query),
            ndcg_at_5=sum(ndcg_scores) / len(ndcg_scores) if ndcg_scores else 0.0,
            confusion_rate=confusion,
            ece=compute_ece(confidences, correct_flags),
            latency_p50=p50,
            latency_p95=p95,
            latency_p99=p99,
            latency_mean=mean_lat,
            server_recall_at_k=server_recall,
            per_query=tuple(per_query),
        )
        confusion_str = f"{confusion:.3f}" if confusion is not None else "N/A"
        ece_str = f"{result.ece:.3f}" if result.ece is not None else "N/A (uncalibrated)"
        logger.info(
            f"evaluate done: P@1={result.precision_at_1:.3f}, "
            f"R@{top_k}={result.recall_at_k:.3f}, MRR={result.mrr:.3f}, "
            f"NDCG@5={result.ndcg_at_5:.3f}, ECE={ece_str}, "
            f"Confusion={confusion_str}, SrvR@K={server_recall:.3f}, "
            f"Latency_p95={result.latency_p95:.1f}ms"
        )
        if n_failed > 0:
            logger.warning(f"evaluate: {n_failed}/{len(queries)} queries failed")
        return result


async def evaluate(
    strategy: PipelineStrategy,
    queries: list[GroundTruthEntry],
    top_k: int = 10,
    gap_threshold: float = 0.15,
) -> EvalResult:
    """Convenience function: run DefaultEvaluator.evaluate().

    For custom evaluation logic, instantiate an Evaluator subclass directly.
    """
    evaluator = DefaultEvaluator(gap_threshold=gap_threshold)
    return await evaluator.evaluate(strategy, queries, top_k=top_k)
