"""Incremental Qdrant indexing for expanded 320-server pool + E4 enriched collection.

Three steps:
1. Add new tools to `mcp_tools` (incremental — only tools not already indexed)
2. Add new servers to `mcp_servers` (incremental — only servers not already indexed)
3. Rebuild `mcp_tools_e4_enriched` from updated `mcp_tools` + 94 enriched descriptions

Minimizes embedding API calls by scrolling existing collections and computing diffs.

Usage:
    PYTHONPATH=src uv run python scripts/index_enriched.py
    PYTHONPATH=src uv run python scripts/index_enriched.py --dry-run
"""

import argparse
import asyncio
import json
from pathlib import Path

# Add src/ to path so we can import project modules
from dotenv import load_dotenv
from loguru import logger
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct

from mcp_discovery.config import Settings
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder
from mcp_discovery.models import MCPServer, MCPTool
from mcp_discovery.retrieval.qdrant_store import QdrantStore

# Collection names
TOOLS_COLLECTION = "mcp_tools"
SERVERS_COLLECTION = "mcp_servers"
ENRICHED_COLLECTION = "mcp_tools_e4_enriched"

# Data paths
BASE_POOL_PATH = Path("data/tool-pools/base_pool.json")
RAW_DATA_FILES = [
    Path("data/raw/mcp_zero_servers.jsonl"),
    Path("data/raw/servers.jsonl"),
    Path("data/raw/atlas_gist_servers.jsonl"),
    Path("data/raw/smithery_atlas_servers.jsonl"),
]
ENRICHED_DATA_PATH = Path("data/e4/enriched_descriptions.jsonl")

SCROLL_BATCH_SIZE = 100
EMBED_BATCH_SIZE = 50


def load_pool_server_ids() -> list[str]:
    """Load 320-server pool from base_pool.json."""
    if not BASE_POOL_PATH.exists():
        raise FileNotFoundError(
            f"base_pool.json not found at {BASE_POOL_PATH}. "
            "Run: uv run python scripts/build_base_pool.py"
        )
    pool: list[str] = json.loads(BASE_POOL_PATH.read_text())
    logger.info(f"Loaded {len(pool)}-server pool from {BASE_POOL_PATH}")
    return pool


def load_raw_servers(pool_server_ids: set[str]) -> list[MCPServer]:
    """Load MCPServer objects from all raw data files, filtered to pool.

    Merges tools across files: if the same server_id appears in multiple files,
    tools are unioned (deduplicated by tool_id). This is needed because some
    servers (e.g. github, gmail, slack) have different tool sets in different
    raw data files (mcp_zero vs servers.jsonl vs smithery_atlas_servers.jsonl).
    """
    # Accumulate per-server: metadata from first occurrence, tools merged
    server_meta: dict[str, dict] = {}  # server_id -> {name, description, homepage}
    server_tools: dict[str, dict[str, MCPTool]] = {}  # server_id -> {tool_id: MCPTool}

    for raw_path in RAW_DATA_FILES:
        if not raw_path.exists():
            logger.warning(f"Raw data file not found, skipping: {raw_path}")
            continue

        new_servers = 0
        new_tools = 0
        with raw_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                sid = data["server_id"]
                if sid not in pool_server_ids:
                    continue

                # First occurrence sets metadata
                if sid not in server_meta:
                    server_meta[sid] = {
                        "name": data.get("name", sid),
                        "description": data.get("description"),
                        "homepage": data.get("homepage"),
                    }
                    server_tools[sid] = {}
                    new_servers += 1

                # Merge tools (new tool_ids only)
                for t in data.get("tools", []):
                    tid = t["tool_id"]
                    if tid not in server_tools[sid]:
                        server_tools[sid][tid] = MCPTool(
                            server_id=t["server_id"],
                            tool_name=t["tool_name"],
                            tool_id=tid,
                            description=t.get("description"),
                            input_schema=t.get("input_schema"),
                        )
                        new_tools += 1

        logger.info(f"  {raw_path.name}: {new_servers} new servers, {new_tools} new tools")

    # Build MCPServer list
    servers: list[MCPServer] = []
    for sid, meta in server_meta.items():
        tools = list(server_tools[sid].values())
        server = MCPServer(
            server_id=sid,
            name=meta["name"],
            description=meta["description"],
            homepage=meta["homepage"],
            tools=tools,
        )
        servers.append(server)

    total_tools = sum(len(server_tools[sid]) for sid in server_meta)
    logger.info(f"Total pool: {len(servers)} servers, {total_tools} tools (merged)")
    return servers


