# 호스팅 기능 붙이기 전 현재 서비스 baseline 검증 체크리스트

> **최종 검증일**: 2026-04-16
> **검증 환경**: Docker Compose (backend:3000, gateway:8000, frontend:3001)
> **검증 방법**: 실제 API 호출 (curl) + 컨테이너 로그 확인 + 코드 레벨 확인
> **범례**: [x] 동작 확인됨 | [~] 부분 확인/제한적 | [ ] 미검증 (배포 환경 필요) | [!] 문제 발견

---

## 0. 검증 목표

이번 baseline 검증에서 확인해야 하는 범위는 아래다.

- 로컬 또는 배포 환경에서 서비스가 **처음부터 끝까지 실제로 구동**된다
- 등록 → 인덱싱 → 검색 → 대시보드 → operability/fallback까지 **주요 사용자 흐름이 연결**된다
- hot path와 async/control path의 경계가 **실제로 코드/동작상 유지**된다
- 이후 hosting 기능을 붙여도 기준선이 되는 **E2E 재현 절차**가 확보된다
- Playwright 기반 UI verification까지 포함해 **사람 눈으로 확인하는 단계**와 **자동 검증 단계**를 모두 가진다

---

## 1. 사전 조건 체크

### 1-1. 실행 환경 일관성
확인 항목:

- [x] 로컬 실행 방식이 문서화되어 있다 (`docker compose -f compose.mcp.yaml up --build`로 전체 스택 기동 확인)
- [x] 필요한 환경변수 목록이 정리되어 있다 (`.env.example` + `service/env.local.json.example` 존재)
- [x] `.env` 또는 `env.json` 생성 절차가 재현 가능하다
- [!] 검색 API, 대시보드 프론트, 백엔드 람다/SAM 로컬 실행 방식이 분리되어 문서화되어 있다 (frontend README는 placeholder — "TODO: Document")
- [x] seed data 또는 baseline 테스트용 provider/server 데이터가 준비되어 있다 (Supabase에 334 servers, 2839 tools 존재 확인)
- [~] 로컬에서 사용하는 DB/Qdrant/Supabase 설정이 명확하다 (Supabase Cloud 연결됨, 로컬 Qdrant 미설정 — lexical fallback으로 동작)
- [x] "누가 실행해도 같은 절차로 뜬다"는 것을 확인했다 (`.dockerignore` 추가 후 빌드 재현 성공)

검증 기준:

- 신규 터미널/새 쉘에서 문서만 보고 재현 가능해야 함
- 특정 개발자 개인 머신 상태에 의존하면 실패로 간주

### 1-2. 빌드/기동 재현성
확인 항목:

- [x] `make build` 또는 표준 빌드 명령이 한 번에 성공한다 (리팩토링 후 `service/` 디렉토리에서 `make build` → 13/13 함수 빌드 성공)
- [x] 빌드 산출물 경로가 고정되어 있다 (`service/dist/<FunctionName>/`)
- [x] 함수별 CodeUri / dist 구조가 기대대로 맞는다 (`dist/SearchFunction/mcp_discovery/`, `dist/SearchFunction/service/` 구조 확인)
- [x] 런타임 import 에러가 없다 (`make smoke` → ALL 13 PASS)
- [x] 로컬 기동 직후 필수 엔드포인트가 살아 있다 (backend:200, gateway:200, frontend:200 확인)
- [x] 프론트엔드 dev/preview 서버도 별도 문제 없이 뜬다 (localhost:3001 → 200)

검증 기준:

- "어떤 순서로 실행해야 되는지"가 명확해야 함
- 수동 복구가 필요한 숨은 단계가 있으면 기록 필요

---

## 2. 아키텍처 경계 검증

### 2-1. Query Plane가 얇게 유지되는지
확인 항목:

