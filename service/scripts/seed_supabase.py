"""Seed Supabase with MCP-Zero tool pool data + GEO scores.

Loads pre-processed MCP-Zero servers from data/raw/mcp_zero_servers.jsonl,
computes GEO scores for each tool description, and upserts into Supabase
mcp_servers and mcp_tools tables.

Usage:
    uv run python mlp/scripts/seed_supabase.py [--dry-run] [--batch-size 50]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from loguru import logger

_project_root = Path(__file__).resolve().parent.parent.parent

from mcp_discovery.analytics.geo_score import DescriptionGEOScorer
from mcp_discovery.models import MCPServer

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
DATA_PATH = _project_root / "data" / "raw" / "mcp_zero_servers.jsonl"
POOL_PATH = _project_root / "data" / "tool-pools" / "base_pool.json"


def _build_headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }


def load_servers(pool_filter: set[str] | None) -> list[MCPServer]:
    """Load MCPServer models from pre-processed JSONL."""
    if not DATA_PATH.exists():
        logger.error(
            f"Data file not found: {DATA_PATH}\n"
            "Run: uv run python scripts/import_mcp_zero.py "
            "--input data/external/mcp-zero/servers.json"
        )
        sys.exit(1)

    servers: list[MCPServer] = []
    with DATA_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            server = MCPServer.model_validate_json(line)
            if pool_filter is None or server.server_id in pool_filter:
                servers.append(server)
    return servers


def load_pool_filter() -> set[str] | None:
    """Load base_pool.json server IDs if available."""
    if not POOL_PATH.exists():
        logger.info("No pool filter found, using all servers")
        return None
    with POOL_PATH.open() as f:
        pool = json.load(f)
    logger.info(f"Pool filter loaded: {len(pool)} servers")
    return set(pool)


def build_server_row(server: MCPServer) -> dict:
    return {
        "server_id": server.server_id,
        "name": server.name,
        "description": server.description or "",
        "url": server.homepage,
        "index_status": "indexed",
    }


def build_tool_row(tool_data: dict, geo: dict) -> dict:
    return {
        "tool_id": tool_data["tool_id"],
        "server_id": tool_data["server_id"],
        "tool_name": tool_data["tool_name"],
        "description": tool_data["description"] or "",
        "input_schema": tool_data["input_schema"],
        "geo_score": geo,
        "index_status": "indexed",
    }


async def upsert_batch(
    client: httpx.AsyncClient,
    table: str,
    rows: list[dict],
    batch_size: int,
    headers: dict[str, str],
) -> int:
    """Upsert rows in batches. Returns count of successfully upserted rows."""
    success = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            resp = await client.post(
                f"{SUPABASE_URL}/rest/v1/{table}",
                json=batch,
                headers=headers,
            )
            resp.raise_for_status()
            success += len(batch)
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Supabase {table} batch {i // batch_size}: "
                f"{e.response.status_code} {e.response.text}"
            )
        except httpx.HTTPError as e:
            logger.error(f"Supabase {table} batch {i // batch_size}: {e}")
    return success


async def main(dry_run: bool = False, batch_size: int = 50) -> None:
    if not dry_run and (not SUPABASE_URL or not SUPABASE_KEY):
        logger.error("Set SUPABASE_URL and SUPABASE_SERVICE_KEY env vars (or use --dry-run)")
        sys.exit(1)

    pool_filter = load_pool_filter()
    servers = load_servers(pool_filter)
    logger.info(f"Loaded {len(servers)} servers from {DATA_PATH.name}")

    scorer = DescriptionGEOScorer()
    server_rows: list[dict] = []
    tool_rows: list[dict] = []
    geo_count = 0

    for server in servers:
        server_rows.append(build_server_row(server))
        for tool in server.tools:
            geo = scorer.score(tool.description)
            tool_dict = tool.model_dump()
            tool_rows.append(build_tool_row(tool_dict, geo.model_dump()))
            if geo.total > 0:
                geo_count += 1

    # Deduplicate: JSONL may contain repeated server_ids / tool_ids
    seen_servers: dict[str, dict] = {}
    for row in server_rows:
        seen_servers[row["server_id"]] = row
    server_rows = list(seen_servers.values())

    seen_tools: dict[str, dict] = {}
    for row in tool_rows:
        seen_tools[row["tool_id"]] = row
    tool_rows = list(seen_tools.values())

    logger.info(
        f"Prepared {len(server_rows)} servers, {len(tool_rows)} tools ({geo_count} with GEO > 0)"
    )

    if dry_run:
        logger.info("[DRY RUN] Would upsert to Supabase:")
        logger.info(f"  mcp_servers: {len(server_rows)} rows")
        logger.info(f"  mcp_tools:   {len(tool_rows)} rows")
        if server_rows:
            logger.info(f"  Sample server: {json.dumps(server_rows[0], indent=2)}")
        if tool_rows:
            logger.info(f"  Sample tool:   {json.dumps(tool_rows[0], indent=2)}")
        return

    headers = _build_headers()
    async with httpx.AsyncClient(timeout=30.0) as client:
        srv_ok = await upsert_batch(client, "mcp_servers", server_rows, batch_size, headers)
        tool_ok = await upsert_batch(client, "mcp_tools", tool_rows, batch_size, headers)

    logger.info(
        f"Seeded {srv_ok}/{len(server_rows)} servers, "
        f"{tool_ok}/{len(tool_rows)} tools, {geo_count} with GEO > 0"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Supabase with MCP-Zero data")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be inserted")
    parser.add_argument("--batch-size", type=int, default=50, help="Rows per batch (default: 50)")
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run, batch_size=args.batch_size))