def load_enriched_tools(path: Path) -> list[MCPTool]:
    """Load enriched descriptions JSONL and build MCPTool objects."""
    if not path.exists():
        raise FileNotFoundError(f"Enriched descriptions not found: {path}")

    tools: list[MCPTool] = []
    with path.open() as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping invalid JSON at line {line_num}: {e}")
                continue

            tool = MCPTool(
                server_id=entry["server_id"],
                tool_name=entry["tool_name"],
                tool_id=entry["tool_id"],
                description=entry["enriched_description"],
                input_schema=entry.get("input_schema"),
            )
            tools.append(tool)

    logger.info(f"Loaded {len(tools)} enriched tools from {path}")
    return tools


async def scroll_existing_ids(
    client: AsyncQdrantClient,
    collection_name: str,
    id_field: str,
) -> set[str]:
    """Scroll a collection and return all values of the given payload field."""
    existing_ids: set[str] = set()
    offset = None

    while True:
        points, next_offset = await client.scroll(
            collection_name=collection_name,
            limit=SCROLL_BATCH_SIZE,
            with_vectors=False,
            with_payload=True,
            offset=offset,
        )
        if not points:
            break
        for p in points:
            val = p.payload.get(id_field, "") if p.payload else ""
            if val:
                existing_ids.add(val)
        offset = next_offset
        if offset is None:
            break

    logger.info(f"Scrolled {collection_name}: {len(existing_ids)} existing {id_field}s")
    return existing_ids


async def copy_collection_with_vectors(
    client: AsyncQdrantClient,
    source_collection: str,
    target_collection: str,
    *,
    dry_run: bool = False,
) -> int:
    """Scroll all points from source and upsert to target (preserves vectors)."""
    total_copied = 0
    offset = None

    while True:
        points, next_offset = await client.scroll(
            collection_name=source_collection,
            limit=SCROLL_BATCH_SIZE,
            with_vectors=True,
            offset=offset,
        )
        if not points:
            break

        point_structs = [PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points]

        if not dry_run:
            await client.upsert(
                collection_name=target_collection,
                points=point_structs,
            )

        total_copied += len(points)
        logger.info(f"  Copied batch: {len(points)} points (total: {total_copied})")

        offset = next_offset
        if offset is None:
            break

    return total_copied


async def step1_index_new_tools(
    client: AsyncQdrantClient,
    embedder: OpenAIEmbedder,
    all_pool_tools: list[MCPTool],
    dimension: int,
    *,
    dry_run: bool = False,
) -> int:
    """Add new tools to mcp_tools (incremental)."""
    logger.info("=" * 60)
    logger.info("STEP 1: Incremental tool indexing")
    logger.info("=" * 60)

    tool_store = QdrantStore(client=client, collection_name=TOOLS_COLLECTION)
    if not dry_run:
        await tool_store.ensure_collection(dimension=dimension)

    # Scroll existing tool_ids
    existing_tool_ids = await scroll_existing_ids(client, TOOLS_COLLECTION, "tool_id")

    # Find new tools
    new_tools = [t for t in all_pool_tools if t.tool_id not in existing_tool_ids]
    logger.info(
        f"Pool tools: {len(all_pool_tools)}, "
        f"Already indexed: {len(existing_tool_ids)}, "
        f"New: {len(new_tools)}"
    )

    if not new_tools:
        logger.info("No new tools to index. Skipping Step 1.")
        return 0

    # Embed + upsert in batches
    for i in range(0, len(new_tools), EMBED_BATCH_SIZE):
        batch = new_tools[i : i + EMBED_BATCH_SIZE]
        texts = [QdrantStore.build_tool_text(t) for t in batch]
        vectors = await embedder.embed_batch(texts, batch_size=EMBED_BATCH_SIZE)
        if not dry_run:
            await tool_store.upsert_tools(batch, vectors)
        logger.info(
            f"  Indexed tool batch {i // EMBED_BATCH_SIZE + 1}: "
            f"{len(batch)} tools (cumulative: {min(i + EMBED_BATCH_SIZE, len(new_tools))})"
        )

    logger.info(f"Step 1 complete: indexed {len(new_tools)} new tools")
    return len(new_tools)


