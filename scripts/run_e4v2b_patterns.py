"""E4v2b Experiment: Description Pattern Comparison (7 Variants).

Extends E4v2 by testing 7 description variants (V0-V6) to identify which
description patterns most effectively steer reranker selection while
minimizing false selection (gaming).

Design:
  - 7 variants: V0 (original), V1 (enriched from E4v2), V2-V6 (new patterns)
  - V0 and V1 results imported from E4v2 results to save API calls
  - Only V2-V6 require new legacy reranker calls (5 variants x 611 queries = 3,055)
  - Statistical tests:
      Cochran's Q (k-way McNemar for 7 variants)
      Pairwise McNemar with Bonferroni correction (21 pairs, alpha=0.0024)
  - Gaming Index = FSR_variant - FSR_V0
  - Net Selection Score = TSR_uplift - Gaming_Index

Usage:
    PYTHONPATH=src uv run python scripts/run_e4v2b_patterns.py --cohere-rpm 95
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from loguru import logger
from scipy import stats as scipy_stats

try:
    import cohere
except ImportError:  # pragma: no cover - optional legacy experiment dependency
    cohere = None  # type: ignore[assignment]

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CLUSTERS_PATH = Path("data/e4v2/clusters.json")
E4V2_RESULTS_PATH = Path("data/e4v2/results.json")
VARIANTS_PATH = Path("data/e4v2b/variants.json")
RESULTS_PATH = Path("data/e4v2b/results.json")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RERANK_MODEL = "rerank-v3.5"
ALL_VARIANTS = ("V0", "V1", "V2", "V3", "V4", "V5", "V6")
IMPORTED_VARIANTS = ("V0", "V1")
NEW_VARIANTS = ("V2", "V3", "V4", "V5", "V6")
BONFERRONI_ALPHA = 0.05 / 21  # 21 pairwise comparisons -> ~0.002381


def _create_legacy_rerank_client(api_key: str) -> Any | None:
    """Create the optional legacy reranker client when its package is installed."""
    if cohere is None:
        logger.error(
            "Optional legacy reranker package is not installed. "
            "Install 'cohere' separately only when reproducing E4v2b historical runs."
        )
        return None
    return cohere.AsyncClientV2(api_key=api_key)


# ---------------------------------------------------------------------------
# Data Containers (immutable where possible)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolInfo:
    tool_id: str
    tool_name: str
    original_description: str
    enriched_description: str


@dataclass(frozen=True)
class QueryEntry:
    query_id: str
    query: str
    correct_tool_id: str
    label: str  # "T" or "C"


@dataclass(frozen=True)
class ClusterDef:
    name: str
    target: str
    tools: tuple[ToolInfo, ...]
    queries: tuple[QueryEntry, ...]
    rationale: str


@dataclass
class QueryResult:
    """Result of a single reranker call for one query under one variant."""

    query_id: str
    query: str
    label: str  # "T" or "C"
    variant: str
    top1_tool_id: str
    target_rank: int
    target_score: float
    all_scores: dict[str, float]
    all_ranks: dict[str, int]


@dataclass(frozen=True)
class VariantDescription:
    """Description text for a specific variant of a specific tool."""

    variant: str
    tool_id: str
    description: str


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------
def _parse_tool_id(tool_id: str) -> str:
    """Extract tool_name from tool_id (server_id::tool_name)."""
    parts = tool_id.split("::")
    if len(parts) != 2:
        raise ValueError(f"Invalid tool_id format: {tool_id}")
    return parts[1]


def load_clusters(path: Path) -> list[ClusterDef]:
    """Load cluster definitions from JSON."""
    if not path.exists():
        raise FileNotFoundError(f"Clusters file not found: {path}")

    raw = json.loads(path.read_text())
    clusters: list[ClusterDef] = []

    for c in raw["clusters"]:
        tools = tuple(
            ToolInfo(
                tool_id=t["tool_id"],
                tool_name=_parse_tool_id(t["tool_id"]),
                original_description=t["original_description"].strip(),
                enriched_description=t["enriched_description"].strip(),
            )
            for t in c["tools"]
        )
        queries = tuple(
            QueryEntry(
                query_id=q["query_id"],
                query=q["query"],
                correct_tool_id=q["correct_tool_id"],
                label=q["label"],
            )
            for q in c["queries"]
        )
        clusters.append(
            ClusterDef(
                name=c["name"],
                target=c["target"],
                tools=tools,
                queries=queries,
                rationale=c.get("rationale", ""),
            )
        )

    return clusters


def load_variant_descriptions(path: Path) -> dict[str, dict[str, str]]:
    """Load variant descriptions from JSON.

    Supports the variants.json structure:
    {clusters: {cluster_name: {target: "...", variants: {V0: "desc", V1: "desc", ...}}}}

    Returns:
        Nested dict: {variant: {tool_id: description}}
        where tool_id is the target tool_id for that cluster.
    """
    if not path.exists():
        raise FileNotFoundError(f"Variants file not found: {path}")

    raw = json.loads(path.read_text())
    result: dict[str, dict[str, str]] = {}

    clusters_data = raw.get("clusters", {})
    for _cluster_name, cluster_info in clusters_data.items():
        target_tool_id = cluster_info["target"]
        variants = cluster_info.get("variants", {})
        for variant_key, desc in variants.items():
            if not variant_key.startswith("V"):
                continue
            if variant_key not in result:
                result[variant_key] = {}
            result[variant_key][target_tool_id] = desc.strip()

    return result


def import_e4v2_results(
    path: Path, clusters: list[ClusterDef]
) -> dict[str, dict[str, list[QueryResult]]]:
    """Import V0 and V1 per-query results from E4v2 results.json.

    Returns:
        {cluster_name: {variant: [QueryResult, ...]}}
    """
    if not path.exists():
        raise FileNotFoundError(f"E4v2 results not found: {path}")

    raw = json.loads(path.read_text())
    cluster_map = {c.name: c for c in clusters}
    imported: dict[str, dict[str, list[QueryResult]]] = {}

    for cluster_data in raw["clusters"]:
        cname = cluster_data["name"]
        if cname not in cluster_map:
            logger.warning(
                f"Cluster '{cname}' in E4v2 results not found in clusters.json, skipping"
            )
            continue

        imported[cname] = {}

        for variant in IMPORTED_VARIANTS:
            per_query = cluster_data.get("per_query", {}).get(variant, [])
            results: list[QueryResult] = []

            for pq in per_query:
                qr = QueryResult(
                    query_id=pq["query_id"],
                    query=pq["query"],
                    label=pq["label"],
                    variant=pq["variant"],
                    top1_tool_id=pq["top1_tool_id"],
                    target_rank=pq["target_rank"],
                    target_score=pq["target_score"],
                    all_scores=pq["all_scores"],
                    all_ranks=pq["all_ranks"],
                )
                results.append(qr)

            imported[cname][variant] = results

    return imported


# ---------------------------------------------------------------------------
# Candidate Document Building
# ---------------------------------------------------------------------------
def build_candidate_docs(
    cluster: ClusterDef,
    target_tool_id: str,
    variant_description: str | None,
) -> list[tuple[str, str]]:
    """Build (tool_id, document_text) pairs for reranker input.

    For V2-V6: target tool uses the variant description, all others use original.
    """
    candidates: list[tuple[str, str]] = []
    for tool in cluster.tools:
        if variant_description is not None and tool.tool_id == target_tool_id:
            desc = variant_description
        else:
            desc = tool.original_description
        doc_text = f"{tool.tool_name}: {desc}"
        candidates.append((tool.tool_id, doc_text))
    return candidates


def shuffle_candidates(
    candidates: list[tuple[str, str]],
    query_id: str,
    variant: str,
) -> list[tuple[str, str]]:
    """Reproducibly shuffle candidates using deterministic seed.

    Uses hashlib instead of built-in hash() because Python's hash() is
    randomized across processes (PYTHONHASHSEED).
    """
    shuffled = list(candidates)
    seed_bytes = hashlib.sha256((query_id + variant).encode()).digest()[:8]
    seed_int = int.from_bytes(seed_bytes, "big")
    random.seed(seed_int)
    random.shuffle(shuffled)
    return shuffled


# ---------------------------------------------------------------------------
# Cohere Rate Limiter
# ---------------------------------------------------------------------------
class RateLimiter:
    """Token-bucket rate limiter for API calls."""

    def __init__(self, max_rpm: int) -> None:
        self._max_rpm = max_rpm
        self._min_interval = 60.0 / max_rpm if max_rpm > 0 else 0.0
        self._last_call_time = 0.0

    async def wait(self) -> None:
        if self._min_interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_call_time = time.monotonic()


# ---------------------------------------------------------------------------
# Reranker Execution
# ---------------------------------------------------------------------------
async def rerank_query(
    client: cohere.AsyncClientV2,
    query: str,
    candidates: list[tuple[str, str]],
    target_tool_id: str,
    rate_limiter: RateLimiter,
) -> dict[str, Any]:
    """Call Cohere reranker and return structured result."""
    await rate_limiter.wait()

    tool_ids = [c[0] for c in candidates]
    documents = [c[1] for c in candidates]

    response = await client.rerank(
        model=RERANK_MODEL,
        query=query,
        documents=documents,
        top_n=len(documents),
    )

    all_scores: dict[str, float] = {}
    all_ranks: dict[str, int] = {}
    top1_tool_id = ""
    target_rank = -1
    target_score = 0.0

    for rank, item in enumerate(response.results, start=1):
        tid = tool_ids[item.index]
        score = item.relevance_score
        all_scores[tid] = score
        all_ranks[tid] = rank
        if rank == 1:
            top1_tool_id = tid
        if tid == target_tool_id:
            target_rank = rank
            target_score = score

    return {
        "top1_tool_id": top1_tool_id,
        "target_rank": target_rank,
        "target_score": target_score,
        "all_scores": all_scores,
        "all_ranks": all_ranks,
    }


# ---------------------------------------------------------------------------
# Experiment Runner (V2-V6 only)
# ---------------------------------------------------------------------------
async def run_new_variants_for_cluster(
    client: cohere.AsyncClientV2,
    cluster: ClusterDef,
    variant_descriptions: dict[str, dict[str, str]],
    rate_limiter: RateLimiter,
) -> dict[str, list[QueryResult]]:
    """Run V2-V6 for all queries in a cluster.

    Returns:
        {"V2": [...], "V3": [...], ...} -- lists of QueryResult per variant
    """
    queries = list(cluster.queries)
    results: dict[str, list[QueryResult]] = {v: [] for v in NEW_VARIANTS}

    for variant in NEW_VARIANTS:
        # Get the variant description for the target tool
        tool_descs = variant_descriptions.get(variant, {})
        target_desc = tool_descs.get(cluster.target)

        if target_desc is None:
            logger.error(
                f"  [{cluster.name}] {variant}: no description for target "
                f"'{cluster.target}', skipping"
            )
            continue

        base_candidates = build_candidate_docs(
            cluster=cluster,
            target_tool_id=cluster.target,
            variant_description=target_desc,
        )

        logger.info(
            f"  [{cluster.name}] {variant}: running {len(queries)} queries "
            f"({len(base_candidates)} candidates)"
        )

        for i, qe in enumerate(queries):
            shuffled = shuffle_candidates(base_candidates, qe.query_id, variant)

            try:
                rr = await rerank_query(
                    client=client,
                    query=qe.query,
                    candidates=shuffled,
                    target_tool_id=cluster.target,
                    rate_limiter=rate_limiter,
                )
            except Exception as e:
                logger.error(f"    Rerank failed for {qe.query_id} ({variant}): {e}")
                continue

            qr = QueryResult(
                query_id=qe.query_id,
                query=qe.query,
                label=qe.label,
                variant=variant,
                top1_tool_id=rr["top1_tool_id"],
                target_rank=rr["target_rank"],
                target_score=rr["target_score"],
                all_scores=rr["all_scores"],
                all_ranks=rr["all_ranks"],
            )
            results[variant].append(qr)

            if (i + 1) % 20 == 0 or (i + 1) == len(queries):
                logger.info(f"    [{variant}] {i + 1}/{len(queries)} done")

    return results


# ---------------------------------------------------------------------------
# Metrics (reused from E4v2 with identical logic)
# ---------------------------------------------------------------------------
def _safe_round(v: float, digits: int = 4) -> float:
    """Round unless NaN."""
    if math.isnan(v):
        return v
    return round(v, digits)


def compute_tsr(results: list[QueryResult], target: str) -> float:
    """Target Selection Rate: fraction of T-queries where target is top-1."""
    t_queries = [r for r in results if r.label == "T"]
    if not t_queries:
        return float("nan")
    return sum(1 for r in t_queries if r.top1_tool_id == target) / len(t_queries)


def compute_fsr(results: list[QueryResult], target: str) -> float:
    """False Selection Rate: fraction of C-queries where target is (wrongly) top-1."""
    c_queries = [r for r in results if r.label == "C"]
    if not c_queries:
        return float("nan")
    return sum(1 for r in c_queries if r.top1_tool_id == target) / len(c_queries)


def compute_selection_precision(tsr: float, fsr: float, n_t: int, n_c: int) -> float:
    """Selection Precision: TP / (TP + FP)."""
    if math.isnan(tsr) or math.isnan(fsr):
        return float("nan")
    tp = tsr * n_t
    fp = fsr * n_c
    if (tp + fp) == 0:
        return float("nan")
    return tp / (tp + fp)


def compute_mean_score_gap(results: list[QueryResult], target: str) -> float:
    """Mean score gap for T-queries where target IS top-1."""
    t_queries = [r for r in results if r.label == "T"]
    gaps: list[float] = []
    for r in t_queries:
        if r.top1_tool_id == target:
            others = [s for tid, s in r.all_scores.items() if tid != target]
            if others:
                gaps.append(r.all_scores[target] - max(others))
    if not gaps:
        return float("nan")
    return sum(gaps) / len(gaps)


def compute_variant_metrics(
    results: list[QueryResult],
    target: str,
) -> dict[str, Any]:
    """Compute all metrics for one variant's results."""
    n_t = sum(1 for r in results if r.label == "T")
    n_c = sum(1 for r in results if r.label == "C")
    tsr = compute_tsr(results, target)
    fsr = compute_fsr(results, target)
    sp = compute_selection_precision(tsr, fsr, n_t, n_c)
    gap = compute_mean_score_gap(results, target)
    return {
        "tsr": _safe_round(tsr),
        "fsr": _safe_round(fsr),
        "sp": _safe_round(sp),
        "mean_score_gap": _safe_round(gap),
        "n_t": n_t,
        "n_c": n_c,
    }