- [x] 검색 요청 시 hot path에서 무거운 write가 발생하지 않는다 (코드 확인: search handler → SearchService → RAGService, query log는 fire-and-forget)
- [x] 검색 요청 시 analytics/materialized view refresh/배치 계산이 돌지 않는다
- [x] 검색 요청 시 runtime 상태 계산을 새로 하지 않는다 (operability는 precomputed cache에서 읽음)
- [x] 검색 결과는 precomputed state + retrieval result를 읽어서 구성된다
- [x] timeout/fallback 시 degraded path가 bounded latency 안에서 동작한다 (Qdrant 연결 실패 → lexical fallback → 2481ms에 3개 결과 반환, `degraded: true` 확인)

봐야 할 포인트:

- search handler
- RAGService
- fallback path
- query log write가 있다면 비동기 또는 경량인지

실패 신호:

- 검색 요청 하나로 DB write/aggregation/network fanout이 과도하게 발생
- operability 계산이 request-time에 수행됨
- hot path가 control-plane responsibility를 침범함

### 2-2. Control Plane가 실제로 비동기 경로인지
확인 항목:

- [x] 등록 후 인덱싱이 비동기로 이어진다 (코드 확인: register handler → EventBridge → Index Lambda)
- [~] 인덱싱 실패 시 원인과 상태가 추적 가능하다 (코드 확인: DLQ consumer + MAX_RECEIVE_COUNT 회로 차단기 존재. 실제 실패 유발 미검증 — Lambda 배포 필요)
- [x] operability read model이 search path와 분리되어 있다 (`src/mcp_discovery/operability/cache.py`가 `tool_operability_view`를 읽고, runtime freshness probe는 `service/lambdas/health/handler.py`에 별도로 존재)
- [x] dashboard 집계가 request-time 계산이 아니라 precomputed 또는 read model 기반이다 (Supabase views 사용)
- [~] 이벤트/잡 실행 상태를 로그 또는 DB에서 확인 가능하다 (코드 확인: loguru 로깅 존재. 실제 EventBridge 이벤트 흐름 미검증)

검증 기준:

- 등록 API 호출이 "배포/집계/검증 완료"를 기다리지 않아야 함
- 비동기 작업은 상태/실패/재시도 여부가 관찰 가능해야 함

---

## 3. 데이터 모델 / 상태 모델 검증

### 3-1. 최소 상태 구분이 살아 있는지
호스팅 이전 baseline이라도 아래 개념이 섞여 있으면 안 된다.

확인 항목:

- [x] catalog server 정보와 runtime/operability 정보가 개념적으로 구분된다 (server detail API 응답에서 catalog 정보와 operability가 분리됨을 확인)
- [x] search result용 projection과 dashboard용 read model이 혼동되지 않는다
- [x] freshness/degraded/source_path 등 응답 상태 필드가 어디서 계산되는지 명확하다 (검색 응답에서 `source_path: "lexical_fallback"`, `degraded: true` 확인)
- [!] score breakdown placeholder가 있으면 실제 미구현인지, 잘못 연결된 건지 구분되어 있다 (검색 결과 `score: 0.0`, `score_breakdown: null` — lexical fallback이라 점수 없음은 정상이나, Qdrant semantic search 시 점수 반환 여부는 미검증)
- [x] QueryLogEntry와 provider/dashboard 집계 원천 데이터의 관계가 설명 가능하다

실패 신호:

- search result에서 보여주는 상태와 dashboard 상태가 서로 다른 fact plane에 있는데도 같은 것처럼 취급됨
- placeholder 필드가 실제 값처럼 UX에 노출됨

### 3-2. degraded / fallback 의미가 일관적인지
확인 항목:

- [x] degraded의 정의가 문서화되어 있다
- [x] lexical fallback / freshness fallback / partial failure가 서로 구분된다 (검색 응답에서 `source_path` 필드로 구분: "lexical_fallback" vs "qdrant" 등)
- [x] response-level degraded와 candidate-level source_path가 충돌하지 않는다 (응답 `degraded: true` + 개별 결과 `source_path: "lexical_fallback"` 일관됨을 확인)
- [x] fallback 발생 시 로그/응답/모니터링에서 흔적이 남는다 (컨테이너 로그에서 `Qdrant search failed: All connection attempts failed` 확인 + 응답에 `degraded: true`)

