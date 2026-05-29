# Multi-Field Tool Retrieval (MFTR)

> 출처: arXiv:2602.05366 (2026-02-05)
> 저자: Yichen Tang, Weihang Su, Yiqun Liu, Qingyao Ai (Tsinghua University, DCST)
> 한 줄 요약: 도구 문서를 Description/Parameters/Response/Examples 4개 필드로 분해하여 독립 매칭 후 적응적 가중치로 결합하면, runner-up 대비 +28.6% (Mixed 데이터셋), Full-Doc 대비 최대 +94%까지 NDCG@10이 향상되며 필드별 중요도가 쿼리 유형에 따라 크게 달라짐을 입증.

---

## 해결하려는 문제

도구 검색에서 기존 접근은 도구 문서를 하나의 텍스트로 취급하여 검색한다. 그러나 도구 문서는 (1) 불완전하고 구조적으로 비일관적이며, (2) 사용자 쿼리와 세밀도(granularity) 불일치가 있고, (3) 기능성/입력 제약/출력 형식 등 다차원적 유용성을 가진다. 이 다중 측면을 단일 벡터로 압축하면 정보 손실이 발생한다.

## 핵심 아이디어

- 도구 문서를 4개 독립 필드로 표준화하고, 각 필드를 독립적으로 매칭한 뒤 적응적 가중치로 결합
- LLM 기반 문서 표준화 → 쿼리 재작성 → 필드별 독립 매칭 → 적응적 가중치 집계

## 방법론

### 4개 필드 정의

| 필드 | 설명 | 평균 단독 NDCG@10 |
|------|------|-------------------|
| **Description** | 도구 기능의 고수준 요약 | ~0.46 (최고, Figure 4 추정값) |
| **Parameters** | 입력 제약 (이름, 타입, 의미, 필수/선택) | ~0.28 (최저, Figure 4 추정값) |
| **Response** | 성공 실행 시 예상 출력 | ~0.34 (높은 분산, Figure 4 추정값) |
| **Examples** | 대표적 사용자 의도 | ~0.39 (Figure 4 추정값) |

### 적응적 가중치 (데이터셋별 변동)

| 데이터셋 | Description | Parameters | Response | Examples | 비고 |
|----------|-------------|------------|----------|----------|------|
| APIGen | 25% | 28% | 40% | 8% | Table 5 기반 |
| Mixed | 37% | 15% | 15% | 33% | Table 5 기반 |
| ToolBench | 48% | 12% | 6% | 34% | 출처 미확인 (논문 Table 5에 미포함) |
| Gorilla | 32% | 10% | 53% | 5% | 출처 미확인 (논문 Table 5에 미포함) |

### 3단계 프레임워크

1. **표준화**: gpt-4o-mini로 이질적 문서를 4개 필드 통일 스키마로 변환
2. **쿼리 재작성**: BM25 기반 pseudo-relevance feedback으로 쿼리를 필드 스키마에 정렬
3. **적응적 가중치**: 필드별 독립 매칭 점수를 학습된 가중치로 선형 결합 + sigmoid 기반 필수 파라미터 패널티

## 주요 결과

### MiniLM-L6 기반

| 데이터셋 | NDCG@10 | Recall@10 | vs Full-Doc | vs Runner-up |
|----------|---------|-----------|-------------|--------------|
| ToolBench | 0.5412 | 0.6256 | +94.0% | — |
| APIGen | 0.8516 | 0.9248 | +11.4% | — |
| APIBank | 0.7237 | 0.7863 | +6.2% | — |
| Gorilla | 0.3775 | 0.5860 | +14.2% | — |
| Toolink | — | — | — | — |
| Mixed | 0.5617 | 0.6449 | +28.6% (Full-Doc 대비 ~71.6%) | runner-up 대비 +28.6% |

> 참고: "+28.6%"는 Mixed 데이터셋에서 runner-up(차순위 baseline) 대비 개선율이다. Full-Doc 대비 실제 개선율은 ToolBench ~94.0% (0.5412/0.2790 - 1), Mixed ~71.6% 등으로 훨씬 크다. Toolink 데이터셋은 논문에서 평가되었으나 위 테이블에 구체적 수치 미확인.

### Ablation

| 조건 | ToolBench NDCG@10 |
|------|-------------------|
| Full-Doc (baseline) | 0.2790 |
| 가중치만 적용 | 0.3458 |
| 적응적 가중치 제외 | 0.5071 |
| **MFTR (full)** | **0.5412** |

## 장점

- "단일 필드가 아무리 좋아도 다중 필드 결합이 항상 우월"을 5개 개별 데이터셋 + 1개 Mixed = 6개 평가 설정에서 일관 입증
- 필드 중요도가 도메인/쿼리 유형에 따라 크게 달라짐을 정량적으로 제시
- 경량 검색기(MiniLM-L6)로도 SOTA 달성 → 실시간 검색에 실용적

## 한계

- Tool-DE, ToolRet과 직접 비교 미수행
- LLM 기반 표준화 비용 (gpt-4o-mini 호출 필요)
- 5개 데이터셋 중 MCP 특화 데이터셋 없음

## 프로젝트 시사점

1. **인덱싱 텍스트 구조**: 현재 `build_tool_text()` = "tool_name: description" 단일 필드인데, MFTR은 다중 필드 분해의 우월성을 입증. Description 단독 NDCG ~0.46 (Figure 4 추정값) vs MFTR 0.54 (ToolBench)
2. **Parameters 필드의 낮은 기여**: Parameters 단독 성능이 가장 낮음 (~0.28) → CallNavi의 "파라미터는 라우팅에 덜 중요" 발견과 일치
3. **Response/Examples 필드의 상황적 중요성**: APIGen에서 Response가 40%로 가장 높은 기여 → 도구의 "무엇을 반환하는가"가 특정 도메인에서 검색 핵심
4. **적응적 가중치 필요성**: 고정 가중치보다 쿼리/도메인별 동적 가중치가 우월 → E4/E7에서 GEO Score 차원별 가중치 동적 조정 고려

## 적용 포인트

- **인덱싱 개선**: `build_tool_text()`를 다중 필드 구조로 확장하는 방안 검토 (Phase 10+)
- **GEO Score 차원 매핑**: MFTR 4개 필드 ↔ GEO Score 6개 차원 대응 분석
- **Provider 피드백**: "어떤 필드를 개선하면 검색 성능이 오르는가" 데이터 기반 안내

## 관련 research 문서

- [Tool Selection & Retrieval 조사](../research/tool-selection-retrieval.md)
- [Description Quality Scoring 조사](../research/description-quality-scoring.md)