# ---------------------------------------------------------------------------
# Cochran's Q Test
# ---------------------------------------------------------------------------
def cochrans_q_test(binary_matrix: np.ndarray) -> dict[str, Any]:
    """Cochran's Q test for k related binary samples.

    Args:
        binary_matrix: shape (n_queries, k_variants), value 0 or 1.
            Each row is a query, each column a variant.
            1 = target selected as top-1 for that query under that variant.

    Returns:
        Dict with keys: statistic, p_value, df
    """
    k = binary_matrix.shape[1]
    n = binary_matrix.shape[0]

    if n == 0 or k < 2:
        return {"statistic": float("nan"), "p_value": float("nan"), "df": k - 1}

    row_totals = binary_matrix.sum(axis=1)  # per-query
    col_totals = binary_matrix.sum(axis=0)  # per-variant
    grand_total = binary_matrix.sum()

    denominator = k * grand_total - (row_totals**2).sum()
    if denominator == 0:
        # All rows identical -> no variation
        return {"statistic": 0.0, "p_value": 1.0, "df": k - 1}

    q_stat = (k - 1) * (k * (col_totals**2).sum() - grand_total**2) / denominator
    df = k - 1
    p_value = 1.0 - scipy_stats.chi2.cdf(float(q_stat), df=df)

    return {
        "statistic": round(float(q_stat), 4),
        "p_value": round(p_value, 6),
        "df": df,
    }


