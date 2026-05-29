# JSPLIT: Taxonomy-Gated Prompt Filtering for Tool Selection

> 출처: arxiv:2510.14537
> 저자: Emanuele Antonioni 외 6명 (7인)
> 한 줄 요약: 도구를 taxonomy로 분류하고 쿼리에 관련된 도구만 LLM 프롬프트에 포함하여 prompt bloating을 해결하는 프레임워크.

---

## 해결하려는 문제

전체 도구 명세를 LLM 프롬프트에 포함하면 토큰 비용이 급증하고 무관한 도구 선택이 증가하는 **prompt bloating** 문제를 해결하려 한다. 도구 수가 수백~수천 개로 늘어날 때(논문에서는 ~2,000 MCP 서버 규모) 프롬프트 크기를 효과적으로 줄이면서 도구 선택 정확도를 유지하는 방법이 필요하다.

## 핵심 아이디어

- 도구를 사전 정의된 taxonomy(카테고리 체계)로 분류한다.
- 쿼리가 들어오면 먼저 LLM 기반 분류 프롬프트가 해당 쿼리의 카테고리를 판별한다(전용 intent classifier가 아닌 LLM 프롬프트 방식).
- 판별된 카테고리에 해당하는 **관련 카테고리의 도구만 LLM 프롬프트에 포함**하여 프롬프트 크기를 대폭 축소한다 (벡터 검색이 아닌 프롬프트 필터링 방식).
- 이를 통해 **"two orders of magnitude"(약 100배) 수준의 토큰 감소**를 달성하면서 도구 선택 정확도를 유지하거나 향상시킨다.

## 방법론

- **데이터셋**: ~2,000개의 MCP 서버, ~200개의 쿼리로 구성된 벤치마크.
- **Taxonomy 구축**: 도구를 카테고리별로 사전 분류하여 도구 목록을 그룹화.
- **LLM 기반 카테고리 판별**: 쿼리가 입력되면 LLM 프롬프트를 통해 해당 쿼리에 적합한 카테고리를 판별.
- **프롬프트 필터링**: 판별된 카테고리에 속하는 도구만 LLM 프롬프트에 포함하여 도구 선택을 수행. 벡터 검색이나 서브 인덱스 검색이 아닌, **프롬프트에 포함되는 도구 명세를 필터링**하는 방식.
- 전체 도구를 프롬프트에 포함하는 baseline 대비 토큰 사용량과 정확도를 비교 평가.

## 주요 결과

- **"Two orders of magnitude" 수준의 토큰 감소**를 달성 — 논문의 핵심 성과. 전체 도구를 프롬프트에 포함하는 baseline 대비 약 100배 토큰 절감.
- 토큰 비용 절감과 도구 선택 정확도를 핵심 metric으로 보고하며, taxonomy-gated 프롬프트 필터링의 효과를 실증.
- 카테고리 분류의 정확성이 전체 파이프라인 성능에 직접적 영향을 미침을 확인 — 분류 오류 시 해당 카테고리의 도구가 프롬프트에서 누락되어 전체 파이프라인 실패.
- 참고: 논문에서 **latency는 직접 측정/보고하지 않음**. 토큰 감소가 간접적으로 latency 개선을 암시하나 실증 데이터는 없음.

## 장점

- 프롬프트에 포함되는 도구 범위를 대폭 축소하여 토큰 비용을 약 100배 절감
- 대규모 도구 풀(~2,000 서버)에서 scalability 확보에 유리
- 도구 선택 정확도를 유지하면서 비용 효율성을 크게 향상

## 한계

- 카테고리 분류(intent classification) 오류 시 전체 파이프라인이 실패할 수 있음
- 도메인 간 경계가 모호한 도구의 분류가 어려움
- Taxonomy 설계 자체가 수동 작업이 필요할 수 있음

## 프로젝트 시사점

MCP Discovery Platform의 Strategy C (Taxonomy-Gated) 전략의 **영감의 원천**이다. 단, JSPLIT은 **벡터 검색이 아닌 LLM 프롬프트 필터링** 방식이며, 프로젝트 Strategy C는 이를 **벡터 인덱스 기반으로 adaptation**한 것이다. 현재 아키텍처(architecture.md)에서 3가지 검색 전략(A: Sequential, B: Parallel, C: Taxonomy-Gated)을 비교하도록 설계되어 있으며, Strategy C가 JSPLIT의 taxonomy-gated 개념에서 착안하되 구현 메커니즘은 다르다.

JSPLIT의 토큰 비용 절감 관점은 우리 아키텍처의 효율성 설계에 참고가 된다. 다만 Latency p50/p95/p99(Metric #6)는 JSPLIT 논문이 직접 측정하거나 보고하는 지표가 아니며, 프로젝트 자체 설계이다.

## 적용 포인트

- **Strategy C (Taxonomy-Gated)**: JSPLIT의 taxonomy-gated 프롬프트 필터링 개념을 벡터 인덱스 기반으로 adaptation하여 MCP 서버/도구 카테고리에 적용. CTO 확인 후 구현 예정
- **토큰 비용 절감**: JSPLIT의 taxonomy-gated 접근이 프롬프트 크기를 약 100배 줄이는 성과 참고. 우리 파이프라인에서도 카테고리 필터링으로 불필요한 도구 노출을 줄이는 방향 적용
- **LLM 기반 카테고리 분류**: 쿼리 카테고리 판별 시 JSPLIT의 LLM 프롬프트 기반 분류 방식 참고 (전용 intent classifier가 아닌 LLM 분류)
- **검색 전략 비교 실험**: Strategy A/B/C의 precision 비교 분석 (latency는 논문에서 직접 측정된 지표가 아님에 유의)

## 관련 research 문서

- [evaluation-metrics.md](../research/evaluation-metrics.md) — 토큰 비용 절감 및 검색 전략 비교 참고
