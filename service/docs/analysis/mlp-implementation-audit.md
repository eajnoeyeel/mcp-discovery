# MLP Implementation Audit

- Date: 2026-04-11
- Branch: `feat/service/audit-done-vs-missing`
- Spec: `docs/superpowers/specs/2026-04-11-mlp-audit-done-vs-missing-design.md`

## Executive Summary
- Total feature rows: 20
- Implemented + verified: 16
- Implemented but verification insufficient: 0
- Planning-only: 3
- Unimplemented: 1
- Top quality risks:
  1. Deployment remains intentionally unimplemented because operator-owned inputs and execution authority are still missing.
  2. Re-run provider-owned dashboard proof if the provider detail contract or auth/runtime inputs change again.
  3. Async indexing is closed on repo-local evidence and should reopen only if the register payload or Qdrant payload shape changes.

## Scope And Method

### Scope
This audit covers the full `service/` tree:
- backend/service/runtime paths
- frontend paths
- harness/test evidence
- planning/release/history artifacts

### Classification rules
- **Implemented + verified**: code path exists and repo evidence shows tests, harnesses, acceptance proof, or history/current verification entries
- **Implemented but verification insufficient**: code path exists but fresh or linked evidence is missing, partial, stale, or contradicted
- **Planning-only**: planning docs exist but no meaningful implementation path exists
- **Unimplemented**: the repository implies the need, but neither implementation nor meaningful planning closure exists

### Evidence sources
- `service/docs/acceptance.md`
- `service/docs/current_slave.md`
- `service/docs/current_master.md`
- `service/docs/history/*.md`
- `service/docs/plan/row-native/*.md`
- `service/` source directories
- `tests/unit/test_mlp_*.py`
- `service/frontend/src/*.test.tsx`
- `service/harness/*.py`

