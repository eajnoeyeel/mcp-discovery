### 2026-04-17 12:54 — Local-direct EventBridge indexing lane closeout
- 이번에 한 일: `MLP_EVENT_MODE=local_direct` 경로는 유지하되, `mlp/api/local_app.py`에 들어갔던 in-memory Qdrant 우회를 제거하고 다시 `.env`의 외부 Qdrant 설정(`QDRANT_URL`, `QDRANT_API_KEY`)을 그대로 쓰는 구조로 정리했다. 같은 기준으로 `tests/unit/test_mlp_api_local_app.py`와 `mlp/docs/acceptance.md`/`mlp/docs/runbook.md`를 갱신했고, 이어 main session Playwright browser proof로 real Google Maps MCP 등록 → local direct auto-index → provider detail/metadata save/refresh preview까지 외부 Qdrant 기준으로 다시 닫았다.
- 다음에 할 일: local-direct lane은 닫혔다. 남은 후속 작업은 필요 시 lore-format granular commits 정리와 branch finish/PR 준비다.
- 검증 결과: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/test_mlp_api_local_app.py -q` PASS (`3 passed`), `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check mlp/api/local_app.py tests/unit/test_mlp_api_local_app.py` PASS, `lsp_diagnostics` PASS (`mlp/api/local_app.py`, `tests/unit/test_mlp_api_local_app.py` 0 errors), `git diff --check -- mlp/api/local_app.py tests/unit/test_mlp_api_local_app.py mlp/docs/runbook.md mlp/docs/acceptance.md` PASS, Playwright browser proof PASS (real Google Maps MCP discovery, `registerStatus=201`, dashboard reflected all three tools as `indexed`, provider detail `200`, metadata save `200`, refresh preview `200`, all against the external Qdrant configured in `.env`).
- 상세 기록: `mlp/docs/history/2026-04-17_1254_slave_local_direct_indexing_lane_closeout.md`

### 2026-04-16 19:45 — True E2E verification blocked by live Supabase schema state
- 이번에 한 일: real Supabase test user session을 발급하고, real public Google Maps MCP(`https://mapstools.googleapis.com/mcp`)를 discovery source로 사용해 local frontend + real local backend + Playwright 기반 true E2E를 다시 시도했다. 그 과정에서 local runtime surface에 provider discovery/metadata routes가 빠져 있던 문제를 수정했고, 이후 real discovery는 성공했지만 registration submit은 live Supabase `mcp_tools` schema cache mismatch로 막힌다는 것을 확인했다.
- 다음에 할 일: 연결된 Supabase에 migration 020/021(`metadata_origin`, parameter metadata columns 등)을 실제 적용하거나 PostgREST schema cache를 갱신한 뒤, 동일 Playwright flow로 registration submit → dashboard reflection까지 true E2E를 재실행한다.
- 검증 결과: real auth PASS, real Google Maps MCP discovery PASS, local runtime exposure fix tests PASS (`uv run pytest tests/unit/test_mlp_api_local_app.py tests/unit/test_mlp_template_contract.py -q`), branch-wide backend PASS (`313 passed`), frontend PASS (`30 passed`), true registration submit BLOCKED (`PGRST204: Could not find the 'metadata_origin' column of 'mcp_tools' in the schema cache`).
- 상세 기록: `mlp/docs/history/2026-04-16_1945_slave_true_e2e_blocked_by_supabase_schema_state.md`

### 2026-04-16 17:14 — Task 5 dashboard parameter-metadata verification lane
- 이번에 한 일: dashboard tool detail 범위에서 published parameter description 편집 UI, effective schema preview, parameter-level refresh warning/test coverage를 추가했고, review follow-up으로 orphaned published override를 운영자가 수정/삭제할 수 있는 UI와 nested path preview regression까지 보강했다. acceptance/runbook evidence wording도 parameter metadata 기준으로 유지했다.
- 다음에 할 일: branch owner가 backend/API lane과 합친 뒤 Playwright MCP proof로 parameter edit → nested effective schema preview → orphaned override removal/warning flow를 실제/모의 데이터로 캡처한다.
- 검증 결과: `cd mlp/frontend && npm test -- src/pages/DashboardToolDetail.test.tsx` PASS, `cd mlp/frontend && npm test -- src/lib/api.test.ts src/pages/RegisterServer.test.tsx src/pages/DashboardToolDetail.test.tsx` PASS, `cd mlp/frontend && npx tsc --noEmit` PASS, `cd mlp/frontend && npm run build` PASS, scoped `git diff --check` PASS.
- 상세 기록: `mlp/docs/history/2026-04-16_1746_slave_task5_dashboard_parameter_metadata_review_followup.md`

### 2026-04-16 12:16 — HTTP MCP registration override public-read closeout
- 이번에 한 일: Task 6 범위에서 outward-facing override precedence를 다시 점검하고 `tests/unit/test_mlp_catalog_dashboard.py`에 public server-tools/tool-detail regression을 추가해 published `description`이 `upstream_description`보다 우선 노출되는 계약을 고정했다. 이어 acceptance/runbook/current docs를 wizard + metadata editor + diff-first refresh flow 기준으로 갱신했다. 기존 `mlp/services/catalog_service.py` / `mlp/adapters/supabase_client.py` read path는 이미 persisted `description`을 outward-facing 값으로 통과시키고 있어 추가 backend patch는 필요하지 않았다.
- 다음에 할 일: branch owner가 다른 task lanes와 합친 뒤 full feature verification/browser proof를 묶어서 최종 closeout evidence를 업데이트한다.
- 검증 결과: `uv run pytest tests/unit/test_mlp_catalog_dashboard.py -q` PASS (`25 passed`), `uv run pytest tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_catalog_service.py tests/unit/test_mlp_handlers.py -q` PASS (`139 passed`), `uv run ruff check mlp/adapters/supabase_client.py mlp/services/catalog_service.py tests/unit/test_mlp_catalog_dashboard.py` PASS, `python3 -m py_compile mlp/adapters/supabase_client.py mlp/services/catalog_service.py tests/unit/test_mlp_catalog_dashboard.py` PASS, `git diff --check -- tests/unit/test_mlp_catalog_dashboard.py mlp/docs/acceptance.md mlp/docs/runbook.md mlp/docs/current_slave.md mlp/docs/history/2026-04-15_1216_slave_http_mcp_registration_override.md` PASS.
- 상세 기록: `mlp/docs/history/2026-04-15_1216_slave_http_mcp_registration_override.md`

