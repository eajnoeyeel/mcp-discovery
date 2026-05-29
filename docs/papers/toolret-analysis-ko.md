# ToolRet: Retrieval Models Aren't Tool-Savvy

> 출처: arXiv:2503.01763 (2025-03-03), ACL 2025
> 저자: Zhengliang Shi, Yuhan Wang (Shandong Univ.), Lingyong Yan, Shuaiqiang Wang, Dawei Yin (Baidu), Pengjie Ren (Shandong), Zhaochun Ren (Leiden Univ.)
> 한 줄 요약: 범용 IR 모델은 도구 검색에서 심각하게 성능이 저하되며(최고 NDCG@10 33.83), 이는 쿼리-도구 간 낮은 term overlap과 conventional information-seeking에서 tool retrieval로의 task shift 때문임을 벤치마크로 입증.

---

## 해결하려는 문제

LLM 도구 사용(tool-use)에서 올바른 도구를 검색하는 것이 성능의 핵심이지만, 기존 IR(Information Retrieval) 모델들이 도구 검색에서 어떤 성능을 보이는지 체계적으로 평가한 연구가 없다. 특히 "문서 검색"과 "도구 검색"이 근본적으로 다른 과제인지를 규명하고자 함.

## 핵심 아이디어

- **낮은 term overlap과 task shift** (문서 작성자의 재해석: "Functional Relevance vs Topical Similarity"): 논문은 쿼리-도구 간 "lower term overlap"과 "task shift from conventional information-seeking tasks to tool retrieval"을 핵심 원인으로 제시. 도구 검색은 "주제가 비슷한 문서 찾기"가 아니라 "사용자 의도를 수행할 수 있는 기능을 가진 도구 찾기"이다
- 쿼리-도구 간 term overlap이 일반 IR 대비 현저히 낮아 더 깊은 의미 이해가 필요
- 범용 IR → 도구 검색으로의 "task shift"가 성능 저하의 주요 원인

## 방법론

### 벤치마크 구성

| 카테고리 | 도구 수 | 태스크 수 |
|----------|---------|-----------|
| Web APIs | 36,978 | 4,916 |
| Code Functions | 3,794 | 950 |
| Customized Apps | 2,443 | 1,749 |
| **합계** | **43,215** | **7,615** |

- 쿼리 평균 길이: 46.87 토큰
- 도구 문서 평균 길이: 174.56 토큰

### 학습 데이터

- **ToolRet-train**: 200K+ 인스턴스
- 소스: ToolACE, APIGen, ToolBench training sets
- 각 예시에 쿼리, 생성된 instruction, 타겟 도구, NV-embed-v1로 검색한 10개 negative 도구 포함
- Target-aware instruction 생성: GPT-4o 기반, 100개 인간 작성 seed instruction 참고

## 주요 결과

| 모델 | NDCG@10 | 비고 |
|------|---------|------|
| NV-Embed-v1 (범용 SOTA) | 33.83 | 범용 IR 벤치마크에서는 강력하나 도구 검색에서 저조 |

> **후속 결과 (ToolRet 논문 외)**: 아래는 Tool-DE 논문(arXiv:2510.22670)에서 ToolRet 벤치마크로 보고한 후속 결과이며, ToolRet 원논문의 결과가 아님.
>
> | 모델 | NDCG@10 | 비고 |
> |------|---------|------|
> | Qwen3-Embedding-8B | 46.21 | ToolRet 데이터로 학습 후 |
> | Tool-Embed-4B (Tool-DE) | 52.23 | Document Expansion 적용 |

### 핵심 발견

1. **범용 IR 모델의 심각한 성능 저하**: MTEB 벤치마크 상위 모델도 ToolRet에서 NDCG@10 < 40
2. **낮은 검색 품질 → 낮은 LLM 태스크 성공률**: retrieved tools 사용 시 agent 성능이 현저히 저하됨을 확인 (Figure 1)
3. **Term Overlap 부족**: 쿼리 "최근 뉴스 요약해줘" → 도구명 "news_summarizer"로 직접 연결되지 않음 (기능적 매핑 필요)
4. **학습 데이터로 개선 가능**: ToolRet-train(200K)으로 학습 시 상당한 성능 향상

## 장점

- 도구 검색과 범용 IR의 근본적 차이를 최초로 체계적으로 입증
- 이질적(heterogeneous) 도구 유형(Web API, Code Function, Custom App)을 모두 포함
- 7.6K 태스크, 43K 도구라는 대규모 벤치마크 제공
- 200K+ 학습 데이터 공개

## 한계

- 도구 문서 품질 자체에 대한 분석은 부족 (어떤 설명 특성이 검색 성능에 기여하는지 미분석)
- 리랭킹 단계 평가 미포함
- MCP 프로토콜 특화 평가 없음

## 프로젝트 시사점

1. **범용 임베딩 모델의 한계 인식**: OpenAI text-embedding-3-small/large를 MCP 도구 검색에 직접 사용하면 최적이 아닐 수 있음 → E2 임베딩 모델 실험에서 도구 검색 특화 성능 평가 필요
2. **Functional Relevance 관점**: 인덱싱 텍스트 구성 시 도구의 "기능적 능력"을 강조하는 것이 단순 주제 설명보다 중요
3. **학습 데이터 활용 가능성**: ToolRet-train 200K 데이터를 fine-tuning 자원으로 활용 가능 (Phase 10+ 고려)
4. **도구 검색의 본질적 난이도**: ToolRet의 NDCG@10 < 34 결과는 도구 검색이 본질적으로 어려운 과제임을 확인 (단, NDCG@10과 P@1은 메트릭/풀 크기가 다르므로 직접 비교 부적절)

## 적용 포인트

- **E2 임베딩 실험**: 범용 모델 vs 도구 특화 모델 비교의 이론적 근거
- **인덱싱 텍스트 구성**: "기능적 관련성" 관점에서 build_tool_text() 최적화
- **벤치마크 참고**: 7.6K 태스크 구성 방법론을 GT 확장 시 참고
- **Reranker 필요성**: 1차 검색의 한계가 명확하므로 2-Stage 파이프라인 타당성 강화

## 관련 research 문서

- [Tool Selection & Retrieval 조사](../research/tool-selection-retrieval.md)
- [Description Quality Scoring 조사](../research/description-quality-scoring.md)
