"""Thin index service wrapper around embedder and Qdrant store."""

from loguru import logger

from mcp_discovery.indexing.enrichment import (
    compute_enrichment_hash,
    enrich_tool,
    rule_based_sparse_input,
)
from mcp_discovery.models import MCPTool
from mcp_discovery.retrieval.qdrant_store import QdrantStore
from service.shared.content_hash import compute_content_hash


class IndexService:
    def __init__(
        self,
        embedder,
        qdrant_store,
        sparse_embedder=None,
        llm_client=None,
        enrichment_cache=None,
        max_llm_retries: int = 2,
        enrichment_disabled: bool = False,
    ):
        self._embedder = embedder
        self._qdrant_store = qdrant_store
        self.sparse_embedder = sparse_embedder
        self.llm_client = llm_client
        self.enrichment_cache = enrichment_cache
        self.max_llm_retries = max_llm_retries
        self.enrichment_disabled = enrichment_disabled

    async def split_rows_by_content_hash(self, rows: list[dict]) -> tuple[list[dict], list[str]]:
        if not rows:
            return [], []

        existing_payloads = await self._qdrant_store.fetch_tool_payloads(
            [row["tool_id"] for row in rows]
        )
        rows_to_index: list[dict] = []
        skipped_tool_ids: list[str] = []

        for row in rows:
            incoming_hash = row.get("content_hash") or compute_content_hash(
                row["tool_name"], row.get("description")
            )
            existing_payload = existing_payloads.get(row["tool_id"])
            if existing_payload:
                existing_hash = compute_content_hash(
                    existing_payload["tool_name"], existing_payload.get("description")
                )
                if existing_hash == incoming_hash:
                    skipped_tool_ids.append(row["tool_id"])
                    continue
            rows_to_index.append(row)

        return rows_to_index, skipped_tool_ids

    async def index_rows(self, rows: list[dict]) -> int:
        if self.sparse_embedder is None:
            logger.warning(
                "IndexService.index_rows without sparse_embedder — writing "
                "dense-only points breaks the hybrid retrieval invariant. "
                "Production callers must inject a sparse_embedder."
            )
        tools = [MCPTool(**row) for row in rows]
        builder = getattr(self._qdrant_store, "build_tool_text", None)
        if callable(builder):
            texts = [builder(tool) for tool in tools]
        else:
            texts = [QdrantStore.build_tool_text(tool) for tool in tools]
        dense_vectors = await self._embedder.embed_batch(texts)

        if self.sparse_embedder is not None:
            sparse_vectors = []
            extra_payloads = []
            for tool in tools:
                hash_key = compute_enrichment_hash(tool)
                cached = (
                    await self.enrichment_cache.get(hash_key) if self.enrichment_cache else None
                )
                if cached:
                    sparse_input = cached["sparse_input"]
                    source = "keyword_llm_cached"
                elif not self.enrichment_disabled and self.llm_client:
                    try:
                        enriched = await enrich_tool(tool, self.llm_client)
                        sparse_input = enriched.sparse_input
                        source = "keyword_llm"
                        if self.enrichment_cache:
                            await self.enrichment_cache.put(
                                hash_key, tool_id=tool.tool_id, enriched=enriched
                            )
                    except Exception:
                        sparse_input = rule_based_sparse_input(tool)
                        source = "rule_based"
                else:
                    sparse_input = rule_based_sparse_input(tool)
                    source = "rule_based"
                sv = self.sparse_embedder.embed_one(sparse_input)
                sparse_vectors.append(sv)
                extra_payloads.append({"sparse_source": source, "enrichment_hash": hash_key})
            await self._qdrant_store.upsert_tools_hybrid(
                tools, dense_vectors, sparse_vectors, extra_payloads=extra_payloads
            )
        else:
            await self._qdrant_store.upsert_tools(tools, dense_vectors)

        return len(tools)

    async def index_server(self, server_id: str, *, db) -> dict:
        """Fetch pending tools, embed, upsert to Qdrant, mark indexed.

        Coordinates the full index lifecycle using the provided DB adapter.
        Returns dict with server_id and indexed_count.
        """
        rows = await db.fetch_pending_tools(server_id)
        if not rows:
            return {"server_id": server_id, "indexed_count": 0, "skipped_count": 0}

        rows_to_index, skipped_tool_ids = await self.split_rows_by_content_hash(rows)
        indexed_count = 0
        indexed_tool_ids: list[str] = []
        if rows_to_index:
            indexed_count = await self.index_rows(rows_to_index)
            indexed_tool_ids = [row["tool_id"] for row in rows_to_index]

        processed_tool_ids = indexed_tool_ids + skipped_tool_ids
        if processed_tool_ids:
            await db.mark_indexed(processed_tool_ids)

        return {
            "server_id": server_id,
            "indexed_count": indexed_count,
            "skipped_count": len(skipped_tool_ids),
        }
