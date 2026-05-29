"""FlatStrategy — 1-Layer direct tool search (E0 baseline)."""

import asyncio

from loguru import logger

from mcp_discovery.embedding.base import Embedder
from mcp_discovery.embedding.sparse_embedder import SparseEmbedder
from mcp_discovery.models import SearchResult
from mcp_discovery.pipeline.strategy import PipelineStrategy, StrategyRegistry
from mcp_discovery.reranking.base import Reranker
from mcp_discovery.retrieval.qdrant_store import QdrantStore


@StrategyRegistry.register("flat")
class FlatStrategy(PipelineStrategy):
    """1-Layer pipeline: embed query -> search tool index directly.

    Supports hybrid search when sparse_embedder is provided.
    """

    def __init__(
        self,
        embedder: Embedder,
        tool_store: QdrantStore,
        reranker: Reranker | None = None,
        sparse_embedder: SparseEmbedder | None = None,
    ) -> None:
        self.embedder = embedder
        self.tool_store = tool_store
        self.reranker = reranker
        self.sparse_embedder = sparse_embedder

    async def search(self, query: str, top_k: int) -> list[SearchResult]:
        """Search all tools directly without server-level filtering.

        Uses hybrid search (dense + sparse RRF) when sparse_embedder is available,
        otherwise falls back to dense-only search.
        """
        if top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")
        logger.info(f"FlatStrategy.search: query='{query[:60]}', top_k={top_k}")

        if self.sparse_embedder is not None:
            dense_task = asyncio.create_task(self.embedder.embed_one(query))
            sparse_task = asyncio.create_task(
                asyncio.to_thread(self.sparse_embedder.embed_one, query)
            )
            query_vector, sparse_vector = await asyncio.gather(dense_task, sparse_task)
            results = await self.tool_store.hybrid_search(
                dense_vector=query_vector,
                sparse_vector=sparse_vector,
                top_k=top_k,
                prefetch_limit=max(20, top_k * 3),
            )
        else:
            query_vector = await self.embedder.embed_one(query)
            results = await self.tool_store.search(
                query_vector=query_vector,
                top_k=top_k,
                server_id_filter=None,
            )

        if self.reranker is not None:
            results = await self.reranker.rerank(query, results, top_k)
        logger.info(f"FlatStrategy: {len(results)} results returned")
        return results
