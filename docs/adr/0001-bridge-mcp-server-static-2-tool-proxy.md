# ADR-0001: Bridge MCP Server — Static 2-Tool Proxy

**Date**: 2026-03-24
**Status**: accepted
**Deciders**: 프로젝트 설계 단계

## Context

LLM이 여러 MCP 서버에 직접 연결되면 모든 툴 정의가 컨텍스트에 올라간다.
서버 10개 × 툴 평균 20개 × 툴 정의 300토큰 = 60,000토큰 → 비용 급증 + LLM 추론 품질 저하.
LLM 클라이언트와 Provider MCP 서버 사이에 단일 중개 레이어가 필요하다.

## Decision

LLM에 `find_best_tool`과 `execute_tool` 두 개의 툴만 고정으로 노출하는 Bridge MCP Server를 운영한다. Bridge가 내부적으로 벡터 검색 파이프라인을 실행하고, Provider MCP 서버로 실제 실행을 프록시한다.

## Alternatives Considered

### Alternative B: Dynamic Tool Injection
- **Pros**: 필요한 툴만 컨텍스트에 노출 → 이론적으로 더 효율적
- **Cons**: `tools/call`은 연결된 서버에만 보낼 수 있음. 동적 주입을 해도 Proxy가 대신 호출해야 하므로 인증 구조가 Static과 동일
- **Why not**: 복잡도만 추가되고 실질적 이점 없음

### Alternative C: N-way Routing
- **Pros**: 쿼리에 따라 직접 최적 서버로 라우팅
- **Cons**: MCP 프로토콜이 런타임에 서버를 동적으로 추가/교체하는 것을 지원하지 않음
- **Why not**: MCP 프로토콜 제약으로 구현 불가

## Consequences

### Positive
- Prompt Bloating 완전 해결 (2툴 고정)
- 모든 MCP 클라이언트와 호환 (`tools/list` 자동 호출 표준)
- `execute_tool` 단일 병목으로 Analytics 100% 로깅 가능
- CTO 설명 용이: "툴 2개, 역할 명확"

### Negative
- Bridge가 단일 장애점 (SPOF)
- Provider MCP 서버가 추가될 때마다 Bridge 레지스트리 업데이트 필요

### Risks
- Bridge 지연이 E2E 레이턴시에 직접 영향 → 파이프라인 최적화 필요
  - **실측 (proxy_verification, 2026-03-22)**: connect-per-call 기준 Python 백엔드 ~2200ms, Node.js 백엔드 ~3300ms
  - **프로덕션 완화**: persistent connections (`initSessions()` 패턴) 필수 — 세션 풀 유지로 cold start 제거

## Validation

**proxy_verification (2026-03-22)**: Python 프록시 MCP 서버 구현으로 E2E 검증 완료.

| 검증 항목 | 결과 |
|-----------|------|
| Python → Python stdio 프록시 | ✅ PASS |
| Python → Node.js 크로스 언어 프록시 | ✅ PASS |
| 다중 백엔드 네임스페이스 집약 | ✅ PASS |
| `__` 구분자 MCP SDK 호환성 | ✅ PASS |
| 에러 전파 (백엔드 부재 시 graceful degradation) | ✅ PASS |
| 상태 있는 백엔드 라운드트립 | ✅ PASS |

상세: `proxy_verification/docs/verification-report.md`
