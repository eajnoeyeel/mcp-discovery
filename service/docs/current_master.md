# Master 작업 현황

> MLP 작업 누적 요약 로그
> 상세 내용은 `mlp/docs/history/` 문서에 기록한다.

## 기록 형식

```md
### YYYY-MM-DD HH:MM — 작업 제목
- 이번에 한 일:
- 다음에 할 일:
- 검증 결과:
- 상세 기록: `mlp/docs/history/YYYY-MM-DD_HHMM_master_<task_slug>.md`
```

### 2026-04-20 15:30 — Claude auth probe + delegated OAuth resume 기반
- 이번에 한 일: Claude/Codex MCP 인증 확인용 `auth_probe`와 bearer-backed user resolution을 추가했고, delegated provider OAuth가 `auth_required -> pending_execution -> ready_to_resume -> resume_pending_execution`으로 이어지도록 backend/bridge/local API 경로를 구현했다.
- 다음에 할 일: 실제 Claude/Codex 클라이언트에서 clear-auth/re-auth와 Apify 등 real OAuth provider resume proof를 캡처한다.
- 검증 결과: targeted ruff PASS, auth/execute/resume 관련 unit suite PASS, resume harness summary 추가
- 상세 기록: `service/docs/history/2026-04-20_1530_master_claude_auth_and_resume_evidence.md`

### 2026-04-05 20:30 — Supabase 시딩 + Migration 002 + 브랜치 merge
- 이번에 한 일: feat/mlp-shared-core-runtime-foundation merge (충돌 없음), Migration 001 적용, MCP-Zero 292서버/2763도구 시딩 (GEO score 포함), Migration 002 (dashboard views, FTS fix, platform stats RPC), seed 스크립트 dedup 버그 수정, .gitignore supabase 패턴 수정
- 다음에 할 일: MCP Discovery 프론트엔드 Supabase 연결 확인, Plan 02 (search path + RAG 연결) 진행
- 검증 결과: ruff PASS, 394 tests PASS, Supabase row count 292/2763 확인, get_platform_stats() + search_tools_fts() 동작 확인
- 상세 기록: `mlp/docs/history/2026-04-05_2030_master_supabase_seeding.md`

### 2026-04-05 20:50 — Plan 02 완료: Search Path → RAGService 연결
- 이번에 한 일: SupabaseFallback 역할 분리 (freshness/degraded), SearchService → RAGService 위임 구조 완성, Bridge handler 동기화, search loop harness 추가
- 다음에 할 일: Plan 03 (registry + async indexing) 또는 Plan 04 (execute proxy + bridge)
- 검증 결과: ruff PASS, 395 tests PASS (unit 395 + RAG 42), lint clean
- 상세 기록: `mlp/docs/history/2026-04-05_2050_master_plan02_search_rag.md`

### 2026-04-05 21:17 — Embedding dimension fix + E2E smoke test 통과
- 이번에 한 일: config/env의 embedding 모델을 text-embedding-3-large(3072D)로 수정하여 Qdrant 인덱스와 일치시킴. FTS fallback E2E (5쿼리, 40% — FTS 한계로 정상) + full pipeline smoke test 1쿼리 통과 (github::search_repositories, score=0.807, 863ms)
- 다음에 할 일: Plan 03 (registry + async indexing) 또는 MCP Discovery 프론트엔드 연결
- 검증 결과: 395 tests PASS, smoke test PASS (semantic path, non-degraded)
- 상세 기록: `mlp/docs/history/2026-04-05_2117_master_embedding_fix_e2e.md`

### 2026-04-05 21:45 — Plan 03/04/05 병렬 구현 완료
- 이번에 한 일: 3개 agent를 worktree로 병렬 실행하여 Plan 03 (Registry+Index), Plan 04 (Execute+Bridge), Plan 05 (Analytics+Dashboard) 동시 구현. 27 files changed, +2454 lines, 467 tests PASS
- 다음에 할 일: Plan 06 (Operations Verification), MCP Discovery 프론트엔드 Supabase 연결, SAM deploy
- 검증 결과: ruff PASS, 467 tests PASS, 충돌 없음
- 상세 기록: `mlp/docs/history/2026-04-05_2145_master_plan03_04_05_parallel.md`

