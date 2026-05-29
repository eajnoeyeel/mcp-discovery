"""Generate per-client description variants for MCP tools.

Reads tool metadata from data/raw/mcp_zero_servers.jsonl,
generates Gemini/Claude/GPT-optimized descriptions via GPT-4o-mini,
and writes results to data/enriched/per_client_variants.jsonl.

Supports incremental re-run: existing (tool_id, vendor) pairs are skipped.

Usage:
    PYTHONPATH=src uv run python scripts/generate_per_client_variants.py
    PYTHONPATH=src uv run python scripts/generate_per_client_variants.py \
        --tool-ids "github::search_repositories,slack::send_message"
    PYTHONPATH=src uv run python scripts/generate_per_client_variants.py --dry-run
"""

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from openai import AsyncOpenAI

from mcp_discovery.analytics.token_tracker import TokenTracker
from mcp_discovery.config import Settings
from mcp_discovery.description.base import VendorStyle
from mcp_discovery.description.llm_generator import LLMVariantGenerator
from mcp_discovery.description.variant_store import VariantStore

load_dotenv()

RAW_PATH = Path("data/raw/mcp_zero_servers.jsonl")
OUTPUT_PATH = Path("data/enriched/per_client_variants.jsonl")
TOKEN_LOG_PATH = Path("data/enriched/variant_generation_tokens.jsonl")


def _load_tools(tool_ids: list[str] | None = None) -> list[dict]:
    """Load tools from mcp_zero_servers.jsonl, optionally filtered."""
    tools: list[dict] = []
    for line in RAW_PATH.read_text().splitlines():
        if not line.strip():
            continue
        server = json.loads(line)
        sid = server.get("server_id", "")
        for tool in server.get("tools", []):
            tname = tool.get("tool_name", "")
            tid = tool.get("tool_id", f"{sid}::{tname}")
            if tool_ids and tid not in tool_ids:
                continue
            tools.append(
                {
                    "tool_id": tid,
                    "server_id": sid,
                    "tool_name": tname,
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema"),
                }
            )
    return tools


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate per-client description variants")
    parser.add_argument(
        "--tool-ids",
        type=str,
        default=None,
        help="Comma-separated tool_ids to process (default: all)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be generated")
    args = parser.parse_args()

    tool_id_filter = args.tool_ids.split(",") if args.tool_ids else None

    if not RAW_PATH.exists():
        logger.error(f"Raw data not found: {RAW_PATH}")
        return

    tools = _load_tools(tool_id_filter)
    logger.info(f"Loaded {len(tools)} tools")

    store = VariantStore(path=OUTPUT_PATH)
    tracker = TokenTracker(log_path=TOKEN_LOG_PATH)

    # Filter out already-generated (tool_id, vendor) pairs
    pending: list[dict] = []
    for tool in tools:
        missing_vendors = [v for v in VendorStyle if not store.exists(tool["tool_id"], v)]
        if missing_vendors:
            tool["_missing_vendors"] = missing_vendors
            pending.append(tool)

    skipped = len(tools) - len(pending)
    logger.info(f"{len(pending)} tools need variant generation ({skipped} skipped)")

    if args.dry_run:
        for tool in pending[:10]:
            logger.info(f"  Would generate: {tool['tool_id']} — {tool['_missing_vendors']}")
        if len(pending) > 10:
            logger.info(f"  ... and {len(pending) - 10} more")
        return

    settings = Settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    generator = LLMVariantGenerator(client=client, token_tracker=tracker)

    for i, tool in enumerate(pending):
        logger.info(f"[{i + 1}/{len(pending)}] Generating variants for {tool['tool_id']}")
        variants = await generator.generate(
            tool_id=tool["tool_id"],
            tool_name=tool["tool_name"],
            raw_description=tool["description"],
            input_schema=tool.get("input_schema"),
        )
        store.save_batch(list(variants.values()))

    summary = tracker.summary()
    logger.info(
        f"Done. Total tokens: {summary['total_tokens']}, Cost: ${summary['total_cost_usd']:.4f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
