"""Generate synthetic traffic by running GT queries through the real search pipeline.

For each sampled Ground Truth query:
  1. RAGService.search(query, top_k=5) via real Qdrant
  2. Present top-K results to GPT-4o-mini as tool_use function definitions
  3. GPT selects one tool
  4. Log selection to JSONL

Usage:
    uv run python scripts/generate_synthetic_traffic.py
    uv run python scripts/generate_synthetic_traffic.py --sample-size 50
    uv run python scripts/generate_synthetic_traffic.py --sample-size 200 --top-k 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Bootstrap imports: project root (for mlp package) and src/ (for core modules)
_repo_root = str(Path(__file__).parent.parent)
sys.path.insert(0, _repo_root)

from dotenv import load_dotenv

load_dotenv(override=False)

# Override Qdrant URL for local access (Docker .env uses host.docker.internal)
os.environ["QDRANT_URL"] = "http://localhost:6333"

from loguru import logger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
GT_PATH = Path("data/ground_truth/mcp_atlas.jsonl")
OUTPUT_PATH = Path("data/experiments/synthetic_traffic.jsonl")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GPT_MODEL = "gpt-4o-mini"


def load_ground_truth(path: Path) -> list[dict]:
    """Load JSONL ground truth entries."""
    entries: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def sample_queries(entries: list[dict], n: int, seed: int = 42) -> list[dict]:
    """Randomly sample n entries from ground truth."""
    rng = random.Random(seed)
    if n >= len(entries):
        return list(entries)
    return rng.sample(entries, n)


def build_tool_functions(results: list) -> list[dict]:
    """Convert SearchResult list into OpenAI function definitions for tool_use."""
    functions: list[dict] = []
    for r in results:
        tool = r.tool
        # Replace :: with __ for valid function names
        func_name = tool.tool_id.replace("::", "__")
        # Truncate to OpenAI's 64-char limit for function names
        func_name = func_name[:64]
        desc = tool.description or f"Tool {tool.tool_name} from server {tool.server_id}"
        # Truncate description to 1024 chars
        desc = desc[:1024]
        functions.append(
            {
                "type": "function",
                "function": {
                    "name": func_name,
                    "description": desc,
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )
    return functions


def extract_recommended_tool_id(response, tool_id_map: dict[str, str]) -> str | None:
    """Extract the selected tool_id from GPT's tool_call response."""
    message = response.choices[0].message
    if message.tool_calls:
        func_name = message.tool_calls[0].function.name
        return tool_id_map.get(func_name)
    return None


async def build_rag_service():
    """Build RAGService from the shared runtime (same pattern as local_bridge_mcp.py)."""
    from service.rag.factory import RAGServiceFactory
    from service.shared.runtime import build_search_runtime

    runtime = build_search_runtime()
    mlp_settings = runtime.mlp_settings

    rag_service = RAGServiceFactory.create(
        strategy=runtime.strategy,
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_key=os.getenv("SUPABASE_SERVICE_KEY", ""),
        cache_ttl=0,  # No cache for synthetic traffic generation
        confidence_gap_threshold=runtime.settings.confidence_gap_threshold,
        reranker=None,
        operability_cache=runtime.operability_cache,
        enable_pending_freshness=False,
        rerank_candidate_pool_size=mlp_settings.rerank_candidate_pool_size,
    )
    return rag_service