### 2026-04-06 19:43 — GEO 논문 서베이 + E4 초기 구현 (32 tools)
- 이번에 한 일: GEO description optimization 논문 7편 서베이, arXiv 원문 35개 오류 검증/수정. Wilcoxon signed-rank + cluster bootstrap 통계 모듈 추가. Tool-DE enrichment 32 GT-covered tools 생성 + Qdrant 인덱싱 (copy+patch)
- 다음에 할 일: pool 302→320 확장, Atlas GT 500 tasks 확장, enrichment 94개로 확대
- 검증 결과: Qdrant enriched collection 인덱싱 PASS (32 tools), ruff PASS
- 상세 기록: `mlp/docs/history/2026-04-06_1943_master_geo_survey_e4_init.md`

### 2026-04-06 22:06 — pool/GT 확장 (302→320 servers, 394→2,301 GT entries)
- 이번에 한 일: MCP-Atlas GT 80→500 tasks 확장 (394→2,301 per-step entries), 18 Atlas GT servers 추가. Pool 302→320 servers (95% GT coverage). convert_mcp_atlas.py에 --task-offset/--task-start-index/--append 옵션 추가
- 다음에 할 일: seed_set.jsonl 정리, enrichment 84→94 tools 확장, E4 enrichment 재생성
- 검증 결과: GT 2,301 entries, pool 95% GT coverage 확인
- 상세 기록: `mlp/docs/history/2026-04-06_2206_master_pool_gt_expansion.md`

### 2026-04-07 01:51 — E4 enrichment 확정 (94 GT-covered tools)
- 이번에 한 일: seed_set.jsonl 제거 (tool name 불일치 다수). Atlas tool_id 19개 처리 (15개 remap, 4개 drop → GT 2,301→2,273). 84→94 GT-covered tools Tool-DE enrichment 전체 재생성. 320-server pool Qdrant 증분 인덱싱 (2 collections)
- 다음에 할 일: E4 A/B experiment 실행
- 검증 결과: GT 94 unique tools / 100% pool 매칭, Qdrant 인덱싱 PASS
- 상세 기록: `mlp/docs/history/2026-04-07_0151_master_e4_enrichment_final.md`

### 2026-04-07 15:20 — E4/E4v2/E4v2b 실험 완료
- 이번에 한 일: E4 A/B 실행 — P@1 +0.97pp (p=0.833, not significant), Stage 1 vs 2 conflict 확인 (Confusion -5pp vs Recall -2.9pp). E4v2 offline 검증 — selection controllability 증명 (p=0.008), baseline-dependent 효과 (mid-BL +5pp, high-BL -33pp), SP +7.39pp. E4v2b 7 patterns 비교 — Cochran's Q p<0.001, best: I/O explicit (mid-BL +9.28pp) / Control (high-BL)
- 다음에 할 일: E5 (pool scaling) / E6 실험, fix/retrieval-audit-followups → main merge
- 검증 결과: 3 clusters × 611 queries (E4v2), 7 patterns × 3 clusters (E4v2b), 통계 유의성 확인
- 상세 기록: `mlp/docs/history/2026-04-07_1520_master_e4_experiments.md`

### 2026-04-07 15:27 — fix branch 정리 (브랜치명/커밋 메시지)
- 이번에 한 일: fix-retrieval-audit-followups → fix/retrieval-audit-followups 브랜치명 수정. codex 작성 커밋 2개(710e7d1, 9f11743)의 메시지를 프로젝트 스타일로 재작성 (Why:/Constraint:/Tested: 메타데이터 제거, 한국어 본문 + bullet 형식으로)
- 다음에 할 일: fix/retrieval-audit-followups → main PR 생성
- 검증 결과: git log 확인 (filter-branch 성공)
- 상세 기록: git log 기준 (별도 history 파일 불필요)