async def step2_index_new_servers(
    client: AsyncQdrantClient,
    embedder: OpenAIEmbedder,
    all_pool_servers: list[MCPServer],
    dimension: int,
    *,
    dry_run: bool = False,
) -> int:
    """Add new servers to mcp_servers (incremental)."""
    logger.info("=" * 60)
    logger.info("STEP 2: Incremental server indexing")
    logger.info("=" * 60)

    server_store = QdrantStore(client=client, collection_name=SERVERS_COLLECTION)
    if not dry_run:
        await server_store.ensure_collection(dimension=dimension)

    # Scroll existing server_ids
    existing_server_ids = await scroll_existing_ids(client, SERVERS_COLLECTION, "server_id")

    # Find new servers
    new_servers = [s for s in all_pool_servers if s.server_id not in existing_server_ids]
    logger.info(
        f"Pool servers: {len(all_pool_servers)}, "
        f"Already indexed: {len(existing_server_ids)}, "
        f"New: {len(new_servers)}"
    )

    if not new_servers:
        logger.info("No new servers to index. Skipping Step 2.")
        return 0

    # Embed + upsert in batches
    for i in range(0, len(new_servers), EMBED_BATCH_SIZE):
        batch = new_servers[i : i + EMBED_BATCH_SIZE]
        texts = [QdrantStore.build_server_text(s) for s in batch]
        vectors = await embedder.embed_batch(texts, batch_size=EMBED_BATCH_SIZE)
        if not dry_run:
            await server_store.upsert_servers(batch, vectors)
        logger.info(
            f"  Indexed server batch {i // EMBED_BATCH_SIZE + 1}: "
            f"{len(batch)} servers (cumulative: {min(i + EMBED_BATCH_SIZE, len(new_servers))})"
        )

    logger.info(f"Step 2 complete: indexed {len(new_servers)} new servers")
    return len(new_servers)


