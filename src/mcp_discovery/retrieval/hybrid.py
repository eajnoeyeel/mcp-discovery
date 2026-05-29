"""Reciprocal Rank Fusion for multi-list score aggregation."""

from collections import defaultdict


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion across multiple ranked lists.

    score(item) = sum over lists: 1 / (k + rank)
    rank is 1-indexed (index 0 = rank 1).

    Args:
        ranked_lists: Each inner list is a sequence of item IDs
            ordered by relevance (index 0 = most relevant).
        k: RRF constant (default 60, from original paper).

    Returns:
        List of (item_id, rrf_score) tuples sorted descending by score.
    """
    scores: dict[str, float] = defaultdict(float)
    for ranked_list in ranked_lists:
        for rank_0, item_id in enumerate(ranked_list):
            rank = rank_0 + 1  # 1-indexed
            scores[item_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
