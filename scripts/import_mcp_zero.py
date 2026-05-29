"""Import MCP-Zero dataset → MCPServer/MCPTool models + optional Qdrant indexing.

Reads MCP-Zero JSON (308 servers, 2,797 tools), converts to our MCPServer/MCPTool
Pydantic models, and optionally indexes them into Qdrant with pre-computed
text-embedding-3-large (3072-dim) vectors.

MCP-Zero server entry fields:
    - name: string
    - summary: string
    - description: string
    - url: string
    - readme_file: string
    - description_embedding: float[3072]
    - summary_embedding: float[3072]
    - tools: array of tool objects

MCP-Zero tool fields:
    - name: string
    - description: string
    - description_embedding: float[3072]
    - parameter: {"param_name": "(type) description"} format

Usage:
    uv run python scripts/import_mcp_zero.py
    uv run python scripts/import_mcp_zero.py --input data/external/mcp-zero/servers.json
    uv run python scripts/import_mcp_zero.py --index  # Also upsert to Qdrant
    uv run python scripts/import_mcp_zero.py --index --index-servers  # Index both
    uv run python scripts/import_mcp_zero.py --index-servers          # Servers only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# Add project root to path so we can import src.* modules
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))

import numpy as np
from loguru import logger
from mcp_discovery.models import TOOL_ID_SEPARATOR, MCPServer, MCPTool
from mcp_discovery.retrieval.qdrant_store import QdrantStore

# Default paths
DEFAULT_INPUT = "data/external/mcp-zero/servers.json"
DEFAULT_OUTPUT = "data/raw/mcp_zero_servers.jsonl"

# MCP-Zero uses text-embedding-3-large (3072-dim)
MCP_ZERO_EMBEDDING_DIM = 3072

# Known JSON Schema types
_KNOWN_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object"})

# Regex to extract "(type) description" from MCP-Zero parameter values
_PARAM_TYPE_RE = re.compile(r"^\((\w+)\)\s*(.*)", re.DOTALL)


def parse_parameter_schema(params: dict | None) -> dict | None:
    """Convert MCP-Zero parameter format to standard JSON Schema.

    MCP-Zero format:  {"param_name": "(type) description"}
    Output format:    {"type": "object", "properties": {"param_name": {...}}}

    Args:
        params: MCP-Zero parameter dict, or None.

    Returns:
        JSON Schema dict, or None if params is empty/None.
    """
    if not params:
        return None

    properties: dict = {}
    for param_name, param_value in params.items():
        param_value = str(param_value).strip()
        match = _PARAM_TYPE_RE.match(param_value)
        if match:
            raw_type = match.group(1).lower()
            description = match.group(2).strip()
            # Unknown types default to string
            param_type = raw_type if raw_type in _KNOWN_TYPES else "string"
        else:
            # No (type) annotation — use string type, full value as description
            param_type = "string"
            description = param_value

        properties[param_name] = {"type": param_type, "description": description}

    if not properties:
        return None

    return {"type": "object", "properties": properties}


def _normalize_server_id(server_name: str) -> str:
    """Normalize server name to server_id: lowercase, spaces → underscores."""
    return server_name.strip().lower().replace(" ", "_")


def convert_server(raw: dict) -> MCPServer | None:
    """Convert a single MCP-Zero server entry to our MCPServer model.

    Uses verified MCP-Zero schema fields:
        - name → server_id (normalized), name
        - description → description (fallback: summary)
        - tools[].name → tool_name
        - tools[].parameter → input_schema (via parse_parameter_schema)

    Args:
        raw: Raw server dictionary from MCP-Zero JSON.

    Returns:
        MCPServer instance or None if conversion fails.
    """
    server_name = raw.get("name", "")
    if not server_name or not server_name.strip():
        logger.warning("Server entry missing name, skipping")
        return None

    server_id = _normalize_server_id(server_name)

    # Description: prefer description, fall back to summary
    description = raw.get("description") or raw.get("summary", "")

    tools_raw = raw.get("tools") or []
    tools: list[MCPTool] = []

    for t in tools_raw:
        tool_name = t.get("name", "")
        if not tool_name:
            continue

        tool_id = f"{server_id}{TOOL_ID_SEPARATOR}{tool_name}"
        input_schema = parse_parameter_schema(t.get("parameter"))

        tools.append(
            MCPTool(
                tool_id=tool_id,
                server_id=server_id,
                tool_name=tool_name,
                description=t.get("description", ""),
                input_schema=input_schema,
            )
        )

    if not tools:
        logger.warning(f"Server '{server_id}' has no tools, skipping")
        return None

    return MCPServer(
        server_id=server_id,
        name=server_name,
        description=description,
        tools=tools,
    )


def extract_tool_embeddings(raw_servers: list[dict]) -> dict[str, list[float]]:
    """Extract pre-computed tool embeddings keyed by tool_id.

    MCP-Zero provides text-embedding-3-large (3072-dim) vectors in each tool's
    `description_embedding` field.  We extract them and key by our tool_id format
    so they can be upserted directly to Qdrant without re-embedding.

    Args:
        raw_servers: List of raw MCP-Zero server dicts.

    Returns:
        Dict mapping tool_id → embedding vector (list[float]).
    """
    embeddings: dict[str, list[float]] = {}

    for raw in raw_servers:
        server_name = raw.get("name", "")
        if not server_name or not server_name.strip():
            continue

        server_id = _normalize_server_id(server_name)

        for t in raw.get("tools") or []:
            tool_name = t.get("name", "")
            if not tool_name:
                continue

            embedding = t.get("description_embedding")
            if not embedding:
                continue

            tool_id = f"{server_id}{TOOL_ID_SEPARATOR}{tool_name}"
            embeddings[tool_id] = embedding

    return embeddings


def extract_server_embeddings(raw_servers: list[dict]) -> dict[str, list[float]]:
    """Extract pre-computed server-level embeddings keyed by server_id.

    MCP-Zero provides text-embedding-3-large (3072-dim) vectors in each server's
    ``description_embedding`` field. We extract them keyed by normalized server_id
    so they can be upserted directly to Qdrant without re-embedding.

    Args:
        raw_servers: List of raw MCP-Zero server dicts.

    Returns:
        Dict mapping server_id -> embedding vector (list[float]).
    """
    embeddings: dict[str, list[float]] = {}

    for raw in raw_servers:
        server_name = raw.get("name", "")
        if not server_name or not server_name.strip():
            continue

        server_id = _normalize_server_id(server_name)

        embedding = raw.get("description_embedding")
        if not embedding:
            continue

        embeddings[server_id] = embedding

    return embeddings


def load_mcp_zero_json(input_path: Path) -> list[dict]:
    """Load MCP-Zero servers from JSON file.

    Args:
        input_path: Path to MCP-Zero servers.json.

    Returns:
        List of raw server dictionaries.
    """
    with input_path.open() as f:
        data = json.load(f)

    # MCP-Zero may store as a list or as {"servers": [...]}
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "servers" in data:
        return data["servers"]

    logger.error(f"Unexpected JSON structure in {input_path}")
    return []


async def index_to_qdrant(
    servers: list[MCPServer],
    embeddings: dict[str, list[float]],
    qdrant_url: str,
    qdrant_api_key: str | None = None,
    collection_name: str = "mcp_tools",
    batch_size: int = 50,
) -> None:
    """Upsert tools with pre-computed embeddings to Qdrant.

    Uses pre-computed text-embedding-3-large vectors from MCP-Zero,
    so no re-embedding is needed.

    Args:
        servers: Converted MCPServer list.
        embeddings: Dict mapping tool_id → pre-computed embedding vector.
        qdrant_url: Qdrant Cloud URL.
        qdrant_api_key: Qdrant API key (optional for local).
        collection_name: Qdrant collection name.
        batch_size: Number of points per upsert batch.
    """
    from qdrant_client import AsyncQdrantClient

    client = AsyncQdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    store = QdrantStore(client=client, collection_name=collection_name)

    await store.ensure_collection(dimension=MCP_ZERO_EMBEDDING_DIM)

    # Collect all tools that have pre-computed embeddings
    tools_with_vectors: list[tuple[MCPTool, np.ndarray]] = []
    skipped = 0

    for server in servers:
        for tool in server.tools:
            vec = embeddings.get(tool.tool_id)
            if vec is not None:
                tools_with_vectors.append((tool, np.array(vec, dtype=np.float32)))
            else:
                skipped += 1

    if skipped > 0:
        logger.warning(f"Skipped {skipped} tools without pre-computed embeddings")

    logger.info(
        f"Indexing {len(tools_with_vectors)} tools to Qdrant collection '{collection_name}'"
    )

    # Batch upsert
    for i in range(0, len(tools_with_vectors), batch_size):
        batch = tools_with_vectors[i : i + batch_size]
        batch_tools = [t for t, _ in batch]
        batch_vectors = [v for _, v in batch]
        await store.upsert_tools(batch_tools, batch_vectors)

    logger.info(f"Qdrant indexing complete: {len(tools_with_vectors)} tools indexed")

    await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import MCP-Zero → MCPServer/MCPTool")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(DEFAULT_INPUT),
        help=f"MCP-Zero servers JSON path (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(DEFAULT_OUTPUT),
        help=f"Output JSONL path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Also upsert to Qdrant with pre-computed embeddings (requires QDRANT_URL)",
    )
    parser.add_argument(
        "--qdrant-url",
        type=str,
        default=None,
        help="Qdrant URL (overrides QDRANT_URL from .env)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Qdrant collection name (overrides settings default)",
    )
    parser.add_argument(
        "--index-servers",
        action="store_true",
        help="Also upsert servers to Qdrant mcp_servers collection (requires QDRANT_URL)",
    )
    parser.add_argument(
        "--server-collection",
        type=str,
        default="mcp_servers",
        help="Qdrant collection name for servers (default: mcp_servers)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        logger.info("Download MCP-Zero first. See data/external/README.md")
        return

    raw_servers = load_mcp_zero_json(args.input)
    logger.info(f"Loaded {len(raw_servers)} raw servers from {args.input}")

    servers: list[MCPServer] = []
    total_tools = 0

    for raw in raw_servers:
        server = convert_server(raw)
        if server is not None:
            servers.append(server)
            total_tools += len(server.tools)

    logger.info(f"Converted {len(servers)} servers, {total_tools} tools")

    # Save as JSONL
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as f:
        for server in servers:
            f.write(server.model_dump_json() + "\n")

    logger.info(f"Output: {args.output}")

    if args.index or args.index_servers:
        from qdrant_client import AsyncQdrantClient
        from src.config import Settings

        settings = Settings()
        qdrant_url = args.qdrant_url or settings.qdrant_url

        async def _run_indexing() -> None:
            client = AsyncQdrantClient(url=qdrant_url, api_key=settings.qdrant_api_key)
            try:
                if args.index:
                    tool_embeddings = extract_tool_embeddings(raw_servers)
                    logger.info(f"Extracted {len(tool_embeddings)} pre-computed tool embeddings")

                    collection_name = args.collection or settings.qdrant_collection_name
                    tool_store = QdrantStore(client=client, collection_name=collection_name)
                    await tool_store.ensure_collection(dimension=MCP_ZERO_EMBEDDING_DIM)

                    tools_with_vectors: list[tuple] = []
                    skipped = 0
                    for server in servers:
                        for tool in server.tools:
                            vec = tool_embeddings.get(tool.tool_id)
                            if vec is not None:
                                tools_with_vectors.append((tool, np.array(vec, dtype=np.float32)))
                            else:
                                skipped += 1

                    if skipped > 0:
                        logger.warning(f"Skipped {skipped} tools without pre-computed embeddings")

                    logger.info(f"Indexing {len(tools_with_vectors)} tools to '{collection_name}'")
                    batch_size = 50
                    for i in range(0, len(tools_with_vectors), batch_size):
                        batch = tools_with_vectors[i : i + batch_size]
                        await tool_store.upsert_tools([t for t, _ in batch], [v for _, v in batch])
                    logger.info(f"Tool indexing complete: {len(tools_with_vectors)} tools")

                if args.index_servers:
                    server_embeddings = extract_server_embeddings(raw_servers)
                    logger.info(
                        f"Extracted {len(server_embeddings)} pre-computed server embeddings"
                    )

                    server_store = QdrantStore(
                        client=client, collection_name=args.server_collection
                    )
                    await server_store.ensure_collection(dimension=MCP_ZERO_EMBEDDING_DIM)

                    servers_with_vectors: list[tuple] = []
                    skipped_servers = 0
                    for server in servers:
                        vec = server_embeddings.get(server.server_id)
                        if vec is not None:
                            servers_with_vectors.append((server, np.array(vec, dtype=np.float32)))
                        else:
                            skipped_servers += 1

                    if skipped_servers > 0:
                        logger.warning(f"Skipped {skipped_servers} servers without embeddings")

                    logger.info(
                        f"Indexing {len(servers_with_vectors)} servers to "
                        f"'{args.server_collection}'"
                    )
                    batch_size = 50
                    for i in range(0, len(servers_with_vectors), batch_size):
                        batch = servers_with_vectors[i : i + batch_size]
                        await server_store.upsert_servers(
                            [s for s, _ in batch], [v for _, v in batch]
                        )
                    logger.info(f"Server indexing complete: {len(servers_with_vectors)} servers")
            finally:
                await client.close()

        asyncio.run(_run_indexing())


if __name__ == "__main__":
    main()
