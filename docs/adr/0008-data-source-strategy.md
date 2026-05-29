# ADR-0008: 데이터 소스 전략 — 큐레이션 + Synthetic

**Date**: 2026-03-24
**Status**: superseded by ADR-0011 (MCP-Zero 외부 데이터) and ADR-0012 (per-step GT 분해)
**Deciders**: 프로젝트 설계 단계

> 현재 전략은 ADR-0011 및 ADR-0012를 참조할 것.

## Context

실험용 Tool Pool(50개)과 Ground Truth 쿼리를 어떻게 확보할지 결정해야 한다.
Smithery 레지스트리에는 수백 개의 MCP 서버가 있지만, 설명 품질이 균일하지 않다.
Ground Truth는 실험 비교의 기준이므로 품질이 보장되어야 한다.
5주 프로젝트이므로 수동 큐레이션 범위도 현실적으로 제한된다.

## Decision

Tool Pool은 Smithery에서 수동 큐레이션한 50개로 구성하고, Ground Truth 쿼리는 Seed set(수동 작성) + Synthetic variants(LLM 생성 후 Human review)로 구성한다.

## Alternatives Considered

### Alternative: Smithery 전체 자동 크롤링
- **Pros**: 데이터 규모 대폭 확대, 자동화 가능
- **Cons**: 설명 품질 통제 불가, 실험 Pool 구성 불명확
- **Why not**: 품질 편차가 크면 실험 결과 해석이 어려워짐. Pool 통제가 실험 설계의 핵심

### Alternative: 완전 수동 큐레이션 (Ground Truth 포함)
- **Pros**: 최고 품질 보장
- **Cons**: 5주 내 충분한 수량 확보 불가
- **Why not**: Synthetic variants로 보완해 현실적인 수량 달성

## Consequences

### Positive
- Pool 50개로 실험 변수 통제 (도메인, 난이도 균형 잡기 가능)
- Seed GT는 신뢰할 수 있는 기준점
- Synthetic variants로 Query 다양성 확보 (동일 의도, 다른 표현)

### Negative
- 수동 큐레이션 시간 비용
- Synthetic variants는 LLM 편향 포함 가능 → Human review 필수

### Risks
- Pool 50개가 너무 작아 실험 결과 일반화 어려울 수 있음 → E5에서 Pool 규모 확대 실험으로 확인
- GT 품질이 낮으면 모든 실험 지표가 의미 없어짐 → Seed set은 절대 LLM 자동 생성 금지