### 2026-04-13 22:30 — MLP pre-deployment rehearsal command
- 이번에 한 일: Lambda/API + gateway container 배포 패키지를 AWS 없이 점검할 수 있도록 repo-local pre-deployment rehearsal command를 추가했다. local build helper tests, gateway health probe harness, and aggregate predeploy runner를 `scripts/ci/run_mlp_predeploy_checks.sh` 한 번으로 리허설하게 만들고, runbook/acceptance 문서에 그 evidence step을 기록했다.
- 다음에 할 일: operator 입력과 AWS 권한이 실제로 생기면 이 rehearsal output을 기준으로 별도 staging/prod execution row를 연다. 그 전까지는 AWS 배포를 진행하지 않는다.
- 검증 결과: focused pytest PASS, aggregate predeploy rehearsal PASS, `git diff --check` PASS.
- 상세 기록: `mlp/docs/history/2026-04-13_2230_slave_mlp_predeployment_rehearsal.md`

### 2026-04-13 20:30 — Production deployment planning container-first closeout
- 이번에 한 일: active row-native production deployment planning row를 Lambda/API control plane + App Runner gateway container 기준으로 다시 정리했다. row-native PRD/test spec, runbook, acceptance, blocked execution row, master index, audit(영문/국문)를 동기화해 container-first planning package를 canonical source로 고정했다.
- 다음에 할 일: operator가 hosted AWS/SAM/ECR/App Runner 권한과 실제 stage 입력값을 줄 때까지 AWS staging/prod deployment execution row는 blocked 상태로 유지한다.
- 검증 결과: deploy-contract unit tests PASS, gateway deploy manifest sample PASS, live gateway transport proof harness PASS, row-native/audit/current/history consistency grep PASS, `git diff --check` PASS.
- 상세 기록: `mlp/docs/history/2026-04-13_2030_slave_production_deployment_planning_container_first_closeout.md`

### 2026-04-12 12:39 — Async indexing path closure
- 이번에 한 일: `feat/mlp/async-indexing-path` 브랜치에서 기존에 반영돼 있던 Qdrant payload lookup + content-hash skip partition + skip-aware handler wiring + skip-evidence harness를 다시 검증한 뒤 row-native master index와 implementation audit를 green/done으로 갱신했다.
- 다음에 할 일: 남아 있는 다른 yellow row인 dashboard/provider-facing UX confidence refresh를 별도 브랜치에서 진행한다.
- 검증 결과: `uv run pytest tests/unit/test_qdrant_store.py tests/unit/test_mlp_services.py tests/unit/test_mlp_handlers.py tests/unit/test_index_handler_failed_status.py tests/unit/test_mlp_index_loop.py -v` PASS, `uv run ruff check src/retrieval/qdrant_store.py mlp/services/index_service.py mlp/lambdas/index/handler.py mlp/harness/index_loop.py tests/unit/test_qdrant_store.py tests/unit/test_mlp_services.py tests/unit/test_mlp_handlers.py tests/unit/test_index_handler_failed_status.py tests/unit/test_mlp_index_loop.py` PASS, `uv run python -m mlp.harness.index_loop --results-file mlp/harness/fixtures/index_runs_content_hash_skip_sample.json` PASS.
- 상세 기록: `mlp/docs/history/2026-04-12_1239_slave_async_indexing_path_closure.md`
### 2026-04-12 01:24 — Async indexing path implementation plan
- 이번에 한 일: `feat/mlp/async-indexing-path` 브랜치를 만든 뒤 row-native PRD/test spec, 현재 index handler/service/tests/harness 상태를 읽고 실행용 계획 `docs/superpowers/plans/2026-04-12-mlp-async-indexing-path.md`를 작성했다. 계획은 Qdrant payload lookup, content-hash skip partition, skip-aware handler wiring, loop-harness evidence, docs closeout까지를 한 acceptance gate로 고정한다.
- 다음에 할 일: 같은 브랜치에서 새 계획을 그대로 실행해 async indexing row를 green/done으로 닫는다.
- 검증 결과: plan readback PASS, placeholder scan PASS, `git branch --show-current` = `feat/mlp/async-indexing-path`, `git diff --check -- docs/superpowers/plans/2026-04-12-mlp-async-indexing-path.md` PASS.
- 상세 기록: `mlp/docs/history/2026-04-12_0124_slave_async_indexing_path_plan.md`

# Slave 작업 현황

### 2026-04-11 17:15 — MLP implementation audit 한국어 번역
- 이번에 한 일: `mlp/docs/analysis/mlp-implementation-audit.md`의 한국어 번역본 `mlp/docs/analysis/mlp-implementation-audit-ko.md`를 추가했다. 표 구조, 분류 체계, 코드/문서 경로는 유지하고 헤더와 설명만 한국어로 옮겼다.
- 다음에 할 일: 사용자가 원하면 같은 analysis 문서군에도 동일한 번역 규칙을 적용한다.
- 검증 결과: 원문/번역본 구조 대응 확인 PASS, 경로 보존 확인 PASS, `git diff --check` PASS.
- 상세 기록: `mlp/docs/history/2026-04-11_1715_slave_mlp_implementation_audit_translation.md`

### 2026-04-11 08:00 — MLP done-vs-missing audit
- 이번에 한 일: `mlp/docs/analysis/mlp-implementation-audit.md`를 작성해 `mlp/` 전체를 구현 존재 여부와 검증 근거 기준으로 inventory 했다. backend/service, frontend, planning/release lanes를 나눠 `구현됨 + 검증됨`, `구현됨 but 검증 부족`, `계획만 있음`, `미구현`으로 분류하고 우선순위 큐를 정리했다.
- 다음에 할 일: audit에서 노란색으로 남은 indexing/content-hash skip closure와 dashboard/provider-facing UX confidence를 다음 bounded lane에서 다룬다. planning-only lane들은 그대로 deferred 상태를 유지한다.
- 검증 결과: audit 문서 readback PASS, inventory table row count/summary consistency PASS, `git diff --check` PASS.
- 상세 기록: `mlp/docs/history/2026-04-11_0800_slave_mlp_done_vs_missing_audit.md`

> MLP 작업 누적 요약 로그
> 상세 내용은 `mlp/docs/history/` 문서에 기록한다.

## 기록 형식

```md
### YYYY-MM-DD HH:MM — 작업 제목
- 이번에 한 일:
- 다음에 할 일:
- 검증 결과:
- 상세 기록: `mlp/docs/history/YYYY-MM-DD_HHMM_slave_<task_slug>.md`
```

### 2026-04-11 — Task 5: Add content_hash for idempotent index skip + Migration 007
- 이번에 한 일: `mlp/shared/content_hash.py` 생성 (SHA-256 utility). TDD RED→GREEN: 4개 테스트 먼저 작성 후 구현. `mlp/supabase/migrations/007_entity_lifecycle_and_freshness.sql` 생성 (content_hash column, entity_status lifecycle, 3-tier freshness timestamps). register handler에 `content_hash` 필드 추가. 전체 660개 테스트 PASS.
- 다음에 할 일: Task 10 — index handler에서 content_hash 비교를 통한 skip 로직 추가. → 2026-04-12 async indexing closure lane에서 완료.
- 검증 결과: 660 passed, 1 warning (integration UserWarning only).
- 상세 기록: `mlp/docs/history/2026-04-11_slave_task5_content_hash.md`

