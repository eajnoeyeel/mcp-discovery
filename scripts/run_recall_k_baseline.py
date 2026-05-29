"""Recall@K Baseline -- Embedding-only retrieval without reranker.

Measures Recall@K for various K values to establish the new North Star baseline.
No Cohere API needed -- only OpenAI (query embedding) + Qdrant.

Usage:
    PYTHONPATH=src uv run python scripts/run_recall_k_baseline.py
    PYTHONPATH=src uv run python scripts/run_recall_k_baseline.py --no-wandb
    PYTHONPATH=src uv run python scripts/run_recall_k_baseline.py --k-values 3 5 10 20
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

# Add src/ to path so we can import project modules
from dotenv import load_dotenv
from loguru import logger
from qdrant_client import AsyncQdrantClient

import wandb
from mcp_discovery.config import Settings
from mcp_discovery.data.ground_truth import load_ground_truth, merge_ground_truth
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder
from mcp_discovery.evaluation.harness import evaluate
from mcp_discovery.evaluation.metrics import EvalResult
from mcp_discovery.models import GroundTruthEntry
from mcp_discovery.pipeline.flat import FlatStrategy
from mcp_discovery.pipeline.parallel import ParallelStrategy
from mcp_discovery.retrieval.qdrant_store import QdrantStore

load_dotenv()

# Ground truth file paths
GT_SEED_PATH = Path("data/ground_truth/seed_set.jsonl")
GT_ATLAS_PATH = Path("data/ground_truth/mcp_atlas.jsonl")

# Embedding model must match the Qdrant collection vectors
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSION = 3072

BASE_POOL_PATH = Path("data/tool-pools/base_pool.json")
RESULTS_PATH = Path("data/results/recall_k_baseline.json")

DEFAULT_K_VALUES = [3, 5, 10]


def _load_pool_server_ids() -> list[str]:
    """Load all server IDs from base_pool.json."""
    if not BASE_POOL_PATH.exists():
        raise FileNotFoundError(
            f"base_pool.json not found at {BASE_POOL_PATH}. "
            "Run: uv run python scripts/build_base_pool.py"
        )
    ordered: list[str] = json.loads(BASE_POOL_PATH.read_text())
    logger.info(f"Loaded {len(ordered)}-server pool from {BASE_POOL_PATH}")
    return ordered


def _load_and_filter_gt(pool_server_ids: list[str]) -> list[GroundTruthEntry]:
    """Load GT from seed + atlas, filter to servers in pool."""
    pool_set = set(pool_server_ids)
    gt_paths: list[Path] = []

    for label, path in [("seed", GT_SEED_PATH), ("atlas", GT_ATLAS_PATH)]:
        if path.exists():
            gt_paths.append(path)
            entries = load_ground_truth(path)
            total = len(entries)
            covered = sum(1 for e in entries if e.correct_server_id in pool_set)
            pct = covered / total * 100
            logger.info(f"  {label}: {total} total, {covered} covered ({pct:.1f}%)")
        else:
            logger.warning(f"GT file not found, skipping: {path}")

    if not gt_paths:
        logger.error("No GT files found.")
        return []

    all_entries = merge_ground_truth(*gt_paths)
    filtered = [e for e in all_entries if e.correct_server_id in pool_set]
    logger.info(f"  Combined: {len(all_entries)} total, {len(filtered)} covered by pool")
    return filtered


def _eval_result_to_dict(result: EvalResult) -> dict:
    """Convert EvalResult to JSON-serializable dict."""
    return {
        "precision_at_1": result.precision_at_1,
        "recall_at_k": result.recall_at_k,
        "server_recall_at_k": result.server_recall_at_k,
        "mrr": result.mrr,
        "ndcg_at_5": result.ndcg_at_5,
        "confusion_rate": result.confusion_rate,
        "ece": result.ece,
        "latency_p50": result.latency_p50,
        "latency_p95": result.latency_p95,
        "latency_mean": result.latency_mean,
        "n_queries": result.n_queries,
        "n_failed": result.n_failed,
    }


def _format_results_table(
    strategy_results: dict[str, dict[int, EvalResult]],
    k_values: list[int],
    n_entries: int,
    pool_size: int,
) -> str:
    """Format a comparison table: strategies x K values."""
    lines = [
        f"\n{'=' * 70}",
        f"RECALL@K BASELINE  (n={n_entries}, pool={pool_size}, reranker=none)",
        f"{'=' * 70}",
        "",
    ]

    for strategy_name, by_k in strategy_results.items():
        lines.append(f"  {strategy_name}")
        hdr = f"  {'K':>4}  {'Recall@K':>10}  {'P@1':>7}  {'MRR':>7}  {'SrvR@K':>8}  {'Lat p50':>9}"
        lines.append(hdr)
        sep = f"  {'-' * 4}  {'-' * 10}  {'-' * 7}  {'-' * 7}  {'-' * 8}  {'-' * 9}"
        lines.append(sep)
        for k in k_values:
            r = by_k[k]
            lines.append(
                f"  {k:>4}  {r.recall_at_k:>10.3f}  {r.precision_at_1:>7.3f}  "
                f"{r.mrr:>7.3f}  {r.server_recall_at_k:>8.3f}  "
                f"{r.latency_p50:>7.1f}ms"
            )
        lines.append("")

    return "\n".join(lines)


async def main(args: argparse.Namespace) -> None:
    settings = Settings()
    k_values: list[int] = sorted(args.k_values)
    use_wandb = not args.no_wandb

    # Setup
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=EMBEDDING_MODEL,
        dimension=EMBEDDING_DIMENSION,
    )
    qdrant_client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

    try:
        pool_server_ids = _load_pool_server_ids()
        pool_size = len(pool_server_ids)

        tool_store = QdrantStore(
            client=qdrant_client,
            collection_name=settings.qdrant_collection_name,
            pool_server_ids=pool_server_ids,
        )
        server_store = QdrantStore(client=qdrant_client, collection_name="mcp_servers")

        entries = _load_and_filter_gt(pool_server_ids)
        if not entries:
            logger.error("No GT entries after filtering. Aborting.")
            return

        logger.info(f"Running Recall@K baseline: K={k_values}, strategies=[Flat, Parallel]")
        logger.info(f"GT: {len(entries)} entries, Pool: {pool_size} servers, Reranker: none")

        # W&B init
        if use_wandb:
            wandb.init(
                project="mcp-discovery",
                name=f"recall-k-baseline-pool{pool_size}",
                config={
                    "experiment": "recall-k-baseline",
                    "k_values": k_values,
                    "pool_size": pool_size,
                    "embedding_model": EMBEDDING_MODEL,
                    "reranker": "none",
                    "n_queries": len(entries),
                },
            )

        # Build strategies (no reranker)
        strategies = {
            "FlatStrategy": FlatStrategy(
                embedder=embedder, tool_store=tool_store, reranker=None,
            ),
            "ParallelStrategy": ParallelStrategy(
                embedder=embedder,
                tool_store=tool_store,
                server_store=server_store,
                top_k_servers=5,
                reranker=None,
            ),
        }

        # Run evaluation for each strategy x K combination
        strategy_results: dict[str, dict[int, EvalResult]] = {}

        for strategy_name, strategy in strategies.items():
            strategy_results[strategy_name] = {}
            for k in k_values:
                logger.info(f"Running {strategy_name} with K={k}...")
                result = await evaluate(strategy, entries, top_k=k)
                strategy_results[strategy_name][k] = result

                if use_wandb:
                    wandb.log({
                        f"{strategy_name}/K{k}/recall_at_k": result.recall_at_k,
                        f"{strategy_name}/K{k}/precision_at_1": result.precision_at_1,
                        f"{strategy_name}/K{k}/mrr": result.mrr,
                        f"{strategy_name}/K{k}/server_recall_at_k": result.server_recall_at_k,
                        f"{strategy_name}/K{k}/latency_p50_ms": result.latency_p50,
                    })

        # Print results table
        output = _format_results_table(strategy_results, k_values, len(entries), pool_size)
        logger.info(output)

        # Build JSON output
        json_strategies = []
        for strategy_name, by_k in strategy_results.items():
            results_by_k = {}
            for k, result in by_k.items():
                results_by_k[str(k)] = _eval_result_to_dict(result)
            json_strategies.append({
                "name": strategy_name,
                "results_by_k": results_by_k,
            })

        payload = {
            "experiment": "recall-k-baseline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "embedding_model": EMBEDDING_MODEL,
                "pool_size": pool_size,
                "reranker": "none",
                "k_values": k_values,
                "gt_sources": ["seed_set", "mcp_atlas"],
            },
            "strategies": json_strategies,
        }

        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info(f"Results saved to {RESULTS_PATH}")

        if use_wandb:
            wandb.finish()

    finally:
        await qdrant_client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Recall@K Baseline -- Embedding-only retrieval without reranker"
    )
    parser.add_argument(
        "--k-values",
        type=int,
        nargs="+",
        default=DEFAULT_K_VALUES,
        help="K values to measure Recall@K for (default: 3 5 10)",
    )
    parser.add_argument(
        "--no-wandb",
        action="store_true",
        help="Disable W&B logging",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