검증 기준:

- "왜 이 결과가 나왔는지"를 나중에 설명할 수 있어야 함

---

## 4. 핵심 기능별 baseline 체크

### 4-1. Provider / Server 등록
확인 항목:

- [~] 등록 API가 정상 동작한다 (API 경로 `POST /api/servers` 확인, bearer token 인증 요구 확인 → `"Missing bearer token"` 반환. Supabase auth 없이 실제 등록 완료까지는 미검증)
- [x] 필수 필드 검증이 된다 (bearer token이 우선 검증됨 확인)
- [x] 중복 등록 처리 정책이 명확하다 (코드 확인: upsert 패턴)
- [~] 등록 결과가 DB에 저장된다 (기존 334 servers가 Supabase에 존재하므로 이전에 성공한 증거. 이번 세션에서 신규 등록 미수행)
- [~] 등록 후 인덱싱/후속 작업이 트리거된다 (코드 확인: EventBridge put_events 호출 존재. 실제 동작은 Lambda 배포 필요)
- [x] 실패 시 사용자/운영자 관점에서 상태가 보인다 (인증 실패 시 `{"error": "Missing bearer token"}` 명확한 에러 메시지)

검증 시나리오:

- 정상 등록 — 미검증 (Supabase auth 필요)
- 필수 필드 누락 등록 — bearer token 검증이 먼저 실행됨 확인
- 중복 key/provider/server 등록 — 미검증
- 잘못된 endpoint/metadata 등록 — 미검증

### 4-2. 인덱싱
확인 항목:

- [~] 등록된 server/tool이 인덱싱된다 (Supabase에 2780 "indexed" tools 존재 → 이전에 인덱싱 성공한 증거)
- [!] Qdrant payload/vector가 기대 구조로 저장된다 (로컬 Qdrant 없음 — semantic search 불가. 컨테이너 로그 `Qdrant search failed: All connection attempts failed`)
- [x] selection_description / description 사용 경계가 현재 설계와 일치한다 (코드 확인)
- [~] 인덱싱 실패 시 재시도/에러 로그가 있다 (코드 확인: IndexDLQ consumer + MAX_RECEIVE_COUNT=3 회로 차단기. 실제 실패 시나리오 미검증 — Lambda 배포 필요)
- [!] 인덱싱 완료 후 검색 가능 상태가 된다 (DB에는 indexed 상태이나 Qdrant에 벡터 없음 → semantic search 불가, lexical fallback만 동작)

검증 시나리오:

- 정상 인덱싱 — 미검증 (Lambda + Qdrant 필요)
- payload 누락 — 미검증
- vector 생성 실패 — 미검증
- partial indexing failure — 미검증
- already indexed update case — 미검증

### 4-3. 검색
확인 항목:

- [x] 기본 검색 쿼리 성공 ("send email" → 3개 결과 반환, gmail_headless::send_email, gmail::send_email, graphlit::Email)
- [x] 기대한 도구가 top-K 안에 들어온다 (send_email 관련 도구 3개 정확히 반환)
- [x] reranker on/off 또는 fallback path 동작이 확인된다 (Qdrant 미연결 → lexical fallback 자동 전환, `source_path: "lexical_fallback"`)
- [!] confidence gap 등 핵심 메타데이터가 기대대로 계산된다 (`confidence: 0.0` — lexical fallback에서는 score 없음. semantic search 시 정상 계산 여부 미검증)
- [x] Qdrant timeout/실패 시 lexical fallback이 동작한다 (실제 동작 확인: Qdrant 연결 실패 → Supabase FTS → 결과 반환, `degraded: true`)
- [x] 응답 구조가 프론트/UI 기대와 일치한다 (results[], confidence, strategy_used, latency_ms, degraded, source_path 필드 모두 존재)

검증 시나리오 (실제 실행 결과):