## Feature Inventory
| Feature | Implementation status | Verification status | Final label | Code evidence | Test / harness evidence | Docs evidence | Remaining gap | Next action |
|---|---|---|---|---|---|---|---|---|
| Search path + RAG service | present in `service/lambdas/search`, `service/services/search_service.py`, and `service/rag/` | linked unit/rag/harness evidence present | Implemented + verified | `service/lambdas/search/handler.py`, `service/services/search_service.py`, `service/rag/service.py` | `tests/unit/test_mlp_handlers.py`, `service/rag/tests/test_service.py`, `tests/unit/test_mlp_search_loop.py`, `service/harness/search_loop.py` | `service/docs/current_master.md`, `service/docs/history/2026-04-05_2050_master_plan02_search_rag.md` | Re-check if provenance/freshness work changes response contracts | keep as current baseline |
| API key authorizer / auth guard | present in `service/lambdas/authorizer/handler.py` and enforced by protected API/browser flows | handler and provider proof show 401 behavior exists | Implemented + verified | `service/lambdas/authorizer/handler.py`, `service/frontend/src/components/ProtectedRoute.tsx` | `tests/unit/test_mlp_handlers.py` | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md` | review if auth contract changes from static API key | keep auth boundary tied to current gate |
| Register path | present in `service/lambdas/register` and `service/services/register_service.py` | local/provider verification evidence present | Implemented + verified | `service/lambdas/register/handler.py`, `service/services/register_service.py`, `service/adapters/supabase_client.py` | `tests/unit/test_mlp_handlers.py`, `tests/unit/test_mlp_provider_ownership.py` | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md` | reopen only if the register payload or content-hash contract changes | keep register + async-index payload contracts aligned |
| Async indexing path | present in `service/lambdas/index`, `service/services/index_service.py`, content-hash skip partitioning, and index-loop evidence | targeted handler/service/harness evidence present | Implemented + verified | `service/lambdas/index/handler.py`, `service/services/index_service.py`, `service/shared/content_hash.py`, `service/supabase/migrations/007_entity_lifecycle_and_freshness.sql` | `tests/unit/test_mlp_handlers.py`, `tests/unit/test_index_handler_failed_status.py`, `tests/unit/test_mlp_services.py`, `tests/unit/test_mlp_index_loop.py`, `service/harness/index_loop.py` | `service/docs/current_slave.md`, `service/docs/history/2026-04-12_1239_slave_async_indexing_path_closure.md` | re-check only if register payload or Qdrant payload shape changes | keep as current baseline |
| Execute path | present in `service/lambdas/execute` and `service/services/execute_service.py` | loop/unit evidence present | Implemented + verified | `service/lambdas/execute/handler.py`, `service/services/execute_service.py`, `service/adapters/mcp_http_client.py` | `tests/unit/test_mlp_handlers.py`, `tests/unit/test_mlp_execute_loop.py`, `service/harness/execute_loop.py` | `service/docs/current_slave.md` Plan 06 entries | re-verify if hosted MCP contract changes | keep as current baseline |
| Bridge path | present in `service/lambdas/bridge`, `service/services/bridge_service.py`, and bridge harnesses | dedicated bridge-loop and recorded-run evidence present | Implemented + verified | `service/lambdas/bridge/handler.py`, `service/services/bridge_service.py`, `service/harness/bridge_loop.py`, `service/harness/record_bridge_runs.py` | `tests/unit/test_mlp_bridge_loop.py`, `tests/unit/test_mlp_record_bridge_runs.py`, `service/harness/fixtures/bridge_runs_recorded_local_sam_pending_20260408T133734Z.json` | `service/docs/current_slave.md`, `service/docs/history/2026-04-08_2233_slave_root_vision_recorded_bridge_runs_evidence.md` | hosted-origin fidelity remains intentionally deferred | keep deferred boundary explicit |
| Catalog + dashboard read APIs | present in `service/lambdas/catalog`, `service/lambdas/dashboard`, `service/services/catalog_service.py`, and `service/services/dashboard_service.py` | backend verification evidence present | Implemented + verified | `service/lambdas/catalog/handler.py`, `service/lambdas/dashboard/handler.py`, `service/services/dashboard_service.py` | `tests/unit/test_mlp_catalog_dashboard.py`, `tests/unit/test_mlp_dashboard_snapshot.py` | `service/docs/current_slave.md`, `service/docs/current_master.md` | provider-first frontend polish remains separate | keep backend/frontend distinction explicit |
| Shared runtime / adapters / validation | present in `service/shared`, `service/adapters`, and `service/validation` | unit evidence present | Implemented + verified | `service/shared/runtime.py`, `service/shared/http.py`, `service/adapters/supabase_client.py`, `service/validation/description_rules.py` | `tests/unit/test_mlp_runtime.py`, `tests/unit/test_mlp_shared_http.py`, `tests/unit/test_mlp_services.py`, `tests/unit/test_mlp_handlers.py` | `service/docs/current_slave.md`, `service/docs/history/2026-04-05_1358_slave_shared_core_runtime_foundation_impl.md` | future contract additions may extend, not invalidate | keep as core foundation |
| Supabase runtime contracts / migrations | migration files exist through `007` | migration/test evidence present, but production deploy is still deferred | Implemented + verified | `service/supabase/migrations/001_initial.sql`, `002_runtime_contracts.sql`, `004_provider_search_simulations.sql`, `005_provider_ownership_and_read_api.sql`, `006_fts_nullable_status.sql`, `007_entity_lifecycle_and_freshness.sql` | `tests/unit/test_mlp_schema_contracts.py`, `tests/unit/test_mlp_template_contract.py` | `service/docs/current_master.md`, `service/docs/current_slave.md` | deployed migration application remains environment-dependent | note deploy dependency separately |
| Operational harnesses / smoke utilities | harness modules exist for search/index/execute/bridge/smoke | repeated local evidence present | Implemented + verified | `service/harness/search_loop.py`, `service/harness/index_loop.py`, `service/harness/execute_loop.py`, `service/harness/bridge_loop.py`, `service/harness/smoke_api.py` | `tests/unit/test_mlp_search_loop.py`, `tests/unit/test_mlp_index_loop.py`, `tests/unit/test_mlp_execute_loop.py`, `tests/unit/test_mlp_bridge_loop.py`, `tests/unit/test_mlp_smoke_api.py` | `service/docs/acceptance.md`, `service/docs/current_slave.md`, `service/docs/history/2026-04-08_1929_slave_root_vision_bridge_loop_sentinel.md` | live-stage/prod harness inputs remain deferred | keep local-first vs deployed boundary explicit |
| Login / auth flow | present in frontend auth context and login page | local test/build evidence and browser proof present | Implemented + verified | `service/frontend/src/contexts/AuthContext.tsx`, `service/frontend/src/pages/Login.tsx`, `service/frontend/src/components/ProtectedRoute.tsx` | `service/frontend/src/contexts/AuthContext.test.tsx`, `service/frontend/src/pages/Login.test.tsx` | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_0027_slave_plan05_api_first_google_oauth.md` | hosted-origin auth settings remain a deploy concern | keep local-first gate separate from deploy |
| Self-serve registration flow | present in `RegisterServer` page and API client mutations | tests/build and local browser proof present | Implemented + verified | `service/frontend/src/pages/RegisterServer.tsx`, `service/frontend/src/lib/api.ts`, `service/frontend/src/pages/Dashboard.tsx` | `service/frontend/src/pages/RegisterServer.test.tsx`, `service/frontend/src/lib/api.test.ts` | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_2025_slave_frontend_self_serve_registration.md`, `service/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md` | no immediate gap on the local-first path | keep as accepted baseline |
| Dashboard reflection / provider-owned feedback states | present in dashboard, tool-detail, competitor, and feedback UI | fresh targeted/frontend regression evidence, rerun provider-owned API proof, and fresh browser proof align after the provider-first actionability pass | Implemented + verified | `service/frontend/src/pages/Dashboard.tsx`, `service/frontend/src/pages/DashboardToolDetail.tsx`, `service/frontend/src/components/CompetitorTable.tsx`, `service/frontend/src/components/ProviderSimulationEvidence.tsx` | `service/frontend/src/pages/Dashboard.test.tsx`, `service/frontend/src/pages/DashboardToolDetail.test.tsx`, `npm test`, `npm exec -- tsc --noEmit`, `npm run build`, `verify_provider_dashboard.py` local proof in `service/docs/history/2026-04-12_2005_slave_provider_dashboard_verifier_rerun.md`, fresh browser proof (`provider-dashboard-tool-detail-proof.png`) | `service/docs/current_slave.md`, `service/docs/history/2026-04-12_1215_slave_dashboard_provider_facing_ux_confidence_refresh_closure.md`, `service/docs/history/2026-04-12_2005_slave_provider_dashboard_verifier_rerun.md`, `service/docs/plan/row-native/00_master_index.md` | re-run only if the provider detail contract or auth/runtime inputs change again | keep this actionability pass as the current provider UX baseline |
| Frontend build/test evidence | frontend test and build scripts exist and are repeatedly exercised in history | repo logs show many passing runs | Implemented + verified | `service/frontend/package.json`, `service/frontend/src/test/setup.ts` | `npm test`, `npm run build` evidence recorded throughout `service/docs/current_slave.md` and matching history entries | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md` | bundle-size warnings exist but are not release blockers in current evidence | keep warnings in notes, not as a blocker |
| Local-first acceptance gate | acceptance contract exists and matches the implemented provider journey | repo-local tests, harnesses, and browser proof are linked in docs | Implemented + verified | `service/docs/acceptance.md`, `service/docs/runbook.md` | harness/test commands referenced in acceptance and current/history entries | `service/docs/current_slave.md`, `service/docs/history/2026-04-06_2252_slave_plan05_local_gate_closed_via_owner_tag_fallback.md` | only deployed acceptance remains deferred | preserve the local-first boundary |
| Production deployment planning | row-native planning docs exist and package the Lambda/API plus App Runner gateway deployment path, but execution is intentionally absent | planning readback plus deploy-contract verification evidence present | Planning-only | `service/docs/plan/row-native/prd-mlp-production-deployment-planning.md`, `service/docs/plan/row-native/test-spec-mlp-production-deployment-planning.md`, `service/docs/runbook.md`, `service/docs/acceptance.md` | `tests/unit/test_mlp_gateway_deploy_manifest.py`, `tests/unit/test_mlp_gateway_settings.py`, `tests/unit/test_mlp_verify_runtime_schema.py`, `tests/unit/test_mlp_template_contract.py` | `service/docs/current_slave.md`, `service/docs/history/2026-04-13_2030_slave_production_deployment_planning_container_first_closeout.md`, `service/docs/plan/row-native/00_master_index.md` | operator inputs and deploy authority are still missing | keep execution blocked until the AWS execution row opens |
| Frontend UI planning lane | row-native planning docs exist, but no implementation is included | readback evidence present for planning closeout only | Planning-only | `service/docs/plan/row-native/prd-mlp-frontend-ui-planning.md`, `service/docs/plan/row-native/test-spec-mlp-frontend-ui-planning.md` | planning verification only | `service/docs/current_slave.md`, `service/docs/history/2026-04-09_1338_slave_frontend_ui_planning_closeout.md` | downstream implementation still separate | keep as a deferred plan |
| Final handoff / query-gate preparation lane | row-native planning docs exist and package prior planning lanes | planning closeout evidence present only | Planning-only | `service/docs/plan/row-native/prd-mlp-final-handoff-query-gate-preparation.md`, `service/docs/plan/row-native/test-spec-mlp-final-handoff-query-gate-preparation.md` | planning verification only | `service/docs/current_slave.md`, `service/docs/history/2026-04-09_2333_slave_final_handoff_query_gate_preparation.md` | deployment execution and query approval are still gated | keep closed until a later gate opens |
| Root-vision recorded-bridge evidence lane | recorded bridge evidence artifacts exist in history | bridge evidence is verified, and the lane is explicitly closed | Implemented + verified | `service/harness/bridge_loop.py`, `service/harness/record_bridge_runs.py` | recorded bridge run + bridge loop evidence already captured in bridge harness docs | `service/docs/current_slave.md`, `service/docs/history/2026-04-08_2306_slave_root_vision_recorded_bridge_lane_handoff.md` | do not reopen without contrary evidence | keep as a closed evidence lane |
| AWS staging / prod deployment execution | no completed execution artifact exists in current MLP records | operator blockers remain explicit in current acceptance/runbook and row-native planning | Unimplemented | no execution-owned deploy artifact in `service/` docs | blocked or deferred evidence only | `service/docs/acceptance.md`, `service/docs/runbook.md`, `service/docs/current_slave.md` blocked/deferred entries | operator inputs and deploy authority are still missing | keep explicitly unimplemented |

## Detailed Notes

### Backend / service features
- Search, register, execute, bridge, dashboard, and shared-runtime lanes all have direct code paths plus linked regression or harness evidence in repo-local docs.
- The async indexing backend gap is now closed by repo-local content-hash skip evidence in the handler, service tests, and index loop harness; reopen only if the register payload or Qdrant payload contract changes.
- Harness coverage is a strength of the MLP lane: search/index/execute/bridge/smoke all have dedicated utilities and matching unit tests.

### Frontend features
- The local-first provider journey is already closed in repo evidence: login, self-serve registration, pending banner, and dashboard reflection all have test/build plus browser-proof traces.
- Dashboard/provider-facing UX confidence is now closed for the current frontend contract: Task 1 and Task 2 landed the bounded actionability pass, fresh browser proof captured the dashboard -> tool-detail flow, and the 2026-04-12 sourced-shell provider-owned API rerun re-confirmed the unchanged 201/401/200/404 backend states.
- Treat hosted auth/origin issues as deployment concerns, not as evidence that the local frontend flow is missing.

### Planning / release features
- The local-first acceptance gate is green in repo evidence and should stay separated from deployed-origin work.
- Deployment planning, frontend UI planning, and final handoff/query-gate packaging are intentionally planning-only closeouts, not hidden implementation lanes.
- Actual AWS staging/prod deployment execution remains red because the repo repeatedly records missing operator inputs and deploy authority.

## Priority Queue
1. Verification gaps to close first:
   - any stale local-first evidence that no longer matches current contracts
2. Planning-only items to keep explicitly deferred:
   - production deployment planning lane
   - frontend UI planning lane
   - final handoff / query-gate preparation lane
3. High-risk areas to re-verify before future implementation:
   - deployment inputs and hosted auth/origin settings
   - index freshness/content-hash behavior
   - provider-facing dashboard detail quality if the provider detail contract or live auth/runtime inputs change again
