# MCP Discovery Platform

MCP Discovery Platform reframes MCP tool selection as an information retrieval problem: instead of asking an LLM to choose from every available tool inside the prompt, the system retrieves, ranks, and validates a small set of relevant MCP server/tool candidates first.

## Problem

As the MCP ecosystem grows, putting every server and tool description into an LLM prompt becomes expensive and unreliable. Large tool catalogs increase context cost, add latency, and make similar tools harder to distinguish. Prompt-only tool selection can also produce hallucinated choices, wrong tool matches, and brittle behavior when descriptions overlap.

This project is built around three assumptions:

- The LLM should receive only the candidates that are relevant to the current user request, not the entire tool registry.
- Tool selection should be narrowed by a discovery layer with retrieval, fusion, and optional reranking before the LLM reasons over the final choices.
- Search relevance is not enough by itself; the control plane also needs operability signals that indicate whether a candidate can actually be executed.

## Solution

MCP Discovery Platform accepts a natural-language query, searches MCP server/tool metadata, and returns ranked candidates that can be used by an execution gateway, dashboard, or evaluation pipeline.

The repository contains two retrieval tracks:

- **Historical experiment path**: Flat, Sequential, and Parallel retrieval strategies were compared quantitatively. In the early E5 pool sweep, the Pool 50 condition reached P@1 = 0.575, meeting the original North Star target.
- **Current hosted path**: after larger ground-truth evaluation, the project shifted the North Star from P@1 alone to Recall@K. The hosted search/bridge contract now uses a simpler `FlatStrategy`-based hybrid dense+sparse retrieval path.

The current implementation focuses on:

- Dense embeddings with OpenAI `text-embedding-3-large`
- Sparse retrieval signals with FastEmbed SPLADE
- Qdrant named vectors and server-side RRF fusion
- Supabase Postgres for metadata, auth/RLS design, full-text fallback, and operability data
- AWS Lambda, API Gateway, and SAM for the serverless backend
- An optional FastAPI gateway for longer-running MCP execution paths
- A React 18, TypeScript, and Vite dashboard
- Evaluation and observability through local artifacts, Langfuse, and W&B hooks

Reranking is kept optional. Some historical experiments used Cohere rerank-v3.5 as an external reranking baseline, but the public portfolio runtime does not require a Cohere package or API key.

## Architecture

```text
User / LLM Client Query
  |
  v
Discovery API / Bridge MCP Server
  |
  v
Retrieval Runtime
  |
  +-- Dense Search: OpenAI embedding -> Qdrant dense vector
  +-- Sparse Search: FastEmbed SPLADE -> Qdrant sparse vector
  |
  v
Qdrant RRF Fusion
  |
  v
Supabase FTS Fallback + Operability Signal Merge
  |
  v
Top-K MCP Tool Candidates
  |
  +-- Execution Gateway / MCP Bridge
  +-- Provider Dashboard
  +-- Offline Evaluation Pipeline
```

Historical two-layer experiments also implement `SequentialStrategy` and `ParallelStrategy`, where server-level and tool-level search are split and fused. The hosted path intentionally uses the simpler Flat hybrid path because larger Recall@K evaluation showed better live-path behavior.

See [docs/architecture.md](docs/architecture.md) for a code-level architecture overview.

## Tech Stack

| Area | Stack |
| --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic v2, loguru |
| Serverless | AWS Lambda, API Gateway HTTP API, AWS SAM |
| Optional gateway | FastAPI gateway for long-running MCP execution paths |
| Frontend | React 18, TypeScript, Vite, Tailwind, shadcn/ui, React Query |
| Vector DB | Qdrant Cloud / Qdrant named vectors |
| Metadata DB | Supabase Postgres, RLS/auth design, full-text fallback |
| Embedding | OpenAI `text-embedding-3-large` |
| Sparse retrieval | FastEmbed SPLADE (`prithivida/Splade_PP_en_v1`) |
| Ranking fusion | Qdrant RRF |
| Reranking | Optional legacy experiment component; not required by the hosted path |
| Observability | Langfuse, W&B, structured logs, stage metrics |
| Testing | pytest, pytest-asyncio, ruff, Vitest, Playwright |