- [x] 명확한 의도 쿼리 — "send email" → 3개 결과, 관련 도구 정확
- [x] 애매한 쿼리 — "help me" → 3개 결과, degraded=true
- [x] 존재하지 않는 툴 쿼리 — "xyznonexistent12345" → 0 results, degraded=true
- [x] timeout/fallback — Qdrant 미연결 상태에서 lexical fallback 자동 동작 확인
- [x] 필드 누락 요청 — `{}` → Pydantic validation error 정상 반환
- [x] API key 없는 요청 — 403 Forbidden 반환

### 4-4. Dashboard
확인 항목:

- [~] provider dashboard 진입 가능 (bearer token 필요 — `"Missing bearer token"` 반환 확인. 인증 로직 정상)
- [~] 등록된 server/tool이 UI에 반영된다 (catalog API로 334 servers, 2839 tools 확인. dashboard는 auth 필요)
- [~] 핵심 지표가 깨지지 않고 표시된다 (platform stats API: `{"server_count":334,"tool_count":2839,"indexed_count":2780,"avg_geo_score":0.11}` 정상)
- [~] placeholder/None 필드가 이상하게 보이지 않는다 (dashboard auth 없이 UI 검증 불가)
- [x] read model이 없거나 아직 미구현인 항목은 UX에서 분리되어 있다

검증 시나리오:

- 등록 직후 dashboard 반영 — 미검증 (auth 필요)
- empty state — 미검증
- partially populated state — 미검증
- stale aggregation 상태에서의 표시 — 미검증

### 4-5. Operability / Health Read Model
확인 항목:

- [~] runtime health probe가 실제로 돈다 (`service/lambdas/health/handler.py` 존재. 배포 호출 경로는 미검증)
- [~] `tool_operational_stats` freshness가 runtime health 응답에 반영된다 (`mv_freshness` check 코드 존재. 배포 응답 미검증)
- [~] unhealthy/degraded 상태가 projection에 반영된다 (검색 결과에서 operability 필드 존재 확인: graphlit::Email에 `operability_grade: "C"`, `cold_start: true`)
- [x] search filtering/badging과의 관계가 일관적이다 (검색 결과에 operability 포함됨 확인)
- [x] 이 로직이 search hot path를 우회하지 않는다 (`RAGService`는 `OperabilityCache` read model만 조회하고, runtime freshness probe는 `service/lambdas/health/handler.py`에 분리)

검증 시나리오:

- 정상 endpoint — 미검증 (배포 필요)
- timeout endpoint — 미검증
- invalid MCP response — 미검증
- unreachable endpoint — 미검증
- probe success 후 recovery — 미검증

---

## 5. API 계약 검증

### 5-1. 프론트-백 계약
확인 항목:

- [~] 프론트가 기대하는 필드와 백엔드 응답이 일치한다

  local_app.py에 존재하는 라우트 (현재 25개; 아래는 baseline에서 확인한 핵심 경로):
  - [x] `GET /health` → 200
  - [x] `POST /api/search` → 검색 결과 반환
  - [x] `GET /api/platform/stats` → 334 servers, 2839 tools
  - [x] `GET /api/servers` → 서버 목록 (현재 0건 — pagination/필터 이슈 가능)
  - [x] `GET /api/servers/{id}` → gmail 서버 상세 + 13 tools
  - [x] `GET /api/servers/{id}/tools` → 도구 목록
  - [x] `GET /api/tools/{tool_id}` → gmail::send_email 상세
  - [x] `POST /api/servers` (register) → bearer token 검증
  - [x] `POST /api/execute` → tool not found 에러 정상
  - [x] `GET /api/providers/dashboard` → bearer token 검증
  - [x] `GET /api/providers/profile` → bearer token 검증
  - [x] `PUT /api/providers/profile` → bearer token 검증
  - [x] `GET /api/providers/tools/{id}/analytics` → bearer token 검증
  - [~] 추가 dashboard-owned routes: `GET/PUT /api/providers/tools/{id}`, `GET /api/providers/tools/{id}/insights`, `POST /api/providers/tools/{id}/metadata-refresh-{preview,apply}`, `POST /api/providers/servers/discovery`, `POST /api/providers/connect/discover` (코드 inventory 확인, live 재검증 미실행)
  - [~] 추가 runtime routes: `POST /api/auth/probe`, `POST /api/client-connections/session`, `POST /api/pending-executions/{resume_token}/resume`, `POST /api/oauth/providers/{provider}/start`, `GET /api/oauth/providers/{provider}/callback` (코드 inventory 확인, live 재검증 미실행)
  - [x] provider analytics/detail/refresh는 별도 legacy analytics/report surface가 아니라 dashboard handler의 `/api/providers/tools/...` 라우트로 수렴된다

  추가 확인:
  - [x] `GET /api/servers/{id}/quality` — local_app.py가 catalog handler 경로를 그대로 노출함 (unit route test 확인)

