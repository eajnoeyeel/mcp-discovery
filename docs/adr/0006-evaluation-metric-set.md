# ADR-0006: 평가 지표 세트 — Option B

**Date**: 2026-03-24
**Status**: partially superseded by 2026-04-11 Recall@K North Star pivot
**Deciders**: 프로젝트 설계 단계

## Context

MCP Tool 추천 파이프라인의 품질을 측정할 지표 세트를 선택해야 한다.
지표가 너무 적으면 파이프라인의 실제 동작을 충분히 설명하지 못하고, 너무 많으면 5주 프로젝트에서 구현 비용이 과도해진다.
CTO에게 "모니터링 → 개선 루프" 스토리를 수치로 증명해야 한다.

## Decision

Precision@1, Recall@K, Confusion Rate, ECE(Expected Calibration Error)를 핵심 지표로 채택한다 (Option B). Latency는 부가 지표로 기록한다.

> 2026-04-11 update: Recall@K is now the North Star for the live retrieval path. Precision@1 remains experiment/analysis context, not the primary live retrieval target.

## Alternatives Considered

### Alternative A: 핵심만 (Precision@1, Recall@K, Latency)
- **Pros**: 구현 최소, TREC 표준 + RAG-MCP 논문 동일 사용
- **Cons**: Confidence 분기(ADR-0005)의 품질을 측정하는 지표 없음
- **Why not**: ECE 없이는 Confidence 분기 효과 검증 불가

### Alternative C: 풀 세트 (B + MRR, Cost/Correct, DQS 상관관계)
- **Pros**: 가장 포괄적, RAGAS(EACL 2024) 기준
- **Cons**: 5주 프로젝트에서 구현 비용 대비 추가 설득력 낮음
- **Why not**: MRR은 Top-K 전체 순위 품질 측정으로 현 scope 초과

## Consequences

### Positive
- Precision@1: North Star 지표(≥50% 목표) — CTO 핵심 관심사
- Recall@K: Top-K에 정답이 포함되는지 — 파이프라인 상한선 확인
- Confusion Rate: 유사 Tool 간 혼동 빈도 — "왜 틀렸나" 분석
- ECE: Confidence 점수 신뢰도 — gap 기반 분기(ADR-0005) 품질 검증

### Negative
- ECE 계산에 Ground Truth Confidence label 추가 필요
- Option A보다 구현 공수 증가

### Risks
- ECE calibration 데이터가 부족하면 신뢰할 수 없는 수치 → Ground Truth 설계 시 Confidence label 포함 필수

---

## 통계적 검증 체계 추가 (2026-03-26, CTO 멘토링 반영)

**Status**: accepted (ADR-0006 보완)

### Context

CTO 피드백: 단순 Precision@1 수치 비교가 아니라 통계적 유의성과 변동성까지 증명해야 논문 수준 설득력을 갖춘다.

### Decision

메트릭 측정과 병행하여 아래 통계 검증 체계를 채택한다.

| 검증 방법 | 적용 시점 | 이유 |
|-----------|-----------|------|
| **X̄-R 관리도** | E1 진행 전 (E0 후) | Precision@1 측정 자체의 반복 안정성 사전 확인. 불안정 시 실험 결과 신뢰 불가 |
| **McNemar's test** | E4 (테제 검증) 필수 | paired binary outcome (정답/오답)에 적합. t-test나 proportion test보다 적절 |
| **Spearman 상관** | E4, E7 | GEO Score ↔ selection_rate 상관. 순위 기반이므로 Pearson보다 robust (비선형 허용) |
| **OLS Regression** | E4 보조 | quality 6차원 중 어느 요소가 selection_rate를 설명하는지 분해 |
| **Mann-Whitney U** | E0, E2, E3 (권장) | 비모수 분포에서 두 조건 비교. 정규성 가정 불필요 |

### Implementation
- `src/analytics/statistical.py`: `compute_control_chart`, `compute_mcnemar`, `compute_spearman` 구현
- Current North Star context: `docs/design/north-star-realignment.md`
