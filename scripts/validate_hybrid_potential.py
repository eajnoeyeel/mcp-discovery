"""Hybrid Search Validation — BM25 simulation to estimate sparse search potential.

No external APIs needed. Pure Python computation.
Compares BM25-only Recall@K with dense-only baseline to estimate hybrid improvement.

Usage:
    PYTHONPATH=src uv run python scripts/validate_hybrid_potential.py
"""

import json
import math
import re
from collections import Counter
from pathlib import Path

from loguru import logger

from mcp_discovery.data.ground_truth import load_ground_truth

# --- Paths ---
SERVERS_JSONL = Path("data/raw/mcp_zero_servers.jsonl")
GT_ATLAS_PATH = Path("data/ground_truth/mcp_atlas.jsonl")
BASE_POOL_PATH = Path("data/tool-pools/base_pool.json")

# Dense baseline from recall_k_baseline.json (FlatStrategy)
DENSE_RECALL = {3: 0.2151, 5: 0.2556, 10: 0.2824}

K_VALUES = [3, 5, 10]


# --- BM25 Implementation ---
def tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer, lowercase."""
    return re.findall(r"[a-z0-9_]+", text.lower())


class BM25Index:
    """Minimal BM25 (Okapi BM25) index."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs: list[list[str]] = []
        self.doc_ids: list[str] = []
        self.doc_lens: list[int] = []
        self.avgdl: float = 0.0
        self.n_docs: int = 0
        self.df: Counter = Counter()  # document frequency per term
        self.tf: list[Counter] = []  # term frequency per doc

    def add_documents(self, doc_ids: list[str], texts: list[str]) -> None:
        for doc_id, text in zip(doc_ids, texts):
            tokens = tokenize(text)
            self.docs.append(tokens)
            self.doc_ids.append(doc_id)
            self.doc_lens.append(len(tokens))
            tf = Counter(tokens)
            self.tf.append(tf)
            for term in set(tokens):
                self.df[term] += 1
        self.n_docs = len(self.docs)
        self.avgdl = sum(self.doc_lens) / self.n_docs if self.n_docs else 1.0

    def score(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Return top_k (doc_id, score) pairs for a query."""
        query_tokens = tokenize(query)
        scores: list[tuple[str, float]] = []

        for i in range(self.n_docs):
            s = 0.0
            dl = self.doc_lens[i]
            for qt in query_tokens:
                if qt not in self.tf[i]:
                    continue
                tf_val = self.tf[i][qt]
                df_val = self.df.get(qt, 0)
                idf = math.log((self.n_docs - df_val + 0.5) / (df_val + 0.5) + 1.0)
                numerator = tf_val * (self.k1 + 1)
                denominator = tf_val + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                s += idf * numerator / denominator
            if s > 0:
                scores.append((self.doc_ids[i], s))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# --- Data Loading ---
def load_tools_from_mcp_zero(pool_server_ids: set[str]) -> dict[str, str]:
    """Load tool_id -> text (tool_name: description) from processed JSONL, filtered by pool."""
    tool_texts: dict[str, str] = {}

    with SERVERS_JSONL.open() as f:
        for line in f:
            server = json.loads(line)
            server_id = server.get("server_id", "")
            if server_id not in pool_server_ids:
                continue
            for tool in server.get("tools", []):
                tool_id = tool.get("tool_id", "")
                tool_name = tool.get("tool_name", "")
                desc = tool.get("description", "") or ""
                tool_texts[tool_id] = f"{tool_name}: {desc}"

    return tool_texts


def main() -> None:
    # Load pool
    pool_server_ids = set(json.loads(BASE_POOL_PATH.read_text()))
    logger.info(f"Pool: {len(pool_server_ids)} servers")

    # Load tools
    tool_texts = load_tools_from_mcp_zero(pool_server_ids)
    logger.info(f"Tools loaded: {len(tool_texts)}")

    # Load GT
    entries = []
    if GT_ATLAS_PATH.exists():
        entries = load_ground_truth(GT_ATLAS_PATH)
    entries = [e for e in entries if e.correct_server_id in pool_server_ids]
    logger.info(f"GT entries (pool-covered): {len(entries)}")

    # Build BM25 index
    logger.info("Building BM25 index...")
    bm25 = BM25Index()
    doc_ids = list(tool_texts.keys())
    doc_texts = list(tool_texts.values())
    bm25.add_documents(doc_ids, doc_texts)
    logger.info(f"BM25 index built: {bm25.n_docs} documents, avgdl={bm25.avgdl:.1f}")

    # Run BM25 retrieval for each query
    max_k = max(K_VALUES)
    logger.info(f"Running BM25 retrieval for {len(entries)} queries (max K={max_k})...")

    bm25_hits: dict[int, int] = {k: 0 for k in K_VALUES}
    bm25_per_query: list[dict] = []  # store per-query results for overlap analysis

    for i, entry in enumerate(entries):
        results = bm25.score(entry.query, top_k=max_k)
        retrieved_ids = [doc_id for doc_id, _ in results]

        hit_at = {}
        for k in K_VALUES:
            hit = entry.correct_tool_id in retrieved_ids[:k]
            if hit:
                bm25_hits[k] += 1
            hit_at[k] = hit

        bm25_per_query.append({
            "query_id": entry.query_id,
            "correct_tool_id": entry.correct_tool_id,
            "hit_at": hit_at,
            "bm25_top3": retrieved_ids[:3],
        })

        if (i + 1) % 500 == 0:
            logger.info(f"  Processed {i + 1}/{len(entries)}")

    n = len(entries)
    logger.info("")
    logger.info("=" * 65)
    logger.info("HYBRID SEARCH POTENTIAL ANALYSIS")
    logger.info("=" * 65)

    # BM25-only results
    logger.info("")
    logger.info("1. BM25-only Recall@K")
    logger.info(f"   {'K':>4}  {'BM25 Recall':>12}  {'Dense Recall':>13}  {'BM25 Hits':>10}")
    logger.info(f"   {'-'*4}  {'-'*12}  {'-'*13}  {'-'*10}")
    for k in K_VALUES:
        bm25_r = bm25_hits[k] / n
        dense_r = DENSE_RECALL[k]
        logger.info(
            f"   {k:>4}  {bm25_r:>12.3f}  {dense_r:>13.3f}  "
            f"{bm25_hits[k]:>5}/{n}"
        )

    # Estimate overlap (need dense per-query data — approximate with random overlap model)
    # P(both hit) ≈ P(dense hit) * P(bm25 hit) if independent
    # Hybrid recall ≈ P(dense) + P(bm25) - P(both) = 1 - (1-P(dense))*(1-P(bm25))
    logger.info("")
    logger.info("2. Hybrid Recall Estimate (independence assumption)")
    logger.info("   (Upper bound if signals are complementary, lower if correlated)")
    logger.info(f"   {'K':>4}  {'Independent':>12}  {'Max (union)':>12}  {'Min (corr)':>12}")
    logger.info(f"   {'-'*4}  {'-'*12}  {'-'*12}  {'-'*12}")
    for k in K_VALUES:
        bm25_r = bm25_hits[k] / n
        dense_r = DENSE_RECALL[k]
        # Independent: P(A or B) = P(A) + P(B) - P(A)*P(B)
        independent = 1 - (1 - dense_r) * (1 - bm25_r)
        # Max (completely complementary): P(A) + P(B), capped at 1
        max_union = min(dense_r + bm25_r, 1.0)
        # Min (fully correlated): max(P(A), P(B))
        min_corr = max(dense_r, bm25_r)
        logger.info(
            f"   {k:>4}  {independent:>12.3f}  {max_union:>12.3f}  {min_corr:>12.3f}"
        )

    # Sample failed queries to show qualitative examples
    logger.info("")
    logger.info("3. Sample: BM25 catches what dense missed")
    bm25_only_hits = [
        q for q in bm25_per_query
        if q["hit_at"][3]  # BM25 found it in top-3
    ]
    # Show first 10 BM25 hits
    shown = 0
    for q in bm25_only_hits[:15]:
        gt_entry = next((e for e in entries if e.query_id == q["query_id"]), None)
        if gt_entry and shown < 10:
            logger.info(
                f"   query: {gt_entry.query[:70]}..."
                if len(gt_entry.query) > 70
                else f"   query: {gt_entry.query}"
            )
            logger.info(f"   correct: {q['correct_tool_id']}")
            logger.info(f"   bm25_top3: {q['bm25_top3']}")
            logger.info("")
            shown += 1


if __name__ == "__main__":
    main()
