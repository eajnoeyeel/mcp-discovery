"""CLI script for crawling MCP servers from Smithery Registry.

Usage:
    uv run scripts/collect_data.py                          # top 100 deployed
    uv run scripts/collect_data.py --max-servers 50
    uv run scripts/collect_data.py --server-list path.txt   # curated list
    uv run scripts/collect_data.py --max-pages 5
"""

import argparse
import asyncio
from pathlib import Path

# Add src/ to path so we can import project modules
from loguru import logger

from mcp_discovery.config import Settings
from mcp_discovery.data.crawler import SmitheryCrawler
from mcp_discovery.data.smithery_client import SmitheryClient


async def main(args: argparse.Namespace) -> None:
    settings = Settings()
    curated_list = Path(args.server_list) if args.server_list else None

    async with SmitheryClient(base_url=settings.smithery_api_base_url) as client:
        crawler = SmitheryCrawler(client=client)
        servers = await crawler.crawl(
            max_pages=args.max_pages,
            curated_list=curated_list,
            max_servers=args.max_servers,
        )

    path = crawler.save(servers, output_dir=Path(args.output_dir))
    total_tools = sum(len(s.tools) for s in servers)
    logger.info(f"Done: {len(servers)} servers, {total_tools} tools -> {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crawl MCP servers from Smithery Registry")
    parser.add_argument("--max-servers", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--server-list", type=str, default=None, help="Path to curated server list")
    parser.add_argument("--output-dir", type=str, default="data/raw")
    args = parser.parse_args()
    asyncio.run(main(args))
