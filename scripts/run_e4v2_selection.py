"""E4v2 Experiment: Selection Controllability (Offline Fixed-Candidate).

Evaluates whether description design can steer a legacy hosted reranker's tool
selection within functional clusters of similar MCP tools.

Design:
  - For each cluster, run a legacy external rerank API under TWO conditions:
    V0 (Control):   all tools use original_description
    V1 (Treatment): ONLY the target tool uses enriched_description
  - Candidate documents shuffled per-query for positional bias control
  - Measures: TSR, FSR, Selection Precision, Score Gap, Rank Displacement
  - McNemar test for statistical significance

Usage:
    # Pilot: check legacy reranker determinism (5 queries x 3 repeats)
    PYTHONPATH=src uv run python scripts/run_e4v2_selection.py --pilot

    # Full run (Trial key, 10 RPM — slow)
    PYTHONPATH=src uv run python scripts/run_e4v2_selection.py

    # Full run (legacy reranker key, 95 RPM)
    PYTHONPATH=src uv run python scripts/run_e4v2_selection.py --cohere-rpm 95
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
RESULTS_PATH = Path("data/e4v2/results.json")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RERANK_MODEL = "rerank-v3.5"
VARIANTS = ("V0", "V1")


def _create_legacy_rerank_client(api_key: str) -> Any | None:
    """Create the optional legacy reranker client when its package is installed."""
    if cohere is None:
        logger.error(
            "Optional legacy reranker package is not installed. "
            "Install 'cohere' separately only when reproducing E4v2 historical runs."
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
    variant: str  # "V0" or "V1"
    top1_tool_id: str
    target_rank: int
    target_score: float
    all_scores: dict[str, float]  # tool_id -> relevance_score
    all_ranks: dict[str, int]  # tool_id -> rank (1-indexed)


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


# ---------------------------------------------------------------------------
# Candidate Document Building
# ---------------------------------------------------------------------------
def build_candidate_docs(
    cluster: ClusterDef,
    variant: str,
) -> list[tuple[str, str]]:
    """Build (tool_id, document_text) pairs for reranker input.

    Document format: "tool_name: description"

    For V0: all tools use original_description.
    For V1: ONLY target tool uses enriched_description, rest use original.
    """
    candidates: list[tuple[str, str]] = []
    for tool in cluster.tools:
        if variant == "V1" and tool.tool_id == cluster.target:
            desc = tool.enriched_description
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
    import hashlib

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
    """Call Cohere reranker and return structured result.

    Returns:
        Dict with keys: top1_tool_id, target_rank, target_score,
                        all_scores, all_ranks
    """
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
# Experiment Runner
# ---------------------------------------------------------------------------
async def run_cluster(
    client: cohere.AsyncClientV2,
    cluster: ClusterDef,
    rate_limiter: RateLimiter,
    pilot_limit: int | None = None,
) -> dict[str, list[QueryResult]]:
    """Run V0 and V1 for all queries in a cluster.

    Returns:
        {"V0": [...], "V1": [...]} — lists of QueryResult per variant
    """
    queries = list(cluster.queries)
    if pilot_limit is not None:
        queries = queries[:pilot_limit]

    results: dict[str, list[QueryResult]] = {"V0": [], "V1": []}

    for variant in VARIANTS:
        base_candidates = build_candidate_docs(cluster, variant)
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
# Metrics
# ---------------------------------------------------------------------------
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


def compute_mean_rank_displacement(
    v0_results: list[QueryResult],
    v1_results: list[QueryResult],
    target: str,
) -> float:
    """Mean rank change for C-queries (V0 rank - V1 rank; positive = promoted)."""
    v0_by_qid = {r.query_id: r for r in v0_results if r.label == "C"}
    v1_by_qid = {r.query_id: r for r in v1_results if r.label == "C"}
    common = set(v0_by_qid.keys()) & set(v1_by_qid.keys())
    if not common:
        return float("nan")
    displacements: list[int] = []
    for qid in common:
        rank_v0 = v0_by_qid[qid].target_rank
        rank_v1 = v1_by_qid[qid].target_rank
        displacements.append(rank_v0 - rank_v1)  # positive = promoted in V1
    return sum(displacements) / len(displacements)


def compute_cluster_metrics(
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


def _safe_round(v: float, digits: int = 4) -> float:
    """Round unless NaN."""
    if math.isnan(v):
        return v
    return round(v, digits)


# ---------------------------------------------------------------------------
# McNemar Test
# ---------------------------------------------------------------------------
def mcnemar_test(
    v0_results: list[QueryResult],
    v1_results: list[QueryResult],
    target: str,
) -> dict[str, Any]:
    """McNemar test on T-query paired binary outcomes (V0 vs V1).

    Builds a 2x2 contingency table:
        V0 correct, V1 correct  (a)
        V0 correct, V1 wrong    (b)
        V0 wrong,   V1 correct  (c)
        V0 wrong,   V1 wrong    (d)

    Tests if b != c using exact binomial test for small samples
    or chi-squared approximation for larger samples.
    """
    v0_by_qid = {r.query_id: r for r in v0_results if r.label == "T"}
    v1_by_qid = {r.query_id: r for r in v1_results if r.label == "T"}
    common = sorted(set(v0_by_qid.keys()) & set(v1_by_qid.keys()))

    if not common:
        return {
            "statistic": float("nan"),
            "p_value": float("nan"),
            "n_discordant": 0,
            "n_pairs": 0,
            "a": 0,
            "b": 0,
            "c": 0,
            "d": 0,
        }

    a, b, c, d = 0, 0, 0, 0
    for qid in common:
        v0_correct = v0_by_qid[qid].top1_tool_id == target
        v1_correct = v1_by_qid[qid].top1_tool_id == target
        if v0_correct and v1_correct:
            a += 1
        elif v0_correct and not v1_correct:
            b += 1
        elif not v0_correct and v1_correct:
            c += 1
        else:
            d += 1

    n_discordant = b + c

    if n_discordant == 0:
        return {
            "statistic": 0.0,
            "p_value": 1.0,
            "n_discordant": 0,
            "n_pairs": len(common),
            "a": a,
            "b": b,
            "c": c,
            "d": d,
        }

    # Use exact binomial test for small discordant counts (<25),
    # chi-squared approximation otherwise (standard McNemar)
    if n_discordant < 25:
        # Exact binomial: under H0, b ~ Binomial(b+c, 0.5)
        result = scipy_stats.binomtest(b, n_discordant, 0.5)
        p_value = result.pvalue
        statistic = float(b)
    else:
        # McNemar chi-squared with continuity correction
        statistic = (abs(b - c) - 1) ** 2 / n_discordant
        p_value = 1.0 - scipy_stats.chi2.cdf(statistic, df=1)

    return {
        "statistic": round(statistic, 4),
        "p_value": round(p_value, 6),
        "n_discordant": n_discordant,
        "n_pairs": len(common),
        "a": a,
        "b": b,
        "c": c,
        "d": d,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
def determine_verdict(mean_tsr_uplift: float, mean_fsr_change: float) -> str:
    """Classify result pattern per E4v2 design composite criterion."""
    if math.isnan(mean_tsr_uplift):
        return "NO_EFFECT"
    if mean_tsr_uplift >= 0.15 and mean_fsr_change <= 0.03:
        return "SUCCESS"
    if mean_tsr_uplift >= 0.15 and mean_fsr_change > 0.03:
        return "PARTIAL"
    if 0.05 <= mean_tsr_uplift < 0.15 and mean_fsr_change <= 0.03:
        return "WEAK_SIGNAL"
    return "NO_EFFECT"


# ---------------------------------------------------------------------------
# Pilot Mode
# ---------------------------------------------------------------------------
async def run_pilot(
    client: cohere.AsyncClientV2,
    cluster: ClusterDef,
    rate_limiter: RateLimiter,
    n_queries: int = 5,
    n_repeats: int = 3,
) -> dict[str, Any]:
    """Run determinism pilot: n_queries x n_repeats to check Cohere variance.

    Returns summary of per-query variance across repeats.
    """
    queries = list(cluster.queries)[:n_queries]
    base_candidates = build_candidate_docs(cluster, "V0")

    logger.info(
        f"  Pilot: {n_queries} queries x {n_repeats} repeats = {n_queries * n_repeats} API calls"
    )

    # Collect rankings: query_id -> list of (repeat, ranking)
    rankings: dict[str, list[list[str]]] = {}

    for repeat_idx in range(n_repeats):
        for qe in queries:
            shuffled = shuffle_candidates(base_candidates, qe.query_id, "V0")

            try:
                rr = await rerank_query(
                    client=client,
                    query=qe.query,
                    candidates=shuffled,
                    target_tool_id=cluster.target,
                    rate_limiter=rate_limiter,
                )
            except Exception as e:
                logger.error(f"    Pilot rerank failed: {e}")
                continue

            ranking = sorted(
                rr["all_scores"].keys(),
                key=lambda tid: rr["all_scores"][tid],
                reverse=True,
            )

            if qe.query_id not in rankings:
                rankings[qe.query_id] = []
            rankings[qe.query_id].append(ranking)

        logger.info(f"    Repeat {repeat_idx + 1}/{n_repeats} done")

    # Check variance: do all repeats produce same ranking?
    deterministic_count = 0
    total_queries = 0
    per_query_detail: list[dict[str, Any]] = []

    for qid, ranking_list in rankings.items():
        total_queries += 1
        is_deterministic = all(r == ranking_list[0] for r in ranking_list)
        if is_deterministic:
            deterministic_count += 1
        per_query_detail.append(
            {
                "query_id": qid,
                "deterministic": is_deterministic,
                "n_repeats": len(ranking_list),
                "top1_variants": list({r[0] for r in ranking_list}),
            }
        )

    determinism_rate = deterministic_count / total_queries if total_queries > 0 else float("nan")

    logger.info(
        f"  Pilot result: {deterministic_count}/{total_queries} queries "
        f"deterministic ({determinism_rate:.1%})"
    )

    return {
        "cluster": cluster.name,
        "n_queries": n_queries,
        "n_repeats": n_repeats,
        "determinism_rate": _safe_round(determinism_rate),
        "deterministic_count": deterministic_count,
        "total_queries": total_queries,
        "per_query": per_query_detail,
    }


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
# Main
# ---------------------------------------------------------------------------
async def main(args: argparse.Namespace) -> None:
    legacy_rerank_api_key = os.getenv("COHERE_API_KEY")
    if not legacy_rerank_api_key:
        logger.error("Legacy reranker API key not set in environment. Aborting.")
        return

    # --- Load clusters ---
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

    # --- Setup legacy reranker client ---
    client = _create_legacy_rerank_client(legacy_rerank_api_key)
    if client is None:
        return
    rate_limiter = RateLimiter(max_rpm=args.cohere_rpm)
    logger.info(f"Legacy reranker client ready: model={RERANK_MODEL}, rpm={args.cohere_rpm}")

    # --- Estimate time ---
    if args.pilot:
        n_calls = len(clusters) * 5 * 3  # 5 queries x 3 repeats per cluster
        est_min = math.ceil(n_calls / args.cohere_rpm)
        logger.info(f"Pilot mode: ~{n_calls} API calls, ~{est_min} min")
    else:
        n_calls = total_queries * 2  # V0 + V1
        est_min = math.ceil(n_calls / args.cohere_rpm)
        logger.info(f"Full run: ~{n_calls} API calls, ~{est_min} min ({est_min / 60:.1f}h)")

    try:
        if args.pilot:
            await _run_pilot_mode(client, clusters, rate_limiter)
        else:
            await _run_full_experiment(client, clusters, rate_limiter, args)
    finally:
        if hasattr(client, "close"):
            await client.close()


async def _run_pilot_mode(
    client: cohere.AsyncClientV2,
    clusters: list[ClusterDef],
    rate_limiter: RateLimiter,
) -> None:
    """Run pilot determinism check on all clusters."""
    logger.info("\n=== PILOT MODE: Determinism Check ===")
    pilot_results: list[dict[str, Any]] = []

    for cluster in clusters:
        logger.info(f"\nCluster: {cluster.name}")
        result = await run_pilot(
            client=client,
            cluster=cluster,
            rate_limiter=rate_limiter,
            n_queries=5,
            n_repeats=3,
        )
        pilot_results.append(result)

    # Summary
    logger.info("\n=== PILOT SUMMARY ===")
    for pr in pilot_results:
        logger.info(
            f"  {pr['cluster']}: {pr['determinism_rate']:.1%} deterministic "
            f"({pr['deterministic_count']}/{pr['total_queries']})"
        )

    all_deterministic = all(pr["determinism_rate"] == 1.0 for pr in pilot_results)
    if all_deterministic:
        logger.info("\n  Verdict: FULLY DETERMINISTIC — 1 run sufficient")
    else:
        logger.warning("\n  Verdict: NON-DETERMINISTIC — consider majority vote (5 repeats)")

    # Save pilot results
    pilot_path = Path("data/e4v2/pilot_results.json")
    pilot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment": "E4v2-pilot",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "all_deterministic": all_deterministic,
        "clusters": pilot_results,
    }
    pilot_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info(f"\nPilot results saved to {pilot_path}")


async def _run_full_experiment(
    client: cohere.AsyncClientV2,
    clusters: list[ClusterDef],
    rate_limiter: RateLimiter,
    args: argparse.Namespace,
) -> None:
    """Run the full E4v2 experiment across all clusters."""
    logger.info("\n=== FULL EXPERIMENT: E4v2 Selection Controllability ===")

    cluster_outputs: list[dict[str, Any]] = []
    tsr_uplifts: list[float] = []
    fsr_changes: list[float] = []

    for cluster in clusters:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Cluster: {cluster.name} (target: {cluster.target})")
        logger.info(f"{'=' * 60}")

        # Run V0 and V1
        variant_results = await run_cluster(
            client=client,
            cluster=cluster,
            rate_limiter=rate_limiter,
        )

        v0_results = variant_results["V0"]
        v1_results = variant_results["V1"]

        # Compute metrics
        v0_metrics = compute_cluster_metrics(v0_results, cluster.target)
        v1_metrics = compute_cluster_metrics(v1_results, cluster.target)

        # Delta
        delta = {
            key: _safe_round(v1_metrics[key] - v0_metrics[key])
            for key in ("tsr", "fsr", "sp", "mean_score_gap")
            if not (math.isnan(v1_metrics[key]) or math.isnan(v0_metrics[key]))
        }
        for key in ("tsr", "fsr", "sp", "mean_score_gap"):
            if key not in delta:
                delta[key] = float("nan")

        # Rank displacement (C-queries)
        rank_disp = compute_mean_rank_displacement(v0_results, v1_results, cluster.target)

        # McNemar test (T-queries only)
        mcnemar = mcnemar_test(v0_results, v1_results, cluster.target)

        # Track for summary
        if not math.isnan(delta.get("tsr", float("nan"))):
            tsr_uplifts.append(delta["tsr"])
        if not math.isnan(delta.get("fsr", float("nan"))):
            fsr_changes.append(delta["fsr"])

        # Per-query details
        per_query_v0 = [_serialize_query_result(qr) for qr in v0_results]
        per_query_v1 = [_serialize_query_result(qr) for qr in v1_results]

        # Log summary
        _log_cluster_summary(cluster, v0_metrics, v1_metrics, delta, mcnemar, rank_disp)

        cluster_output = {
            "name": cluster.name,
            "target": cluster.target,
            "n_tools": len(cluster.tools),
            "n_t_queries": v0_metrics["n_t"],
            "n_c_queries": v0_metrics["n_c"],
            "v0": {k: v for k, v in v0_metrics.items() if k not in ("n_t", "n_c")},
            "v1": {k: v for k, v in v1_metrics.items() if k not in ("n_t", "n_c")},
            "delta": delta,
            "rank_displacement": _safe_round(rank_disp),
            "mcnemar": mcnemar,
            "per_query": {"V0": per_query_v0, "V1": per_query_v1},
        }
        cluster_outputs.append(cluster_output)

    # --- Summary ---
    mean_tsr_uplift = sum(tsr_uplifts) / len(tsr_uplifts) if tsr_uplifts else float("nan")
    mean_fsr_change = sum(fsr_changes) / len(fsr_changes) if fsr_changes else float("nan")
    verdict = determine_verdict(mean_tsr_uplift, mean_fsr_change)

    logger.info(f"\n{'=' * 60}")
    logger.info("E4v2 SUMMARY")
    logger.info(f"{'=' * 60}")
    logger.info(f"  Mean TSR uplift: {mean_tsr_uplift:+.4f}")
    logger.info(f"  Mean FSR change: {mean_fsr_change:+.4f}")
    logger.info(f"  Verdict: {verdict}")

    # --- Save results ---
    payload = {
        "experiment": "E4v2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "rerank_model": RERANK_MODEL,
            "cohere_rpm": args.cohere_rpm,
            "n_clusters": len(clusters),
            "total_queries": sum(len(c.queries) for c in clusters),
            "clusters_path": str(CLUSTERS_PATH),
            "shuffle_seed": "hash(query_id + variant)",
            "doc_format": "tool_name: description",
        },
        "clusters": cluster_outputs,
        "summary": {
            "mean_tsr_uplift": _safe_round(mean_tsr_uplift),
            "mean_fsr_change": _safe_round(mean_fsr_change),
            "per_cluster_tsr_uplifts": [_safe_round(u) for u in tsr_uplifts],
            "per_cluster_fsr_changes": [_safe_round(c) for c in fsr_changes],
            "verdict": verdict,
        },
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info(f"\nResults saved to {RESULTS_PATH}")


def _log_cluster_summary(
    cluster: ClusterDef,
    v0: dict[str, Any],
    v1: dict[str, Any],
    delta: dict[str, Any],
    mcnemar: dict[str, Any],
    rank_disp: float,
) -> None:
    """Log a formatted summary table for one cluster."""
    col_w = 14
    v0_hdr = f"{'V0 (control)':>{col_w}}"
    v1_hdr = f"{'V1 (enriched)':>{col_w}}"
    d_hdr = f"{'Delta':>{col_w}}"
    logger.info(f"\n  {'Metric':<22} {v0_hdr} {v1_hdr} {d_hdr}")
    sep = f"{'-' * col_w}"
    logger.info(f"  {'-' * 22} {sep} {sep} {sep}")

    for metric_name in ("tsr", "fsr", "sp", "mean_score_gap"):
        v0_val = v0[metric_name]
        v1_val = v1[metric_name]
        d_val = delta.get(metric_name, float("nan"))
        v0_str = f"{v0_val:.4f}" if not math.isnan(v0_val) else "N/A"
        v1_str = f"{v1_val:.4f}" if not math.isnan(v1_val) else "N/A"
        d_str = f"{d_val:+.4f}" if not math.isnan(d_val) else "N/A"
        row = f"  {metric_name.upper():<22} {v0_str:>{col_w}} {v1_str:>{col_w}} {d_str:>{col_w}}"
        logger.info(row)

    rd_str = f"{rank_disp:+.2f}" if not math.isnan(rank_disp) else "N/A"
    logger.info(f"  {'RANK_DISPLACEMENT':<22} {'':>{col_w}} {'':>{col_w}} {rd_str:>{col_w}}")

    sig = "YES" if mcnemar["p_value"] < 0.05 else "NO"
    logger.info(
        f"  McNemar: statistic={mcnemar['statistic']}, "
        f"p={mcnemar['p_value']:.6f}, "
        f"discordant={mcnemar['n_discordant']}, "
        f"significant={sig}"
    )
    logger.info(
        f"  Contingency: a={mcnemar['a']} b={mcnemar['b']} c={mcnemar['c']} d={mcnemar['d']}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="E4v2: Selection Controllability Experiment")
    parser.add_argument(
        "--pilot",
        action="store_true",
        help="Run pilot mode: 5 queries x 3 repeats to check legacy reranker determinism",
    )
    parser.add_argument(
        "--cohere-rpm",
        type=int,
        default=10,
        help="Legacy reranker API rate limit in requests/min (default: 10)",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
