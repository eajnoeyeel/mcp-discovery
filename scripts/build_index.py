"""CLI script for building the Qdrant vector index from crawled data.

Usage:
    uv run scripts/build_index.py
    uv run scripts/build_index.py --input data/raw/servers.jsonl
    uv run scripts/build_index.py --pool-size 50     # max tools to index
    uv run scripts/build_index.py --batch-size 100   # embedding batch size
"""

import argparse
import asyncio
from pathlib import Path

# Add src/ to path so we can import project modules
from loguru import logger
from qdrant_client import AsyncQdrantClient

from mcp_discovery.config import Settings
from mcp_discovery.data.crawler import SmitheryCrawler
from mcp_discovery.data.indexer import ToolIndexer
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder
from mcp_discovery.models import MCPTool
from mcp_discovery.retrieval.qdrant_store import QdrantStore

SERVER_COLLECTION = "mcp_servers"


async def main(args: argparse.Namespace) -> None:
    settings = Settings()

    # Load servers
    input_path = Path(args.input)
    servers = SmitheryCrawler.load(input_path)
    logger.info(f"Loaded {len(servers)} servers from {input_path}")

    # Flatten tools
    tools: list[MCPTool] = []
    no_desc_count = 0
    for server in servers:
        for tool in server.tools:
            if tool.description is None:
                no_desc_count += 1
                logger.warning(f"Tool without description: {tool.tool_id}")
            tools.append(tool)
    logger.info(f"Total tools: {len(tools)} ({no_desc_count} without description)")

    if not tools:
        logger.warning("No tools to index. Exiting.")
        return

    # Truncate to pool_size if specified
    if args.pool_size and args.pool_size < len(tools):
        logger.info(f"Truncating to --pool-size={args.pool_size} tools")
        tools = tools[: args.pool_size]
        # Sync servers to only those with tools in the truncated pool
        pool_server_ids = {t.server_id for t in tools}
        servers = [s for s in servers if s.server_id in pool_server_ids]
        logger.info(f"Server pool synced to {len(servers)} servers (matching tool pool)")

    # Validate required API key
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is required for embedding. Set it in .env")
        raise SystemExit(1)

    # Setup components
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )
    qdrant_client = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
    )
    try:
        # --- Tool index ---
        tool_store = QdrantStore(
            client=qdrant_client, collection_name=settings.qdrant_collection_name
        )
        await tool_store.ensure_collection(dimension=settings.embedding_dimension)
        indexer = ToolIndexer(embedder=embedder, store=tool_store)
        count = await indexer.index_tools(tools, batch_size=args.batch_size)
        logger.info(f"Tool index: Indexed {count} tools from {len(servers)} servers")

        # --- Server index ---
        server_store = QdrantStore(client=qdrant_client, collection_name=SERVER_COLLECTION)
        await server_store.ensure_collection(dimension=settings.embedding_dimension)
        server_texts = [server_store.build_server_text(s) for s in servers]
        server_vectors = await embedder.embed_batch(server_texts)
        await server_store.upsert_servers(servers, server_vectors)
        logger.info(f"Server index: Indexed {len(servers)} servers")

        logger.info(f"Done: Indexed {count} tools + {len(servers)} servers")
    finally:
        await qdrant_client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Qdrant vector index from crawled data")
    parser.add_argument("--input", type=str, default="data/raw/servers.jsonl")
    parser.add_argument("--pool-size", type=int, default=None, help="Max number of tools to index")
    parser.add_argument("--batch-size", type=int, default=50, help="Embedding API batch size")
    args = parser.parse_args()
    asyncio.run(main(args))
