"""CLI script for building the Qdrant hybrid vector index from MCP-Zero data.

Loads MCP-Zero tools from JSONL, merges enriched descriptions, then generates
dense (OpenAI text-embedding-3-large, 3072d) + sparse (FastEmbed SPLADE) embeddings
and upserts into a named-vector hybrid Qdrant collection.

Usage:
    uv run scripts/build_hybrid_index.py
    uv run scripts/build_hybrid_index.py --input data/raw/mcp_zero_servers.jsonl
    uv run scripts/build_hybrid_index.py --enriched data/enriched/tool_profiles.jsonl
    uv run scripts/build_hybrid_index.py --collection mcp_tools_hybrid
    uv run scripts/build_hybrid_index.py --batch-size 50
    uv run scripts/build_hybrid_index.py --target staging
    uv run scripts/build_hybrid_index.py --target prod --collection mcp_tools_hybrid_prod
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add src/ to path so we can import project modules
from loguru import logger
from qdrant_client import AsyncQdrantClient

from mcp_discovery.config import Settings
from mcp_discovery.embedding.fastembed_sparse import FastEmbedSparseEmbedder
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder
from mcp_discovery.models import MCPTool
from mcp_discovery.retrieval.qdrant_store import QdrantStore

_DENSE_DIMENSION = 3072
_DENSE_MODEL = "text-embedding-3-large"


def get_qdrant_config(target: str) -> tuple[str, str]:
    """Return (qdrant_url, qdrant_api_key) for the given target environment."""
    if target == "prod":
        return os.environ["PROD_QDRANT_URL"], os.environ["PROD_QDRANT_API_KEY"]
    elif target == "staging":
        return os.environ["STAGING_QDRANT_URL"], os.environ["STAGING_QDRANT_API_KEY"]
    else:
        return (
            os.environ.get("QDRANT_URL", "http://localhost:6333"),
            os.environ.get("QDRANT_API_KEY", ""),
        )


def load_tools_from_jsonl(input_path: Path) -> list[MCPTool]:
    """Load MCPTool objects from a JSONL file where each line is a server with tools array.

    Each server line contains a 'tools' array. Each tool entry has:
        server_id, tool_name, tool_id, description, input_schema
    """
    tools: list[MCPTool] = []
    no_desc_count = 0

    with input_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(f"Line {line_num}: JSON parse error — {e}")
                continue

            raw_tools = record.get("tools") or []
            for tool_dict in raw_tools:
                try:
                    tool = MCPTool(
                        tool_id=tool_dict["tool_id"],
                        server_id=tool_dict["server_id"],
                        tool_name=tool_dict["tool_name"],
                        description=tool_dict.get("description"),
                        input_schema=tool_dict.get("input_schema"),
                    )
                except (KeyError, Exception) as e:
                    logger.warning(f"Line {line_num}: skipping tool — {e}")
                    continue

                if not tool.description:
                    no_desc_count += 1
                tools.append(tool)

    logger.info(
        f"Loaded {len(tools)} tools from {input_path} ({no_desc_count} without description)"
    )
    return tools


def load_enriched_texts(enriched_path: Path) -> dict[str, str]:
    """Load enriched descriptions keyed by tool_id.

    Each JSONL line: {"tool_id": "...", "enriched_text": "..."}
    """
    enriched: dict[str, str] = {}

    if not enriched_path.exists():
        logger.warning(f"Enriched file not found: {enriched_path} — sparse will use original text")
        return enriched

    with enriched_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                tool_id = record["tool_id"]
                enriched_text = record["enriched_text"]
                enriched[tool_id] = enriched_text
            except (KeyError, json.JSONDecodeError) as e:
                logger.warning(f"Enriched line {line_num}: parse error — {e}")
                continue

    logger.info(f"Loaded {len(enriched)} enriched descriptions from {enriched_path}")
    return enriched


async def main(args: argparse.Namespace) -> None:
    settings = Settings()

    # Validate required API key
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is required for dense embedding. Set it in .env")
        raise SystemExit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        raise SystemExit(1)

    enriched_path = Path(args.enriched)

    # Load tools
    tools = load_tools_from_jsonl(input_path)
    if not tools:
        logger.warning("No tools loaded. Exiting.")
        return

    # Load enriched descriptions (sparse text source)
    enriched_map = load_enriched_texts(enriched_path)

    # Build text lists
    # Dense: original tool text (tool_name: description)
    dense_texts = [QdrantStore.build_tool_text(tool) for tool in tools]
    # Sparse: enriched text if available, else fall back to original tool text
    sparse_texts = [
        enriched_map.get(tool.tool_id, QdrantStore.build_tool_text(tool)) for tool in tools
    ]

    fallback_count = sum(1 for tool in tools if tool.tool_id not in enriched_map)
    if fallback_count:
        logger.info(
            f"{fallback_count}/{len(tools)} tools using original text for sparse "
            "(no enriched_text found)"
        )

    # Setup embedders
    logger.info(f"Initializing dense embedder: {_DENSE_MODEL} (dim={_DENSE_DIMENSION})")
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=_DENSE_MODEL,
        dimension=_DENSE_DIMENSION,
    )

    logger.info("Initializing sparse embedder (FastEmbed SPLADE)")
    sparse_embedder = FastEmbedSparseEmbedder()

    # Setup Qdrant — resolve URL and key from --target flag
    qdrant_url, qdrant_key = get_qdrant_config(args.target)
    logger.info(f"Qdrant target: {args.target} → {qdrant_url[:40]}...")
    qdrant_client = AsyncQdrantClient(
        url=qdrant_url,
        api_key=qdrant_key or None,
    )

    try:
        store = QdrantStore(client=qdrant_client, collection_name=args.collection)
        await store.ensure_hybrid_collection(dense_dimension=_DENSE_DIMENSION)

        total_tools = len(tools)
        total_upserted = 0
        batch_size = args.batch_size

        for batch_start in range(0, total_tools, batch_size):
            batch_end = min(batch_start + batch_size, total_tools)
            batch_tools = tools[batch_start:batch_end]
            batch_dense_texts = dense_texts[batch_start:batch_end]
            batch_sparse_texts = sparse_texts[batch_start:batch_end]

            logger.info(
                f"Processing batch {batch_start // batch_size + 1} "
                f"[{batch_start + 1}–{batch_end}/{total_tools}]"
            )

            # Dense embedding (async, OpenAI API)
            batch_dense_vectors = await embedder.embed_batch(batch_dense_texts)

            # Sparse embedding (sync, local SPLADE model)
            batch_sparse_vectors = sparse_embedder.embed_batch(batch_sparse_texts)

            await store.upsert_tools_hybrid(batch_tools, batch_dense_vectors, batch_sparse_vectors)
            total_upserted += len(batch_tools)
            logger.info(f"Progress: {total_upserted}/{total_tools} tools upserted")

        logger.info(
            f"Done: Indexed {total_upserted} tools into '{args.collection}' "
            f"(dense={_DENSE_MODEL} {_DENSE_DIMENSION}d, sparse=SPLADE)"
        )
    finally:
        await qdrant_client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build Qdrant hybrid index (dense + sparse) from MCP-Zero JSONL"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="data/raw/mcp_zero_servers.jsonl",
        help="Path to MCP-Zero servers JSONL file",
    )
    parser.add_argument(
        "--enriched",
        type=str,
        default="data/enriched/tool_profiles.jsonl",
        help="Path to enriched tool profiles JSONL (tool_id → enriched_text)",
    )
    parser.add_argument(
        "--target",
        choices=["local", "staging", "prod"],
        default="local",
        help="Qdrant target environment — selects env vars (local/staging/prod)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="mcp_tools_hybrid",
        help="Qdrant collection name for hybrid index",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of tools per embedding batch",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