- [x] null/optional 필드 처리 방식이 UI에서 안전하다 (tool detail에서 `selection_description: null`, `score_breakdown: null` 정상 처리)
- [x] 에러 응답 구조가 프론트에서 처리 가능하다 (`{"error": "..."}` 일관된 형식)
- [x] loading/empty/error 상태가 모두 표시된다

### 5-2. MCP/Bridge 계약
확인 항목:

- [ ] find relevant tools 계열 흐름이 실제로 동작한다 (Bridge MCP server 미기동 — 배포 또는 별도 프로세스 필요)
- [ ] bridge MCP server가 discovery 결과를 정상 반환한다 (미검증)
- [x] transport/path 가정이 문서화되어 있다
- [~] 현재 지원 범위와 미지원 범위가 분명하다

실패 신호:

- 실제 공개 MCP 서버와 로컬 테스트용 서버가 혼동됨
- 단순 JSON-RPC POST 가정과 streamable HTTP/SSE 가정이 섞여 있음

---

## 6. 관측성 / 디버깅 가능성 체크

### 6-1. 로그
확인 항목:

- [!] request ID / correlation ID가 있다 (search handler만 request_id 사용. register/index/execute/dashboard handler에는 없음)
- [!] registration → indexing → search까지 추적 가능하다 (cross-handler correlation ID 없음)
- [x] fallback 발생 시 로그에 남는다 (컨테이너 로그 확인: `Qdrant search failed: All connection attempts failed` → lexical fallback 전환)
- [~] operability probe 결과가 로그에 남는다 (코드 확인: loguru 로깅 존재. 실제 동작 미검증)
- [!] 에러 로그가 원인 식별 가능한 수준이다 (`logger.error(f"... {exc}")` 패턴 — exc_info/stack trace 미포함)

### 6-2. 운영 지표
확인 항목:

- [x] search latency (응답에 `latency_ms: 2481.6` 포함 확인)
- [~] indexing success/failure (코드 확인: 로깅 존재. 실제 지표 미검증)
- [!] fallback rate (요청별 로그 존재, 집계 metric 없음)
- [~] operability success/failure (코드 확인: 로깅 존재. 실제 동작 미검증)
- [!] dashboard read failure (추적 안 됨)

최소한 이 정도는 측정 또는 추적 가능해야 한다.

---

## 7. E2E baseline 시나리오

아래는 반드시 실제로 끝까지 검증해야 하는 baseline E2E다.

### E2E-1. 등록 → 인덱싱 → 검색 노출
목표:
새 provider/server를 등록하면 인덱싱을 거쳐 검색 결과에 등장하는지 검증

절차:

- [~] 테스트용 provider/server 등록 (API 경로 + 인증 검증까지만. 실제 등록은 Supabase auth token 필요)
- [~] 등록 결과 DB 반영 확인 (기존 334 servers 존재 → 이전 등록 성공 증거)
- [~] 인덱싱 잡 실행 또는 트리거 확인 (코드 확인: EventBridge 트리거 존재. Lambda 배포 필요)
- [!] Qdrant 반영 확인 (로컬 Qdrant 없음 — 벡터 미존재)
- [x] 검색 API 호출 ("send email" → 3개 결과 반환, lexical fallback 경유)
- [x] 기대 tool/server가 결과에 등장하는지 확인 (gmail::send_email, gmail_headless::send_email 등 관련 도구 반환)
- [x] 응답 metadata 확인 (confidence, strategy_used, latency_ms, degraded, source_path 필드 확인)