## Key Features

| Feature | Status | Notes |
| --- | --- | --- |
| MCP server/tool indexing | Implemented | `scripts/build_hybrid_index.py`, `service/services/index_service.py` |
| Hybrid retrieval | Implemented | Dense + sparse named vectors with Qdrant RRF |
| Server/tool parallel search | Implemented / historical | `ParallelStrategy` remains in `src/mcp_discovery/pipeline/parallel.py` |
| Reranking | Historical / optional | Earlier experiments evaluated reranking; the hosted path has no required live reranker |
| Provider dashboard | Implemented | Vite dashboard under `service/frontend/` |
| Evaluation pipeline | Implemented | `src/mcp_discovery/evaluation/`, `tests/evaluation/`, `scripts/run_*` |
| Experiment tracking | Implemented | W&B hooks and tracked `data/results/*` artifacts |
| Operability scoring | Implemented / evolving | Supabase-backed operability cache and status lifecycle |
| Supabase auth/RLS design | Implemented | See migrations and ADRs around auth and secret references |
| Deployment scripts | Implemented | SAM templates, `service/Makefile`, Docker Compose local stack |

## Experiments & Results

The project started with synthetic ground truth, then moved toward external datasets because synthetic labels underrepresented ambiguity and cross-server alternatives.

Primary datasets:

- MCP-Zero server/tool pool
- MCP-Atlas task trajectories decomposed into per-step single-tool ground truth
- Local seed and synthetic data retained as historical or auxiliary artifacts

Key results:

| Experiment | Result | Source |
| --- | --- | --- |
| E0/E5 historical strategy comparison | Pool 50 reached P@1 = 0.575 for Flat and Parallel; Parallel was more robust at larger pools in the E5 sweep | [data/results/e5_scale_sweep.json](data/results/e5_scale_sweep.json) |
| Sequential strategy | Lower confusion, but weaker server-stage recall in larger settings | [data/results/e5_scale_sweep.json](data/results/e5_scale_sweep.json) |
| Recall@K pivot | Dense-only FlatStrategy baseline: Recall@3 = 21.5%, P@1 = 13.4% on 2,273 ground-truth entries | [docs/experiments/recall-k-baseline-report.md](docs/experiments/recall-k-baseline-report.md) |
| Hybrid retrieval | Dense + SPLADE + Qdrant RRF improved Recall@3 from 21.5% to 48.9% in the April 12 report | [docs/experiments/hybrid-search-report.md](docs/experiments/hybrid-search-report.md) |
| Dense model comparison | OpenAI `text-embedding-3-large` was best among tested hybrid arms: Recall@3 = 0.4703, P@1 = 0.3110 | [docs/experiments/hybrid-embedding-benchmark-report.md](docs/experiments/hybrid-embedding-benchmark-report.md) |

Important caveat: early E0/E5 results and later Recall@K/hybrid results are not directly comparable because pool size, ground-truth size, and reranker usage changed.

See [docs/experiments.md](docs/experiments.md) for the full experiment narrative.

## Setup

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js and npm
- Docker, for the full local stack
- AWS SAM CLI, for Lambda template validation, local API checks, and deployment

### Clone

```bash
git clone <repo-url>
cd mcp-discovery
git submodule update --init --recursive
```

### Backend Setup

```bash
uv sync
uv run pytest service/rag/tests -q
uv run ruff check src service tests
```

### Frontend Setup

```bash
cd service/frontend
npm install
npm run build
npm run test
npm run lint
```

### Environment Variables

Use local `.env` files only. Do not commit real values.

```dotenv
OPENAI_API_KEY=
QDRANT_URL=
QDRANT_API_KEY=
QDRANT_COLLECTION_NAME=mcp_tools_hybrid
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_KEY=
MLP_API_KEY=
MLP_PUBLIC_API_BASE_URL=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
WANDB_API_KEY=

VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_API_URL=
VITE_MLP_API_KEY=

GATEWAY_INTERNAL_AUTH_SECRET=
GATEWAY_BASE_URL=
```

