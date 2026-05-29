"""Pure metric computation functions and result dataclasses.

All functions are stateless and have no I/O — fully unit-testable without
any external services.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from mcp_discovery.models import GroundTruthEntry, SearchResult

_NDCG_CUTOFF = 5


@dataclass(frozen=True)
class PerQueryResult:
    """Evaluation result for a single query."""

    query_id: str
    top_1_correct: bool  # results[0].tool_id == correct_tool_id
    in_top_k: bool  # correct_tool_id in results[:k]
    rank_of_correct: int | None  # 1-indexed rank; None if not found in top-k
    confidence: float  # score of top-1 result (0.0 if empty)
    latency_ms: float
    retrieved_tool_ids: tuple[str, ...]
    correct_server_in_top_k: bool = False  # correct server_id present in any top-k result


@dataclass(frozen=True)
class EvalResult:
    """Aggregated evaluation metrics for a pipeline strategy run."""

    strategy_name: str
    n_queries: int
    n_failed: int
    k_used: int

    # Rank-based metrics
    precision_at_1: float  # [0, 1] — North Star
    recall_at_k: float  # [0, 1] — K == k_used
    mrr: float  # [0, 1] mean reciprocal rank of correct tool
    ndcg_at_5: float  # [0, 1] NDCG@5 with graded relevance

    # Error analysis — None when there are no errors (all correct)
    confusion_rate: float | None

    # Calibration (for DP6 confidence branching validation)
    # None when confidence values are not calibrated (e.g. raw similarity scores)
    ece: float | None

    # Latency (ms)
    latency_p50: float
    latency_p95: float
    latency_p99: float
    latency_mean: float

    # Diagnostic: server-level recall (fraction of queries where correct server appeared in top-k)
    # Useful for diagnosing SequentialStrategy Layer 1 loss (OQ-4)
    server_recall_at_k: float = 0.0

    # Raw per-query data for post-hoc analysis (E4 A/B, E7 correlation)
    per_query: tuple[PerQueryResult, ...] = field(default_factory=tuple)


def compute_precision_at_1(per_query: list[PerQueryResult]) -> float:
    """Fraction of queries where rank-1 result is the correct tool."""
    if not per_query:
        return 0.0
    return sum(1 for r in per_query if r.top_1_correct) / len(per_query)


def compute_recall_at_k(per_query: list[PerQueryResult]) -> float:
    """Fraction of queries where correct tool appears anywhere in top-K results."""
    if not per_query:
        return 0.0
    return sum(1 for r in per_query if r.in_top_k) / len(per_query)


def compute_mrr(per_query: list[PerQueryResult]) -> float:
    """Mean Reciprocal Rank of the correct tool across all queries.

    Queries where correct tool is not found contribute 0.
    """
    if not per_query:
        return 0.0
    return sum(1.0 / r.rank_of_correct for r in per_query if r.rank_of_correct is not None) / len(
        per_query
    )


def compute_ndcg_at_5(
    results: list[SearchResult],
    entry: GroundTruthEntry,
) -> float:
    """NDCG@5 with graded relevance: correct_tool=2, alternative_tool=1, else=0.

    Args:
        results: Ranked SearchResults from strategy.search(), highest score first.
        entry: Ground truth entry defining correct and alternative tools.
    """
    k = _NDCG_CUTOFF
    alternative_ids: set[str] = set(entry.alternative_tools or [])

    def grade(tool_id: str) -> int:
        if tool_id == entry.correct_tool_id:
            return 2
        if tool_id in alternative_ids:
            return 1
        return 0

    dcg = sum(
        grade(results[i].tool.tool_id) / math.log2(i + 2) for i in range(min(k, len(results)))
    )
    # Ideal ranking: correct tool first, then alternatives
    ideal_grades = sorted([2] + [1] * len(alternative_ids), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal_grades))
    return dcg / idcg if idcg > 0 else 0.0


def compute_confusion_rate(per_query: list[PerQueryResult]) -> float | None:
    """Fraction of errors where correct tool IS in top-K (confusion vs miss).

    Returns None if there are no errors at all.

    - Confusion: wrong rank-1 but correct in top-K -> description disambiguation issue
    - Miss: correct tool absent from top-K -> embedding/search strategy issue
    """
    errors = [r for r in per_query if not r.top_1_correct]
    if not errors:
        return None
    return sum(1 for r in errors if r.in_top_k) / len(errors)


def compute_ece(
    confidences: list[float],
    correct: list[bool],
    n_bins: int = 10,
) -> float | None:
    """Expected Calibration Error (Naeini et al., AAAI 2015).

    Bins queries by confidence score, then sums the weighted absolute gap
    between bin accuracy and bin mean confidence.

    Returns None if confidences are not calibrated (outside [0, 1]),
    since ECE requires calibrated probability estimates to be meaningful.

    Args:
        confidences: Calibrated confidence per query (must be in [0, 1]).
        correct: Whether rank-1 result was correct per query.
        n_bins: Number of equal-width bins over [0, 1].

    Returns:
        ECE value in [0, 1], or None if confidences are uncalibrated.
    """
    if not confidences:
        return None
    if not all(0.0 <= c <= 1.0 for c in confidences):
        from loguru import logger

        out_min, out_max = min(confidences), max(confidences)
        logger.warning(
            f"compute_ece: confidences outside [0,1] (range [{out_min:.3f}, {out_max:.3f}]). "
            "Returning None — ECE requires calibrated probabilities."
        )
        return None
    n = len(confidences)
    bin_edges = [i / n_bins for i in range(n_bins + 1)]
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        if i == n_bins - 1:
            indices = [j for j, c in enumerate(confidences) if lo <= c <= hi]
        else:
            indices = [j for j, c in enumerate(confidences) if lo <= c < hi]
        if not indices:
            continue
        bin_size = len(indices)
        bin_acc = sum(correct[j] for j in indices) / bin_size
        bin_conf = sum(confidences[j] for j in indices) / bin_size
        ece += (bin_size / n) * abs(bin_acc - bin_conf)
    return ece


def compute_latency_stats(
    latencies_ms: list[float],
) -> tuple[float, float, float, float]:
    """Return (p50, p95, p99, mean) latency in milliseconds."""
    if not latencies_ms:
        return 0.0, 0.0, 0.0, 0.0
    arr = np.array(latencies_ms, dtype=float)
    return (
        float(np.percentile(arr, 50)),
        float(np.percentile(arr, 95)),
        float(np.percentile(arr, 99)),
        float(np.mean(arr)),
    )


def compute_server_recall_at_k(per_query: list[PerQueryResult]) -> float:
    """Fraction of queries where the correct server appears in any top-k result.

    Diagnoses SequentialStrategy Layer 1 loss: if the correct server is absent
    from all top-k results, Layer 1 missed it entirely.  Compare against
    FlatStrategy (which always scores 1.0 since it searches all tools globally).
    """
    if not per_query:
        return 0.0
    return sum(1 for r in per_query if r.correct_server_in_top_k) / len(per_query)
