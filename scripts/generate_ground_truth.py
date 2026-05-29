#!/usr/bin/env python3
"""Generate synthetic ground truth from crawled server data.

Usage:
    uv run python scripts/generate_ground_truth.py \\
        --servers data/raw/servers.jsonl \\
        --output data/ground_truth/synthetic.jsonl \\
        [--model gpt-4o-mini]
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add src/ to path so we can import project modules

from loguru import logger
from openai import AsyncOpenAI

from mcp_discovery.data.ground_truth import (
    QualityGate,
    QualityGateError,
    generate_synthetic_gt,
    load_ground_truth,
    save,
)
from mcp_discovery.models import MCPServer


def load_servers(path: Path) -> list[MCPServer]:
    servers = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        servers.append(MCPServer.model_validate_json(line))
    logger.info(f"Loaded {len(servers)} servers from {path}")
    return servers


async def main(args: argparse.Namespace) -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    servers = load_servers(Path(args.servers))
    client = AsyncOpenAI(api_key=api_key)

    entries = await generate_synthetic_gt(
        servers=servers,
        client=client,
        model=args.model,
        created_at=args.date,
    )

    # Run quality gate if seed set is available
    if args.seed and Path(args.seed).exists():
        seed = load_ground_truth(Path(args.seed), only_verified=True)
        gate = QualityGate()
        try:
            gate.check_difficulty_distribution(entries, seed)
            logger.info("Quality gate: difficulty distribution OK")
        except QualityGateError as e:
            logger.warning(f"Quality gate warning: {e}")

        # Check for tool name leakage in Medium/Hard queries
        tool_names = [t.tool_name for s in servers for t in s.tools]
        try:
            gate.check_no_tool_name_leakage(entries, tool_names)
            logger.info("Quality gate: no tool name leakage OK")
        except QualityGateError as e:
            logger.warning(f"Quality gate warning: {e}")

    out = Path(args.output)
    count = save(entries, out)
    logger.info(f"Wrote {count} entries to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--servers", default="data/raw/servers.jsonl")
    parser.add_argument("--output", default="data/ground_truth/synthetic.jsonl")
    parser.add_argument("--seed", default="data/ground_truth/seed_set.jsonl")
    parser.add_argument("--model", default="gpt-4o-mini")
    from datetime import date as _date

    parser.add_argument("--date", default=_date.today().isoformat())
    asyncio.run(main(parser.parse_args()))
