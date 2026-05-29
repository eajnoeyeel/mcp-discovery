"""Cohere Rerank 3 implementation."""

import asyncio
import time

from loguru import logger

from mcp_discovery.models import SearchResult
from mcp_discovery.reranking.base import Reranker

try:  # pragma: no cover - exercised through optional dependency tests
    import cohere
except ImportError:  # pragma: no cover
    cohere = None


class CohereReranker(Reranker):
    """Legacy experiment reranker using Cohere Rerank API.

    The hosted/public portfolio runtime does not require Cohere. This class is
    retained for historical experiment reproducibility only and requires the
    optional ``cohere`` package when instantiated.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "rerank-v3.5",
        max_rpm: int = 10,
    ) -> None:
        if cohere is None:
            raise RuntimeError(
                "CohereReranker is a legacy optional experiment component. "
                "Install the 'cohere' package separately to reproduce old reranking runs."
            )
        self._client = cohere.AsyncClientV2(api_key=api_key)
        self._model = model
        self._max_rpm = max_rpm
        self._min_interval = 60.0 / max_rpm if max_rpm > 0 else 0.0
        self._last_call_time = 0.0
        logger.info(f"CohereReranker initialized with model={model!r}, max_rpm={max_rpm}")

    @property
    def model(self) -> str:
        return self._model

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int = 3,
    ) -> list[SearchResult]:
        """Rerank search results using Cohere Rerank API.

        Args:
            query: Original search query
            results: Initial search results from embedding search
            top_k: Number of results to return after reranking

        Returns:
            Reranked and truncated list of SearchResult
        """
        if not results:
            return []

        documents = [
            f"{r.tool.tool_name}: {r.tool.selection_description or r.tool.description or ''}"
            for r in results
        ]

        # Rate limiting: wait if we're calling too fast
        if self._min_interval > 0:
            now = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call_time = time.monotonic()

        try:
            response = await self._client.rerank(
                model=self._model,
                query=query,
                documents=documents,
                top_n=top_k,
            )
        except Exception as e:
            logger.warning(f"Cohere rerank failed, returning original results: {e}")
            return _fallback_truncate(results, top_k)

        reranked: list[SearchResult] = []
        for rank, item in enumerate(response.results, start=1):
            original = results[item.index]
            reranked.append(
                SearchResult(
                    tool=original.tool,
                    score=item.relevance_score,
                    rank=rank,
                    reason=original.reason,
                )
            )

        return reranked


def _fallback_truncate(results: list[SearchResult], top_k: int) -> list[SearchResult]:
    """Return original results truncated to top_k with ranks preserved."""
    truncated = results[:top_k]
    return [
        SearchResult(
            tool=r.tool,
            score=r.score,
            rank=i + 1,
            reason=r.reason,
        )
        for i, r in enumerate(truncated)
    ]
