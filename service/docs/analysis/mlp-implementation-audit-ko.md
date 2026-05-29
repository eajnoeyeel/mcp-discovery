# MLP 구현 감사

- 날짜: 2026-04-11
- 브랜치: `feat/service/audit-done-vs-missing`
- 스펙: `docs/superpowers/specs/2026-04-11-mlp-audit-done-vs-missing-design.md`

## 핵심 요약
- 전체 기능 행 수: 20
- 구현됨 + 검증됨: 16
- 구현되었지만 검증 불충분: 0
- 계획만 있음: 3
- 미구현: 1
- 주요 품질 리스크:
  1. 배포는 operator가 보유한 입력과 실행 권한이 아직 없어서 의도적으로 구현하지 않았다.
  2. provider detail 계약이나 auth/runtime 입력이 다시 바뀌면 provider-owned dashboard proof를 재실행해야 한다.
  3. async indexing은 저장소 로컬 근거로 닫혔으며 register payload 또는 Qdrant payload shape가 바뀔 때만 다시 열어야 한다.

## 범위와 방법

### 범위
이번 감사는 `service/` 전체 트리를 다룬다.
- backend/service/runtime 경로
- frontend 경로
- harness/test 근거
- planning/release/history 산출물

### 분류 규칙
- **구현됨 + 검증됨**: 코드 경로가 존재하고, 저장소 근거에 테스트, 하네스, acceptance proof, 또는 history/current 검증 기록이 있다.
- **구현되었지만 검증 불충분**: 코드 경로는 존재하지만, 최신 또는 연결된 근거가 없거나, 부분적이거나, 오래되었거나, 상충된다.
- **계획만 있음**: 계획 문서는 존재하지만 의미 있는 구현 경로는 없다.
- **미구현**: 저장소 상 필요성은 암시되지만 구현도 없고 의미 있게 닫힌 계획도 없다.

### 근거 출처
- `service/docs/acceptance.md`
- `service/docs/current_slave.md`
- `service/docs/current_master.md`
- `service/docs/history/*.md`
- `service/docs/plan/row-native/*.md`
- `service/` 소스 디렉터리
- `tests/unit/test_mlp_*.py`
- `service/frontend/src/*.test.tsx`
- `service/harness/*.py`

