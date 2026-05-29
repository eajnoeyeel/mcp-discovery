"""E4 Experiment: Description A/B Validation.

Compares Precision@1 between original and enriched descriptions for 94
GT-covered tools across 2,273 queries.  Uses tool-level Wilcoxon
signed-rank test + cluster bootstrap CI to handle within-tool query
clustering.

The ONLY difference between Version A and B is the Qdrant collection:
  - A: mcp_tools           (original descriptions)
  - B: mcp_tools_e4_enriched (94 tools with Tool-DE enriched descriptions)

Both use the same embedder, reranker, strategy, GT queries, and pool filter.

Usage:
    # Smoke test (no reranker — fast, ~5 min)
    PYTHONPATH=src uv run python scripts/run_e4.py --no-rerank --no-wandb

    # Full run with reranker (Trial key: ~7.5h at 10 rpm)
    PYTHONPATH=src uv run python scripts/run_e4.py --no-wandb

    # Production key (fast)
    PYTHONPATH=src uv run python scripts/run_e4.py --cohere-rpm 95 --no-wandb
"""

import argparse
import asyncio
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from qdrant_client import AsyncQdrantClient

import wandb
from mcp_discovery.analytics.statistical import (
    cluster_bootstrap_ci,
    compute_tool_level_stats,
    wilcoxon_signed_rank,
)
from mcp_discovery.config import Settings
from mcp_discovery.data.ground_truth import load_ground_truth
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder
from mcp_discovery.evaluation.harness import evaluate
from mcp_discovery.evaluation.metrics import EvalResult
from mcp_discovery.models import GroundTruthEntry
from mcp_discovery.pipeline.flat import FlatStrategy
from mcp_discovery.pipeline.parallel import ParallelStrategy
from mcp_discovery.pipeline.sequential import SequentialStrategy
from mcp_discovery.reranking.cohere_reranker import CohereReranker
from mcp_discovery.retrieval.qdrant_store import QdrantStore

load_dotenv()

# --- Paths ---
GT_ATLAS_PATH = Path("data/ground_truth/mcp_atlas.jsonl")
POOL_PATH = Path("data/tool-pools/base_pool.json")
ENRICHED_PATH = Path("data/e4/enriched_descriptions.jsonl")
RESULTS_DIR = Path("data/e4")

# --- Collection names ---
ORIGINAL_COLLECTION = "mcp_tools"
ENRICHED_COLLECTION = "mcp_tools_e4_enriched"

# --- Embedding ---
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIM = 3072


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_pool_server_ids() -> list[str]:
    """Load ordered server IDs from base_pool.json."""
    if not POOL_PATH.exists():
        raise FileNotFoundError(
            f"base_pool.json not found at {POOL_PATH}. "
            "Run: uv run python scripts/build_base_pool.py"
        )
    pool: list[str] = json.loads(POOL_PATH.read_text())
    logger.info(f"Loaded {len(pool)}-server pool from {POOL_PATH}")
    return pool


def _load_gt_entries(pool_server_ids: list[str]) -> list[GroundTruthEntry]:
    """Load GT entries from mcp_atlas.jsonl, filtered to pool-covered servers."""
    if not GT_ATLAS_PATH.exists():
        raise FileNotFoundError(f"GT file not found: {GT_ATLAS_PATH}")
    all_entries = load_ground_truth(GT_ATLAS_PATH)
    pool_set = set(pool_server_ids)
    filtered = [e for e in all_entries if e.correct_server_id in pool_set]
    logger.info(
        f"GT: {len(all_entries)} total, {len(filtered)} covered by pool "
        f"({len(filtered) / len(all_entries) * 100:.1f}%)"
    )
    return filtered


def _load_enriched_tool_ids() -> set[str]:
    """Load set of tool_ids that have enriched descriptions."""
    if not ENRICHED_PATH.exists():
        logger.warning(f"Enriched descriptions not found: {ENRICHED_PATH}")
        return set()
    tool_ids: set[str] = set()
    for line in ENRICHED_PATH.read_text().splitlines():
        if line.strip():
            tool_ids.add(json.loads(line)["tool_id"])
    return tool_ids


