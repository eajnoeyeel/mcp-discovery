"""Batch embed + upsert orchestrator."""

from loguru import logger

from mcp_discovery.embedding.base import Embedder
from mcp_discovery.models import MCPTool
from mcp_discovery.retrieval.qdrant_store import QdrantStore


class ToolIndexer:
    """Orchestrates embedding and upserting tools to Qdrant."""

    def __init__(self, embedder: Embedder, store: QdrantStore) -> None:
        self.embedder = embedder
        self.store = store

    async def index_tools(self, tools: list[MCPTool], batch_size: int = 50) -> int:
        if not tools:
            return 0

        for i in range(0, len(tools), batch_size):
            batch = tools[i : i + batch_size]
            texts = [QdrantStore.build_tool_text(tool) for tool in batch]
            vectors = await self.embedder.embed_batch(texts, batch_size=batch_size)
            await self.store.upsert_tools(batch, vectors)
            logger.info(f"Indexed batch {i // batch_size + 1}: {len(batch)} tools")

        logger.info(f"Indexing complete: {len(tools)} tools")
        return len(tools)