async def process_single_query(
    rag_service,
    openai_client,
    entry: dict,
    top_k: int,
) -> dict | None:
    """Process a single GT query: search -> GPT selection -> record."""
    query_id = entry.get("query_id", "unknown")
    query = entry.get("query") or entry.get("query_text", "")
    correct_tool_id = entry.get("correct_tool_id", "")

    if not query:
        logger.warning(f"Skipping {query_id}: empty query")
        return None

    # Stage 1: Real Qdrant search
    try:
        response = await rag_service.search(query, top_k=top_k)
    except Exception as exc:
        logger.warning(f"Search failed for {query_id}: {exc}")
        return None

    results = response.results
    if not results:
        logger.warning(f"No results for {query_id}")
        return None

    # Build function definitions for GPT
    functions = build_tool_functions(results)
    if not functions:
        return None

    # Map func_name -> original tool_id
    tool_id_map: dict[str, str] = {}
    for r in results:
        func_name = r.tool.tool_id.replace("::", "__")[:64]
        tool_id_map[func_name] = r.tool.tool_id

    top_k_tool_ids = [r.tool.tool_id for r in results]

    # Stage 2: GPT selects a tool
    try:
        gpt_response = openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a tool selection agent. "
                        "Given a user query, select the single most appropriate tool by calling it. "
                        "You MUST call exactly one tool."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Use the single most appropriate tool: {query}",
                },
            ],
            tools=functions,
            tool_choice="required",
        )
    except Exception as exc:
        logger.warning(f"GPT call failed for {query_id}: {exc}")
        return None

    recommended_tool_id = extract_recommended_tool_id(gpt_response, tool_id_map)
    if not recommended_tool_id:
        logger.warning(f"GPT did not select a tool for {query_id}")
        return None

    hit = recommended_tool_id == correct_tool_id

    return {
        "query_id": query_id,
        "query": query,
        "recommended_tool_id": recommended_tool_id,
        "top_k_tools": top_k_tool_ids,
        "correct_tool_id": correct_tool_id,
        "hit": hit,
        "model": GPT_MODEL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "synthetic",
    }


async def run(sample_size: int, top_k: int, seed: int) -> None:
    """Main async entry point."""
    logger.info(f"Loading ground truth from {GT_PATH}")
    all_entries = load_ground_truth(GT_PATH)
    logger.info(f"Loaded {len(all_entries)} GT entries, sampling {sample_size}")

    sampled = sample_queries(all_entries, sample_size, seed=seed)
    logger.info(f"Sampled {len(sampled)} queries (seed={seed})")

    logger.info("Building RAG service (connecting to Qdrant)...")
    rag_service = await build_rag_service()

    import openai

    openai_client = openai.OpenAI()

    records: list[dict] = []
    hits = 0
    errors = 0
    t_start = time.time()

    for i, entry in enumerate(sampled):
        try:
            record = await process_single_query(rag_service, openai_client, entry, top_k)
        except Exception as exc:
            logger.error(f"Unexpected error on query {i}: {exc}")
            errors += 1
            continue

        if record is None:
            errors += 1
            continue

        records.append(record)
        if record["hit"]:
            hits += 1

        if (i + 1) % 10 == 0 or (i + 1) == len(sampled):
            elapsed = time.time() - t_start
            accuracy = hits / len(records) if records else 0.0
            logger.info(
                f"Progress: {i + 1}/{len(sampled)} | "
                f"recorded={len(records)} | hits={hits} | "
                f"accuracy={accuracy:.1%} | errors={errors} | "
                f"elapsed={elapsed:.1f}s"
            )

    # Write output JSONL
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info(f"Wrote {len(records)} records to {OUTPUT_PATH}")

    # Summary
    total_elapsed = time.time() - t_start
    accuracy = hits / len(records) if records else 0.0

    logger.info("=" * 60)
    logger.info("SYNTHETIC TRAFFIC GENERATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total queries processed: {len(sampled)}")
    logger.info(f"Successful records:      {len(records)}")
    logger.info(f"Errors/skipped:          {errors}")
    logger.info(f"GPT selection accuracy:  {hits}/{len(records)} = {accuracy:.1%}")
    logger.info(f"Total time:              {total_elapsed:.1f}s")
    logger.info(f"Output file:             {OUTPUT_PATH}")

    if records:
        # Top selected tools
        selected_counter: Counter = Counter(r["recommended_tool_id"] for r in records)
        logger.info("Top 10 selected tools:")
        for tool_id, count in selected_counter.most_common(10):
            logger.info(f"  {tool_id}: {count} selections")

        # Top correct tools in GT sample
        correct_counter: Counter = Counter(r["correct_tool_id"] for r in records)
        logger.info("Top 10 expected tools (GT):")
        for tool_id, count in correct_counter.most_common(10):
            logger.info(f"  {tool_id}: {count} expected")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic traffic from GT queries")
    parser.add_argument("--sample-size", type=int, default=100, help="Number of GT queries to sample")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K results from RAG search")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    args = parser.parse_args()

    asyncio.run(run(sample_size=args.sample_size, top_k=args.top_k, seed=args.seed))


if __name__ == "__main__":
    main()
