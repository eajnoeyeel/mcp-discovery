"""Hybrid Search Recall@K Baseline — dense + sparse (SPLADE) with RRF fusion.

Compares hybrid search against dense-only baseline to measure improvement.
Requires: mcp_tools_hybrid collection (built by build_hybrid_index.py).

Usage:
    PYTHONPATH=src uv run python scripts/run_hybrid_baseline.py
    PYTHONPATH=src uv run python scripts/run_hybrid_baseline.py --no-wandb
    PYTHONPATH=src uv run python scripts/run_hybrid_baseline.py --k-values 3 5 10
    PYTHONPATH=src uv run python scripts/run_hybrid_baseline.py --emit-rrf-distribution
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from qdrant_client import AsyncQdrantClient

import wandb
from mcp_discovery.config import Settings
from mcp_discovery.data.ground_truth import load_ground_truth
from mcp_discovery.embedding.fastembed_sparse import FastEmbedSparseEmbedder
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder
from mcp_discovery.evaluation.harness import evaluate
from mcp_discovery.evaluation.metrics import EvalResult
from mcp_discovery.models import GroundTruthEntry
from mcp_discovery.pipeline.flat import FlatStrategy
from mcp_discovery.retrieval.qdrant_store import QdrantStore

load_dotenv()

GT_ATLAS_PATH = Path("data/ground_truth/mcp_atlas.jsonl")
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSION = 3072
BASE_POOL_PATH = Path("data/tool-pools/base_pool.json")
RESULTS_PATH = Path("data/results/hybrid_baseline.json")

HYBRID_COLLECTION = "mcp_tools_hybrid"
DENSE_COLLECTION = "mcp_tools"

DEFAULT_K_VALUES = [3, 5, 10]

# Dense-only baseline from previous measurement (for comparison table)
DENSE_BASELINE = {
    3: {"recall_at_k": 0.2151, "precision_at_1": 0.1337, "mrr": 0.1682},
    5: {"recall_at_k": 0.2556, "precision_at_1": 0.1337, "mrr": 0.1774},
    10: {"recall_at_k": 0.2824, "precision_at_1": 0.1337, "mrr": 0.1822},
}


RRF_DISTRIBUTION_PATH = Path("data/results/rrf_distribution.json")


def _compute_rrf_distribution(gaps: list[float]) -> dict:
    """Compute percentile statistics over RRF rank1-rank2 score gaps."""
    if not gaps:
        return {
            "gaps": [],
            "count": 0,
            "percentiles": {"p50": None, "p75": None, "p90": None},
        }
    sorted_gaps = sorted(gaps)
    n = len(sorted_gaps)
    return {
        "gaps": sorted_gaps,
        "count": n,
        "percentiles": {
            "p50": sorted_gaps[int(n * 0.50)],
            "p75": sorted_gaps[int(n * 0.75)],
            "p90": sorted_gaps[int(n * 0.90)],
        },
    }


async def _collect_rrf_gaps(
    strategy: FlatStrategy,
    entries: list,
) -> list[float]:
    """Query the hybrid strategy with top_k=2 for each GT entry and collect rank1-rank2 score gaps.

    Only queries that return at least 2 hits contribute a gap value.
    """
    gaps: list[float] = []
    for entry in entries:
        try:
            hits = await strategy.search(entry.query, top_k=2)
            if len(hits) >= 2:
                gaps.append(hits[0].score - hits[1].score)
        except Exception as e:
            logger.warning(f"RRF gap collection failed for query_id={entry.query_id}: {e}")
    return gaps


def _load_pool_server_ids() -> list[str]:
    if not BASE_POOL_PATH.exists():
        raise FileNotFoundError(f"base_pool.json not found at {BASE_POOL_PATH}")
    ordered: list[str] = json.loads(BASE_POOL_PATH.read_text())
    logger.info(f"Loaded {len(ordered)}-server pool from {BASE_POOL_PATH}")
    return ordered


def _load_and_filter_gt(pool_server_ids: list[str]) -> list[GroundTruthEntry]:
    pool_set = set(pool_server_ids)
    if not GT_ATLAS_PATH.exists():
        logger.error(f"GT file not found: {GT_ATLAS_PATH}")
        return []
    entries = load_ground_truth(GT_ATLAS_PATH)
    filtered = [e for e in entries if e.correct_server_id in pool_set]
    logger.info(f"GT: {len(entries)} total, {len(filtered)} covered by pool")
    return filtered


def _eval_to_dict(result: EvalResult) -> dict:
    return {
        "precision_at_1": result.precision_at_1,
        "recall_at_k": result.recall_at_k,
        "server_recall_at_k": result.server_recall_at_k,
        "mrr": result.mrr,
        "ndcg_at_5": result.ndcg_at_5,
        "confusion_rate": result.confusion_rate,
        "latency_p50": result.latency_p50,
        "latency_p95": result.latency_p95,
        "latency_mean": result.latency_mean,
        "n_queries": result.n_queries,
        "n_failed": result.n_failed,
    }


def _format_comparison_table(
    hybrid_results: dict[int, EvalResult],
    k_values: list[int],
    n_entries: int,
    pool_size: int,
) -> str:
    lines = [
        f"\n{'=' * 80}",
        f"HYBRID vs DENSE-ONLY COMPARISON  (n={n_entries}, pool={pool_size})",
        f"{'=' * 80}",
        "",
        f"  {'K':>4}  {'Hybrid R@K':>11}  {'Dense R@K':>10}  {'Delta':>7}  "
        f"{'Hybrid P@1':>11}  {'Hybrid MRR':>11}  {'Lat p50':>9}",
        f"  {'-' * 4}  {'-' * 11}  {'-' * 10}  {'-' * 7}  "
        f"{'-' * 11}  {'-' * 11}  {'-' * 9}",
    ]
    for k in k_values:
        hr = hybrid_results[k]
        db = DENSE_BASELINE.get(k, {})
        dense_r = db.get("recall_at_k", 0)
        delta = hr.recall_at_k - dense_r
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"  {k:>4}  {hr.recall_at_k:>11.3f}  {dense_r:>10.3f}  "
            f"{sign}{delta:>6.3f}  {hr.precision_at_1:>11.3f}  "
            f"{hr.mrr:>11.3f}  {hr.latency_p50:>7.1f}ms"
        )
    lines.append("")
    return "\n".join(lines)


async def main(args: argparse.Namespace) -> None:
    settings = Settings()
    k_values: list[int] = sorted(args.k_values)
    use_wandb = not args.no_wandb

    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=EMBEDDING_MODEL,
        dimension=EMBEDDING_DIMENSION,
    )
    sparse_embedder = FastEmbedSparseEmbedder()
    qdrant_client = AsyncQdrantClient(
        url=settings.qdrant_url, api_key=settings.qdrant_api_key
    )

    try:
        pool_server_ids = _load_pool_server_ids()
        pool_size = len(pool_server_ids)

        hybrid_store = QdrantStore(
            client=qdrant_client,
            collection_name=HYBRID_COLLECTION,
            pool_server_ids=pool_server_ids,
        )

        entries = _load_and_filter_gt(pool_server_ids)
        if not entries:
            logger.error("No GT entries. Aborting.")
            return

        logger.info(
            f"Running Hybrid Recall@K: K={k_values}, "
            f"n={len(entries)}, pool={pool_size}"
        )

        if use_wandb:
            wandb.init(
                project="mcp-discovery",
                name=f"hybrid-baseline-pool{pool_size}",
                config={
                    "experiment": "hybrid-baseline",
                    "k_values": k_values,
                    "pool_size": pool_size,
                    "dense_model": EMBEDDING_MODEL,
                    "sparse_model": "prithivida/Splade_PP_en_v1",
                    "fusion": "RRF",
                    "reranker": "none",
                    "n_queries": len(entries),
                },
            )

        strategy = FlatStrategy(
            embedder=embedder,
            tool_store=hybrid_store,
            reranker=None,
            sparse_embedder=sparse_embedder,
        )

        hybrid_results: dict[int, EvalResult] = {}
        for k in k_values:
            logger.info(f"Running Hybrid FlatStrategy with K={k}...")
            result = await evaluate(strategy, entries, top_k=k)
            hybrid_results[k] = result

            if use_wandb:
                wandb.log({
                    f"hybrid/K{k}/recall_at_k": result.recall_at_k,
                    f"hybrid/K{k}/precision_at_1": result.precision_at_1,
                    f"hybrid/K{k}/mrr": result.mrr,
                    f"hybrid/K{k}/server_recall_at_k": result.server_recall_at_k,
                    f"hybrid/K{k}/latency_p50_ms": result.latency_p50,
                })

        # Print comparison table
        output = _format_comparison_table(hybrid_results, k_values, len(entries), pool_size)
        logger.info(output)

        # Save JSON
        json_results = {}
        for k, result in hybrid_results.items():
            json_results[str(k)] = _eval_to_dict(result)

        payload = {
            "experiment": "hybrid-baseline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "dense_model": EMBEDDING_MODEL,
                "sparse_model": "prithivida/Splade_PP_en_v1",
                "fusion": "RRF",
                "pool_size": pool_size,
                "reranker": "none",
                "k_values": k_values,
                "collection": HYBRID_COLLECTION,
            },
            "hybrid_results_by_k": json_results,
            "dense_baseline": {str(k): v for k, v in DENSE_BASELINE.items()},
        }

        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info(f"Results saved to {RESULTS_PATH}")

        if args.emit_rrf_distribution:
            logger.info("Collecting RRF rank1-rank2 gap distribution (top_k=2 pass)...")
            gaps = await _collect_rrf_gaps(strategy, entries)
            distribution = _compute_rrf_distribution(gaps)
            RRF_DISTRIBUTION_PATH.parent.mkdir(parents=True, exist_ok=True)
            RRF_DISTRIBUTION_PATH.write_text(json.dumps(distribution, indent=2, ensure_ascii=False))
            logger.info(
                f"RRF distribution written to {RRF_DISTRIBUTION_PATH} "
                f"(n={distribution['count']}, percentiles={distribution['percentiles']})"
            )

        if use_wandb:
            wandb.finish()

    finally:
        await qdrant_client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Hybrid Search Recall@K Baseline"
    )
    parser.add_argument(
        "--k-values",
        type=int,
        nargs="+",
        default=DEFAULT_K_VALUES,
        help="K values (default: 3 5 10)",
    )
    parser.add_argument(
        "--no-wandb",
        action="store_true",
        help="Disable W&B logging",
    )
    parser.add_argument(
        "--emit-rrf-distribution",
        action="store_true",
        help="Write RRF rank1-rank2 gap distribution to data/results/rrf_distribution.json",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
