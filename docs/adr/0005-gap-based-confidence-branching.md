# ADR-0005: Gap 기반 Confidence 분기 방식

**Date**: 2026-03-24
**Status**: accepted
**Deciders**: 프로젝트 설계 단계

## Context

검색 단계가 여러 Tool 후보를 점수화한 뒤, LLM에 몇 개를 반환할지 결정해야 한다.
항상 Top-1만 반환하면 확신이 낮을 때 틀린 Tool을 단정짓는 위험이 있다.
항상 Top-3를 반환하면 LLM이 매번 추가 판단을 해야 해 불필요한 비용과 지연이 발생한다.
분기 임계값(0.15)은 데이터 없이 설정되는 초기값이다.

## Decision

`rank-1 score - rank-2 score > 0.15`이면 Top-1 반환, 이하면 Top-3 + disambiguation hint를 반환하는 gap 기반 동적 분기를 사용한다. 임계값 0.15는 현재 FlatStrategy/embedding score 경로에서도 유지한다.

## Alternatives Considered

### Alternative A: 항상 Top-1 반환
- **Pros**: 구현 단순, LLM 컨텍스트 최소
- **Cons**: 확신이 낮을 때 틀린 Tool을 확정 반환 → UX 최악
- **Why not**: Precision@1이 낮을 경우 사용자 경험 복구 불가

### Alternative B: 항상 Top-3 반환
- **Pros**: 구현 단순, 틀릴 확률 낮음
- **Cons**: 매번 LLM이 3개 중 선택해야 함 → 불필요한 추론 비용 + 지연
- **Why not**: 고확신 케이스에서도 LLM 부하 발생, 비용 비효율

## Consequences

### Positive
- 고확신(gap > 0.15) → 즉각 Top-1 반환으로 레이턴시 최소화
- 저확신(gap ≤ 0.15) → Top-3 + hint로 LLM이 context를 보고 최종 판단
- Precision@1과 UX 사이 균형점

### Negative
- 임계값이 초기값(0.15)이므로 실제 성능과 괴리 가능성
- 분기 로직 자체가 추가 코드 복잡도

### Risks
- 0.15가 너무 낮으면 대부분이 Top-3로 분기 → 비용 증가
- 0.15가 너무 높으면 저확신 케이스도 Top-1 강제 → Precision 저하
- **완화**: Recall@K baseline 및 query-log evidence로 임계값 calibration
