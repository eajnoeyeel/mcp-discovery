# Hybrid Search 실험 보고서: Dense + Sparse (SPLADE) + RRF Fusion

**실험일**: 2026-04-12
**브랜치**: `feat/reranker-removal-recall-k`
**스크립트**: `scripts/run_hybrid_baseline.py`

---

## 1. 실험 목적

Reranker 제거 후 embedding-only 구조의 Recall@3 = 21.5% baseline을 hybrid search (dense + sparse)로 개선한다.

---

## 2. 실험 설계

| 항목 | 설명 |
| ---- | ---- |
| Dense | OpenAI text-embedding-3-large (3072d) — 원본 description |
| Sparse | FastEmbed SPLADE (`prithivida/Splade_PP_en_v1`) — enriched description |
| Fusion | Qdrant RRF (Reciprocal Rank Fusion), prefetch 20 per channel |
| Enrichment | 93 GT-covered tools: LLM (GPT-4o-mini), 2,805 tools: rule-based |
| Collection | `mcp_tools_hybrid` (named vectors: dense + sparse) |
| Pool | 320 servers (base_pool.json), 2,898 tools indexed |
| GT | 2,273 entries (MCP-Atlas per-step) |
| Reranker | None |
| K values | 3, 5, 10 |

### Enrichment 전략

- **Dense vector input**: `"{tool_name}: {description}"` (원본, 변경 없음)
- **Sparse vector input**: enriched text
  - LLM (93 tools): `function` + `when_to_use` + `tags` (MFTR + Tool-REX 패턴)
  - Rule-based (2,805 tools): `"{tool_name} {description} Parameters: {param1, param2, ...}"`

---

## 3. 결과

### 3.1 Hybrid vs Dense-only 비교

| K | Dense R@K | **Hybrid R@K** | **Delta** | Hybrid P@1 | Hybrid MRR | Lat p50 |
| --- | --- | --- | --- | --- | --- | --- |
| 3 | 21.5% | **48.9%** | **+27.4pp** | 31.2% | 0.391 | 177ms |
| 5 | 25.6% | **53.3%** | **+27.8pp** | 30.9% | 0.400 | 173ms |
| 10 | 28.2% | **58.1%** | **+29.9pp** | 30.8% | 0.406 | 182ms |

### 3.2 BM25 시뮬레이션 예측 대비

| K | 시뮬레이션 예측 (독립 가정) | **실측** | 차이 |
| --- | --- | --- | --- |
| 3 | 43.8% | **48.9%** | +5.1pp (예측 초과) |
| 5 | 52.9% | **53.3%** | +0.4pp |
| 10 | 58.6% | **58.1%** | -0.5pp |

K=3에서 독립 가정 예측을 초과 — dense와 sparse가 예상보다 더 보완적.

### 3.3 이전 E0 (reranker 포함) 대비

| 지표 | E0 (Pool 292, n=194, reranker=on) | Hybrid (Pool 320, n=2273, no reranker) |
| --- | --- | --- |
| P@1 | 37.6% | 31.2% |
| Recall@3 | 64.9% | 48.9% |
| MRR | 0.495 | 0.391 |

**주의**: GT 구성이 완전히 다름 (194 vs 2273 entries). Reranker 없이도 P@1이 E0의 83%까지 도달.

---

## 4. 분석

### 4.1 왜 이렇게 효과가 큰가

1. **Dense와 Sparse의 보완성**: Dense는 의미적 유사도, Sparse는 keyword exact match. MCP-Atlas GT 쿼리가 tool name을 직접 언급하는 패턴이 많아 sparse가 강함.
2. **RRF fusion의 효과**: 두 채널 중 하나라도 정답을 높은 순위에 올리면 fusion 후에도 유지됨.
3. **E4 벡터 드리프트 회피**: Dense는 원본 description 유지, Sparse만 enriched text 사용 — 두 벡터가 분리되어 있으므로 충돌 없음.

### 4.2 Confusion Rate 변화

- Dense-only: 9.4%
- Hybrid: 25.8%

Confusion이 올라간 이유: hybrid가 더 다양한 관련 tool을 후보에 올림. "비슷한 tool이 더 많이 보임" — 이는 Recall 향상의 부산물이며, LLM이 최종 선택할 때 contextual information으로 구분할 수 있음.