## 기능 인벤토리
| 기능 | 구현 상태 | 검증 상태 | 최종 라벨 | 코드 근거 | 테스트 / 하네스 근거 | 문서 근거 | 남은 격차 | 다음 조치 |
|---|---|---|---|---|---|---|---|---|
| Search path + RAG service | `service/lambdas/search`, `service/services/search_service.py`, `service/rag/`에 존재 | 연결된 unit/rag/harness 근거 존재 | 구현됨 + 검증됨 | `service/lambdas/search/handler.py`, `service/services/search_service.py`, `service/rag/service.py` | `tests/unit/test_mlp_handlers.py`, `service/rag/tests/test_service.py`, `tests/unit/test_mlp_search_loop.py`, `service/harness/search_loop.py` | `service/docs/current_master.md`, `service/docs/history/2026-04-05_2050_master_plan02_search_rag.md` | provenance/freshness 작업이 응답 계약을 바꾸는지 재확인 필요 | 현재 기준선으로 유지 |
| API key authorizer / auth guard | `service/lambdas/authorizer/handler.py`에 존재하며 보호된 API/browser 흐름에서 강제됨 | handler와 provider proof가 401 동작을 보여줌 | 구현됨 + 검증됨 | `service/lambdas/authorizer/handler.py`, `service/frontend/src/components/ProtectedRoute.tsx` | `tests/unit/test_mlp_handlers.py` | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md` | auth 계약이 static API key에서 바뀌는지 검토 필요 | auth 경계를 현재 gate에 묶어 유지 |
| Register path | `service/lambdas/register`와 `service/services/register_service.py`에 존재 | 로컬/provider 검증 근거 존재 | 구현됨 + 검증됨 | `service/lambdas/register/handler.py`, `service/services/register_service.py`, `service/adapters/supabase_client.py` | `tests/unit/test_mlp_handlers.py`, `tests/unit/test_mlp_provider_ownership.py` | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md` | register payload 또는 content-hash 계약이 바뀔 때만 다시 연다 | register와 async-index payload 계약을 맞춰 유지 |
| Async indexing path | `service/lambdas/index`, `service/services/index_service.py`, content-hash skip partitioning, index-loop evidence에 존재 | 대상 handler/service/harness 근거 존재 | 구현됨 + 검증됨 | `service/lambdas/index/handler.py`, `service/services/index_service.py`, `service/shared/content_hash.py`, `service/supabase/migrations/007_entity_lifecycle_and_freshness.sql` | `tests/unit/test_mlp_handlers.py`, `tests/unit/test_index_handler_failed_status.py`, `tests/unit/test_mlp_services.py`, `tests/unit/test_mlp_index_loop.py`, `service/harness/index_loop.py` | `service/docs/current_slave.md`, `service/docs/history/2026-04-12_1239_slave_async_indexing_path_closure.md` | register payload 또는 Qdrant payload shape가 바뀔 때만 재확인 | 현재 기준선으로 유지 |
| Execute path | `service/lambdas/execute`와 `service/services/execute_service.py`에 존재 | loop/unit 근거 존재 | 구현됨 + 검증됨 | `service/lambdas/execute/handler.py`, `service/services/execute_service.py`, `service/adapters/mcp_http_client.py` | `tests/unit/test_mlp_handlers.py`, `tests/unit/test_mlp_execute_loop.py`, `service/harness/execute_loop.py` | `service/docs/current_slave.md`의 Plan 06 항목 | hosted MCP 계약이 바뀌면 재검증 필요 | 현재 기준선으로 유지 |
| Bridge path | `service/lambdas/bridge`, `service/services/bridge_service.py`, bridge harness에 존재 | 전용 bridge-loop 및 recorded-run 근거 존재 | 구현됨 + 검증됨 | `service/lambdas/bridge/handler.py`, `service/services/bridge_service.py`, `service/harness/bridge_loop.py`, `service/harness/record_bridge_runs.py` | `tests/unit/test_mlp_bridge_loop.py`, `tests/unit/test_mlp_record_bridge_runs.py`, `service/harness/fixtures/bridge_runs_recorded_local_sam_pending_20260408T133734Z.json` | `service/docs/current_slave.md`, `service/docs/history/2026-04-08_2233_slave_root_vision_recorded_bridge_runs_evidence.md` | hosted-origin fidelity는 의도적으로 defer 상태 | deferred 경계를 명시적으로 유지 |
| Catalog + dashboard read APIs | `service/lambdas/catalog`, `service/lambdas/dashboard`, `service/services/catalog_service.py`, `service/services/dashboard_service.py`에 존재 | backend 검증 근거 존재 | 구현됨 + 검증됨 | `service/lambdas/catalog/handler.py`, `service/lambdas/dashboard/handler.py`, `service/services/dashboard_service.py` | `tests/unit/test_mlp_catalog_dashboard.py`, `tests/unit/test_mlp_dashboard_snapshot.py` | `service/docs/current_slave.md`, `service/docs/current_master.md` | provider-first frontend polish는 별도 작업으로 남아 있음 | backend/frontend 경계를 명시적으로 유지 |
| Shared runtime / adapters / validation | `service/shared`, `service/adapters`, `service/validation`에 존재 | unit 근거 존재 | 구현됨 + 검증됨 | `service/shared/runtime.py`, `service/shared/http.py`, `service/adapters/supabase_client.py`, `service/validation/description_rules.py` | `tests/unit/test_mlp_runtime.py`, `tests/unit/test_mlp_shared_http.py`, `tests/unit/test_mlp_services.py`, `tests/unit/test_mlp_handlers.py` | `service/docs/current_slave.md`, `service/docs/history/2026-04-05_1358_slave_shared_core_runtime_foundation_impl.md` | 향후 계약 추가는 확장일 뿐 현재 효력을 깨지는 않음 | 핵심 기반으로 유지 |
| Supabase runtime contracts / migrations | migration 파일이 `007`까지 존재 | migration/test 근거 존재하지만 production deploy는 여전히 defer 상태 | 구현됨 + 검증됨 | `service/supabase/migrations/001_initial.sql`, `002_runtime_contracts.sql`, `004_provider_search_simulations.sql`, `005_provider_ownership_and_read_api.sql`, `006_fts_nullable_status.sql`, `007_entity_lifecycle_and_freshness.sql` | `tests/unit/test_mlp_schema_contracts.py`, `tests/unit/test_mlp_template_contract.py` | `service/docs/current_master.md`, `service/docs/current_slave.md` | 배포된 환경에 실제 migration을 적용하는 일은 환경 의존적 | deploy 의존성은 별도로 기록 |
| Operational harnesses / smoke utilities | search/index/execute/bridge/smoke용 harness 모듈 존재 | 반복된 로컬 근거 존재 | 구현됨 + 검증됨 | `service/harness/search_loop.py`, `service/harness/index_loop.py`, `service/harness/execute_loop.py`, `service/harness/bridge_loop.py`, `service/harness/smoke_api.py` | `tests/unit/test_mlp_search_loop.py`, `tests/unit/test_mlp_index_loop.py`, `tests/unit/test_mlp_execute_loop.py`, `tests/unit/test_mlp_bridge_loop.py`, `tests/unit/test_mlp_smoke_api.py` | `service/docs/acceptance.md`, `service/docs/current_slave.md`, `service/docs/history/2026-04-08_1929_slave_root_vision_bridge_loop_sentinel.md` | live-stage/prod harness 입력은 여전히 defer 상태 | local-first와 deployed 경계를 명시적으로 유지 |
| Login / auth flow | frontend auth context와 login page에 존재 | 로컬 test/build 근거와 browser proof 존재 | 구현됨 + 검증됨 | `service/frontend/src/contexts/AuthContext.tsx`, `service/frontend/src/pages/Login.tsx`, `service/frontend/src/components/ProtectedRoute.tsx` | `service/frontend/src/contexts/AuthContext.test.tsx`, `service/frontend/src/pages/Login.test.tsx` | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_0027_slave_plan05_api_first_google_oauth.md` | hosted-origin auth 설정은 배포 이슈로 남아 있음 | local-first gate와 deploy를 분리 유지 |
| Self-serve registration flow | `RegisterServer` 페이지와 API client mutation에 존재 | tests/build 및 로컬 browser proof 존재 | 구현됨 + 검증됨 | `service/frontend/src/pages/RegisterServer.tsx`, `service/frontend/src/lib/api.ts`, `service/frontend/src/pages/Dashboard.tsx` | `service/frontend/src/pages/RegisterServer.test.tsx`, `service/frontend/src/lib/api.test.ts` | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_2025_slave_frontend_self_serve_registration.md`, `service/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md` | local-first 경로에서는 즉시 남은 격차 없음 | 승인된 기준선으로 유지 |
| Dashboard reflection / provider-owned feedback states | dashboard, tool-detail, competitor, feedback UI에 존재 | provider-first actionability pass 이후 fresh targeted/frontend regression evidence, rerun provider-owned API proof, fresh browser proof가 모두 일치함 | 구현됨 + 검증됨 | `service/frontend/src/pages/Dashboard.tsx`, `service/frontend/src/pages/DashboardToolDetail.tsx`, `service/frontend/src/components/CompetitorTable.tsx`, `service/frontend/src/components/ProviderSimulationEvidence.tsx` | `service/frontend/src/pages/Dashboard.test.tsx`, `service/frontend/src/pages/DashboardToolDetail.test.tsx`, `npm test`, `npm exec -- tsc --noEmit`, `npm run build`, `service/docs/history/2026-04-12_2005_slave_provider_dashboard_verifier_rerun.md`의 `verify_provider_dashboard.py` local proof, fresh browser proof (`provider-dashboard-tool-detail-proof.png`) | `service/docs/current_slave.md`, `service/docs/history/2026-04-12_1215_slave_dashboard_provider_facing_ux_confidence_refresh_closure.md`, `service/docs/history/2026-04-12_2005_slave_provider_dashboard_verifier_rerun.md`, `service/docs/plan/row-native/00_master_index.md` | provider detail 계약이나 auth/runtime 입력이 다시 바뀔 때만 재검증 필요 | 이번 actionability pass를 현재 provider UX 기준선으로 유지 |
| Frontend build/test evidence | frontend test/build 스크립트가 존재하고 history에서 반복 실행됨 | 저장소 로그에 많은 성공 실행 기록 존재 | 구현됨 + 검증됨 | `service/frontend/package.json`, `service/frontend/src/test/setup.ts` | `npm test`, `npm run build` 근거가 `service/docs/current_slave.md` 및 연결된 history 항목들에 기록됨 | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md` | bundle-size warning은 있지만 현재 근거에서는 release blocker가 아님 | warning은 메모로만 남기고 blocker로 보지 않음 |
| Local-first acceptance gate | acceptance 계약이 존재하며 구현된 provider journey와 일치 | 저장소 로컬 tests/harness/browser proof가 문서에 연결되어 있음 | 구현됨 + 검증됨 | `service/docs/acceptance.md`, `service/docs/runbook.md` | acceptance와 current/history 항목에서 참조한 harness/test 명령 | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md` | deployed acceptance만 여전히 defer 상태 | local-first 경계를 유지 |
| Production deployment planning | row-native 계획 문서가 Lambda/API + App Runner gateway 배포 경로를 패키징하지만 실행은 의도적으로 없음 | planning readback와 deploy-contract 검증 근거가 존재 | 계획만 있음 | `service/docs/plan/row-native/prd-mlp-production-deployment-planning.md`, `service/docs/plan/row-native/test-spec-mlp-production-deployment-planning.md`, `service/docs/runbook.md`, `service/docs/acceptance.md` | `tests/unit/test_mlp_gateway_deploy_manifest.py`, `tests/unit/test_mlp_gateway_settings.py`, `tests/unit/test_mlp_verify_runtime_schema.py`, `tests/unit/test_mlp_template_contract.py` | `service/docs/current_slave.md`, `service/docs/history/2026-04-13_2030_slave_production_deployment_planning_container_first_closeout.md`, `service/docs/plan/row-native/00_master_index.md` | operator 입력과 deploy 권한이 아직 없음 | AWS execution row가 열릴 때까지 blocked 유지 |
| Frontend UI planning lane | row-native 계획 문서는 존재하지만 구현은 포함하지 않음 | planning closeout에 대한 readback 근거만 존재 | 계획만 있음 | `service/docs/plan/row-native/prd-mlp-frontend-ui-planning.md`, `service/docs/plan/row-native/test-spec-mlp-frontend-ui-planning.md` | planning 검증만 존재 | `service/docs/current_slave.md`, `service/docs/history/2026-04-09_1338_slave_frontend_ui_planning_closeout.md` | downstream 구현은 별도 작업 | defer된 계획으로 유지 |
| Final handoff / query-gate preparation lane | row-native 계획 문서가 존재하며 이전 planning lane을 패키징함 | planning closeout 근거만 존재 | 계획만 있음 | `service/docs/plan/row-native/prd-mlp-final-handoff-query-gate-preparation.md`, `service/docs/plan/row-native/test-spec-mlp-final-handoff-query-gate-preparation.md` | planning 검증만 존재 | `service/docs/current_slave.md`, `service/docs/history/2026-04-09_2333_slave_final_handoff_query_gate_preparation.md` | deployment execution과 query approval은 여전히 gated 상태 | 이후 gate가 열릴 때까지 닫힌 상태 유지 |
| Root-vision recorded-bridge evidence lane | recorded bridge evidence artifact가 history에 존재 | bridge 근거는 검증되었고 이 lane은 명시적으로 닫혀 있음 | 구현됨 + 검증됨 | `service/harness/bridge_loop.py`, `service/harness/record_bridge_runs.py` | recorded bridge run + bridge loop 근거가 bridge harness 문서에 이미 기록됨 | `service/docs/current_slave.md`, `service/docs/history/2026-04-08_2306_slave_root_vision_recorded_bridge_lane_handoff.md` | 반대 근거가 나오지 않는 한 다시 열지 않음 | 닫힌 근거 lane으로 유지 |
| AWS staging / prod deployment execution | 현재 MLP 기록에 완료된 실행 산출물이 없음 | operator blocker가 현재 acceptance/runbook 및 row-native 계획에 명시되어 있음 | 미구현 | `service/` 문서에 execution 소유의 deploy artifact 없음 | blocker 또는 defer 근거만 존재 | `service/docs/acceptance.md`, `service/docs/runbook.md`, `service/docs/current_slave.md`의 blocked/deferred 항목 | operator 입력과 deploy 권한이 아직 없음 | 명시적으로 미구현 상태 유지 |