# ---------------------------------------------------------------------------
# Pairwise McNemar Test
# ---------------------------------------------------------------------------
def pairwise_mcnemar(
    variant_results: dict[str, list[QueryResult]],
    target: str,
    variants: tuple[str, ...] = ALL_VARIANTS,
) -> list[dict[str, Any]]:
    """Pairwise McNemar tests for all variant pairs on T-queries.

    Returns:
        List of dicts, one per pair, with Bonferroni-corrected significance.
    """
    # Build per-variant T-query outcome maps: {query_id: bool(correct)}
    outcome_maps: dict[str, dict[str, bool]] = {}
    for v in variants:
        results = variant_results.get(v, [])
        outcome_maps[v] = {
            r.query_id: (r.top1_tool_id == target) for r in results if r.label == "T"
        }

    pairs: list[dict[str, Any]] = []
    variant_list = list(variants)

    for i in range(len(variant_list)):
        for j in range(i + 1, len(variant_list)):
            v_a = variant_list[i]
            v_b = variant_list[j]

            map_a = outcome_maps.get(v_a, {})
            map_b = outcome_maps.get(v_b, {})
            common = sorted(set(map_a.keys()) & set(map_b.keys()))

            if not common:
                pairs.append(
                    {
                        "pair": [v_a, v_b],
                        "statistic": float("nan"),
                        "p_value": float("nan"),
                        "n_discordant": 0,
                        "n_pairs": 0,
                        "significant_bonferroni": False,
                    }
                )
                continue

            # Build 2x2 contingency
            a_val, b_val, c_val, d_val = 0, 0, 0, 0
            for qid in common:
                a_correct = map_a[qid]
                b_correct = map_b[qid]
                if a_correct and b_correct:
                    a_val += 1
                elif a_correct and not b_correct:
                    b_val += 1
                elif not a_correct and b_correct:
                    c_val += 1
                else:
                    d_val += 1

            n_discordant = b_val + c_val

            if n_discordant == 0:
                pairs.append(
                    {
                        "pair": [v_a, v_b],
                        "statistic": 0.0,
                        "p_value": 1.0,
                        "n_discordant": 0,
                        "n_pairs": len(common),
                        "significant_bonferroni": False,
                    }
                )
                continue

            if n_discordant < 25:
                result = scipy_stats.binomtest(b_val, n_discordant, 0.5)
                p_value = result.pvalue
                statistic = float(b_val)
            else:
                statistic = (abs(b_val - c_val) - 1) ** 2 / n_discordant
                p_value = 1.0 - scipy_stats.chi2.cdf(statistic, df=1)

            pairs.append(
                {
                    "pair": [v_a, v_b],
                    "statistic": round(statistic, 4),
                    "p_value": round(p_value, 6),
                    "n_discordant": n_discordant,
                    "n_pairs": len(common),
                    "significant_bonferroni": p_value < BONFERRONI_ALPHA,
                }
            )

    return pairs