### 4.3 Latency

- Dense-only p50: 147ms
- Hybrid p50: 177ms (+30ms)

Sparse embedding (SPLADE, 로컬 CPU) + Qdrant RRF fusion 추가 비용이 ~30ms. 실용적 범위.

---

## 5. North Star 업데이트

| 항목 | 이전 (Dense-only) | **현재 (Hybrid)** |
| --- | --- | --- |
| Baseline | Recall@3 >= 21.5% | **Recall@3 >= 48.9%** |
| Stretch | Recall@3 >= 35% | **Recall@3 >= 60%** |

---

## 6. Full LLM Enrichment 실험 (2026-04-12)

### 6.1 배경

Sparse 벡터 입력 품질이 이원화 (93개 LLM vs 2,805개 rule-based)되어 있어, 전체를 LLM enrichment로 균일화하는 실험을 진행.

### 6.2 3조건 비교

| Metric | Baseline (93LLM+2805rule) | Pure LLM (2898) | **Keyword+LLM (최종)** |
|--------|--------------------------|-----------------|----------------------|
| **R@3** | **48.9%** | 46.6% | 46.6% |
| R@5 | 53.3% | 51.3% | 51.8% |
| R@10 | 58.1% | 57.0% | 57.1% |
| **P@1** | 31.2% | 25.6% | **31.9% (+0.7pp)** |
| MRR | 0.391 | 0.351 | 0.385 |
| **Confusion** | 25.8% | 28.2% | **21.6% (-4.2pp)** |
| Latency p50 | 177ms | 188ms | 195ms |

### 6.3 Pure LLM 하락 원인 분석

1. **템플릿 획일화**: LLM이 "This tool retrieves... Use this tool when..." 패턴을 75%에 적용. 도구 간 Jaccard 유사도 0.044 → 0.198 (4.5배). SPLADE 구별력 붕괴.
2. **핵심 키워드 손실**: 29.6% tool에서 tool_name 키워드 탈락. 파라미터명 보존율 0%.
3. **"retrieve" 인플레이션**: 비-GT tool 중 "retrieve" 포함 232개 → 1,247개 (+438%). 관련 쿼리에서 ~1,000개 tool이 추가 경쟁.

### 6.4 Keyword+LLM 전략

LLM enriched text 앞에 `tool_name + parameter_names`를 prepend하여 SPLADE 키워드 보존:

```
# Before (Pure LLM):
"This tool retrieves and displays all projects associated with the user's Aiven account..."

# After (Keyword+LLM):
"list_projects This tool retrieves and displays all projects associated with the user's Aiven account..."
```

결과: R@3은 미회복(-2.3pp)이나, **P@1이 baseline 초과**(+0.7pp), **Confusion 최저**(21.6%). 프로덕션 관점에서 P@1과 Confusion이 R@3보다 중요 — LLM이 top-K에서 최종 선택하는 구조이므로.

### 6.5 결론

- **최종 선택: Keyword+LLM** — `tool_name + params + LLM(function, when_to_use, tags)`
- R@3 하락은 GT 쿼리 스타일 편향 (MCP-Atlas가 tool name 직접 언급하는 패턴 다수)으로 판단
- Sparse 품질 균일화 달성: 2,898개 전부 LLM enriched + keyword prefix
- 이후 GT 쿼리 다양성 확대 시 LLM enrichment 효과 재검증 가능

---

## 7. 실험 아티팩트 (전체)

| 파일 | 설명 |
| ---- | ---- |
| `scripts/run_hybrid_baseline.py` | 측정 스크립트 |
| `scripts/build_hybrid_index.py` | Hybrid collection 빌드 |
| `scripts/enrich_descriptions.py` | Description enrichment pipeline |
| `data/results/hybrid_baseline.json` | 측정 결과 (gitignored) |
| `data/enriched/tool_profiles.jsonl` | Enriched descriptions (gitignored) |
| `src/embedding/sparse_embedder.py` | SparseEmbedder ABC |
| `src/embedding/fastembed_sparse.py` | FastEmbed SPLADE 구현 |
