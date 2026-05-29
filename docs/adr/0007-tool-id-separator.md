# ADR-0007: Tool ID 구분자 — `::`

**Date**: 2026-03-24
**Status**: accepted
**Deciders**: 프로젝트 설계 단계

## Context

Tool ID는 `{server_id}{separator}{tool_name}` 형식으로 구성된다. Smithery의 qualifiedName은 `@anthropic/github` 형태로 `/`를 포함하고, Tool name은 `search_issues` 형태로 `_`를 포함한다. 구분자가 server_id나 tool_name과 충돌하면 파싱이 불가능해진다.

## Decision

Tool ID 구분자로 `::`를 사용한다. 형식: `server_id::tool_name` (예: `@anthropic/github::search_issues`).

## Alternatives Considered

### Alternative: `/`
- **Pros**: 직관적, URL 유사 형식
- **Cons**: Smithery qualifiedName 자체에 `/`가 포함됨 (`@anthropic/github`) → `"@anthropic/github/search_issues"`에서 서버 ID 끝이 어디인지 파싱 불가
- **Why not**: 파싱 불가능 — 즉시 탈락

### Alternative: `:` (단일)
- **Pros**: 짧고 간결
- **Cons**: URI 스키마(`http:`, `ftp:`)에서 혼동 가능, 일부 tool_name에 `:` 포함 가능성
- **Why not**: 안전하지 않음

### Alternative: `__` (더블 언더스코어)
- **Pros**: 파이썬 식별자 친화적
- **Cons**: tool_name에 `__`가 포함될 가능성 (Python dunder 패턴)
- **Why not**: MCP Tool name이 Python 규칙을 따를 경우 충돌 위험

## Consequences

### Positive
- Smithery qualifiedName(`/` 포함)과 tool_name(`_` 포함) 어느 쪽과도 충돌 없음
- 파싱이 `tool_id.split("::", 1)`로 단순하게 처리됨

### Negative
- 코드베이스 전체에서 `TOOL_ID_SEPARATOR = "::"` 상수를 일관되게 사용해야 함
- 문자열 표현이 다소 생소함

### Risks
- 미래 MCP 서버가 `::` 포함 이름을 사용하면 재검토 필요 (현재 MCP 사양에서는 불가)