# ---------------------------------------------------------------------------
# Gaming Index & Net Selection Score
# ---------------------------------------------------------------------------
def compute_gaming_index(
    variant_metrics: dict[str, dict[str, Any]],
) -> dict[str, float]:
    """Gaming Index = FSR_variant - FSR_V0 for each variant."""
    fsr_v0 = variant_metrics.get("V0", {}).get("fsr", float("nan"))
    gaming: dict[str, float] = {}

    for v in ALL_VARIANTS:
        fsr_v = variant_metrics.get(v, {}).get("fsr", float("nan"))
        if math.isnan(fsr_v0) or math.isnan(fsr_v):
            gaming[v] = float("nan")
        else:
            gaming[v] = _safe_round(fsr_v - fsr_v0)

    return gaming


def compute_net_selection_score(
    variant_metrics: dict[str, dict[str, Any]],
    gaming_index: dict[str, float],
) -> dict[str, float]:
    """Net Selection Score = TSR_uplift - Gaming_Index for each variant."""
    tsr_v0 = variant_metrics.get("V0", {}).get("tsr", float("nan"))
    nss: dict[str, float] = {}

    for v in ALL_VARIANTS:
        tsr_v = variant_metrics.get(v, {}).get("tsr", float("nan"))
        gi = gaming_index.get(v, float("nan"))

        if math.isnan(tsr_v0) or math.isnan(tsr_v) or math.isnan(gi):
            nss[v] = float("nan")
        else:
            tsr_uplift = tsr_v - tsr_v0
            nss[v] = _safe_round(tsr_uplift - gi)

    return nss