### 2026-04-07 19:50 — 누적 브랜치 전수 정리 및 main 병합 완료
- 이번에 한 일: 로컬 브랜치 6개 분석 (parallel agents 3개 병렬 실행). research/geo-description-optimization 폐기 (pool-gt-expansion에 완전 포함). 나머지 5개 브랜치 PR 생성 (#12~#16) 후 순서대로 병합. feat/mlp/docs rebase(cherry-pick) 처리. feat/e4-selection-controllability에 MCPTool.selection_description 아키텍처 변경사항 커밋 후 rebase 충돌 해결하여 병합. TestSupabaseClient 4개 테스트 수정 (httpx.AsyncClient → httpx.Client mock). main 522 tests PASS.
- 다음에 할 일: E5 (pool scaling) / E6 실험 진행
- 검증 결과: 522 unit tests PASS (0 failures), PR #12–#16 모두 Merged
- 상세 기록: `mlp/docs/history/2026-04-07_1950_master_branch_cleanup_merge.md`

### 2026-04-13 12:24 — description-control row-native 로드맵 설계
- 이번에 한 일: retrieval-facing / client-delivery description control을 row-native canonical roadmap으로 승격하기 위한 설계 문서를 작성했다. 기존 evidence 문서와 row-native authority를 분리하고, 두 lane을 P0로 유지하되 실행은 release-prep 및 현재 품질 상승 작업 뒤로 미루는 two-clock 우선순위 모델을 확정했다.
- 다음에 할 일: 사용자가 설계 문서를 리뷰/승인하면 writing-plans로 row-native PRD/test-spec 및 master index 반영 계획을 작성한다.
- 검증 결과: spec 작성 PASS, placeholder/TODO grep PASS, 수동 self-review PASS
- 상세 기록: `mlp/docs/history/2026-04-13_1224_master_description_control_roadmap_design.md`

### 2026-04-13 12:30 — description-control row-native implementation plan 작성
- 이번에 한 일: retrieval-facing / client-delivery description control을 row-native master index와 PRD/test-spec pair로 반영하기 위한 implementation plan을 작성했다. 두 row는 P0로 유지하되 실행은 release-prep 및 현재 품질 상승 작업 뒤로 미루는 two-clock sequencing을 plan 차원에서 구체화했다.
- 다음에 할 일: 승인된 plan에 따라 master index와 row-native planning artifacts를 작성한다.
- 검증 결과: plan 문서 작성 PASS, placeholder scan review PASS, 수동 self-review PASS
- 상세 기록: `mlp/docs/history/2026-04-13_1230_master_description_control_row_native_plan.md`

### 2026-04-13 13:30 — description-control row-native planning artifacts 작성
- 이번에 한 일: row-native master index에 retrieval-facing / client-delivery description P0 rows와 execution queue note를 추가하고, 각 lane의 PRD/test-spec pair를 작성했다. master index header에 2026-04-13 description-control roadmap 포인터도 반영했다.
- 다음에 할 일: release-prep 및 현재 품질 상승 tranche를 우선 진행하고, 이후 retrieval → client-delivery 순으로 execution gate를 연다.
- 검증 결과: placeholder scan PASS, two-clock sequencing consistency PASS, retrieval-vs-delivery separation PASS, subagent spec/code reviews PASS
- 상세 기록: `mlp/docs/history/2026-04-13_1330_master_description_control_row_native_artifacts.md`

### 2026-04-13 16:59 — MLP upstream auth layer
- 이번에 한 일: MetaMCP를 참고해 MLP execute proxy의 provider MCP upstream 인증 레이어를 추가했다. public `mcp_servers` row와 분리된 service-role-only `mcp_server_auth` migration을 만들고, registration에서 optional `execution_auth`를 검증/저장하며, execute 시 `ToolContract.upstream_auth`를 HTTP header로 주입하고, auth metadata 조회 실패는 missing-table 호환 케이스만 제외하고 fail-closed로 처리하도록 했다. 구현 계획은 `docs/superpowers/plans/2026-04-13-mlp-upstream-auth-layer.md`에 저장했다.
- 다음에 할 일: hosted/staging Supabase에 migration 008을 적용하고 실제 bearer/API-key 보호 provider MCP로 live execute proof를 확보한다. OAuth delegation, AWS Secrets Manager/KMS-backed secret storage, SSE/STDIO session pooling은 MLP 이후 hardening으로 남긴다.
- 검증 결과: TDD RED/GREEN focused tests PASS, `uv run pytest tests/unit/test_mlp_services.py tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_execute_loop.py -q` PASS (`135 passed`), `uv run python -m mlp.harness.execute_auth_loop --iterations 12` PASS (`runs=12`, `success_rate=1.0`), `uv run ruff check mlp/ tests/unit/test_mlp_services.py tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_execute_loop.py` PASS.
- 상세 기록: `mlp/docs/history/2026-04-13_1659_master_mlp_upstream_auth_layer.md`

### 2026-04-13 17:23 — MLP MetaMCP runtime parity execution
- 이번에 한 일: MetaMCP 수준의 OAuth token refresh, transport metadata, and long-running gateway execution 기반을 구현했다. Lambda는 stateless control/execute path를 유지하고, `requires_gateway=true`인 STDIO/SSE/Streamable HTTP provider MCP는 internal FastAPI gateway로 위임하도록 분리했다. gateway에는 bounded session pool, MCP SDK transport config/session factory, `/gateway/health`, `/gateway/execute` API를 추가했다.
- 다음에 할 일: hosted runtime에 migration 009와 gateway 배포를 적용하고, 실제 OAuth-protected Streamable HTTP MCP 및 local STDIO fixture로 live pooled-session proof를 확보한다. production hardening에서는 OAuth client secrets/refresh tokens를 Secrets Manager/KMS-backed secret refs로 이전해야 한다.
- 검증 결과: subagent TDD RED/GREEN slices PASS, `uv run pytest tests/unit/test_mlp_oauth_tokens.py tests/unit/test_mlp_gateway_session_pool.py tests/unit/test_mlp_gateway_app.py tests/unit/test_mlp_services.py tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_execute_loop.py -q` PASS (`173 passed`), `UV_CACHE_DIR=/tmp/uv-cache uv run python -m mlp.harness.metamcp_runtime_loop --iterations 12` PASS (`success_rate=1.0`, `session_reuse_rate=0.9167`), targeted ruff PASS. Full `tests/` run was attempted but blocked by sandbox/external network dependencies (OpenAI/Qdrant/Smithery/HuggingFace DNS plus local socket bind permission), not by the runtime parity changes.
- 상세 기록: `mlp/docs/history/2026-04-13_1723_master_metamcp_runtime_parity_execution.md`

### 2026-04-13 18:44 — runtime risk burndown tranche (Tasks 1–5)
- 이번에 한 일: runtime risk burndown plan 기준으로 남은 5개 리스크를 순서대로 닫았다. hosted migration 009/010 rollout visibility verifier, App Runner gateway deployment contract, Secrets Manager-backed OAuth secret refs, live transport proof harness, Lambda→gateway internal auth hardening을 각각 TDD로 구현하고 tranche 단위 커밋으로 정리했다.
- 다음에 할 일: hosted/staging에 migration 009/010을 실제 적용하고 `verify_runtime_schema.py`로 readiness를 확인한 뒤, App Runner gateway를 배포하고 실제 streamable HTTP/SSE/STDIO proof를 수집한다. 이후 gateway secret rotation 및 replay nonce 저장 전략을 추가 hardening으로 연다.
- 검증 결과: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/test_mlp_verify_runtime_schema.py tests/unit/test_mlp_gateway_settings.py tests/unit/test_mlp_gateway_deploy_manifest.py tests/unit/test_mlp_secret_refs.py tests/unit/test_mlp_live_gateway_transport_proof.py tests/unit/test_mlp_gateway_internal_auth.py tests/unit/test_mlp_oauth_tokens.py tests/unit/test_mlp_gateway_session_pool.py tests/unit/test_mlp_gateway_app.py tests/unit/test_mlp_services.py tests/unit/test_mlp_handlers.py tests/unit/test_mlp_catalog_dashboard.py tests/unit/test_mlp_execute_loop.py -q` PASS (`192 passed`), `UV_CACHE_DIR=/tmp/uv-cache uv run python -m mlp.harness.metamcp_runtime_loop --iterations 12` PASS, `UV_CACHE_DIR=/tmp/uv-cache uv run python -m mlp.harness.live_gateway_transport_proof` PASS, targeted `ruff check` PASS. 전체 `tests/` 실행은 sandbox/external dependency 제약(OpenAI/Qdrant/Smithery/HuggingFace/network bind)으로 여전히 block 상태다.
- 상세 기록: `mlp/docs/history/2026-04-13_1844_master_runtime-risk-burndown-closure.md`

### 2026-04-15 14:34 — Pre-Hosting Baseline Verification (Go/No-Go)
- 이번에 한 일: 호스팅 기능 추가 전 전체 서비스 baseline 검증 수행. 환경 구축, 아키텍처 경계, E2E 플로우, API/UI 계약, 관측성, Playwright 브라우저 검증 (14개 스크린샷) 전 영역 검사
- 다음에 할 일: **3개 BLOCKER 해결 필수** — (1) Qdrant 검색 0건 (벡터 컬렉션 비어있거나 연결 문제), (2) SAM build 3함수 실패 (dependency group 누락), (3) 3개 API 라우트 미배포/미정의 (stats, insights, profile)
- 검증 결과: **NOT READY** — 카탈로그 plane PASS (327서버, 2804도구), Query plane FAIL (검색 0건), Dashboard PASS (메인), Dashboard sub-pages PARTIAL (tool detail/settings 실패), Python 1572 tests PASS, Frontend 52 tests PASS
- 상세 기록: `mlp/docs/history/2026-04-15_1434_master_pre_hosting_baseline_verification.md`

### 2026-04-20 00:29 — Delegated provider OAuth broker implementation
- 이번에 한 일: client-facing MCP execute path에 delegated provider OAuth broker 기반을 추가했다. 사용자 소유 provider connection 스키마, scope coverage helper, auth-aware execute/bridge 응답, OAuth start/callback endpoint, local delegated OAuth loop harness를 구현했다.
- 다음에 할 일: controlled local provider stub 또는 실제 GitHub OAuth app 설정으로 live local proof를 확장하고, dashboard에서 provider auth requirement 편집/검토 UI를 후속으로 연다.
- 검증 결과: `uv run pytest tests/unit/mlp/test_mlp_services.py tests/unit/mlp/test_mlp_handlers.py tests/unit/mlp/test_mlp_api_local_app.py -q` PASS, `uv run python -m service.harness.delegated_oauth_execute_loop` PASS(sample), `uv run python -m service.harness.execute_loop` PASS(sample), `uv run python -m service.harness.smoke_api --sample` PASS.
- 상세 기록: `service/docs/history/2026-04-20_0029_master_provider_oauth_broker.md`

## 2026-04-24 16:20 KST — OAuth provider bootstrap automation hardening

- Implemented provider-agnostic OAuth provider bootstrap path: discovery + DCR + guided manual draft/promotion, with registry metadata, secret refs, admin-only enable, and frontend register wizard support.
- Hardened delegated OAuth runtime: opaque server-side state nonce, PKCE verifier stored server-side, nonce replay consumption, issuer/redirect binding, fail-closed delegated header execution, and Supabase pending execution `resume_token`/`retry_token` contract compatibility.
- Added runtime schema/migration checks for bootstrap drafts and state nonces; repaired predeploy rehearsal path drift, requirements lock output, OAuth start/callback SAM deployment, public OAuth callback base URL configuration, Secrets Manager IAM/dependency coverage, live-schema opt-in/required gate, and disabled-provider runtime kill-switch enforcement.
- Verification: backend ruff passed; focused OAuth/backend suite passed; full relevant backend suite passed `491 passed`; frontend `npm audit --omit=dev` found 0 vulnerabilities; frontend targeted Vitest `22 passed`; `tsc`, production build, and lint passed with existing warnings only; `sam validate --lint` passed for prod/local templates; final `scripts/ci/run_mlp_predeploy_checks.sh` passed with 13 functions built/smoked, predeploy `9/9`, and migration prefix gate PASS. `MLP_REQUIRE_LIVE_SCHEMA_VERIFY=1` fails closed when Supabase credentials are absent.
- Next: before staging/prod deploy, provide `MlpPublicApiBaseUrl`, apply migrations 034-036, run the predeploy wrapper with real `SUPABASE_URL`/`SUPABASE_SERVICE_KEY`, and publish/pin the dirty frontend submodule commit if the UI changes are part of the release.

### 2026-04-24 17:20 KST — Local migration applied for Claude E2E
- Applied Supabase migrations `oauth_provider_bootstrap_automation` and `oauth_state_nonces_provider_fk_index` to project `ojuclgsxseygcnjgdpau`.
- Added migration 037 to keep `oauth_state_nonces.provider_key` FK covered after advisor review.
- Verification: runtime schema ready, uniqueness probes ready, compose config/build OK, predeploy with live schema verification passed 10/10.
- Next: run Claude Desktop E2E against `http://127.0.0.1:8080/mcp` after recreating compose containers with `docker compose -f compose.mcp.yaml up --build -d`.

### 2026-04-24 17:48 KST — Context7 real-world MCP registration E2E
- 이번에 한 일: Playwright로 dashboard register flow를 사용해 Apify가 아닌 real-world remote MCP(Context7)를 `context7-realworld-pw-hybrid`로 등록하고, discovery/registration/index/search/execute path를 검증했다. 이 과정에서 local compose Qdrant collection drift, `indexed_at` column mismatch, server-level index status reconciliation gap, stateless HTTP MCP Accept header 문제를 수정했다.
- 검증 결과: discovery 200, registration 201, Supabase `mcp_servers.index_status=indexed` + 2 tools indexed, `/api/search`에서 Context7 tool rank 1/4 노출(`degraded=false`), Playwright browser session auth로 `/mcp` `execute_tool` 호출 성공 및 Context7 React docs 반환. Focused unit tests `16 passed`, targeted ruff PASS, compose config PASS, `git diff --check` PASS, backend `/health` 200, live-schema predeploy wrapper `10/10 passed`.
- 다음에 할 일: 사용자가 Claude Desktop에서 같은 local MCP endpoint(`http://127.0.0.1:8080/mcp`)로 find_best_tool/execute_tool E2E를 수행한다. 관측된 query log 409는 hot path non-blocking이지만 analytics 완전성이 필요하면 별도 follow-up으로 정리한다.
- 상세 기록: `service/docs/history/2026-04-24_1748_master_context7_realworld_registration_e2e.md`

### 2026-04-24 18:45 KST — MCP registration/auth documentation package
- 이번에 한 일: real-world MCP 등록/검증 작업 과정을 `service/docs/history/2026-04-24_1845_master_mcp_oauth_realworld_worklog.md`에 정리하고, 운영자가 그대로 따라할 수 있는 MCP 등록 가이드(`service/docs/guides/mcp_registration_guide.md`)와 플랫폼 인증 로직 상세 문서(`service/docs/architecture/platform_auth_logic.md`)를 새로 작성했다.
- 검증 결과: 문서는 Context7 성공 E2E와 GitHub Remote MCP provider-bootstrap blocker를 분리해 기록했고, `execution_auth`/`client_auth`/`oauth_provider_registry`/pending execution/resume token/nonce/PKCE/token refresh/fail-closed 규칙을 코드 경로 기준으로 설명했다.
- 다음에 할 일: 문서와 기존 구현 변경을 함께 최종 검증한 뒤 commit/push/PR/merge를 진행한다.
- 상세 기록: `service/docs/history/2026-04-24_1845_master_mcp_oauth_realworld_worklog.md`