### Local Run

Docker Compose local stack:

```bash
docker compose -f compose.mcp.yaml up --build
```

Expected local endpoints:

- Backend: `http://127.0.0.1:3000`
- Frontend: `http://127.0.0.1:3001`
- Local MCP dev server: `http://127.0.0.1:8080`
- Gateway: `http://127.0.0.1:8000`

Service-local SAM workflow:

```bash
cd service
make doctor
make build
make smoke
make local
```

### Test And Build

```bash
uv run ruff check src service tests
uv run pytest tests/unit tests/evaluation -q
uv run pytest service/rag/tests -q

cd service/frontend
npm run build
npm run test
npm run lint

cd ../..
sam validate --template-file service/template.yaml --lint
sam validate --template-file service/template.local.yaml --lint
```

## Deployment

Deployment is split by surface:

- **Frontend**: Vercel configuration lives in `service/frontend/vercel.json`.
- **Backend**: `service/template.yaml` defines the AWS SAM deployment for Lambda and API Gateway.
- **Local/serverless parity**: `service/template.local.yaml` and `compose.mcp.yaml` support local development and smoke checks.
- **Optional execution gateway**: the FastAPI gateway exposes local health and execution routes for longer-running MCP paths.

See [docs/deployment.md](docs/deployment.md) for deployment status, environment variables, and verification commands.

## Repository Structure

```text
.
|-- src/mcp_discovery/          # Core retrieval, embedding, evaluation, models
|-- service/
|   |-- lambdas/                # Lambda handlers
|   |-- rag/                    # RAG runtime service used by hosted search
|   |-- gateway/                # Optional FastAPI execution gateway
|   |-- api/                    # Local FastAPI wrapper for Lambda routes
|   |-- services/               # Business logic layer
|   |-- adapters/               # Supabase, AWS, MCP HTTP clients
|   |-- supabase/migrations/    # Database schema and RLS/auth migrations
|   |-- frontend/               # React/Vite dashboard submodule
|   |-- template.yaml           # Production SAM template
|   `-- template.local.yaml     # Local SAM template
|-- scripts/                    # Indexing, evaluation, benchmark scripts
|-- tests/                      # Unit, integration, evaluation tests
|-- data/
|   |-- ground_truth/           # Ground-truth data
|   |-- results/                # Experiment result artifacts
|   `-- tool-pools/             # MCP pool definitions
|-- docs/
|   |-- adr/                    # Architecture Decision Records
|   |-- design/                 # Design notes
|   |-- experiments/            # Experiment reports
|   `-- runbook/                # Operations notes
`-- compose.mcp.yaml            # Local full-stack compose
```

## Design Decisions

- [ADR-0004: Qdrant Cloud vector store](docs/adr/0004-qdrant-cloud-vector-store.md): chose Qdrant for upsert-friendly vector search and payload filtering.
- [ADR-0011: External datasets](docs/adr/0011-external-dataset-strategy.md): moved from synthetic-only ground truth to MCP-Zero and MCP-Atlas.
- [ADR-0012: Per-step ground truth decomposition](docs/adr/0012-per-step-ground-truth-decomposition.md): converted multi-step MCP-Atlas tasks into single-tool retrieval entries.
- [ADR-0017: Hybrid retrieval rollout](docs/adr/0017-hybrid-retrieval-rollout.md): adopted dense + SPLADE + Qdrant RRF with Lambda container images for SPLADE.
- [ADR-0023: Upstream secrets to Secrets Manager](docs/adr/0023-upstream-secrets-to-secrets-manager.md): moved provider secrets toward secret references instead of plaintext storage.

## Portfolio Notes

What I focused on:

- Reframing MCP tool selection as an information retrieval problem.
- Comparing Flat, Sequential, and Parallel retrieval architectures with quantitative metrics.
- Updating the North Star metric when larger ground truth showed that P@1 alone was misleading.
- Designing a serverless deployment path that separates query, indexing, and execution concerns.
- Connecting architecture choices to measured behavior through evaluation artifacts, ADRs, and observability hooks.
