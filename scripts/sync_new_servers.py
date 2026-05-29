"""One-shot sync for new servers/tools added to pool JSONL.

Reads data/raw/mcp_zero_servers.jsonl, filters to the server_ids passed
via --servers, and propagates to:
  - Qdrant mcp_tools             (dense only, legacy collection)
  - Qdrant mcp_tools_hybrid      (dense + SPLADE sparse)
  - Qdrant mcp_servers           (server-level dense)
  - Supabase mcp_servers + mcp_tools (REST upsert)

Embeddings:
  - Dense: OpenAI text-embedding-3-large (3072d). ~$0.0001 per tool.
  - Sparse: FastEmbed SPLADE (local inference, free).

Idempotent: Qdrant point IDs are uuid5(MCP_DISCOVERY_NAMESPACE, tool_id).
Supabase upsert uses on_conflict=tool_id / server_id.

Usage:
    uv run python scripts/sync_new_servers.py --servers postgres yahoo-finance
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Repo-local sys.path shim so `mcp_discovery` imports work via `uv run`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx  # noqa: E402
import numpy as np  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from loguru import logger  # noqa: E402
from qdrant_client import AsyncQdrantClient  # noqa: E402

from mcp_discovery.embedding.fastembed_sparse import FastEmbedSparseEmbedder  # noqa: E402
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder  # noqa: E402
from mcp_discovery.models import MCPServer, MCPTool  # noqa: E402
from mcp_discovery.retrieval.qdrant_store import QdrantStore  # noqa: E402

load_dotenv()

POOL_PATH = Path("data/raw/mcp_zero_servers.jsonl")


def load_filtered_pool(pool_path: Path, server_ids: set[str]) -> list[MCPServer]:
    servers: list[MCPServer] = []
    with pool_path.open() as f:
        for line in f:
            r = json.loads(line)
            if r["server_id"] not in server_ids:
                continue
            tools = [MCPTool(**t) for t in r.get("tools", [])]
            servers.append(
                MCPServer(
                    server_id=r["server_id"],
                    name=r.get("name") or r["server_id"],
                    description=r.get("description") or "",
                    homepage=r.get("homepage"),
                    tools=tools,
                )
            )
    return servers


def tool_text(tool: MCPTool) -> str:
    parts = [tool.tool_name, tool.description or ""]
    return " — ".join(p for p in parts if p)


def server_text(server: MCPServer) -> str:
    return f"{server.name}: {server.description}"


async def upsert_supabase(servers: list[MCPServer]) -> None:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    server_rows = [
        {
            "server_id": s.server_id,
            "name": s.name,
            "description": s.description,
            "url": s.homepage,
            "index_status": "indexed",
        }
        for s in servers
    ]
    tool_rows = [
        {
            "tool_id": t.tool_id,
            "server_id": t.server_id,
            "tool_name": t.tool_name,
            "description": t.description,
            "input_schema": t.input_schema,
            "index_status": "indexed",
        }
        for s in servers
        for t in s.tools
    ]
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{url}/rest/v1/mcp_servers?on_conflict=server_id",
            headers=headers,
            content=json.dumps(server_rows),
        )
        r.raise_for_status()
        logger.info(f"Supabase mcp_servers: upserted {len(server_rows)} rows")

        r = await client.post(
            f"{url}/rest/v1/mcp_tools?on_conflict=tool_id",
            headers=headers,
            content=json.dumps(tool_rows),
        )
        r.raise_for_status()
        logger.info(f"Supabase mcp_tools: upserted {len(tool_rows)} rows")


async def main(args: argparse.Namespace) -> None:
    server_ids = set(args.servers)
    servers = load_filtered_pool(POOL_PATH, server_ids)
    if not servers:
        logger.error(f"No matching servers for {server_ids}")
        return
    tools: list[MCPTool] = [t for s in servers for t in s.tools]
    logger.info(f"Loaded {len(servers)} servers, {len(tools)} tools: {[s.server_id for s in servers]}")

    dense = OpenAIEmbedder(
        api_key=os.environ["OPENAI_API_KEY"],
        model="text-embedding-3-large",
        dimension=3072,
    )
    logger.info("Embedding tools (OpenAI dense)")
    tool_texts = [tool_text(t) for t in tools]
    tool_dense = await dense.embed_batch(tool_texts)

    logger.info("Embedding tools (FastEmbed SPLADE sparse)")
    sparse = FastEmbedSparseEmbedder()
    tool_sparse = sparse.embed_batch(tool_texts)

    logger.info("Embedding servers (OpenAI dense)")
    server_dense = await dense.embed_batch([server_text(s) for s in servers])

    client = AsyncQdrantClient(
        url=os.environ["QDRANT_URL"], api_key=os.environ.get("QDRANT_API_KEY")
    )

    store_tools = QdrantStore(client=client, collection_name="mcp_tools")
    await store_tools.upsert_tools(tools, [np.asarray(v) for v in tool_dense])
    logger.info(f"Qdrant mcp_tools: upserted {len(tools)} points")

    store_hybrid = QdrantStore(client=client, collection_name="mcp_tools_hybrid")
    await store_hybrid.upsert_tools_hybrid(
        tools, [np.asarray(v) for v in tool_dense], tool_sparse
    )
    logger.info(f"Qdrant mcp_tools_hybrid: upserted {len(tools)} points")

    store_srv = QdrantStore(client=client, collection_name="mcp_servers")
    await store_srv.upsert_servers(servers, [np.asarray(v) for v in server_dense])
    logger.info(f"Qdrant mcp_servers: upserted {len(servers)} points")

    # Supabase
    await upsert_supabase(servers)

    logger.info("All sinks updated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync new pool servers to Qdrant + Supabase")
    parser.add_argument("--servers", nargs="+", required=True, help="server_ids to sync")
    asyncio.run(main(parser.parse_args()))