### 2026-04-11 — Task 1: Add provenance fields to SearchResult and FindBestToolResponse
- 이번에 한 일: `src/models.py`에 provenance 필드 추가. `ScoreBreakdown`에 `trust`, `operability` (0.0 scaffold), `SearchResult`에 `source_path` Literal, `FindBestToolResponse`에 `degraded` bool + `source_path` Literal. 모든 필드에 default 설정하여 backward compatibility 완전 유지. TDD 준수: 5개 테스트 먼저 작성(RED) → 구현(GREEN) → 655개 전체 테스트 PASS.
- 다음에 할 일: Task 2 — RAG 파이프라인에서 degraded 상태와 source_path를 SearchResult/FindBestToolResponse로 전파.
- 검증 결과: 655 passed, 1 warning (integration UserWarning only). ruff lint/format PASS. pre-commit hook PASS.
- 상세 기록: `mlp/docs/history/2026-04-11_slave_task1_provenance_fields.md`

### 2026-04-09 23:33 — Final handoff packaging / query-gate preparation closeout
- 이번에 한 일: `feat/mlp/final-handoff-query-gate-preparation` 브랜치에서 canonical/mirror lane-13 문서를 작성해 roadmap 08, handoff 10, deployment-planning 11, frontend UI 12의 planning outputs를 하나의 final handoff package로 묶었다. deferred blocker table, future query-set draft skeleton, execution-readiness boundary를 추가해 later deployment execution / later query approval과의 경계를 명시했다.
- 다음에 할 일: 이 handoff package를 기준으로 operator inputs가 실제로 있을 때만 bounded deployment execution lane을 열고, approved queries가 필요하면 separate future query approval gate를 연다.
- 검증 결과: Architect APPROVE (boundary hardening 반영), Critic APPROVE, canonical/mirror/history/current readback PASS, `git branch --show-current` = `feat/mlp/final-handoff-query-gate-preparation`, `git diff --check` PASS.
- 상세 기록: `mlp/docs/history/2026-04-09_2333_slave_final_handoff_query_gate_preparation.md`

### 2026-04-09 21:08 — Production deployment planning closeout
- 이번에 한 일: `feat/mlp/deployment-planning-closeout` 브랜치에서 canonical/mirror lane-11 문서를 closeout 상태로 보강해 readiness matrix, operator input checklist, rollout/rollback checklist, post-deploy verification matrix, deferred items list를 채웠다. 이 artifact가 deployment execution이 아니라 planning closeout이며 operator inputs가 여전히 없다는 점을 명시했다.
- 다음에 할 일: roadmap 순서대로 frontend UI planning lane을 연 뒤 final handoff/query-gate preparation lane으로 이어간다. 실제 backend 실행이 필요해지면 3000 포트만 사용하고, 3000이 점유 중이면 먼저 종료한 뒤 시작한다.
- 검증 결과: Architect APPROVE, Critic APPROVE, canonical/mirror/history/current readback 확인, `git branch --show-current` = `feat/mlp/deployment-planning-closeout`, `git diff --check` PASS.
- 상세 기록: `mlp/docs/history/2026-04-09_2108_slave_production_deployment_planning_closeout.md`

### 2026-04-09 20:56 — MLP remaining work inventory + next lane selection
- 이번에 한 일: `docs/plan/checklist.md`, `mlp/docs/plan/08_root_vision_gap_and_future_roadmap.md`, `mlp/docs/plan/11_production_deployment_planning_lane*.md`를 다시 읽고 남은 MLP 작업을 near-term / later로 재분류했다. 남은 near-term은 production deployment planning closeout, frontend UI planning lane, final handoff/query-gate prep이며 later는 bounded deployment execution, Phase 8-12 실제 구현/실험 잔여다.
- 다음에 할 일: 새 브랜치 `feat/mlp/deployment-planning-closeout` 기준으로 현재 production deployment planning lane을 먼저 마감하고, 그 다음 frontend UI planning lane을 여는 순서로 진행한다.
- 검증 결과: 계획용 readback만 수행했고 코드/테스트는 아직 실행하지 않았다.
- 상세 기록: `mlp/docs/history/2026-04-09_2056_slave_remaining_mlp_work_inventory_and_next_lane.md`

### 2026-04-05 12:19 — MLP 구현 계획 문서 작성
- 이번에 한 일: `mlp/` 현재 구조를 읽고 코드 구조 문서 1개와 순차 구현 계획 문서 6개를 `mlp/docs/plan/`에 작성
- 다음에 할 일: `01_shared_core_runtime_foundation.md`부터 순서대로 실행하며 handler/service 경계를 정리
- 검증 결과: 문서만 작성했으며 테스트는 실행하지 않음
- 상세 기록: `mlp/docs/history/2026-04-05_1219_slave_mlp_plan_bootstrap.md`

### 2026-04-05 13:08 — Shared core runtime 실행 계획 작성
- 이번에 한 일: `feat/mlp-shared-core-runtime-foundation` 브랜치를 만들고 `mlp/docs/plan/01_shared_core_runtime_foundation.md`를 실행용 체크리스트로 재작성해 `docs/superpowers/plans/2026-04-05-mlp-shared-core-runtime-foundation.md`에 저장
- 다음에 할 일: 새 계획의 Task 1부터 shared settings/http/logging과 runtime factory를 먼저 구현
- 검증 결과: 브랜치 생성은 확인했고 문서 작업만 수행했으므로 테스트는 실행하지 않음
- 상세 기록: `mlp/docs/history/2026-04-05_1308_slave_shared_core_runtime_foundation_plan.md`

### 2026-04-05 13:58 — Shared core runtime foundation 구현
- 이번에 한 일: `mlp/shared/`, `mlp/services/` 공용 계층을 추가하고 search/index/bridge handler를 thin adapter로 리팩터링했으며 관련 단위 테스트 4개 파일을 추가/갱신
- 다음에 할 일: 다음 계획 문서(`02_search_path_and_rag_service.md`)로 넘어가 search path와 RAG service 연결을 실제로 닫기
- 검증 결과: `uv run ruff check src mlp tests` PASS, `uv run pytest tests/unit/test_mlp_shared_http.py tests/unit/test_mlp_runtime.py tests/unit/test_mlp_services.py tests/unit/test_mlp_handlers.py -v` PASS (`49 passed`)
- 상세 기록: `mlp/docs/history/2026-04-05_1358_slave_shared_core_runtime_foundation_impl.md`

