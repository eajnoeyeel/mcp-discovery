# ADR-0002: 2-Layer 추천 아키텍처 (서버 → Tool)

**Date**: 2026-03-24
**Status**: superseded by 2026-04-11 Recall@K / FlatStrategy pivot
**Deciders**: 프로젝트 설계 단계

## Context

LLM 쿼리에 맞는 Tool을 추천할 때, 검색 공간을 어떤 단위로 정의할지 결정해야 한다.
MCP 생태계에서 Tool은 반드시 특정 서버에 속하며, Tool 이름만으로는 서버 컨텍스트가 없어 충돌이 발생할 수 있다.
현재 Pool 규모 50개 기준으로 단일 레이어도 가능하지만, 확장 시 검색 공간 폭발 문제가 생긴다.

## Decision

서버 인덱스에서 후보 서버를 먼저 추출한 뒤, 해당 서버 내 Tool을 검색하는 2-Layer 구조를 채택한다. 단, 1-Layer 대비 실제 성능 우위는 E0 실험으로 검증한다.

> 2026-04-11 update: live retrieval no longer follows this ADR. Current authority is `docs/design/north-star-realignment.md`: FlatStrategy, embedding-only, no reranker, Recall@K optimization.

## Alternatives Considered

### Alternative A: MCP 서버 단위 추천
- **Pros**: 단순, Smithery와 동일 레벨
- **Cons**: LLM이 실제 호출하는 단위(Tool)와 불일치 — 서버를 추천해도 LLM이 어떤 Tool을 쓸지 여전히 모름
- **Why not**: 최종 사용자(LLM)가 필요한 것은 Tool 이름과 파라미터

### Alternative B: 개별 Tool 단위 직접 검색 (1-Layer)
- **Pros**: 구현 단순, 레이어 간 오류 전파 없음
- **Cons**: 서버 수가 많아지면 Tool 수가 수천 개로 증가 → 정밀도 저하
- **Why not**: E0 실험에서 열등하면 폐기 예정이지만, 현재는 2-Layer가 이론적으로 더 정확할 것으로 판단

## Consequences

### Positive
- Layer 1(서버)에서 검색 공간을 좁혀 Layer 2(Tool) 정밀도 향상
- 서버 단위 Analytics 분리가 자연스럽게 가능
- Provider 대시보드에서 "왜 내 서버가/툴이 선택 안 됐나" 분석 용이

### Negative
- Layer 1 실패(서버 미매칭)가 Layer 2에 전파 → Sequential 전략의 Hard Gate 문제
- 구현 복잡도 증가 (두 개의 인덱스 관리)

### Risks
- E0 실험 결과 1-Layer가 더 나으면 아키텍처 재검토 필요

## E0 Validation Result (2026-03-31)

실행 결과: Flat=0.356, Sequential=0.325, Parallel=0.376

- Sequential이 Flat 대비 +5%p 미충족 (오히려 -3.1%p) → Layer 1 hard gate 문제 확인
- Parallel은 Flat 대비 +2.0%p → 약한 개선. RRF 융합이 Layer 1 miss를 부분 보완
- 실험 세부 조건:
  - 임베딩: text-embedding-3-large (3072D, MCP-Zero precomputed vectors)
  - GT: 194개 covered entries (474개 총; base_pool.json GT-first 정렬)
  - Qdrant 필터: 활성 pool 서버로 검색 제한
