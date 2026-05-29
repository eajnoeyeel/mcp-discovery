"""ParallelStrategy -- 2-Layer parallel search + RRF fusion."""

import asyncio

import numpy as np
from loguru import logger
from qdrant_client.models import FieldCondition, Filter, MatchAny

from mcp_discovery.embedding.base import Embedder
from mcp_discovery.models import SearchResult
from mcp_discovery.pipeline.strategy import PipelineStrategy, StrategyRegistry
from mcp_discovery.reranking.base import Reranker
from mcp_discovery.retrieval.hybrid import reciprocal_rank_fusion
from mcp_discovery.retrieval.qdrant_store import QdrantStore


@StrategyRegistry.register("parallel")
class ParallelStrategy(PipelineStrategy):
    """2-layer pipeline: parallel server + tool search -> RRF fusion.

    Unlike SequentialStrategy which hard-gates on server results,
    ParallelStrategy searches both indexes simultaneously and
    fuses with RRF -- robust to Layer 1 server misses.

        Flow:
            1. Embed query
            2. asyncio.gather: tool_store.search (unfiltered) + server_store.search_server_ids
            3. If candidate servers exist, run a second tool search constrained to that server set
            4. Build two ranked lists:
               - List A: all tool results by score (unfiltered)
               - List B: tool results retrieved from candidate servers
            5. RRF fusion -> top_k results
    """

    def __init__(
        self,
        embedder: Embedder,
        tool_store: QdrantStore,
        server_store: QdrantStore,
        top_k_servers: int = 5,
        rrf_k: int = 60,
        reranker: Reranker | None = None,
    ) -> None:
        self.embedder = embedder
        self.tool_store = tool_store
        self.server_store = server_store
        self.top_k_servers = top_k_servers
        self.rrf_k = rrf_k
        self.reranker = reranker

    async def search(self, query: str, top_k: int) -> list[SearchResult]:
        """Execute parallel 2-Layer retrieval with RRF fusion.

        Args:
            query: Natural language query.
            top_k: Number of final results to return.

        Returns:
            Top-k SearchResults fused from parallel server + tool search.
        """
        if top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")
        logger.info(f"ParallelStrategy.search: query='{query[:60]}', top_k={top_k}")

        # Step 1: Embed query
        query_vector: np.ndarray = await self.embedder.embed_one(query)

        # Step 2: Parallel search
        candidate_k = top_k * 2
        tool_results, candidate_server_ids = await asyncio.gather(
            self.tool_store.search(
                query_vector=query_vector,
                top_k=candidate_k,
                server_id_filter=None,
            ),
            self.server_store.search_server_ids(query_vector, top_k=self.top_k_servers),
        )
        logger.debug(
            f"Parallel search: {len(tool_results)} tools, "
            f"{len(candidate_server_ids)} candidate servers"
        )

        if not tool_results:
            return []

        server_tool_results: list[SearchResult] = []
        if candidate_server_ids:
            server_tool_results = await self.tool_store.search(
                query_vector=query_vector,
                top_k=candidate_k,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="server_id",
                            match=MatchAny(any=candidate_server_ids),
                        )
                    ]
                ),
            )

        # Step 3: Build ranked lists for RRF
        # List A: all tool results ordered by score (already sorted from Qdrant)
        list_a = [r.tool.tool_id for r in tool_results]

        # List B: candidate-server tool results ordered by score
        list_b = [r.tool.tool_id for r in server_tool_results]

        # Step 4: RRF fusion
        fused = reciprocal_rank_fusion([list_a, list_b], k=self.rrf_k)

        # Step 5: Reconstruct SearchResults
        tool_map = {r.tool.tool_id: r.tool for r in tool_results}
        tool_map.update({r.tool.tool_id: r.tool for r in server_tool_results})
        results = [
            SearchResult(tool=tool_map[tool_id], score=rrf_score, rank=i + 1)
            for i, (tool_id, rrf_score) in enumerate(fused[:top_k])
        ]
        logger.debug(f"RRF fusion: {len(fused)} unique tools -> top {len(results)}")
        if self.reranker is not None:
            results = await self.reranker.rerank(query, results, top_k)
        return results
