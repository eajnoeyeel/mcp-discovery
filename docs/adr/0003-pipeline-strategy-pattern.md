# ADR-0003: Pipeline Strategy Pattern 적용

**Date**: 2026-03-24
**Status**: accepted
**Deciders**: 프로젝트 설계 단계

## Context

검색 파이프라인을 구현할 때 어떤 전략(Sequential / Parallel / Taxonomy-gated)이 최적인지 사전에 알 수 없다.
각 전략은 정확도, 복잡도, 비용에서 서로 다른 트레이드오프를 가지며, 실험 없이는 우열을 판단할 수 없다.
E1 실험에서 동일한 조건으로 비교하려면 전략들이 동일한 인터페이스를 구현해야 한다.

## Decision

`PipelineStrategy` ABC를 정의하고 Sequential(A), Parallel(B), Taxonomy-gated(C) 세 전략을 모두 구현한다. 어떤 전략이 최적인지는 E1 실험 결과로 결정하며, 결정 전까지는 어떤 전략도 "기본값"으로 확정하지 않는다.

## Alternatives Considered

### Alternative: 단일 전략으로 구현 후 필요 시 교체
- **Pros**: 초기 구현 속도 빠름
- **Cons**: 전략 교체 시 코드 대규모 수정 필요, 비교 실험 불가
- **Why not**: E1 비교 실험이 프로젝트 핵심 요구사항이므로 처음부터 Strategy Pattern 필수

### Alternative: Config 플래그로 분기 (if/else)
- **Pros**: 간단한 구현
- **Cons**: 전략 추가 시 기존 코드 수정 필요 (OCP 위반), 테스트 격리 어려움
- **Why not**: Strategy Pattern이 동일한 목적을 더 명확하게 달성

## Consequences

### Positive
- E1 실험에서 동일한 평가 하네스로 세 전략을 공정하게 비교 가능
- 새로운 전략 추가 시 기존 코드 무수정 (OCP 준수)
- 각 전략 독립 테스트 가능

### Negative
- 세 전략을 모두 구현해야 하므로 초기 개발 비용 증가
- `StrategyRegistry` 등 추가 인프라 코드 필요

### Risks
- E1 결과가 나오기 전까지 "어떤 전략을 써야 하나" 질문에 답하기 어려움 → 실험 중임을 명시
