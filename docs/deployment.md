# Deployment

## Current Status

| Surface | Evidence | Status |
| --- | --- | --- |
| Frontend | `service/frontend/vercel.json`, `.vercel/project.json`, documented Vercel URL | Live URL responded HTTP 200 during audit |
| Backend SAM | `service/template.yaml` | `sam validate --template-file service/template.yaml --lint` passed |
| Backend API Gateway | documented URL in `service/docs/pre_hosting_baseline_checklist.md` | Host exists; unauthenticated protected routes return 401; `/health` returned 404 |
| Local backend | `service/api/local_app.py` | `/health` exists for local FastAPI wrapper |
| Optional gateway | `service/gateway/app.py` | `/gateway/health` exists locally |
| Frontend Docker | `service/ops/frontend/Dockerfile`, `compose.mcp.yaml` | Local compose path documented |

## Verified In This Audit

- `curl -I https://frontend-topaz-nine-24.vercel.app` -> HTTP 200
- `curl -I 'https://frontend-topaz-nine-24.vercel.app/search?q=search%20github%20repo'` -> HTTP 200 SPA response
- `curl https://5xr8wbpwhb.execute-api.us-east-1.amazonaws.com/prod/api/platform/stats` without API key -> HTTP 401
- `curl https://5xr8wbpwhb.execute-api.us-east-1.amazonaws.com/prod/health` -> HTTP 404
- `sam validate --template-file service/template.yaml --lint` -> valid SAM template

## Local Verification

```bash
uv sync
uv run pytest service/rag/tests -q
uv run ruff check src service tests

cd service/frontend
npm install
npm run build
npm run test
npm run lint
```

Full local stack:

```bash
docker compose -f compose.mcp.yaml up --build
```

Expected local checks:

- `GET http://127.0.0.1:3000/health`
- `GET http://127.0.0.1:3001/`
- `GET http://127.0.0.1:8000/gateway/health`
- `POST http://127.0.0.1:3000/api/search` with `x-api-key`

## Required Environment Variables

Document names only; never commit values.

| Service | Variables |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Qdrant | `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_NAME` |
| Supabase | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` |
| API auth | `MLP_API_KEY`, `MLP_PUBLIC_API_BASE_URL` |
| Gateway | `GATEWAY_INTERNAL_AUTH_SECRET`, `GATEWAY_BASE_URL`, `GATEWAY_SECRET_BACKEND` |
| Frontend | `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL`, `VITE_MLP_API_KEY` |
| Observability | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `WANDB_API_KEY` |

## Deployment Gaps

- There is no public unauthenticated backend health endpoint in the SAM template.
- Production route health requires either a configured API key check or a documented operator-only command.
- Frontend is live, but full page-by-page authenticated workflow was not re-run in this audit.
- `service/template-direct.yaml` exists as an untracked direct-image deployment artifact; decide whether to formalize, ignore, or archive it before public release.