### 2026-04-06 00:27 — Plan 05 상태 문서화 + Google OAuth 전환
- 이번에 한 일: Plan 05를 실제 구현 상태 기준으로 재정리하고, MLP dashboard를 API-first + provider ownership 구조로 문서에 반영했다. MCP Discovery 로그인 화면을 Google OAuth 전용으로 바꾸고 AuthContext를 `signInWithGoogle()` 기준으로 단순화했다. 로컬 프론트 env 점검 결과 `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`는 존재하지만 `VITE_API_URL`, `VITE_MLP_API_KEY`는 미설정 상태임을 확인했다.
- 다음에 할 일: 배포된 `ApiUrl`과 `MlpApiKey`를 찾아 프론트 env에 채우고, Supabase Google OAuth redirect를 포함한 sign-in → dashboard 복귀 → provider-owned dashboard 표시를 실제 브라우저에서 검증한다.
- 검증 결과: `uv run pytest tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_template_contract.py -q` PASS (`42 passed`), `npm test -- src/lib/api.test.ts src/pages/Dashboard.test.tsx` PASS (`3 passed`), `npm test -- src/contexts/AuthContext.test.tsx src/pages/Login.test.tsx` PASS (`2 passed`), `npm test` PASS (`5 files, 6 tests`), `npm run build` PASS
- 상세 기록: `mlp/docs/history/2026-04-06_0027_slave_plan05_api_first_google_oauth.md`

### 2026-04-06 11:37 — Plan 05 잔여 작업 로컬 closure 구현
- 이번에 한 일: Plan 06 closeout용 `index_loop`, `execute_loop`, `smoke_api` 하네스와 관련 unit test를 추가했고, `replay_queries.py`, `verify_provider_dashboard.py`, `runbook.md`, `acceptance.md`를 작성했다. `test_mlp_template_contract.py`를 release guard 기준으로 강화했다.
- 다음에 할 일: 배포 stage의 `ApiUrl`/`MlpApiKey`를 확보해 프론트 env에 반영하고, Supabase Google OAuth redirect 설정 후 실제 `/login -> Google OAuth -> /dashboard` 및 provider-owned dashboard E2E를 live로 검증한다.
- 검증 결과: `uv run ruff check`(touched files) PASS, `uv run pytest tests/unit/test_mlp_index_loop.py tests/unit/test_mlp_execute_loop.py tests/unit/test_mlp_smoke_api.py tests/unit/test_mlp_template_contract.py tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py -q` PASS (`48 passed`), `npm test -- src/lib/api.test.ts src/pages/Dashboard.test.tsx` PASS (`3 passed`), `npm test -- src/contexts/AuthContext.test.tsx src/pages/Login.test.tsx` PASS (`2 passed`), `npm test` PASS (`5 files, 6 tests`), `npm run build` PASS, `uv run python -m mlp.harness.index_loop` / `execute_loop` / `smoke_api --sample` PASS, `uv run python mlp/scripts/replay_queries.py --format lines` PASS, `uv run python mlp/scripts/verify_provider_dashboard.py --help` PASS
- 상세 기록: `mlp/docs/history/2026-04-06_1137_slave_plan05_release_closure_local_impl.md`

### 2026-04-06 12:13 — 로컬 backend 테스트용 env 동기화
- 이번에 한 일: root `.env`에 이미 존재하던 `VITE_API_URL`, `VITE_MLP_API_KEY`를 확인하고, Vite가 실제로 읽는 `mlp/frontend/.env.local`에도 동일 키를 동기화했다. local-first 경로 기준으로 backend test 준비 상태를 점검했고, 현재 환경에는 `sam` CLI가 없어 `sam local start-api` / 배포는 아직 실행하지 못하는 상태임을 확인했다.
- 다음에 할 일: `sam` CLI를 설치한 뒤 `sam build` / `sam local start-api`로 로컬 backend를 띄워 smoke를 확인하고, 이후 AWS 배포로 넘어간다.
- 검증 결과: key presence check PASS (root `.env`, `mlp/frontend/.env.local` 모두 `VITE_API_URL`, `VITE_MLP_API_KEY` 존재), `uv run pytest tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_template_contract.py -q` PASS (`42 passed`), `npm run build` PASS, `command -v sam` 결과 없음 (`sam` 미설치 확인)
- 상세 기록: `mlp/docs/history/2026-04-06_1213_slave_local_backend_env_sync.md`

### 2026-04-06 12:28 — local SAM build 성공, Docker runtime blocker 확인
- 이번에 한 일: Homebrew 설치 상태를 점검해 `sam` CLI를 활성 경로에서 확인했고, `sam build -t template.yaml`를 성공시켰다. 이어 `sam local start-api --port 3000`를 root `.env` 기반 parameter override로 실행해 local Lambda/API 기동을 시도했다.
- 다음에 할 일: Docker Desktop(또는 Finch)을 실행한 뒤 `sam local start-api`를 재시도하고, 로컬 smoke를 붙인 후 AWS 배포 단계로 넘어간다.
- 검증 결과: `/opt/homebrew/bin/sam --version` PASS (`1.157.1`), `sam build -t template.yaml` PASS (`Build Succeeded`), `sam local start-api` FAIL (container runtime 미기동: `Do you have Docker or Finch installed and running?`)
- 상세 기록: `mlp/docs/history/2026-04-06_1228_slave_local_sam_build_and_docker_blocker.md`

### 2026-04-06 12:44 — local SAM API 기동 심화 점검
- 이번에 한 일: Docker daemon/socket 경로를 잡아 `sam local start-api`를 실제로 띄웠고, 로컬 smoke 요청까지 보냈다. 그 과정에서 빌드 artifact에 `mlp` runtime package가 누락되는 문제를 확인해 `mlp/__init__.py`, `mlp/Makefile` 보강과 built artifact runtime sync를 시도했다. 이후 import error는 `mlp` 누락에서 `pydantic_core` ABI mismatch로 진전됐고, 이를 해결하려고 `sam build --use-container`까지 시도했다.
- 다음에 할 일: `sam build --use-container`가 실패하는 custom Makefile path 문제(`cp //mlp/...`)를 고쳐 Lambda-compatible build를 만들고, 다시 `sam local start-api` + smoke를 통과시킨 뒤 AWS 배포로 넘어간다.
- 검증 결과: `docker info` PASS (`27.4.0`), `sam local start-api` PASS (endpoint mount 성공), local smoke FAIL 1차 (`No module named 'mlp'`), built artifact runtime sync 후 local smoke FAIL 2차 (`No module named 'pydantic_core._pydantic_core'`), `sam build --use-container -t template.yaml` FAIL (container build에서 Makefile root path 해석 오류: `cp //mlp/lambdas/authorizer/handler.py`)
- 상세 기록: `mlp/docs/history/2026-04-06_1244_slave_local_sam_runtime_and_container_build_blockers.md`

