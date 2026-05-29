"""Offline search simulation — rank lookup from pre-computed results.

Pure functions. No external API calls (Qdrant, Cohere, OpenAI).
Works entirely with pre-computed search result lists.

Use case: Provider asks "If someone searches X, where does my tool rank?"
"""

from __future__ import annotations


def simulate_search_rank(
    tool_id: str,
    precomputed_results: list[dict],
) -> int | None:
    """Find the 1-based rank of a tool in a pre-computed result list.

    Results are assumed to be sorted by descending score already.

    Args:
        tool_id: The tool to look up (e.g. "github::search_repositories").
        precomputed_results: List of dicts with at least "tool_id" and "score",
                             ordered by score descending.

    Returns:
        1-based rank if the tool appears, None otherwise.
    """
    for idx, result in enumerate(precomputed_results):
        if result.get("tool_id") == tool_id:
            return idx + 1
    return None


def build_simulation_report(
    tool_id: str,
    query_results: dict[str, list[dict]],
) -> dict:
    """Build a multi-query simulation report for a single tool.

    Answers: across N benchmark queries, how often and at what rank does
    this tool appear?

    Args:
        tool_id: The tool to analyze.
        query_results: Mapping from query string to pre-computed ranked results.
                       Each value is a list of {"tool_id": ..., "score": ...}
                       sorted by score descending.

    Returns:
        Report dict with:
        - tool_id: the analyzed tool
        - total_queries: how many queries in the benchmark
        - appeared_in: how many queries the tool appeared in results
        - rank_1_count: how many times the tool was the top result
        - avg_rank: average rank across queries where it appeared (None if never)
        - ranks: list of (query, rank) pairs for transparency
    """
    total_queries = len(query_results)
    ranks: list[tuple[str, int]] = []

    for query, results in query_results.items():
        rank = simulate_search_rank(tool_id, results)
        if rank is not None:
            ranks.append((query, rank))

    appeared_in = len(ranks)
    rank_1_count = sum(1 for _, r in ranks if r == 1)
    avg_rank: float | None = None
    if ranks:
        avg_rank = round(sum(r for _, r in ranks) / len(ranks), 4)

    return {
        "tool_id": tool_id,
        "total_queries": total_queries,
        "appeared_in": appeared_in,
        "rank_1_count": rank_1_count,
        "avg_rank": avg_rank,
        "ranks": ranks,
    }
