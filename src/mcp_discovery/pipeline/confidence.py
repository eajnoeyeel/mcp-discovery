"""Gap-based confidence branching for retrieval results."""

from mcp_discovery.models import SearchResult


def _retrieval_score(r: SearchResult) -> float:
    """Return the raw retrieval similarity score, pre-score-merge.

    After _apply_score_merge(), SearchResult.score holds the composite
    (retrieval * w_rel + operability * w_op + boost) while retrieval_score
    preserves the original embedding/reranker similarity.  Confidence gap
    must reflect semantic match quality, not operability-inflated values.

    Falls back to score when retrieval_score is not set (e.g. evaluation
    harness or pipelines that skip score merge).
    """
    return r.retrieval_score if r.retrieval_score is not None else r.score


def compute_confidence(
    results: list[SearchResult],
    gap_threshold: float = 0.15,
    *,
    strategy_hint: str = "dense",
) -> tuple[float, bool]:
    """Compute confidence score and disambiguation flag from ranked results.

    Uses the score gap between rank-1 and rank-2 to determine confidence.
    A small gap means the top two results are close — the LLM may need to
    ask for clarification (disambiguation_needed=True).

    Args:
        results: Ranked SearchResults, highest score first.
        gap_threshold: Minimum gap for a clear winner. Default 0.15 (from config).
            For hybrid (RRF) scores the caller should pass a smaller threshold
            (e.g. 0.005) because RRF scores occupy a much narrower range.
        strategy_hint: Identifies the retrieval strategy that produced the results
            ("dense" or "hybrid"). Currently informational; callers control
            gap_threshold directly for hybrid paths.

    Returns:
        (confidence, needs_disambiguation):
            confidence: Retrieval score of the top result (0.0 if no results).
            needs_disambiguation: True if gap < threshold or no results.
    """
    if not results:
        return 0.0, True

    confidence = _retrieval_score(results[0])

    if len(results) == 1:
        return confidence, False

    gap = _retrieval_score(results[0]) - _retrieval_score(results[1])
    needs_disambiguation = gap < gap_threshold
    return confidence, needs_disambiguation
