# MLP Acceptance Checklist

## Current Release Gate (Local First)

이번 release closure 기준은 아래 local provider journey다. HTTP MCP registration override feature는 이 local-first gate 안에서 닫는다.

1. `/login`에서 Google OAuth sign-in이 시작된다.
2. signed-in provider가 self-serve HTTP MCP registration wizard(또는 manual fallback path)에 접근한다.
3. MCP URL discovery가 tool metadata를 prefill할 수 있고, discovery 실패 시 manual continuation이 가능하다.
4. provider가 fetched upstream metadata를 검토한 뒤 published override metadata를 편집하고 최종 등록한다.
5. indexing/pending 상태가 사용자에게 보이고, local EventBridge mode에서는 register -> auto-index가 `.env`에 설정된 외부 Qdrant(`QDRANT_URL`, `QDRANT_API_KEY`)를 사용해 완료된다.
6. provider dashboard와 public/catalog/tool-detail surface가 published `description`을 outward-facing 값으로 노출한다.
7. dashboard metadata refresh는 diff preview를 먼저 보여 주고, apply 전 review step을 유지한다.
8. dashboard detail은 structured parameter metadata가 있을 때 published parameter description 편집 UI와 effective schema preview를 함께 보여 준다.
9. refresh preview는 orphaned parameter path와 parameter-level change detail을 apply 전에 보여 준다.

AWS staging/prod 배포는 현재 acceptance gate가 아니다. local gate 통과 이후에만 deferred follow-up으로 다시 연다.

## Evidence Required Now

### Repo-local regression evidence
- `uv run pytest tests/unit/mlp/test_mlp_catalog_dashboard.py tests/unit/mlp/test_mlp_catalog_service.py tests/unit/mlp/test_mlp_handlers.py -q`
- `uv run pytest tests/unit/mlp/test_mlp_template_contract.py tests/unit/mlp/test_mlp_index_loop.py tests/unit/mlp/test_mlp_execute_loop.py tests/unit/mlp/test_mlp_smoke_api.py -q`
- frontend `npm test`
- frontend `npm run build`

### Local operational evidence
- `uv run python -m service.harness.search_loop`
- `uv run python -m service.harness.index_loop`
- `uv run python -m service.harness.execute_loop`
- `uv run python -m service.harness.smoke_api --sample`
- local browser/frontend proof for `login -> HTTP MCP registration wizard/manual fallback -> override edit/publish -> dashboard reflection -> refresh diff preview`
- local browser/frontend proof for `parameter description edit -> effective schema preview -> parameter-level refresh warning`
- local API/operator proof that outward-facing catalog/tool detail reads expose published `description` while keeping `upstream_description` as reference metadata
- local EventBridge proof that provider register triggers auto-index to completion against the configured external Qdrant endpoint from `.env`

### Supporting evidence
- `service/docs/runbook.md` steps aligned to local-first gate
- Before changing MCP auth code, review the special locked auth reference artifact in `service/docs/history/2026-04-20_auth_reference_audit.md` (stable preflight reference, not a normal timestamped evidence record).
- Auth work is not complete unless it is checked against Claude Code docs, OpenAI MCP docs, the MCP Authorization spec, and at least one reference remote MCP auth implementation.
- `service/docs/current_slave.md` or `current_master.md` updated
- matching `service/docs/history/YYYY-MM-DD_HHMM_<owner>_<task_slug>.md`

## Feature-specific closeout additions

- MCP URL discovery can prefill registration metadata before submit.
- Delegated provider OAuth proof covers `execute -> auth_required -> provider OAuth callback -> retry -> success`.
- Claude/Codex OAuth proof covers `auth_probe unauthenticated -> re-authenticated -> clear-auth unauthenticated`.
- Delegated provider OAuth resume proof covers `execute -> auth_required -> provider OAuth callback -> ready_to_resume -> resume_pending_execution -> client-visible result`.
- Dashboard metadata editor can publish override metadata after registration.
- Local-direct FastAPI/EventBridge runtime keeps the normal index handler/Qdrant path and proves provider registration can reach `indexed` against the configured external Qdrant endpoint from `.env`.
- Dashboard metadata editor can publish parameter-description overrides and show the merged effective schema clients will see.
- Published/dashboard/tool-detail descriptions reflect MLP override metadata, not raw upstream descriptions.
- Metadata refresh remains diff-first: operators review changed upstream description/schema before adoption.
- Parameter metadata verification must capture one case where published parameter descriptions override upstream schema descriptions and one refresh preview where orphaned parameter paths are warned before apply.

## Current Blocker Policy

- If local SAM/runtime blocker prevents E2E, release closure is **blocked**, not complete.
- The blocked step must be written explicitly with the exact error and next operator action.
- Known examples already observed in history:
  - `pydantic_core._pydantic_core` ABI mismatch during local Lambda path
  - `sam build --use-container` Makefile path failure (`cp //mlp/...`)

## Required Before Future Deployment Execution

### Repo-local pre-deployment rehearsal evidence
- `UV_CACHE_DIR=/tmp/uv-cache scripts/ci/run_mlp_predeploy_checks.sh`
- output summary reports all repo-local build/contract/harness checks passed
- no AWS mutation command (`sam deploy`, `aws`, `docker push`) is part of this rehearsal

## Deferred Follow-ups (Not Required Now)

- AWS staging deployment
- AWS prod deployment
- live-stage API smoke on deployed endpoint
- deployed frontend/browser proof on hosted origin

### Hosted runtime prerequisites
- migration 009 applied and verified via `service/scripts/verify_runtime_schema.py`
- migrations 025 and 026 applied for delegated provider OAuth and pending execution resume tables
- authoritative hosted API base URL recorded
- authoritative hosted gateway URL recorded
- hosted auth secret source identified

### Hosted deployment readiness bundle (planning only)
- `service/scripts/verify_runtime_schema.py` reports hosted runtime readiness before deployment execution opens
- `service/template.yaml` remains the canonical Lambda/API control-plane artifact
- `service/gateway/Dockerfile` + `service/ops/apprunner.gateway.yaml` remain the canonical gateway container artifacts
- `service/scripts/print_gateway_deploy_manifest.py` is used to freeze required gateway env and image identity before rollout
- authoritative hosted `ApiUrl` and hosted gateway URL are both recorded
- hosted login/dashboard verification remains blocked until both control-plane and gateway targets exist

### Live MCP transport proof (post-deploy gate)
- hosted streamable HTTP provider MCP proof captured
- hosted or controlled SSE provider MCP proof captured
- local/controlled STDIO subprocess proof captured through the deployed gateway path
- transport proof harness summary recorded in history docs
