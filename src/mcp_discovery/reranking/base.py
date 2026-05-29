"""Reranker abstract base class."""

from abc import ABC, abstractmethod

from mcp_discovery.models import SearchResult


class Reranker(ABC):
    """ABC for reranking search results."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int = 3,
    ) -> list[SearchResult]:
        """Rerank search results and return top_k.

        Args:
            query: Original search query
            results: Initial search results from embedding search
            top_k: Number of results to return after reranking

        Returns:
            Reranked and truncated list of SearchResult
        """
        ...
