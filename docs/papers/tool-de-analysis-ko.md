# Tool-DE: Tools are Under-Documented — Simple Document Expansion Boosts Tool Retrieval

> 출처: arXiv:2510.22670 (2025-10-26)
> 저자: Xuan Lu, Haohang Huang, Rui Meng, Yaohui Jin, Wenjun Zeng, Xiaoyu Shen (Shanghai Jiao Tong University, Eastern Institute of Technology, Ningbo)
> 한 줄 요약: 도구 문서를 5개 구조화 필드로 LLM 기반 확장(Document Expansion)하면 NDCG@10이 +10pp 이상 향상되며, example_usage 필드는 오히려 성능을 저하시킨다는 ablation 결과를 제시한 연구.

---

## 해결하려는 문제

LLM 도구 검색(tool retrieval)에서 사용자 쿼리와 도구 문서 사이의 의미적 간극(semantic gap)이 성능 병목이다. 도구 문서는 불완전하고 이질적(heterogeneous)이며, 사용자 쿼리는 모호하거나 비공식적인 표현을 사용한다. 이 "낮은 의미 중첩(lower semantic overlap)"이 검색 모델에 과도한 부담을 지운다.

## 핵심 아이디어

- 도구 문서를 5개 구조화 필드로 LLM 기반 확장(Document Expansion)하여 의미 정보를 보강
- 확장된 문서로 전용 임베딩 모델(Tool-Embed)과 리랭커(Tool-Rank)를 학습
- 대규모 학습 데이터 자동 생성 파이프라인 제공 (50K 임베딩 + 200K 리랭킹)

## 방법론

### 5개 구조화 필드 (Document Expansion)

| 필드 | 설명 | 검색 기여도 |
|------|------|------------|
| `function_description` | 핵심 기능 요약 | **높음** (일관적 양의 기여) |
| `tags` | 3-5개 핵심 키워드 | **높음** (일관적 양의 기여) |
| `when_to_use` | 현실적 사용 시나리오 | 중간 |
| `limitations` | 입출력 제약조건 | 중간 |
| `example_usage` | API 호출 예제 | **부정적** (제거 시 성능 향상) |

### Ablation 결과 (핵심 발견)

- **example_usage 제거 시 NDCG@10이 오히려 향상**: "example_usage provides the smallest (often negative) gains"
- **최종 채택 필드**: function_description, tags, when_to_use, limitations (4개)
- function_description과 tags가 sparse(BM25)와 dense(GritLM) 검색기 모두에서 일관적으로 양의 기여

### 학습 데이터

- **Tool-Embed-Train**: ~50,000개 (임베딩 학습용, InfoNCE loss)
- **Tool-Rank-Train**: ~200,000개 (리랭킹 학습용, cross-entropy)
- 기반 모델: Qwen3-Embedding 시리즈, Qwen3-Reranker-4B
- 하드웨어: NVIDIA A100 80GB x 2

### 검증

- 100개 확장 프로파일 대상 인간 검증 → **100% annotation agreement**

## 주요 결과

| 모델 | 벤치마크 | NDCG@10 | Recall@10 | Completeness@10 |
|------|----------|---------|-----------|-----------------|
| NV-Embed-v1 | ToolRet 벤치마크 기준 | 33.83 | — | — |
| Qwen3-Embedding-8B | ToolRet 벤치마크 기준 | 41.61 | — | — |
| Qwen3-Embedding-8B | Tool-DE 벤치마크 기준 | 46.23 (≈46.21*) | 57.52 | 47.52 |
| **Tool-Embed-4B** | **Tool-DE 벤치마크 기준** | **52.23** | **63.13** | **51.61** |
| + Tool-Rank-4B | **Tool-DE 벤치마크 기준** | **56.44** | **67.81** | **56.60** |

> *주: Qwen3-Embedding-8B의 Tool-DE 벤치마크 수치는 논문에서 46.23으로 보고됨. 이전 기재된 46.21은 반올림 차이로 추정.

- Tool-Embed-4B는 기존 SOTA 대비 NDCG@10 +6.02pp 향상
- Tool-Rank-4B 추가 시 +4.21pp 추가 향상 (총 +10.23pp)

### 평가된 검색 모델

- Sparse: BM25s
- Dense: GritLM-7B, NV-Embed-v1, gte-Qwen2-1.5B-instruct, e5-mistral-7b-instruct, Qwen3-Embedding (0.6B/4B/8B)
- Reranker: jina-reranker-m0, bge-reranker-v2-gemma, Qwen3-Reranker-4B

## 장점

- 도구 문서 확장을 체계적으로 분석한 최초의 대규모 연구 (35개 데이터셋, 43K 도구)
- 필드별 ablation으로 "무엇이 도움이 되고 무엇이 해로운지" 정량적 근거 제공
- 학습 데이터 자동 생성 파이프라인으로 확장성 확보
- 코드 공개: https://github.com/EIT-NLP/Tool-DE

## 한계

- example_usage가 왜 해로운지에 대한 심층 분석 부족 (추정: API 호출 구문이 의미 공간에 노이즈로 작용)
- MCP 프로토콜 특화 평가 없음 (범용 도구 검색 벤치마크 사용)
- 4B/8B 모델 기반으로, 실시간 검색 시 추론 비용 고려 필요

## 프로젝트 시사점

MCP Discovery Platform의 도구 인덱싱 파이프라인에 직접 적용 가능한 핵심 연구.

1. **example_usage 제외 근거**: 인덱싱 시 `build_tool_text()`에 example_usage를 포함하지 않아야 한다는 실증적 근거. API 호출 예제는 임베딩 품질을 오히려 저하시킴
2. **DQS/GEO Score 차원 매핑** *(프로젝트 팀의 매핑 해석 — 논문이 직접 제시한 대응이 아님)*: Tool-DE의 4개 유효 필드(function_description, tags, when_to_use, limitations)가 프로젝트의 GEO Score 6개 차원과 상당 부분 대응
   - function_description ↔ clarity_score
   - when_to_use ↔ disambiguation_score
   - limitations ↔ boundary_score
   - tags ↔ precision_score (기술 용어/키워드)
3. **Description Enrichment 전략**: Provider에게 설명 개선 피드백 시 "function_description + tags + when_to_use + limitations" 4개 필드를 중심으로 가이드 제공

## 적용 포인트

- **인덱싱 파이프라인**: `build_tool_text()` 구성 시 Tool-DE 4개 필드 구조 참고 (example_usage 제외)
- **GEO Score 차원 가중치**: function_description/tags의 높은 기여를 clarity_score/precision_score 가중치 설계에 반영
- **Provider Analytics**: 도구 설명 개선 피드백 시 4개 핵심 필드 우선 안내
- **E4 실험 설계**: Description Quality → Selection Rate 인과 관계 검증 시 Tool-DE의 ablation 방법론 참고

## 관련 research 문서

- [Description Quality Scoring 조사](../research/description-quality-scoring.md)
- [Tool Selection & Retrieval 조사](../research/tool-selection-retrieval.md)