# ---------------------------------------------------------------------------
# Per-Query Serialization
# ---------------------------------------------------------------------------
def _serialize_query_result(qr: QueryResult) -> dict[str, Any]:
    """Convert QueryResult to JSON-serializable dict."""
    return {
        "query_id": qr.query_id,
        "query": qr.query,
        "label": qr.label,
        "variant": qr.variant,
        "top1_tool_id": qr.top1_tool_id,
        "target_rank": qr.target_rank,
        "target_score": round(qr.target_score, 6),
        "all_scores": {k: round(v, 6) for k, v in qr.all_scores.items()},
        "all_ranks": qr.all_ranks,
    }


# ---------------------------------------------------------------------------
# Build Binary Matrix for Cochran's Q
# ---------------------------------------------------------------------------
def build_binary_matrix(
    variant_results: dict[str, list[QueryResult]],
    target: str,
    variants: tuple[str, ...] = ALL_VARIANTS,
) -> tuple[np.ndarray, list[str]]:
    """Build binary outcome matrix for T-queries across all variants.

    Returns:
        (matrix, query_ids) where matrix is (n_queries, k_variants) with
        1 = target was top-1, 0 = target was not top-1.
        Only includes queries present in ALL variants.
    """
    # Collect T-query IDs per variant
    t_query_ids_per_variant: dict[str, set[str]] = {}
    for v in variants:
        results = variant_results.get(v, [])
        t_query_ids_per_variant[v] = {r.query_id for r in results if r.label == "T"}

    # Find common T-query IDs across all variants
    if not t_query_ids_per_variant:
        return np.zeros((0, len(variants)), dtype=int), []

    common_ids = set.intersection(*t_query_ids_per_variant.values())
    common_ids_sorted = sorted(common_ids)

    if not common_ids_sorted:
        return np.zeros((0, len(variants)), dtype=int), []

    # Build outcome maps
    outcome_maps: dict[str, dict[str, bool]] = {}
    for v in variants:
        results = variant_results.get(v, [])
        outcome_maps[v] = {
            r.query_id: (r.top1_tool_id == target) for r in results if r.label == "T"
        }

    # Build matrix
    n = len(common_ids_sorted)
    k = len(variants)
    matrix = np.zeros((n, k), dtype=int)

    for col_idx, v in enumerate(variants):
        omap = outcome_maps.get(v, {})
        for row_idx, qid in enumerate(common_ids_sorted):
            matrix[row_idx, col_idx] = 1 if omap.get(qid, False) else 0

    return matrix, common_ids_sorted


