# Experiments

This project uses experiments to decide architecture, not only to report final scores.

## Dataset Evolution

Initial synthetic GT was useful for bootstrapping but had structural limits: ambiguity was underrepresented, difficulty was loosely defined, and alternatives were often same-server rather than cross-server.

The project then adopted:

- MCP-Zero as the main server/tool pool.
- MCP-Atlas as external task data.
- Per-step decomposition so multi-step MCP-Atlas tasks become single-tool retrieval questions.

Key decisions:

- [ADR-0011](adr/0011-external-dataset-strategy.md)
- [ADR-0012](adr/0012-per-step-ground-truth-decomposition.md)
- [ADR-0013](adr/0013-pool-gt-alignment-policy.md)

## Historical Strategy Sweep

Early experiments compared three retrieval strategies:

| Strategy | Shape | Finding |
| --- | --- | --- |
| Flat | Direct tool search | Strong baseline; later became the hosted base path |
| Sequential | Server search -> filtered tool search | Reduced confusion but suffered when server-stage recall missed |
| Parallel | Server and tool search in parallel, RRF merge | Stronger in early pool sweeps, especially under the old P@1 framing |

The E5 sweep in [data/results/e5_scale_sweep.json](../data/results/e5_scale_sweep.json) includes the historical Pool 50 result: P@1 = 0.575 for Flat and Parallel.

## North Star Pivot

After GT grew to 2,273 MCP-Atlas per-step entries, P@1 alone became a weaker fit for the product contract. The system returns a small candidate set to an LLM, so the retrieval layer's most important job is to include the correct tool in Top-K.

Current retrieval North Star:

- Recall@K, with K=3 as the practical default.
- Baseline: dense-only FlatStrategy Recall@3 = 21.5%.
- Stretch/current hybrid evidence: dense + sparse RRF raised Recall@3 materially.

Source: [docs/design/north-star-realignment.md](design/north-star-realignment.md)

## Hybrid Retrieval Result

The April 12 hybrid report measured:

| Metric | Dense-only | Hybrid dense+sparse RRF |
| --- | ---: | ---: |
| Recall@3 | 21.5% | 48.9% |
| P@1 | 13.4% | 31.2% |
| MRR | 0.168 | 0.391 |

Source: [docs/experiments/hybrid-search-report.md](experiments/hybrid-search-report.md)

The later dense-model benchmark kept SPLADE and sparse text fixed and compared dense encoders. OpenAI `text-embedding-3-large` won the top-rank metrics among tested arms:

| Dense model | Recall@3 | P@1 | MRR |
| --- | ---: | ---: | ---: |
| OpenAI `text-embedding-3-large` | 0.4703 | 0.3110 | 0.3820 |
| Voyage `voyage-4-large` | 0.4386 | 0.2789 | 0.3468 |
| BGE-M3 | 0.4188 | 0.2714 | 0.3328 |

Source: [docs/experiments/hybrid-embedding-benchmark-report.md](experiments/hybrid-embedding-benchmark-report.md)

## Reranker Status

Historical E0/E5-style experiments evaluated an external reranker baseline. It is not enabled in the current hosted search/bridge runtime according to `service/shared/runtime.py` and the RAG authority docs.

This distinction matters for portfolio readers: the project evaluated reranking, but the current production-like path favors hybrid retrieval plus Top-K recall over a live reranking call and does not require a reranker API key.