### 2026-04-06 13:27 — Plan 05 live/stage verification blocker 정리
- 이번에 한 일: `feat/mlp/live-stage-verification` branch를 새 worktree(`/tmp/mcp_optimizer-mlp-live-stage`)로 만들고, live verification 입력값을 점검했다. 현재 root `.env`와 `mlp/frontend/.env.local`의 `VITE_API_URL`은 배포 stage가 아니라 `127.0.0.1:3000`을 가리키며, 실제 deployed `ApiUrl`/`MLP_BEARER_TOKEN`은 확보되지 않았음을 확인했다. local target probe는 sandbox에서는 `ConnectError`였고, escalated probe에서는 최종적으로 `Connection refused`였다.
- 다음에 할 일: deployed `ApiUrl`, `MlpApiKey`, provider bearer token, Supabase Google OAuth redirect/origin 접근 권한을 확보한 뒤 `verify_provider_dashboard.py`와 브라우저 `/login -> Google OAuth -> /dashboard` 검증을 재실행한다.
- 검증 결과: `git worktree add /tmp/mcp_optimizer-mlp-live-stage -b feat/mlp/live-stage-verification main` PASS, worktree branch 생성 확인 PASS, env presence check PASS (`VITE_API_URL`/`VITE_MLP_API_KEY` present, `MLP_BEARER_TOKEN` missing), API target classification PASS (`127.0.0.1:3000` = local only), API probe FAIL (sandbox `ConnectError`, escalated `Connection refused`), AWS config discovery FAIL (`aws` CLI/config 없음), `uv run pytest tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_template_contract.py -q` PASS (`42 passed`), `npm test -- src/lib/api.test.ts src/pages/Dashboard.test.tsx src/contexts/AuthContext.test.tsx src/pages/Login.test.tsx` PASS (`5 passed`), `npm run build` PASS
- 상세 기록: `mlp/docs/history/2026-04-06_1327_slave_plan05_live_stage_verification_blocked_on_stage_inputs.md`

### 2026-04-06 14:29 — 로컬 backend/frontend 기동 검증
- 이번에 한 일: `feat/mlp/live-stage-verification` worktree에서 local-only SAM 경로를 추가해 backend를 `127.0.0.1:3001`에 띄웠고, frontend는 동일 submodule commit의 hydrated checkout에서 Vite dev server를 `127.0.0.1:4173`로 띄워 로컬 backend와 연결해 검증했다. repo-root `Makefile`, `mlp/template.local.yaml`을 추가했고, `mlp/services/__init__.py`, `mlp/shared/__init__.py`를 lazy import로 바꿔 catalog/dashboard가 search/retrieval stack을 eager import하지 않도록 정리했다.
- 다음에 할 일: local-only 지원 파일을 커밋 가능한 상태로 정리하고, 필요하면 provider login/browser 경로를 별도 lane으로 확장한다.
- 검증 결과: `sam build --use-container -t mlp/template.local.yaml` PASS, built template 기반 `sam local start-api --port 3001 -t .aws-sam/build/template.yaml` PASS, `GET /api/platform/stats` PASS (`200` + stats payload), `GET /api/servers?limit=5&offset=0` PASS, `POST /api/search` PASS (`200` + result payload), frontend dev server PASS (`http://127.0.0.1:4173/`), browser 확인 PASS (`/` 및 `/servers` 렌더 + backend requests 200 + console error 0), `uv run pytest tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_template_contract.py -q` PASS (`42 passed`), `npm test -- src/lib/api.test.ts src/pages/Dashboard.test.tsx src/contexts/AuthContext.test.tsx src/pages/Login.test.tsx` PASS (`5 passed`), `npm run build` PASS
- 상세 기록: `mlp/docs/history/2026-04-06_1429_slave_local_frontend_backend_verification.md`

### 2026-04-06 19:10 — Plan 05/06 local-first re-scope
- 이번에 한 일: Plan 05/06와 supporting docs를 local-first release gate 기준으로 재정리했다. provider registration은 backend API 존재만으로 완료가 아니라 frontend self-serve 등록과 dashboard reflection까지 포함하는 것으로 기준을 고정했고, AWS staging/prod는 deferred로 내렸다.
- 다음에 할 일: Plan 05의 frontend self-serve registration lane을 실제 구현하고, local `login -> register -> dashboard reflection` 증거를 확보한다.
- 검증 결과: 문서 readback 기준으로 Plan 05, Plan 06, acceptance, runbook, current/history 로그가 같은 done criteria와 deferred AWS 정책을 사용하도록 정렬했다. 로컬 SAM/runtime blocker 자체는 아직 해결되지 않아 E2E는 미완료 상태다.
- 상세 기록: `mlp/docs/history/2026-04-06_1910_slave_plan05_06_local_first_rescope.md`

### 2026-04-06 20:25 — Plan 05 frontend self-serve registration 구현
- 이번에 한 일: `/dashboard/register` protected route와 self-serve registration form을 추가했고, authenticated `POST /api/servers` mutation 및 pending banner가 dashboard와 연결되도록 구현했다. 관련 frontend tests와 Plan 05 source of truth도 현재 구현 상태에 맞게 갱신했다.
- 다음에 할 일: local SAM/runtime blocker를 정리하고 실제 `login -> register -> dashboard reflection` evidence를 확보한다.
- 검증 결과: `cd mlp/frontend && npm test -- src/lib/api.test.ts src/pages/Dashboard.test.tsx src/pages/RegisterServer.test.tsx` PASS (`3 files, 7 tests`), `cd mlp/frontend && npm test` PASS (`6 files, 13 tests`), `cd mlp/frontend && npm run build` PASS, TS diagnostics PASS (`App.tsx`, `api.ts`, `database.ts`, `Dashboard.tsx`, `Dashboard.test.tsx`, `RegisterServer.tsx`, `RegisterServer.test.tsx` 모두 0 errors)
- 상세 기록: `mlp/docs/history/2026-04-06_2025_slave_frontend_self_serve_registration.md`

### 2026-04-06 21:05 — local runtime/E2E blocked by Supabase schema
- 이번에 한 일: `sam build`/`sam local start-api` 경로를 다시 복구하고, test provider session으로 local register/dashboard API + browser registration submit까지 실제로 검증했다.
- 다음에 할 일: 연결된 Supabase에 migration 005(`owner_user_id`) 반영 여부를 확인하고 schema cache를 갱신한 뒤 동일 E2E를 재실행한다.
- 검증 결과: `cd mlp && sam build -t template.yaml` PASS, local API on `127.0.0.1:3003` started PASS, `uv run pytest tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_template_contract.py -q` PASS (`42 passed`), `cd mlp/frontend && npm test` PASS (`6 files, 13 tests`), `cd mlp/frontend && npm run build` PASS. 실제 E2E는 Supabase 400 (`owner_user_id` column missing / schema cache miss)로 BLOCKED.
- 상세 기록: `mlp/docs/history/2026-04-06_2105_slave_local_runtime_e2e_blocked_by_supabase_schema.md`

