# Hybrid Embedding Benchmark Report

**Experiment date**: 2026-04-24  
**Branch**: `codex/hybrid-embedding-benchmark-v2-20260423`  
**Primary script**: `scripts/run_hybrid_embedding_benchmark.py`

## Goal

Compare dense embedding candidates inside the same hybrid retrieval stack. This is not a
dense-only benchmark: sparse retrieval stays fixed so the measured difference is the dense model.

| Component | Setting |
| --- | --- |
| Retrieval | Hybrid dense + sparse + Qdrant RRF |
| Sparse encoder | SPLADE (`prithivida/Splade_PP_en_v1`) |
| Sparse text | Keyword+LLM enriched text |
| Dense candidates | OpenAI `text-embedding-3-large`, Voyage `voyage-4-large`, BGE-M3 |
| GT | `data/ground_truth/mcp_atlas.jsonl` |
| Pool | `data/tool-pools/base_pool.json` |
| Primary metric | Recall@3 |
| Secondary metrics | P@1, MRR, Recall@5/10, latency |

Stage 2 sparse-encoder and sparse-text-policy ablations remain intentionally out of scope for
this report.

## Final Full GT Results

OpenAI and Voyage were measured in the same full Stage 1 run:

- `data/results/hybrid_embedding_benchmark/20260424T_full_stage1_final_tpm/hybrid_embedding_benchmark.json`

BGE-M3 failed in that run during Qdrant upsert with `httpx.WriteTimeout`. It was then measured in
a BGE-only recovery run:

- `data/results/hybrid_embedding_benchmark/20260424T_bge_retry_batch10_env/hybrid_embedding_benchmark.json`

Clean merged summary artifact:

- `data/results/hybrid_embedding_benchmark/20260424_final_hybrid_embedding_summary.json`

The BGE recovery used the same GT, pool, dense/sparse arm config, SPLADE sparse policy, query
precompute path, and single max-K evaluation path. The only intentional difference was
`--batch-size 10` for indexing transport, to avoid Qdrant write timeouts. That changes write
chunking, not the indexed corpus, embeddings, retrieval formula, or evaluation queries.

| Arm | Status | Recall@3 | P@1 | MRR | Recall@5 | Recall@10 | p50 | p95 | n |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| OpenAI `text-embedding-3-large` + SPLADE + Keyword+LLM | measured | **0.4703** | **0.3110** | **0.3820** | **0.5187** | **0.5693** | 213.4ms | 300.1ms | 2,273 |
| Voyage `voyage-4-large` + SPLADE + Keyword+LLM | measured | 0.4386 | 0.2789 | 0.3468 | 0.4980 | 0.5653 | 207.2ms | 320.8ms | 2,273 |
| BGE-M3 dense + SPLADE + Keyword+LLM | measured | 0.4188 | 0.2714 | 0.3328 | 0.4809 | 0.5394 | **205.3ms** | **298.6ms** | 2,273 |

Control parity for the OpenAI run passed against the frozen Keyword+LLM baseline:

| Metric | Frozen baseline | Measured control | Delta |
| --- | ---: | ---: | ---: |
| Recall@3 | 0.4660 | 0.4703 | +0.43pp |
| P@1 | 0.3190 | 0.3110 | -0.80pp |
| Confusion | 0.2160 | 0.2312 | +1.52pp |

All measured arms used query-vector precompute and a single `K=10` evaluation pass, deriving
`K=3/5/10` metrics from the same result set.

## Decision

`best_tested_hybrid = control_openai_large_splade_keyword_llm`

OpenAI `text-embedding-3-large + SPLADE + Keyword+LLM` remains the recommended stack for the
current hybrid retrieval pipeline.

Compared with Voyage `voyage-4-large`, OpenAI is better on the tool-selection-sensitive top-rank
metrics: +3.17pp Recall@3, +3.21pp P@1, and +3.52pp MRR. Voyage is close at Recall@10
(-0.40pp), which suggests it often retrieves the right tool somewhere in the larger candidate set
but ranks it lower than OpenAI.

Compared with BGE-M3, OpenAI is materially better: +5.15pp Recall@3, +3.96pp P@1, +4.92pp MRR,
and +2.99pp Recall@10. BGE-M3 is slightly faster on p50/p95 latency, but the quality loss is too
large for it to replace the current dense model.

## Cost And Operability Notes

Voyage was the only additional paid embedding provider used in the final comparison. To avoid
waste, the matrix disabled `voyage-4-lite` and measured only `voyage-4-large`, because the user
asked for OpenAI vs BGE-M3 vs Voyage and the account has strict rate limits.

Observed Voyage account limit was handled with conservative throttling:

| Limit control | Value |
| --- | ---: |
| Requests per minute | 2.8 |
| Tokens per minute | 8,000 |
| Max estimated tokens per request | 8,000 |

The run precomputed 1,852 unique Voyage query vectors once and reused them across K values, avoiding
the old expensive path that would call the provider once per query per K. Voyage document indexing
used `input_type="document"` and query evaluation used `input_type="query"`.

## Interview-Safe Wording

> We compared dense embedding models under the same hybrid search stack: dense vector search plus
> SPLADE sparse retrieval over the same Keyword+LLM-enriched tool descriptions. On the full 2,273
> query GT benchmark, OpenAI `text-embedding-3-large` had the best top-rank quality. Voyage
> `voyage-4-large` was competitive at Recall@10 but weaker at Recall@3/P@1/MRR, and BGE-M3 was
> cheaper/local and slightly faster but lost too much retrieval quality. So we kept
> `text-embedding-3-large` for the production-like hybrid stack.

## Remaining Risks

1. BGE-M3 was measured in a recovery run because Qdrant timed out on the combined run. The recovery
   changed only indexing batch size, but the final comparison still combines two artifacts.
2. Only one Voyage dense model was measured in full GT to control cost. `voyage-4-lite` remains
   wired from bounded samples but is not part of the final quality ranking.
3. This report covers retrieval Recall@K/P@1/MRR only. Full RAG-MCP client/tool-selection logging
   and execute-tool success are deliberately deferred.
4. Sparse encoder and sparse-text-policy experiments should be run as separate ablations, not mixed
   into the dense-model conclusion.