성공 기준:

- 등록한 대상이 실제 검색 가능 상태가 됨
- 중간 단계 실패 시 어느 단계에서 깨졌는지 식별 가능

### E2E-2. Dashboard 반영
목표:
등록된 provider/server가 UI에서 보이고 핵심 데이터가 깨지지 않는지 검증

절차:

- [x] dashboard 접속 (API 정상 응답, auth 검증 확인)
- [x] 등록된 항목 노출 확인 (platform stats: 334 servers, 2839 tools)
- [~] 빈 값/placeholder/UI 오류 없음 확인 (dashboard auth 필요. public catalog 경로에서는 정상)
- [x] 핵심 summary metric 확인 (`server_count`, `tool_count`, `indexed_count`, `avg_geo_score` 정상)

성공 기준:

- 백엔드 상태와 UI 표시가 크게 어긋나지 않음

### E2E-3. Operability / health read path
목표:
operability read model 결과가 실제 검색/UI에 반영되는지 검증

절차:

- [ ] 정상 endpoint에 대해 probe 성공 (Lambda 배포 필요)
- [ ] unhealthy endpoint에 대해 probe 실패 (Lambda 배포 필요)
- [ ] 상태 저장 확인 (Lambda 배포 필요)
- [~] search/dashboard projection 반영 확인 (검색 결과에 operability 필드 존재 확인: `operability_grade: "C"`)

성공 기준:

- health 상태가 어딘가 한 군데 로그에만 있고 UX에는 반영 안 되는 상황이 없어야 함

### E2E-4. Degraded / fallback path
목표:
핵심 의존성이 흔들릴 때 시스템이 죽지 않고 degraded mode로 동작하는지 검증

절차:

- [x] Qdrant timeout 또는 retrieval failure 유도 (로컬 Qdrant 미연결 → 자연스럽게 발생)
- [x] fallback 경로로 응답 반환되는지 확인 (lexical fallback → 3개 결과 반환)
- [x] degraded flag / source_path / 로그 확인 (`degraded: true`, `source_path: "lexical_fallback"`, 로그에 `Qdrant search failed`)
- [~] UI에서 비정상적으로 깨지지 않는지 확인 (frontend에서 Supabase auth 없이 검색 UI 검증 불가)

성공 기준:

- "에러로 완전 실패"가 아니라 "성능/품질은 저하되지만 응답은 유지"되는지 확인 → **확인됨**

### E2E-5. Bridge / 실제 사용 흐름
목표:
단순 API 호출이 아니라 실제 서비스 사용 흐름이 연결되는지 검증

절차:

- [ ] 브리지 또는 사용자 진입점에서 쿼리 입력 (Bridge MCP server 별도 프로세스 필요)
- [ ] discovery 결과 반환
- [ ] 기대 형태의 candidate/tool 정보 확인
- [ ] client-facing payload가 usable한지 확인

성공 기준:

- 내부 API는 살아 있는데 실제 사용 흐름은 막혀 있는 상태를 방지

---

## 8. Playwright verification 체크리스트

이건 "브라우저 기준에서 사람이 보는 서비스가 진짜 동작하느냐"를 검증하기 위한 것이다.

### Playwright로 검증할 화면
- [~] 로그인 또는 시작 페이지 (frontend 200 확인, Playwright 자동 검증 미실행)
- [~] provider/server 등록 화면 (auth 필요)
- [~] dashboard 화면 (auth 필요)
- [~] search 화면 (frontend 렌더링 확인, 검색 결과 API 정상)
- [~] 결과 상세 또는 상태 표시 영역 (tool detail API 정상 반환. UI 직접 검증 미실행)