### 2026-04-06 22:52 — Plan 05 local gate closure 재검증
- 이번에 한 일: provider ownership compatibility fallback이 실제 연결된 Supabase schema mismatch를 우회하는지 fresh evidence로 재검증했고, local SAM rebuild + provider-owned register/dashboard API proof까지 다시 통과시켰다.
- 다음에 할 일: Plan 06 local operations/release verification 정리로 넘어가거나 deferred AWS lane을 재평가한다.
- 검증 결과: `uv run ruff check mlp/shared/provider_ownership.py mlp/adapters/supabase_client.py mlp/lambdas/register/handler.py tests/unit/test_mlp_handlers.py tests/unit/test_mlp_provider_ownership.py` PASS, `uv run pytest tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_template_contract.py tests/unit/test_mlp_index_loop.py tests/unit/test_mlp_execute_loop.py tests/unit/test_mlp_smoke_api.py tests/unit/test_mlp_provider_ownership.py -q` PASS (`52 passed`), `cd mlp/frontend && npm test` PASS (`6 files, 13 tests`), local-API rebuild frontend `npm run build` PASS, `cd mlp && SAM_CLI_TELEMETRY=0 PIP_CACHE_DIR=/tmp/pip-cache sam build -t template.yaml` PASS, local provider-owned API verification PASS (`register 201`, dashboard unauth `401`, owned detail `200`, missing tool `404`, reflected tool visible), browser proof PASS (`/login` CTA visible, `/dashboard/register` submit redirects, pending banner + reflected tool visible).
- 상세 기록: `mlp/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md`

### 2026-04-07 20:48 — Plan 05 local provider journey closed
- 이번에 한 일: self-serve registration UI/route를 복구하고, local SAM build/runtime blockers(`pip`, async httpx local runtime, Supabase owner schema mismatch)를 해소해 `/dashboard/register -> pending banner -> dashboard reflection`까지 local provider journey를 실제로 닫았다.
- 다음에 할 일: Plan 06을 별도 브랜치/acceptance gate로 진행한다.
- 검증 결과: backend unit regression PASS (`51 passed`), focused ownership/register regression PASS (`44 passed`), frontend tests PASS (`6 files, 9 tests`), frontend build PASS, `verify_provider_dashboard.py` local proof PASS (`201/401/200/404`), browser proof PASS (`/dashboard/register` submit redirects, pending banner + reflected owned tools visible).
- 상세 기록: `mlp/docs/history/2026-04-07_2048_slave_plan05_local_provider_journey_closed.md`

### 2026-04-08 00:34 — Root vision gap roadmap 문서화
- 이번에 한 일: 브랜치 `feat/mlp/root-vision-gap-plan`를 만든 뒤, deep-interview spec과 consensus review(Planner/Architect/Critic)를 바탕으로 루트 비전 기준 gap audit/future roadmap PRD + test spec을 `mlp/docs/plan/07_root_vision_gap_and_future_roadmap*.md`로 문서화했다.
- 다음에 할 일: roadmap 기준으로 gap matrix를 더 구체화하고, execution 전 승인 필요한 validation query set 초안을 만든다.
- 검증 결과: roadmap/test spec readback 확인, Architect APPROVE, Critic APPROVE, planning-only boundary 유지 확인.
- 상세 기록: `mlp/docs/history/2026-04-08_0034_slave_root_vision_gap_plan.md`

### 2026-04-08 16:18 — Root vision gap execution-ready planning pass
- 이번에 한 일: `$ralplan` consensus로 root-vision roadmap의 다음 planning pass를 execution-ready 수준으로 재정의했고, canonical `.omx/plans/*`와 repo mirror `mlp/docs/plan/08_root_vision_gap_and_future_roadmap*.md`를 작성했다.
- 다음에 할 일: 새 planning set을 기준으로 실제 implementation 착수 여부를 판단하고, 필요하면 `$ralph` 또는 `$team`으로 bounded execution lane으로 넘긴다.
- 검증 결과: canonical/mirror readback 확인, Architect APPROVE, Critic APPROVE, `git diff --check` 통과.
- 상세 기록: `mlp/docs/history/2026-04-08_1618_slave_root_vision_gap_execution_ready_plan.md`

### 2026-04-08 19:29 — Root vision bridge loop sentinel
- 이번에 한 일: `hear/mlp/root-vision-bridge-contract-sentinel` 브랜치에서 bridge 전용 loop harness(`mlp/harness/bridge_loop.py`)와 그 회귀 테스트를 추가해 root-vision 첫 실행 슬라이스를 좁게 잠갔다.
- 다음에 할 일: 실제 recorded bridge run 입력을 붙일 수 있는 다음 validation slice(예: hosted HTTP MCP sample evidence)로 이어간다.
- 검증 결과: `uv run ruff check mlp/harness/bridge_loop.py tests/unit/test_mlp_bridge_loop.py tests/unit/test_mlp_handlers.py` PASS, `uv run pytest tests/unit/test_mlp_bridge_loop.py tests/unit/test_mlp_handlers.py -q` PASS (`42 passed`), `UV_CACHE_DIR=/tmp/uv-cache uv run python -m mlp.harness.bridge_loop` PASS
- 상세 기록: `mlp/docs/history/2026-04-08_1929_slave_root_vision_bridge_loop_sentinel.md`

### 2026-04-08 21:32 — Root vision bridge file-mode evidence
- 이번에 한 일: 대표 bridge-run 입력 파일 `mlp/harness/fixtures/bridge_runs_recorded_sample.json`을 추가하고, `bridge_loop --input` 경로를 fixture 기반 회귀 테스트 + 실제 CLI 실행으로 검증했다.
- 다음에 할 일: representative fixture를 넘어 실제 recorded bridge runs 또는 hosted HTTP MCP evidence로 확장하는 다음 validation slice를 진행한다.
- 검증 결과: `uv run ruff check tests/unit/test_mlp_bridge_loop.py` PASS, `uv run pytest tests/unit/test_mlp_bridge_loop.py tests/unit/test_mlp_handlers.py -q` PASS (`43 passed`), `UV_CACHE_DIR=/tmp/uv-cache uv run python -m mlp.harness.bridge_loop --input mlp/harness/fixtures/bridge_runs_recorded_sample.json` PASS
- 상세 기록: `mlp/docs/history/2026-04-08_2132_slave_root_vision_bridge_filemode_evidence.md`

