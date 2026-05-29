# EVAL: E0 — 1-Layer vs 2-Layer Architecture Validation

> Portfolio note: this is a historical experiment record. Some runs used Cohere
> Rerank as an external reranking baseline; the current public runtime does not
> require Cohere or `COHERE_API_KEY`.

> Gate experiment. E1+ does not proceed unless E0 passes.
> Grader type: Code (deterministic)

## Success Criteria

- [ ] `src/pipeline/flat.py` (1-Layer) executes without error — **implemented**
- [ ] `src/pipeline/sequential.py` (2-Layer Sequential) executes without error — **implemented**
- [ ] `src/pipeline/parallel.py` (2-Layer Parallel) executes without error — **implemented**
- [ ] Precision@1 measured on 474개 총 GT (MCP-Atlas per-step 394 + seed 80), pool covered 194개 (all single-step)
- [ ] Embedding: text-embedding-3-large (3072D, MCP-Zero precomputed vectors; re-embedding 불수행)
- [ ] Pool: `data/tool-pools/base_pool.json` (GT-first order), full 292-server pool
- [ ] Results logged to W&B run tagged `E0`

> **Note**: `run_e0.py`는 Flat + Sequential + Parallel 모두 실행. Historical
> reranker reproduction is optional; when no legacy reranker key/package is
> present, the script runs without reranking.

## Judgment Gate

```text
2-Layer valid if:
  Sequential_P@1 - FlatLayer_P@1 >= +5%p

→ PASS: proceed to E1
→ FAIL: investigate pipeline (check OQ-4 server classification errors)
```

## Regression Criteria

N/A — this is the baseline. Results become the regression floor for E1-E6.

## Metric Targets (pre-experiment, calibrate after)

| Strategy | Precision@1 target | Notes |
|----------|--------------------|-------|
| 1-Layer (flat) | — | baseline measurement |
| 2-Layer Sequential | > flat + 5%p | OQ-5 gate |
| 2-Layer Parallel | > flat + 5%p | OQ-5 gate |

## Reranker Configuration

- Default: no required reranker for the public portfolio runtime
- Historical reproduction: optional legacy external reranker applied post-retrieval
- `--no-rerank`: Disables reranker for embedding-only comparison
- If no legacy reranker key/package is available, the script runs without reranker

## CLI

```bash
PYTHONPATH=src uv run python scripts/run_e0.py                # All strategies
PYTHONPATH=src uv run python scripts/run_e0.py --no-rerank    # Embedding-only baseline
PYTHONPATH=src uv run python scripts/run_e0.py --strategy flat # Single strategy
```

## pass@k

- Capability: pass@1 (single deterministic run per strategy)
- Gate decision: deterministic threshold, not probabilistic

## Artifacts

- `.claude/evals/E0-baseline.log` — run history
- `docs/experiments/E0-report.md` — release snapshot (post-run)