# ---------------------------------------------------------------------------
# Logging Helpers
# ---------------------------------------------------------------------------
def _log_cluster_summary(
    cluster_name: str,
    target: str,
    variant_metrics: dict[str, dict[str, Any]],
    gaming_index: dict[str, float],
    net_selection_score: dict[str, float],
    cochrans_q: dict[str, Any],
    pattern_ranking: list[str],
) -> None:
    """Log a formatted summary table for one cluster."""
    col_w = 10
    header_parts = [f"{'Metric':<16}"]
    for v in ALL_VARIANTS:
        header_parts.append(f"{v:>{col_w}}")
    logger.info(f"\n  {''.join(header_parts)}")
    logger.info(f"  {'-' * (16 + col_w * len(ALL_VARIANTS))}")

    for metric_name in ("tsr", "fsr", "sp", "mean_score_gap"):
        row_parts = [f"{metric_name.upper():<16}"]
        for v in ALL_VARIANTS:
            val = variant_metrics.get(v, {}).get(metric_name, float("nan"))
            val_str = f"{val:.4f}" if not math.isnan(val) else "N/A"
            row_parts.append(f"{val_str:>{col_w}}")
        logger.info(f"  {''.join(row_parts)}")

    # Gaming Index
    row_parts = [f"{'GAMING_IDX':<16}"]
    for v in ALL_VARIANTS:
        gi = gaming_index.get(v, float("nan"))
        gi_str = f"{gi:+.4f}" if not math.isnan(gi) else "N/A"
        row_parts.append(f"{gi_str:>{col_w}}")
    logger.info(f"  {''.join(row_parts)}")

    # Net Selection Score
    row_parts = [f"{'NET_SEL_SCORE':<16}"]
    for v in ALL_VARIANTS:
        nss = net_selection_score.get(v, float("nan"))
        nss_str = f"{nss:+.4f}" if not math.isnan(nss) else "N/A"
        row_parts.append(f"{nss_str:>{col_w}}")
    logger.info(f"  {''.join(row_parts)}")

    # Cochran's Q
    logger.info(
        f"  Cochran's Q: statistic={cochrans_q['statistic']}, "
        f"p={cochrans_q['p_value']:.6f}, df={cochrans_q['df']}"
    )

    # Pattern ranking
    logger.info(f"  Pattern ranking (by TSR desc): {' > '.join(pattern_ranking)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main(args: argparse.Namespace) -> None:
    legacy_rerank_api_key = os.getenv("COHERE_API_KEY")
    if not legacy_rerank_api_key:
        logger.error("Legacy reranker API key not set in environment. Aborting.")
        return

    # --- Load data ---
    clusters = load_clusters(CLUSTERS_PATH)
    total_queries = sum(len(c.queries) for c in clusters)
    logger.info(f"Loaded {len(clusters)} clusters, {total_queries} total queries")

    for c in clusters:
        n_t = sum(1 for q in c.queries if q.label == "T")
        n_c = sum(1 for q in c.queries if q.label == "C")
        logger.info(
            f"  {c.name}: {len(c.tools)} tools, "
            f"{len(c.queries)} queries (T={n_t}, C={n_c}), "
            f"target={c.target}"
        )

    # --- Load variant descriptions ---
    variant_descriptions = load_variant_descriptions(VARIANTS_PATH)
    logger.info(f"Loaded variant descriptions for: {sorted(variant_descriptions.keys())}")
    for v_key, tool_descs in sorted(variant_descriptions.items()):
        logger.info(f"  {v_key}: {len(tool_descs)} tool descriptions")

    # --- Import V0/V1 from E4v2 ---
    imported = import_e4v2_results(E4V2_RESULTS_PATH, clusters)
    for cname, vdata in imported.items():
        for v, results in vdata.items():
            logger.info(f"  Imported {cname}/{v}: {len(results)} queries")

    # --- Setup legacy reranker client ---
    client = _create_legacy_rerank_client(legacy_rerank_api_key)
    if client is None:
        return
    rate_limiter = RateLimiter(max_rpm=args.cohere_rpm)
    logger.info(f"Legacy reranker client ready: model={RERANK_MODEL}, rpm={args.cohere_rpm}")

    # --- Estimate time ---
    n_new_calls = total_queries * len(NEW_VARIANTS)
    est_min = math.ceil(n_new_calls / args.cohere_rpm)
    logger.info(
        f"New API calls needed: {n_new_calls} "
        f"({len(NEW_VARIANTS)} variants x {total_queries} queries), "
        f"~{est_min} min ({est_min / 60:.1f}h)"
    )

    try:
        await _run_full_experiment(
            client,
            clusters,
            imported,
            variant_descriptions,
            rate_limiter,
            args,
        )
    finally:
        if hasattr(client, "close"):
            await client.close()


async def _run_full_experiment(
    client: cohere.AsyncClientV2,
    clusters: list[ClusterDef],
    imported: dict[str, dict[str, list[QueryResult]]],
    variant_descriptions: dict[str, dict[str, str]],
    rate_limiter: RateLimiter,
    args: argparse.Namespace,
) -> None:
    """Run the full E4v2b experiment across all clusters."""
    logger.info("\n=== FULL EXPERIMENT: E4v2b Pattern Comparison (7 Variants) ===")

    cluster_outputs: list[dict[str, Any]] = []
    all_gaming_detected: list[str] = []
    all_cochrans_significant = True

    for cluster in clusters:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Cluster: {cluster.name} (target: {cluster.target})")
        logger.info(f"{'=' * 60}")

        # --- Collect all variant results ---
        variant_results: dict[str, list[QueryResult]] = {}

        # Import V0/V1
        cluster_imported = imported.get(cluster.name, {})
        for v in IMPORTED_VARIANTS:
            variant_results[v] = cluster_imported.get(v, [])
            logger.info(f"  [{cluster.name}] {v}: imported {len(variant_results[v])} queries")

        # Run V2-V6
        new_results = await run_new_variants_for_cluster(
            client=client,
            cluster=cluster,
            variant_descriptions=variant_descriptions,
            rate_limiter=rate_limiter,
        )
        for v in NEW_VARIANTS:
            variant_results[v] = new_results.get(v, [])

        # --- Compute per-variant metrics ---
        variant_metrics: dict[str, dict[str, Any]] = {}
        for v in ALL_VARIANTS:
            results = variant_results.get(v, [])
            if results:
                variant_metrics[v] = compute_variant_metrics(results, cluster.target)
            else:
                variant_metrics[v] = {
                    "tsr": float("nan"),
                    "fsr": float("nan"),
                    "sp": float("nan"),
                    "mean_score_gap": float("nan"),
                    "n_t": 0,
                    "n_c": 0,
                }

        # --- Gaming Index ---
        gaming_index = compute_gaming_index(variant_metrics)

        # --- Net Selection Score ---
        net_selection_score = compute_net_selection_score(variant_metrics, gaming_index)

        # --- Detect gaming (FSR increase > 0.03 over V0) ---
        for v in ALL_VARIANTS:
            gi = gaming_index.get(v, 0.0)
            if not math.isnan(gi) and gi > 0.03:
                all_gaming_detected.append(f"{cluster.name}/{v}")

        # --- Cochran's Q test ---
        binary_matrix, common_qids = build_binary_matrix(variant_results, cluster.target)
        cochrans_q = cochrans_q_test(binary_matrix)
        if math.isnan(cochrans_q["p_value"]) or cochrans_q["p_value"] >= 0.05:
            all_cochrans_significant = False

        # --- Pairwise McNemar ---
        mcnemar_pairs = pairwise_mcnemar(variant_results, cluster.target)

        # --- Pattern ranking (by TSR descending) ---
        ranked = sorted(
            ALL_VARIANTS,
            key=lambda v: variant_metrics.get(v, {}).get("tsr", float("-inf")),
            reverse=True,
        )
        pattern_ranking = [
            v for v in ranked if not math.isnan(variant_metrics.get(v, {}).get("tsr", float("nan")))
        ]

        # --- Log summary ---
        _log_cluster_summary(
            cluster_name=cluster.name,
            target=cluster.target,
            variant_metrics=variant_metrics,
            gaming_index=gaming_index,
            net_selection_score=net_selection_score,
            cochrans_q=cochrans_q,
            pattern_ranking=pattern_ranking,
        )

        # --- Serialize per-query results ---
        per_query_serialized: dict[str, list[dict[str, Any]]] = {}
        for v in ALL_VARIANTS:
            per_query_serialized[v] = [
                _serialize_query_result(qr) for qr in variant_results.get(v, [])
            ]

        # --- Build cluster output ---
        cluster_output: dict[str, Any] = {
            "name": cluster.name,
            "target": cluster.target,
            "n_tools": len(cluster.tools),
            "n_t_queries": variant_metrics.get("V0", {}).get("n_t", 0),
            "n_c_queries": variant_metrics.get("V0", {}).get("n_c", 0),
            "variants": {
                v: {
                    k: val
                    for k, val in variant_metrics.get(v, {}).items()
                    if k not in ("n_t", "n_c")
                }
                for v in ALL_VARIANTS
            },
            "cochrans_q": cochrans_q,
            "pairwise_mcnemar": mcnemar_pairs,
            "gaming_index": gaming_index,
            "net_selection_score": net_selection_score,
            "pattern_ranking": pattern_ranking,
            "per_query": per_query_serialized,
        }
        cluster_outputs.append(cluster_output)

    # --- Summary ---
    logger.info(f"\n{'=' * 60}")
    logger.info("E4v2b SUMMARY")
    logger.info(f"{'=' * 60}")

    # Best pattern per cluster
    best_pattern_per_cluster: dict[str, str] = {}
    for co in cluster_outputs:
        ranking = co["pattern_ranking"]
        best = ranking[0] if ranking else "N/A"
        best_pattern_per_cluster[co["name"]] = best
        logger.info(f"  {co['name']}: best={best}, ranking={' > '.join(ranking)}")

    logger.info(f"  Gaming detected: {all_gaming_detected if all_gaming_detected else 'none'}")
    logger.info(f"  Cochran's Q significant (all clusters): {all_cochrans_significant}")

    # --- Save results ---
    payload: dict[str, Any] = {
        "experiment": "E4v2b",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "rerank_model": RERANK_MODEL,
            "cohere_rpm": args.cohere_rpm,
            "n_clusters": len(clusters),
            "total_queries": sum(len(c.queries) for c in clusters),
            "n_variants": len(ALL_VARIANTS),
            "variants": list(ALL_VARIANTS),
            "imported_variants": list(IMPORTED_VARIANTS),
            "new_variants": list(NEW_VARIANTS),
            "clusters_path": str(CLUSTERS_PATH),
            "variants_path": str(VARIANTS_PATH),
            "e4v2_results_path": str(E4V2_RESULTS_PATH),
            "shuffle_seed": "sha256(query_id + variant)",
            "doc_format": "tool_name: description",
            "bonferroni_alpha": round(BONFERRONI_ALPHA, 6),
        },
        "clusters": cluster_outputs,
        "summary": {
            "best_pattern_per_cluster": best_pattern_per_cluster,
            "gaming_detected": all_gaming_detected,
            "cochrans_q_significant": all_cochrans_significant,
        },
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Custom JSON serializer for numpy types
    def _json_default(obj: Any) -> Any:
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    RESULTS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default)
    )
    logger.info(f"\nResults saved to {RESULTS_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="E4v2b: Description Pattern Comparison (7 Variants)"
    )
    parser.add_argument(
        "--cohere-rpm",
        type=int,
        default=10,
        help="Legacy reranker API rate limit in requests/min (default: 10)",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