### 2026-04-08 22:33 — Root vision recorded bridge runs evidence
- 이번에 한 일: local bridge proof를 자동화하는 `mlp.harness.record_bridge_runs`와 회귀 테스트를 추가했고, 실제 local provider register -> bridge search -> execute_tool raw artifact `mlp/harness/fixtures/bridge_runs_recorded_local_sam_pending_20260408T133734Z.json`를 생성했다.
- 다음에 할 일: 이번 recorded local proof를 기준으로 hosted HTTP MCP fallback lane이 필요한지 판단하고, 필요하면 다음 validation slice로 넘긴다.
- 검증 결과: `uv run ruff check mlp/harness/record_bridge_runs.py tests/unit/test_mlp_record_bridge_runs.py mlp/harness/bridge_loop.py tests/unit/test_mlp_bridge_loop.py tests/unit/test_mlp_handlers.py` PASS, `uv run pytest tests/unit/test_mlp_record_bridge_runs.py tests/unit/test_mlp_bridge_loop.py tests/unit/test_mlp_handlers.py -q` PASS (`49 passed`), `cd mlp && DOCKER_HOST=unix:///Users/iyeonjae/.docker/run/docker.sock SAM_CLI_TELEMETRY=0 sam build --use-container -t template.yaml` PASS, `UV_CACHE_DIR=/tmp/uv-cache uv run python -m mlp.harness.record_bridge_runs --base-url http://127.0.0.1:3000 --source local_sam_pending` PASS, `UV_CACHE_DIR=/tmp/uv-cache uv run python -m mlp.harness.bridge_loop --input mlp/harness/fixtures/bridge_runs_recorded_local_sam_pending_20260408T133734Z.json` PASS
- 상세 기록: `mlp/docs/history/2026-04-08_2233_slave_root_vision_recorded_bridge_runs_evidence.md`

### 2026-04-08 22:54 — Hosted HTTP MCP fallback necessity memo
- 이번에 한 일: Stage 0 decision memo를 canonical `.omx/plans/decision-mlp-hosted-http-mcp-fallback-necessity.md`와 repo mirror `mlp/docs/plan/09_hosted_http_mcp_fallback_necessity_memo.md`로 작성하고, current root-vision lane에서 별도 hosted fallback evidence는 **지금은 불필요**하다고 결정했다.
- 다음에 할 일: 현재 lane을 close/handoff 하거나, 새로운 contrary evidence가 생길 때만 hosted fallback PRD/test spec lane을 별도로 연다.
- 검증 결과: memo readback PASS, canonical/mirror cross-check PASS, supporting roadmap/history evidence grep PASS, `git diff --check` PASS
- 상세 기록: `mlp/docs/history/2026-04-08_2254_slave_hosted_http_mcp_fallback_necessity_memo.md`

### 2026-04-08 23:06 — Root vision recorded-bridge lane handoff
- 이번에 한 일: canonical handoff `.omx/plans/handoff-mlp-root-vision-recorded-bridge-lane.md`와 repo mirror `mlp/docs/plan/10_root_vision_recorded_bridge_lane_handoff.md`를 작성해 현재 recorded-bridge evidence lane을 **closed / handoff-ready** 상태로 정리했다.
- 다음에 할 일: 새 bounded planning lane으로 넘어간다. 우선순위는 production deployment planning lane → frontend UI planning lane → later handoff/query-gate preparation 순서다.
- 검증 결과: handoff doc readback PASS, canonical/mirror cross-check PASS, scope reopen 방지 wording PASS, `git diff --check` PASS
- 상세 기록: `mlp/docs/history/2026-04-08_2306_slave_root_vision_recorded_bridge_lane_handoff.md`

### 2026-04-09 19:39 — Production deployment planning lane start
- 이번에 한 일: `origin/main` 동기화와 3000번 포트 점검을 먼저 끝낸 뒤, `$ralplan` consensus 결과에 따라 production deployment planning lane을 새 canonical `.omx/plans/*` + repo mirror `mlp/docs/plan/11_*` 문서로 시작했다.
- 다음에 할 일: 이 doc-only planning artifact를 기준으로 frontend UI planning lane 또는 별도 bounded deployment execution lane의 입력 정리를 판단한다.
- 검증 결과: `git fetch origin main` PASS, `git merge --ff-only origin/main` already up to date, `lsof -nP -iTCP:3000 -sTCP:LISTEN` listener 없음, canonical/mirror doc readback PASS, lane-order cross-check PASS, `git diff --check` PASS.
- 상세 기록: `mlp/docs/history/2026-04-09_1939_slave_production_deployment_planning_lane.md`

### 2026-04-09 13:38 — Frontend UI planning closeout
- 이번에 한 일: frontend UI planning lane의 canonical PRD/test spec과 repo mirror를 작성해 UI gap table, state/feedback gap notes, downstream-dev marker wording, and later handoff boundary를 planning-only closeout으로 정리했다.
- 다음에 할 일: final handoff packaging / query-gate preparation lane로 넘어가되, UI implementation이나 broad redesign로 확장하지 않는다.
- 검증 결과: canonical/mirror readback PASS, architect wording hardening 반영 PASS, `git diff --check` PASS
- 상세 기록: `mlp/docs/history/2026-04-09_1338_slave_frontend_ui_planning_closeout.md`

### 2026-04-11 23:59 — Row-native replanning reset
- 이번에 한 일: non-green MLP audit rows의 canonical planning surface를 `mlp/docs/plan/row-native/`로 재설정했다. Yellow rows(async indexing content-hash closure, dashboard/provider-facing UX confidence refresh)를 먼저 rewrite했고, planning-only rows(production deployment planning, frontend UI planning, final handoff/query-gate preparation)는 row-native targets로 옮겼다. AWS staging/prod deployment execution은 operator-owned inputs와 deploy authority가 생길 때까지 red/blocked로 유지한다.
- 다음에 할 일: row-native plan이 active/blocked에서 done으로 이동하면 current/history docs를 다시 갱신한다. Legacy lane docs 03/05는 reference로 유지하고, 11/12/13과 test specs는 later cleanup이 필요하다는 audit evidence가 나오기 전까지 superseded 상태로 둔다.
- 검증 결과: current/history readback PASS, row-native planning placeholder scan PASS(no `TODO`/`TBD`/`FIXME` matches), `git diff --check` PASS.
- 상세 기록: `mlp/docs/history/2026-04-11_slave_row_native_replanning_reset.md`

### 2026-04-12 01:12 — Dashboard/provider-facing UX confidence refresh planning
- 이번에 한 일: `feat/mlp/dashboard-provider-facing-ux-confidence-refresh` 브랜치를 만든 뒤 row-native PRD/test spec, provider-first frontend quality plan, 현재 dashboard/tool-detail 구현을 읽고 `docs/superpowers/plans/2026-04-12-mlp-dashboard-provider-facing-ux-confidence-refresh.md` 실행 계획을 작성했다.
- 다음에 할 일: plan 순서대로 `DashboardToolDetail` actionability pass → `Dashboard` minimal drilldown cue → provider proof/audit reconciliation 순서로 실행한다.
- 검증 결과: PRD/test spec/frontend/readback PASS, plan saved PASS, `git branch --show-current` = `feat/mlp/dashboard-provider-facing-ux-confidence-refresh`, `git diff --check` PASS
- 상세 기록: `mlp/docs/history/2026-04-12_0112_slave_dashboard_provider_facing_ux_confidence_refresh_planning.md`