def _build_strategy(
    name: str,
    embedder: OpenAIEmbedder,
    tool_store: QdrantStore,
    server_store: QdrantStore,
    reranker: CohereReranker | None,
):
    """Build a PipelineStrategy by name."""
    if name == "flat":
        return FlatStrategy(embedder=embedder, tool_store=tool_store, reranker=reranker)
    if name == "sequential":
        return SequentialStrategy(
            embedder=embedder,
            tool_store=tool_store,
            server_store=server_store,
            top_k_servers=5,
            reranker=reranker,
        )
    if name == "parallel":
        return ParallelStrategy(
            embedder=embedder,
            tool_store=tool_store,
            server_store=server_store,
            top_k_servers=5,
            reranker=reranker,
        )
    raise ValueError(f"Unknown strategy: {name}")


def _per_query_to_dicts(
    eval_result: EvalResult,
    entries: list[GroundTruthEntry],
) -> list[dict]:
    """Convert EvalResult per_query to dicts for the statistical module.

    The harness iterates GT entries sequentially, so per_query and entries
    are aligned by index.
    """
    results: list[dict] = []
    for pq, entry in zip(eval_result.per_query, entries):
        results.append(
            {
                "tool_id": entry.correct_tool_id,
                "query_id": pq.query_id,
                "top_1_correct": pq.top_1_correct,
            }
        )
    return results


def _eval_result_to_dict(result: EvalResult) -> dict:
    """Convert EvalResult to JSON-serializable dict (excluding per_query)."""
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


def _format_comparison_table(
    result_a: EvalResult,
    result_b: EvalResult,
    n_entries: int,
    strategy: str,
) -> str:
    """Format a side-by-side comparison table for A vs B."""
    col_w = 18
    header = (
        f"\n{'=' * 64}\n"
        f"E4 COMPARISON  (n={n_entries}, strategy={strategy})\n"
        f"{'=' * 64}\n"
        f"{'Metric':<22} {'A (original)':>{col_w}} {'B (enriched)':>{col_w}} {'Delta':>{col_w}}\n"
        f"{'-' * 22} {'-' * col_w} {'-' * col_w} {'-' * col_w}\n"
    )
    metrics = [
        ("Precision@1", "precision_at_1"),
        ("Recall@K", "recall_at_k"),
        ("Server Recall@K", "server_recall_at_k"),
        ("MRR", "mrr"),
        ("NDCG@5", "ndcg_at_5"),
        ("Confusion Rate", "confusion_rate"),
    ]
    rows: list[str] = []
    for label, attr in metrics:
        val_a = getattr(result_a, attr)
        val_b = getattr(result_b, attr)
        if val_a is not None and val_b is not None:
            delta = val_b - val_a
            rows.append(f"{label:<22} {val_a:>{col_w}.4f} {val_b:>{col_w}.4f} {delta:>+{col_w}.4f}")
        else:
            a_str = f"{val_a:.4f}" if val_a is not None else "N/A"
            b_str = f"{val_b:.4f}" if val_b is not None else "N/A"
            rows.append(f"{label:<22} {a_str:>{col_w}} {b_str:>{col_w}} {'N/A':>{col_w}}")

    latency_metrics = [
        ("Latency p50 (ms)", "latency_p50"),
        ("Latency mean (ms)", "latency_mean"),
    ]
    for label, attr in latency_metrics:
        val_a = getattr(result_a, attr)
        val_b = getattr(result_b, attr)
        delta = val_b - val_a
        rows.append(f"{label:<22} {val_a:>{col_w}.1f} {val_b:>{col_w}.1f} {delta:>+{col_w}.1f}")

    return header + "\n".join(rows) + "\n"