## 상세 메모

### Backend / service 기능
- Search, register, execute, bridge, dashboard, shared-runtime lane은 모두 직접 코드 경로가 있고 저장소 로컬 문서에 연결된 회귀 또는 harness 근거도 있다.
- async indexing backend 격차는 이제 handler, service test, index loop harness의 저장소 로컬 content-hash skip 근거로 닫혔다. register payload 또는 Qdrant payload 계약이 바뀔 때만 다시 연다.
- Harness coverage는 MLP lane의 강점이다. search/index/execute/bridge/smoke 모두 전용 유틸리티와 대응되는 unit test를 갖고 있다.

### Frontend 기능
- local-first provider journey는 이미 저장소 근거로 닫혀 있다. login, self-serve registration, pending banner, dashboard reflection 모두 test/build와 browser-proof trace가 있다.
- dashboard/provider-facing UX confidence는 현재 frontend 계약 기준으로 닫혔다. Task 1/Task 2 actionability pass, fresh browser proof, 그리고 2026-04-12 sourced-shell provider-owned API rerun이 변경되지 않은 201/401/200/404 backend 상태를 다시 확인했다.
- hosted auth/origin 이슈는 local frontend flow가 빠졌다는 근거가 아니라 deployment concern으로 다뤄야 한다.

### Planning / release 기능
- local-first acceptance gate는 저장소 근거상 초록이며, deployed-origin 작업과 분리된 상태를 유지해야 한다.
- deployment planning, frontend UI planning, final handoff/query-gate packaging은 의도적으로 planning-only closeout이지, 숨겨진 구현 lane이 아니다.
- 실제 AWS staging/prod deployment execution은 저장소가 operator 입력과 deploy 권한 부재를 반복해서 기록하고 있으므로 빨간색 상태로 남아 있다.

## 우선순위 큐
1. 먼저 닫아야 할 검증 격차:
   - 더 이상 현재 계약과 맞지 않는 오래된 local-first 근거
2. 명시적으로 defer 유지할 planning-only 항목:
   - production deployment planning lane
   - frontend UI planning lane
   - final handoff / query-gate preparation lane
3. 이후 구현 전에 다시 검증할 고위험 영역:
   - deployment 입력과 hosted auth/origin 설정
   - index freshness/content-hash 동작
   - provider detail 계약 또는 live auth/runtime 입력이 다시 바뀌는 경우의 provider-facing dashboard detail 품질
