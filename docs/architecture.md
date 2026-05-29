# Architecture

MCP Discovery Platform is split into a reusable retrieval library, a serverless service layer, an optional execution gateway, and a dashboard frontend.

## Runtime Shape

```text
Client / LLM
  |
  v
API Gateway HTTP API
  |
  +-- Search Lambda image
  |     `service/lambdas/search/handler.py`
  |     -> `service/shared/runtime.py`
  |     -> `service/rag/service.py`
  |
  +-- Bridge Lambda
  |     MCP-facing `find_best_tool` / execution bridge
  |
  +-- Register / Index Lambdas
  |     Async indexing, EventBridge, DLQ/replay
  |
  +-- Catalog / Dashboard Lambdas
        Public catalog and provider dashboard APIs
```

## Retrieval Path

The current hosted path is `FlatStrategy` with hybrid capability:

```text
query
  |
  +-- OpenAI dense embedding
  +-- FastEmbed SPLADE sparse embedding
  |
  v
Qdrant named-vector search
  |
  v
Qdrant RRF fusion
  |
  v
Supabase lexical fallback and operability merge
  |
  v
Top-K SearchResult
```

Important distinction: `SequentialStrategy` and `ParallelStrategy` remain implemented under `src/mcp_discovery/pipeline/` for experiments and historical comparison. They are not the current hosted search contract.

## Backend Structure

| Path | Purpose |
| --- | --- |
| `src/mcp_discovery/` | Core package: embeddings, retrieval, pipeline strategies, models, evaluation |
| `service/lambdas/` | Lambda entry points |
| `service/rag/` | Hosted retrieval orchestration and fallback logic |
| `service/services/` | Business logic for register, index, execute, dashboard, catalog |
| `service/adapters/` | Supabase, AWS, MCP HTTP, OAuth token adapters |
| `service/shared/` | Runtime wiring, settings, logging, event loop helpers |
| `service/gateway/` | Optional FastAPI gateway for long-running MCP execution |
| `service/api/` | Local FastAPI wrapper around Lambda handlers |
| `service/supabase/migrations/` | Supabase schema, auth, RLS, secret-ref migrations |

## Frontend Structure

The dashboard is a submodule at `service/frontend`.

| Path | Purpose |
| --- | --- |
| `service/frontend/src/` | React app source |
| `service/frontend/e2e/` | Playwright specs |
| `service/frontend/vercel.json` | Vercel SPA rewrite config |
| `service/ops/frontend/Dockerfile` | Static SPA nginx image |

## Data And Evaluation

| Path | Purpose |
| --- | --- |
| `data/ground_truth/` | MCP-Atlas and synthetic GT artifacts |
| `data/tool-pools/` | MCP-Zero pool definitions |
| `data/results/` | Experiment result JSON artifacts |
| `scripts/run_*` | Experiment runners and baselines |
| `tests/evaluation/` | Metric and harness tests |

## Design Constraints

- Search and indexing are separated so write-path failures do not block the query path.
- SPLADE is too large for normal Lambda ZIP packaging, so search/index paths use container images.
- Supabase stores metadata, auth, full-text fallback, and dashboard-facing state; Qdrant owns vector retrieval.
- The live path avoids popularity/usage-count ranking and keeps operability as a stability signal rather than a popularity signal.