### 2026-04-12 12:15 — Dashboard/provider-facing UX confidence row closure
- 이번에 한 일: isolated worktree에서 `DashboardToolDetail` actionability pass와 `Dashboard` minimal drilldown cue를 완료하고, fresh frontend/browser evidence와 보존된 provider-owned API proof를 근거로 row-native audit 문서를 green 기준으로 정렬했다.
- 다음에 할 일: 현재 우선순위는 async indexing content-hash closure다. provider detail 계약이나 live auth/runtime 입력이 다시 바뀔 때만 dashboard/provider-facing proof를 재실행한다.
- 검증 결과: `cd mlp/frontend && npm test` PASS (`16 passed`), `npm run lint` FAIL (pre-existing unrelated errors in `src/components/ui/command.tsx`, `src/components/ui/textarea.tsx`, `tailwind.config.ts`), `npm exec -- tsc --noEmit` PASS, `npm run build` PASS, fresh browser proof PASS, `uv run python mlp/scripts/verify_provider_dashboard.py --server-id dashboard-provider-ux-proof` BLOCKED (missing `MLP_BASE_URL`/`MLP_BEARER_TOKEN`), preserved 2026-04-07 provider-owned API proof reused, `git diff --check` PASS
- 상세 기록: `mlp/docs/history/2026-04-12_1215_slave_dashboard_provider_facing_ux_confidence_refresh_closure.md`

### 2026-04-12 20:05 — Provider dashboard verifier rerun
- 이번에 한 일: `feat/mlp/provider-dashboard-bearer-token-proof-rerun` worktree에서 verifier missing-input 실패를 다시 재현하고, root `.env` / `mlp/frontend/.env.local` env split을 확인한 뒤, expired frontend bearer token을 fresh Supabase session 기준으로 갱신해 local SAM(`127.0.0.1:3000`) 위에서 `verify_provider_dashboard.py`를 두 번 모두 PASS로 만들고, temp token/proof artifacts까지 정리했다.
- 다음에 할 일: provider dashboard proof를 다시 돌릴 때는 먼저 cached bearer token expiry를 확인하고, 만료되어 있으면 fresh token을 얻은 뒤 root `.env`를 source한 같은 shell에서 verifier를 실행한다.
- 검증 결과: failure reproduction PASS, env split PASS, cached-token expiry detection PASS, fresh bearer-token recovery PASS, local `sam build`/`sam local start-api` PASS, `/api/platform/stats` probe PASS (`200`), `uv run python mlp/scripts/verify_provider_dashboard.py --server-id dashboard-provider-ux-proof` PASS (`201/401/200/404`), `uv run python mlp/scripts/verify_provider_dashboard.py --server-id dashboard-provider-ux-proof-rerun` PASS (`201/401/200/404`), temp token/proof cleanup PASS, `git diff --check` PASS.
- 상세 기록: `mlp/docs/history/2026-04-12_2005_slave_provider_dashboard_verifier_rerun.md`

### 2026-04-15 21:01 — Latest main local runtime consistency fix
- 이번에 한 일: latest main에서 깨져 있던 local runtime 일관성을 복구했다. `compose.mcp.yaml`가 참조하던 `mlp.mcp_server.local_app`, `mlp.mcp_server.mock_provider` 모듈을 추가하고, `our-mcp-server-dev`의 install path를 `pip install .`로 고쳐 compose 로컬 MCP 서비스 import 경로를 안정화했다. 또한 upstream에 없는 `mlp/frontend` gitlink를 fetch 가능한 `998202399badbb16bc9f3d2bd58f92e702c7fdf7`로 맞췄다.
- 다음에 할 일: 사용자 승인 전까지 option 2는 진행하지 않는다. 필요 시 Docker daemon을 띄운 뒤 live `docker compose up` proof를 다시 실행하거나, 승인 후 real-world MCP onboarding/LLM client validation(option 2)로 넘어간다.
- 검증 결과: targeted pytest PASS (`7 passed`), ruff PASS, `py_compile` PASS, `docker compose config` PASS, frontend build PASS, repo-local backend/frontend/MCP health probes PASS. 단, live compose 실행은 Docker daemon 미기동으로 BLOCKED.
- 상세 기록: `mlp/docs/history/2026-04-15_2101_slave_latest_main_local_runtime_consistency_fix.md`

### 2026-04-15 22:08 — Compose full-stack operational validation
- 이번에 한 일: Docker Desktop을 띄운 뒤 `compose.mcp.yaml` 전체 스택을 실제로 올려 backend/frontend/gateway/MCP/mock-provider를 검증했고, real `n8n-mcp`를 외부 provider로 등록해 compose MCP 서버에서 `execute_tool`까지 실행했다. 실행 후 `execution_logs`와 `tool_operability_view`에 호출 수/성공률/지연이 반영되는지 확인했다.
- 다음에 할 일: 남은 blocker는 live Supabase 쪽 `provider_tool_dashboard` view/schema cache 문제와 Playwright MachPort 브라우저 권한 문제다. 이 둘이 풀리면 dashboard에서 실행 횟수 반영 여부와 browser proof를 마저 닫는다.
- 검증 결과: `docker compose up --build -d` PASS, compose service health PASS, real n8n registration PASS (`202 Accepted`), compose MCP `execute_tool` PASS, `execution_logs`/`tool_operability_view` update PASS. 단, provider dashboard API는 `provider_tool_dashboard` missing schema-cache 문제로 tool/call_count를 보여주지 못했고, Playwright browser proof는 MachPort 권한으로 BLOCKED.
- 상세 기록: `mlp/docs/history/2026-04-15_2208_slave_compose_operational_validation.md`

### 2026-04-15 22:14 — Option 2 runtime compatibility follow-up
- 이번에 한 일: option 2 검증 중 발견된 repo-side compatibility 문제를 추가로 정리했다. `repository_url` schema drift fallback을 register/API 쪽에 넣고, `fetch_server()`가 fallback 시 `owner_user_id`를 유지하도록 고친 뒤 관련 회귀 테스트를 추가했다. 또한 `.mcp.json`, `mlp/harness/local_bridge_mcp.py`, `compose.mcp.yaml`를 보강해 compose MCP 서비스와 로컬 MCP client 경로를 더 안정화했다.
- 다음에 할 일: 남은 blocker는 runtime/environment 쪽이다. live Supabase의 `provider_tool_dashboard` schema cache 문제, Playwright MachPort 권한 문제, Qdrant 부재, Codex/Claude MCP client 불안정성을 풀어야 dashboard visibility/browser proof/semantic retrieval을 닫을 수 있다.
- 검증 결과: broader pytest PASS (`174 passed`), focused fallback regressions PASS, ruff PASS, py_compile PASS, `git diff --check` PASS, compose MCP service startup PASS.
- 상세 기록: `mlp/docs/history/2026-04-15_2214_slave_option2_runtime_compatibility_followup.md`