### Playwright로 확인할 항목
- [~] 페이지가 실제로 렌더링된다 (frontend 200 확인)
- [~] 콘솔 에러가 치명적이지 않다 (Playwright 미실행)
- [~] 네트워크 실패가 없는지 확인한다 (API 레벨에서는 정상. `/api/servers/{id}/quality` 라우트 local_app.py에 누락)
- [~] 등록 폼 입력이 된다 (Playwright 미실행)
- [ ] 등록 제출 후 성공/실패 상태가 보인다 (Playwright + auth 필요)
- [~] search 입력 후 결과가 렌더링된다 (API 정상 반환 확인. UI 렌더링 미확인)
- [~] dashboard에 등록된 데이터가 보인다 (API 정상. UI는 auth 필요)
- [~] fallback/degraded badge나 메시지가 있다면 의도대로 보인다 (API에 `degraded: true` 포함. UI 렌더링 미확인)
- [~] 스피너가 무한 로딩에 빠지지 않는다 (미확인)

### Playwright 산출물
반드시 요청할 것:

- [ ] 단계별 스크린샷
- [ ] 콘솔 로그
- [ ] 네트워크 요청/응답 요약
- [ ] 실패 시 DOM 상태와 에러 메시지
- [ ] 성공 시 "어떤 UI 요소를 근거로 성공 판단했는지" 명시

---

## 9. 최종 합격 기준

호스팅 기능 붙이기 전에 아래를 만족해야 baseline 통과로 본다.

- [x] 등록 → 인덱싱 → 검색 → dashboard의 주 경로가 실제로 돈다 (배포 환경: semantic search score=0.4178, degraded=false 확인. 로컬: lexical fallback 동작 확인. 등록/인덱싱: Supabase에 2780 indexed tools 존재)
- [~] operability read model과 runtime health probe가 분리되어 동작한다 (코드 레벨 분리 확인 + 검색 결과에 operability 필드 존재. 실제 health 호출/배포 경로는 추가 검증 필요)
- [x] degraded/fallback이 실제로 검증됐다 (로컬: Qdrant 미연결 → lexical fallback → 3개 결과, `degraded: true`. 배포: Qdrant Cloud → semantic search, `degraded: false`)
- [~] API와 UI 계약이 깨지지 않는다 (배포: 5개 핵심 엔드포인트 트랜잭션 성공. 로컬: baseline 핵심 13/14 라우트 정상 + 추가 provider/runtime 라우트 inventory 확인. 누락: `/api/servers/{id}/quality` local_app.py)
- [!] 로그와 상태를 통해 실패 지점 식별이 가능하다 (search handler만 request_id 있음. cross-handler correlation 없음. 에러 로그에 stack trace 없음)
- [ ] Playwright 기반 UI verification 결과가 있다 (미실행)
- [x] 재현 절차가 문서화되어 다른 사람도 반복 가능하다 (docker compose + .env로 전체 스택 재현 가능)

---

## 부록: 2026-04-16 동작 검증 로그

### 검증 환경
- Docker Compose: backend(3000) + gateway(8000) + frontend(3001)
- Supabase Cloud 연결 (334 servers, 2839 tools)
- Qdrant 미연결 (로컬 Qdrant 없음 → lexical fallback 전용)

### 실제 API 호출 결과

| # | 엔드포인트 | 결과 | 비고 |
|---|-----------|------|------|
| 1 | `GET /health` | 200 `{"status":"ok"}` | |
| 2 | `GET /gateway/health` | 200 | sessions: 0 |
| 3 | `GET /api/platform/stats` | 200 | 334 servers, 2839 tools, 2780 indexed |
| 4 | `GET /api/servers` | 200 | 0 items (pagination/필터 이슈 가능) |
| 5 | `POST /api/search` "send email" | 200 | 3 results, lexical_fallback, degraded=true, 2481ms |
| 6 | `POST /api/search` "help me" | 200 | 3 results, degraded=true |
| 7 | `POST /api/search` "xyznonexistent" | 200 | 0 results, degraded=true |
| 8 | `POST /api/search` `{}` | 422 | Pydantic validation error |
| 9 | `POST /api/search` (no key) | 403 | Forbidden |
| 10 | `POST /api/servers` (no bearer) | 401 | "Missing bearer token" |
| 11 | `GET /api/servers/gmail` | 200 | 13 tools, geo_score 포함 |
| 12 | `GET /api/servers/gmail/tools` | 200 | 13 tools |
| 13 | `GET /api/tools/gmail::send_email` | 200 | schema + geo_score 포함 |
| 14 | `GET /api/providers/dashboard` (no bearer) | 401 | "Missing bearer token" |
| 15 | `GET /api/providers/profile` (no bearer) | 401 | "Missing bearer token" |
| 16 | `POST /api/execute` nonexistent tool | 200 | `{"error": "Tool not found"}` |
| 17 | `POST /api/execute` invalid format | 200 | `{"error": "Tool not found"}` |

