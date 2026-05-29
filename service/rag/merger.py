"""Merge and deduplicate search results from multiple sources."""

from mcp_discovery.models import SearchResult


class ResultMerger:
    """Merges primary (semantic) and fallback (lexical) search results."""

    @staticmethod
    def merge_candidates(*sources: list[SearchResult]) -> list[SearchResult]:
        """Merge all candidate sources without truncating before rerank."""
        seen: dict[str, SearchResult] = {}
        for source in sources:
            for result in source:
                tool_id = result.tool.tool_id
                if tool_id not in seen or result.score > seen[tool_id].score:
                    seen[tool_id] = result

        ranked = sorted(seen.values(), key=lambda item: item.score, reverse=True)
        return [item.model_copy(update={"rank": idx + 1}) for idx, item in enumerate(ranked)]

    @staticmethod
    def truncate_and_reassign(results: list[SearchResult], top_k: int) -> list[SearchResult]:
        if top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")
        truncated = results[:top_k]
        return [item.model_copy(update={"rank": idx + 1}) for idx, item in enumerate(truncated)]

    @classmethod
    def merge_and_deduplicate(
        cls,
        primary: list[SearchResult],
        fallback: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        candidates = cls.merge_candidates(primary, fallback)
        return cls.truncate_and_reassign(candidates, top_k)
