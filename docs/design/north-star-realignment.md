# North Star Realignment

## 변경 이력

### 1차 변경 (2026-03-29)

- **변경 전**: Precision@1 >= 50% (Pool 50, mixed domain)
- **변경 후**: Precision@1 >= 30% baseline, 50% stretch (Pool 292, MCP-Zero+Atlas regime)
- **이유**: Pool 확대 (50 → 292), 외부 GT 도입 (MCP-Atlas)

### 2차 변경 (2026-04-11)

- **변경 전**: Precision@1 >= 30% baseline, 50% stretch
- **변경 후**: Recall@K >= 21.5% baseline, 35% stretch (K=3, Pool 320, embedding-only)
- **이유**: Reranker 제거, top-K 반환 + LLM 선택 구조로 전환.
  우리가 통제하는 것은 "후보 안에 정답을 포함시키는 것"이므로 Recall@K가 적절.
  LLM이 최종 tool 선택을 하므로, retrieval 품질은 Recall로 측정한다.

### 3차 변경 (2026-04-23)

- **변경 전**: live contract documented as embedding-only
- **변경 후**: live hosted search/bridge contract documented as FlatStrategy hybrid dense+sparse retrieval, no live reranker
- **이유**: hosted search와 bridge artifact가 동일한 hybrid-capable query-plane contract로 정렬되었고, 이전 문서는 historical dense baseline과 현재 live contract를 혼동하고 있었다.

## 현재 North Star

```
Recall@K >= 21.5% baseline, 35% stretch
  K = 3 (default, 사용자 지정 가능)
  Pool = 320 servers (MCP-Zero)
  GT = 2,273 entries (MCP-Atlas per-step)
  Historical baseline pipeline = FlatStrategy, embedding-only (no reranker)
  Current hosted pipeline = FlatStrategy, hybrid dense+sparse when sparse capability is present (still no live reranker)
  Embedding = text-embedding-3-large (3072-dim)
```

## 측정 근거

`scripts/run_recall_k_baseline.py` 실행 결과 (2026-04-11):

| Strategy | Recall@3 | Recall@5 | Recall@10 |
|----------|----------|----------|-----------|
| FlatStrategy | 21.5% | 25.6% | 28.2% |
| ParallelStrategy | 20.1% | 21.6% | 26.8% |

상세: `docs/experiments/recall-k-baseline-report.md`

## 왜 Recall@K인가

1. **우리의 역할**: 후보 top-K를 반환하여 LLM이 선택하게 함
2. **Precision@1은 부적절**: 최종 선택은 LLM이 함. 우리가 1등을 맞출 필요 없음
3. **Recall@K가 측정하는 것**: "정답이 K개 후보 안에 있는가?"
4. **K=3 선택 이유**: LLM context에 3개 tool description + input_schema를 넣는 것이 실용적 상한