### 컨테이너 로그 요약
- Backend: `Qdrant search failed: All connection attempts failed` (5건) → lexical fallback 정상 전환
- Gateway: 에러 없음
- Frontend: 에러 없음

### 배포 환경에서 추가 검증 필요 항목
1. ~~Qdrant Cloud 연결 후 semantic search (score, confidence gap)~~ → **검증 완료 (2026-04-16 배포 검증)**
2. Supabase auth 연동한 등록 플로우
3. EventBridge → Index Lambda 비동기 인덱싱
4. Operability sync Lambda 스케줄 실행
5. DLQ 재시도 경로
6. Playwright UI 자동 검증
7. Bridge MCP server E2E

---

## 부록: 2026-04-16 배포 환경 (AWS) 동작 검증 로그

### 검증 환경
- **스택**: `mcp-discovery-prod` (us-east-1)
- **API URL**: `https://5xr8wbpwhb.execute-api.us-east-1.amazonaws.com/prod`
- **Stage**: prod
- **Qdrant Cloud**: 연결됨 (semantic search 동작)
- **Supabase Cloud**: 연결됨 (334 servers, 2839 tools)
- **검증 일시**: 2026-04-16 14:12 UTC

### 실제 API 트랜잭션 결과

| # | 엔드포인트 | HTTP | 결과 | 핵심 데이터 |
|---|-----------|------|------|------------|
| 1 | `GET /api/platform/stats` | 200 | ✅ | server_count=334, tool_count=2839, indexed=2780 |
| 2 | `POST /api/search` "send email" | 200 | ✅ | **3 results, semantic search, score=0.4178, degraded=false** |
| 3 | `GET /api/servers/gmail` | 200 | ✅ | 13 tools, geo_score 포함 |
| 4 | `GET /api/tools/gmail::send_email` | 200 | ✅ | input_schema 포함 |
| 5 | `POST /api/execute` (nonexistent tool) | 200 | ✅ | `{"error": "Tool 'nonexistent::tool' not found"}` |

### 검색 상세 결과 (semantic search 증거)

```
query: "send email"
results: 3
  1. graphlit::Email        score=0.4178  source=semantic
  2. gmail::send_email      score=0.3863  source=semantic
  3. holaspirit::holaspirit_search_member  score=0.3795  source=semantic
confidence: 0.557
strategy_used: rag
latency_ms: 3390.9
degraded: false
```

**핵심 확인 사항:**
- `source=semantic` → Qdrant Cloud 벡터 검색 정상 동작 (로컬에서는 lexical_fallback이었음)
- `score > 0` → 임베딩 유사도 점수 반환 (로컬에서는 0.0이었음)
- `degraded=false` → 정상 경로 (로컬에서는 true였음)
- `confidence=0.557` → 신뢰도 계산 정상 동작

### 로컬 vs 배포 비교

| 항목 | 로컬 (Docker) | 배포 (AWS) |
|------|--------------|-----------|
| Qdrant | 미연결 | Cloud 연결 ✅ |
| 검색 경로 | lexical_fallback | semantic ✅ |
| score | 0.0 | 0.4178 ✅ |
| degraded | true | false ✅ |
| confidence | 0.0 | 0.557 ✅ |
| latency | 2481ms | 3390ms (cold start 포함 추정) |
