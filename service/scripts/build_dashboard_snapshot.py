"""Build provider dashboard snapshots from Supabase tool data.

Reads tools from Supabase mcp_tools table, computes per-server GEO score
aggregates using service.analytics.snapshots, and outputs JSON summary.

Usage:
    uv run python service/scripts/build_dashboard_snapshot.py [--output snapshots.json]
    uv run python service/scripts/build_dashboard_snapshot.py --dry-run
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

# Make `service.*` importable when run as a script (mirrors pytest's
# pythonpath = [..., "."] setting; no installed wheel required).
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from service.analytics.snapshots import build_all_snapshots  # noqa: E402

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# Supabase REST API page size limit
_PAGE_SIZE = 1000


def _build_headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


async def fetch_all_tools(client: httpx.AsyncClient) -> list[dict]:
    """Fetch all tools from Supabase mcp_tools table with pagination."""
    tools: list[dict] = []
    offset = 0

    while True:
        url = (
            f"{SUPABASE_URL}/rest/v1/mcp_tools"
            f"?select=tool_id,server_id,tool_name,description,geo_score,index_status"
            f"&order=tool_id.asc"
            f"&limit={_PAGE_SIZE}"
            f"&offset={offset}"
        )
        resp = await client.get(url, headers=_build_headers())
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        tools.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    return tools


async def run(output_path: str | None, dry_run: bool) -> None:
    """Main pipeline: fetch tools -> build snapshots -> output."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        logger.info("Fetching tools from Supabase...")
        tools = await fetch_all_tools(client)
        logger.info(f"Fetched {len(tools)} tools")

    snapshots = build_all_snapshots(tools)
    logger.info(f"Built {len(snapshots)} provider snapshots")

    # Summary stats
    if snapshots:
        avg_scores = [s["avg_geo_score"] for s in snapshots]
        overall_avg = sum(avg_scores) / len(avg_scores)
        low_score_servers = sum(1 for s in snapshots if s["avg_geo_score"] < 0.5)
        logger.info(f"Overall avg GEO: {overall_avg:.4f}")
        logger.info(f"Servers with avg GEO < 0.5: {low_score_servers}/{len(snapshots)}")

    if dry_run:
        logger.info("[DRY RUN] Snapshots computed but not written")
        for snap in snapshots[:5]:
            logger.info(
                f"  {snap['server_id']}: {snap['tool_count']} tools, "
                f"avg={snap['avg_geo_score']:.4f}"
            )
        if len(snapshots) > 5:
            logger.info(f"  ... and {len(snapshots) - 5} more")
        return

    if output_path:
        out = Path(output_path)
        out.write_text(json.dumps(snapshots, indent=2, ensure_ascii=False))
        logger.info(f"Written {len(snapshots)} snapshots to {out}")
    else:
        # Print to stdout as JSON
        sys.stdout.write(json.dumps(snapshots, indent=2, ensure_ascii=False))
        sys.stdout.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build provider dashboard snapshots from Supabase")
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path (JSON). Defaults to stdout.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute snapshots but do not write output.",
    )
    args = parser.parse_args()
    asyncio.run(run(output_path=args.output, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