def _estimate_time(n_queries: int, cohere_rpm: int, use_reranker: bool) -> str:
    """Estimate total experiment time."""
    if not use_reranker:
        return "~5-10 min (embedding only, no reranker)"
    total_calls = n_queries * 2  # A + B
    minutes = math.ceil(total_calls / cohere_rpm)
    hours = minutes / 60
    if hours >= 1:
        return f"~{hours:.1f}h ({total_calls} rerank calls at {cohere_rpm} rpm)"
    return f"~{minutes} min ({total_calls} rerank calls at {cohere_rpm} rpm)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    settings = Settings()

    # --- Load data ---
    pool_server_ids = _load_pool_server_ids()
    entries = _load_gt_entries(pool_server_ids)
    if not entries:
        logger.error("No GT entries after pool filtering. Aborting.")
        return

    enriched_tool_ids = _load_enriched_tool_ids()
    logger.info(f"Enriched tools: {len(enriched_tool_ids)}")

    # Count unique tools in GT
    gt_tool_ids = {e.correct_tool_id for e in entries}
    enriched_in_gt = enriched_tool_ids & gt_tool_ids
    logger.info(f"GT unique tools: {len(gt_tool_ids)}, enriched & in GT: {len(enriched_in_gt)}")

    # --- Setup shared components ---
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=EMBEDDING_MODEL,
        dimension=EMBEDDING_DIM,
    )
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

    reranker: CohereReranker | None = None
    legacy_rerank_api_key = os.getenv("COHERE_API_KEY")
    legacy_rerank_model = os.getenv("RERANK_MODEL", "rerank-v3.5")
    use_reranker = not args.no_rerank and bool(legacy_rerank_api_key)
    if use_reranker:
        try:
            reranker = CohereReranker(
                api_key=legacy_rerank_api_key,
                model=legacy_rerank_model,
                max_rpm=args.cohere_rpm,
            )
            logger.info(f"Legacy reranker enabled: {legacy_rerank_model} (rpm={args.cohere_rpm})")
        except RuntimeError as exc:
            reranker = None
            use_reranker = False
            logger.warning(f"Legacy reranker unavailable; running without reranker: {exc}")
    elif args.no_rerank:
        logger.info("Reranker disabled via --no-rerank flag")
    else:
        logger.info("Legacy reranker API key not set -- running without reranker")

    # --- Estimate time ---
    est = _estimate_time(len(entries), args.cohere_rpm, use_reranker)
    logger.info(f"Estimated time: {est}")

    try:
        server_store = QdrantStore(client=client, collection_name="mcp_servers")

        # --- Version A: Original descriptions ---
        logger.info(f"\n{'=' * 50}")
        logger.info("Version A: Original descriptions")
        logger.info(f"Collection: {ORIGINAL_COLLECTION}")
        logger.info(f"{'=' * 50}")

        original_store = QdrantStore(
            client=client,
            collection_name=ORIGINAL_COLLECTION,
            pool_server_ids=pool_server_ids,
        )
        strategy_a = _build_strategy(
            args.strategy, embedder, original_store, server_store, reranker
        )
        result_a = await evaluate(strategy_a, entries, top_k=args.top_k)

        # --- Version B: Enriched descriptions ---
        logger.info(f"\n{'=' * 50}")
        logger.info("Version B: Enriched descriptions")
        logger.info(f"Collection: {ENRICHED_COLLECTION}")
        logger.info(f"{'=' * 50}")

        enriched_store = QdrantStore(
            client=client,
            collection_name=ENRICHED_COLLECTION,
            pool_server_ids=pool_server_ids,
        )
        strategy_b = _build_strategy(
            args.strategy, embedder, enriched_store, server_store, reranker
        )
        result_b = await evaluate(strategy_b, entries, top_k=args.top_k)

        # --- Comparison Table ---
        table = _format_comparison_table(result_a, result_b, len(entries), args.strategy)
        logger.info(table)

        # --- Statistical Analysis ---
        logger.info(f"\n{'=' * 50}")
        logger.info("Statistical Analysis (tool-level)")
        logger.info(f"{'=' * 50}")

        before_dicts = _per_query_to_dicts(result_a, entries)
        after_dicts = _per_query_to_dicts(result_b, entries)
        comparisons = compute_tool_level_stats(before_dicts, after_dicts)

        stat, p_value = wilcoxon_signed_rank(comparisons)
        ci_low, ci_high, mean_delta = cluster_bootstrap_ci(comparisons, seed=42)

        logger.info("Wilcoxon signed-rank test:")
        logger.info(f"  statistic = {stat:.3f}")
        logger.info(f"  p-value   = {p_value:.6f}")
        logger.info(f"  Mean delta: {mean_delta:+.4f} [{ci_low:+.4f}, {ci_high:+.4f}] (95% CI)")
        significance = "SIGNIFICANT" if p_value < 0.05 else "NOT SIGNIFICANT"
        logger.info(f"  Judgment: {significance} (alpha=0.05)")

        # --- Per-tool breakdown ---
        improved = [c for c in comparisons if c.p1_after > c.p1_before]
        degraded = [c for c in comparisons if c.p1_after < c.p1_before]
        same = [c for c in comparisons if c.p1_after == c.p1_before]

        logger.info(f"\nPer-tool breakdown ({len(comparisons)} tools):")
        logger.info(f"  Improved: {len(improved)}, Degraded: {len(degraded)}, Same: {len(same)}")

        for c in sorted(comparisons, key=lambda x: x.p1_after - x.p1_before, reverse=True):
            delta = c.p1_after - c.p1_before
            if delta > 0:
                marker = "^"
            elif delta < 0:
                marker = "v"
            else:
                marker = "="
            is_enriched = "*" if c.tool_id in enriched_tool_ids else " "
            logger.info(
                f"  {marker}{is_enriched} {c.tool_id}: "
                f"{c.p1_before:.3f} -> {c.p1_after:.3f} "
                f"({delta:+.3f}) [n={c.n_queries}]"
            )

        # --- Save results ---
        delta_p1 = result_b.precision_at_1 - result_a.precision_at_1
        baseline_p1 = max(result_a.precision_at_1, 1e-9)
        lift_pct = (delta_p1 / baseline_p1) * 100

        payload = {
            "experiment": "E4",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "strategy": args.strategy,
                "top_k": args.top_k,
                "embedding_model": EMBEDDING_MODEL,
                "reranker": legacy_rerank_model if reranker else "none",
                "cohere_rpm": args.cohere_rpm if reranker else None,
                "pool_size": len(pool_server_ids),
                "n_enriched_tools": len(enriched_tool_ids),
                "n_gt_queries": len(entries),
                "n_unique_tools_in_gt": len(gt_tool_ids),
                "n_enriched_in_gt": len(enriched_in_gt),
                "gt_source": "mcp_atlas.jsonl",
            },
            "results": {
                "version_a": _eval_result_to_dict(result_a),
                "version_b": _eval_result_to_dict(result_b),
                "delta_p1": delta_p1,
                "lift_pct": lift_pct,
            },
            "statistics": {
                "test": "wilcoxon_signed_rank",
                "statistic": stat,
                "p_value": p_value,
                "mean_delta": mean_delta,
                "ci_95_lower": ci_low,
                "ci_95_upper": ci_high,
                "n_tools": len(comparisons),
                "improved": len(improved),
                "degraded": len(degraded),
                "same": len(same),
            },
            "per_tool": [
                {
                    "tool_id": c.tool_id,
                    "p1_before": c.p1_before,
                    "p1_after": c.p1_after,
                    "delta": c.p1_after - c.p1_before,
                    "n_queries": c.n_queries,
                    "is_enriched": c.tool_id in enriched_tool_ids,
                }
                for c in sorted(
                    comparisons,
                    key=lambda x: x.p1_after - x.p1_before,
                    reverse=True,
                )
            ],
        }
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result_path = RESULTS_DIR / "e4_result.json"
        result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info(f"\nResults saved to {result_path}")

        # --- W&B logging ---
        if not args.no_wandb:
            wandb.init(
                project="mcp-discovery",
                name=f"E4-{args.strategy}",
                config=payload["config"],
            )
            wandb.log(
                {
                    "version_a/precision_at_1": result_a.precision_at_1,
                    "version_a/recall_at_k": result_a.recall_at_k,
                    "version_a/mrr": result_a.mrr,
                    "version_b/precision_at_1": result_b.precision_at_1,
                    "version_b/recall_at_k": result_b.recall_at_k,
                    "version_b/mrr": result_b.mrr,
                    "delta/precision_at_1": delta_p1,
                    "delta/lift_pct": lift_pct,
                    "statistics/p_value": p_value,
                    "statistics/mean_delta": mean_delta,
                    "statistics/ci_95_lower": ci_low,
                    "statistics/ci_95_upper": ci_high,
                    "tools/improved": len(improved),
                    "tools/degraded": len(degraded),
                    "tools/same": len(same),
                }
            )
            wandb.finish()

    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="E4: Description A/B Validation")
    parser.add_argument(
        "--strategy",
        choices=["flat", "sequential", "parallel"],
        default="parallel",
        help="Pipeline strategy (default: parallel)",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="Disable Cohere reranker (embedding-only mode)",
    )
    parser.add_argument(
        "--cohere-rpm",
        type=int,
        default=10,
        help="Cohere API rate limit in requests/min (default: 10 for Trial key)",
    )
    parser.add_argument(
        "--no-wandb",
        action="store_true",
        help="Disable W&B logging",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
