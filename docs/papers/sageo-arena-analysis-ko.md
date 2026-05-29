# SAGEO Arena: Realistic Environment for Evaluating Search-Augmented GEO

## 논문명
SAGEO Arena: A Realistic Environment for Evaluating Search-Augmented Generative Engine Optimization

## 출처/링크
- arXiv: [2602.12187](https://arxiv.org/abs/2602.12187)
- 저자: Sunghwan Kim, Wooseok Jeong, Serin Kim, Sangam Lee, Dongha Lee
- 날짜: 2026-02-12

## 한 줄 요약
170K 웹 문서 기반 벤치마크에서 기존 GEO 전략이 retrieval/reranking을 오히려 악화시키며, 구조적 메타데이터 최적화만이 효과적임을 발견.

## 해결하려는 문제
기존 GEO 연구가 LLM 생성 단계만 평가하고, retrieval/reranking 단계에서의 영향을 무시하는 문제.

## 핵심 아이디어
RAG 파이프라인의 각 단계(Retrieval → Reranking → Generation)를 분리하여 GEO 전략의 영향을 측정.

## 방법론
- 170,000개 웹 문서, 9개 도메인
- Body text vs Structural information (meta description, headings, schema markup) 분리 분석
- BM25 lexical retrieval 사용

## 주요 결과

| 파이프라인 단계 | Body Text 최적화 | Structural Info 최적화 |
|----------------|-------------------|----------------------|
| **Retrieval** | **평균 -9% (AutoGEO 최악 -36%, 범위 -1%~-36%) (악화)** | **+22% (개선)** |
| **Reranking** | **-16% (악화)** | **-17% (악화)** |
| **Generation** | -6% (미미) | +2% (미미) |

- AutoGEO 적용 시 retrieval **-36%** 하락 (최악)
- 5.8%의 target 문서가 rank 10→11로 밀려남 (reranking 실패로 generation 입력에서 완전 제외)

## 장점
- 기존에 포괄적 평가 환경이 없었다고 주장 (explicitly claims 'no evaluation environment currently supports comprehensive investigation')
- Body text vs 구조적 정보 분리 → 실용적 지침 제공
- 대규모 데이터셋(170K)으로 통계적 신뢰성 확보

## 한계
- **BM25 lexical retrieval만 테스트** — dense embedding retrieval에서의 효과는 다를 수 있음
- 웹 문서 대상 (짧은 tool description 미검증)
- GEO 전략의 효과가 retrieval 방식에 따라 크게 달라질 가능성

## 프로젝트 시사점
- **간접적 시사점 (단, BM25 lexical retrieval만 테스트됨, dense embedding retrieval에서의 효과는 미검증)**: 과도한 GEO 본문 최적화가 검색 성능을 악화시킬 수 있음
- **구조적 메타데이터에 해당하는 MCP 요소**: tool_name, server_id, input_schema가 "구조적 정보"에 해당하며, 이것들의 품질이 retrieval에 더 중요할 수 있음
- Slave의 실험 결과(P@1 -0.069)와 방향이 일치 — GEO 본문 최적화가 retrieval을 악화시킨 것

## 적용 포인트
- E4 실험 설계: 본문 GEO 최적화 대신 구조적 보강 접근 검토
- `build_tool_text()` 개선: 구조적 정보(tool_name, server context) 활용 강화
- GEO Score v2: body text 품질보다 구조적 완성도에 가중치 부여

## 관련 research 문서
- `../research/geo-for-mcp-descriptions.md`
- `../research/description-optimization-survey.md`