async def step3_rebuild_enriched(
    client: AsyncQdrantClient,
    embedder: OpenAIEmbedder,
    enriched_tools: list[MCPTool],
    dimension: int,
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Rebuild mcp_tools_e4_enriched from updated mcp_tools + enriched descriptions."""
    logger.info("=" * 60)
    logger.info("STEP 3: Rebuild enriched collection")
    logger.info("=" * 60)

    # Delete existing collection if present
    try:
        collections = await client.get_collections()
        existing_names = [c.name for c in collections.collections]
        if ENRICHED_COLLECTION in existing_names:
            if not dry_run:
                await client.delete_collection(ENRICHED_COLLECTION)
            logger.info(f"Deleted stale collection: {ENRICHED_COLLECTION}")
    except Exception as e:
        logger.warning(f"Could not check/delete existing collection: {e}")

    # Create fresh collection
    enriched_store = QdrantStore(client=client, collection_name=ENRICHED_COLLECTION)
    if not dry_run:
        await enriched_store.ensure_collection(dimension=dimension)

    # Copy all points from mcp_tools (now 3,090) to enriched collection
    logger.info(f"Copying all points from '{TOOLS_COLLECTION}' to '{ENRICHED_COLLECTION}'...")
    copied_count = await copy_collection_with_vectors(
        client,
        TOOLS_COLLECTION,
        ENRICHED_COLLECTION,
        dry_run=dry_run,
    )
    logger.info(f"Copied {copied_count} points from '{TOOLS_COLLECTION}'")

    # Re-embed and upsert enriched tools (overwrites the copied points)
    if enriched_tools:
        logger.info(f"Re-embedding {len(enriched_tools)} enriched tools...")
        texts = [QdrantStore.build_tool_text(t) for t in enriched_tools]
        vectors = await embedder.embed_batch(texts, batch_size=EMBED_BATCH_SIZE)
        if not dry_run:
            await enriched_store.upsert_tools(enriched_tools, vectors)
        logger.info(f"Upserted {len(enriched_tools)} enriched tools (overwriting copied points)")

    logger.info(
        f"Step 3 complete: {ENRICHED_COLLECTION} has "
        f"{copied_count} base + {len(enriched_tools)} re-embedded"
    )
    return copied_count, len(enriched_tools)


async def verify_counts(client: AsyncQdrantClient) -> dict[str, int]:
    """Verify point counts for all three collections."""
    counts: dict[str, int] = {}
    for name in [TOOLS_COLLECTION, SERVERS_COLLECTION, ENRICHED_COLLECTION]:
        try:
            info = await client.get_collection(name)
            counts[name] = info.points_count
        except Exception as e:
            logger.warning(f"Could not get count for {name}: {e}")
            counts[name] = -1
    return counts


async def main(args: argparse.Namespace) -> None:
    load_dotenv()
    settings = Settings()

    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is required. Set it in .env")
        raise SystemExit(1)

    # Load pool
    pool_server_ids = load_pool_server_ids()
    pool_set = set(pool_server_ids)

    # Load raw servers and flatten tools
    all_servers = load_raw_servers(pool_set)
    all_tools: list[MCPTool] = []
    seen_tool_ids: set[str] = set()
    for server in all_servers:
        for tool in server.tools:
            if tool.tool_id not in seen_tool_ids:
                all_tools.append(tool)
                seen_tool_ids.add(tool.tool_id)
    logger.info(f"Pool: {len(all_servers)} servers, {len(all_tools)} unique tools")

    # Load enriched descriptions
    enriched_tools = load_enriched_tools(ENRICHED_DATA_PATH)

    # Setup embedder
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )

    # Setup Qdrant client
    qdrant_client = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
    )

    try:
        # Pre-run counts
        logger.info("--- Pre-run collection counts ---")
        pre_counts = await verify_counts(qdrant_client)
        for name, count in pre_counts.items():
            logger.info(f"  {name}: {count} points")

        # Step 1: Incremental tool indexing
        new_tools_count = await step1_index_new_tools(
            qdrant_client,
            embedder,
            all_tools,
            settings.embedding_dimension,
            dry_run=args.dry_run,
        )

        # Step 2: Incremental server indexing
        new_servers_count = await step2_index_new_servers(
            qdrant_client,
            embedder,
            all_servers,
            settings.embedding_dimension,
            dry_run=args.dry_run,
        )

        # Step 3: Rebuild enriched collection
        copied, enriched = await step3_rebuild_enriched(
            qdrant_client,
            embedder,
            enriched_tools,
            settings.embedding_dimension,
            dry_run=args.dry_run,
        )

        # Post-run verification
        logger.info("--- Post-run collection counts ---")
        post_counts = await verify_counts(qdrant_client)
        for name, count in post_counts.items():
            logger.info(f"  {name}: {count} points")

        # Summary
        logger.info("=" * 60)
        logger.info("INDEXING SUMMARY")
        logger.info("=" * 60)
        logger.info(f"  Step 1 — New tools indexed:      {new_tools_count}")
        logger.info(f"  Step 2 — New servers indexed:     {new_servers_count}")
        logger.info(f"  Step 3 — Enriched collection:     {copied} copied + {enriched} re-embedded")
        logger.info(f"  Dry run:                          {args.dry_run}")
        logger.info(f"  Embedding model:                  {settings.embedding_model}")
        logger.info(f"  Embedding dimension:              {settings.embedding_dimension}")
        for name in [TOOLS_COLLECTION, SERVERS_COLLECTION, ENRICHED_COLLECTION]:
            pre = pre_counts.get(name, "?")
            post = post_counts.get(name, "?")
            logger.info(f"  {name}: {pre} → {post}")
        logger.info("=" * 60)

    finally:
        await qdrant_client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=("Incremental Qdrant indexing for 320-server pool + E4 enriched collection"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview operations without writing to Qdrant",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
