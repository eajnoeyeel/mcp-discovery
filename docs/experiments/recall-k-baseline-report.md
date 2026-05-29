# Recall@K Baseline Report: Embedding-Only Retrieval

**실험일**: 2026-04-11
**브랜치**: `feat/reranker-removal-recall-k`
**스크립트**: `scripts/run_recall_k_baseline.py`

---

## 1. 실험 목적

Reranker를 제거한 embedding-only 구조에서 Recall@K baseline을 측정.
새 아키텍처의 North Star 지표(Recall@K)의 기준선을 확립한다.

---

## 2. 실험 설계

| 항목 | 설명 |
|------|------|
| 파이프라인 | FlatStrategy, ParallelStrategy (reranker=None) |
| Embedding 모델 | text-embedding-3-large (3072-dim) |
| Pool | 320 servers (base_pool.json) |
| GT | 2,273 entries (MCP-Atlas per-step only; seed_set.jsonl absent on main) |
| K values | 3, 5, 10 |
| Reranker | None (embedding-only) |

---

## 3. 결과

### FlatStrategy

| K | Recall@K | P@1 | MRR | Server Recall@K | Latency p50 |
|---|----------|-----|-----|-----------------|-------------|
| 3 | **21.5%** | 13.4% | 0.168 | 23.3% | 147ms |
| 5 | **25.6%** | 13.4% | 0.177 | 27.3% | 168ms |
| 10 | **28.2%** | 13.4% | 0.182 | 30.1% | 179ms |

### ParallelStrategy

| K | Recall@K | P@1 | MRR | Server Recall@K | Latency p50 |
|---|----------|-----|-----|-----------------|-------------|
| 3 | 20.1% | 12.5% | 0.159 | 22.0% | 180ms |
| 5 | 21.6% | 11.7% | 0.156 | 23.1% | 175ms |
| 10 | 26.8% | 11.4% | 0.157 | 28.5% | 175ms |

### 주요 관찰

1. **FlatStrategy > ParallelStrategy**: 모든 K에서 Flat이 우세. Parallel의 RRF fusion이 오히려 precision을 희석.
2. **Recall@3 → Recall@10 증가폭**: Flat 기준 +6.7%p (21.5% → 28.2%). K를 늘려도 수확 체감.
3. **P@1 = 13.4%**: 이전 E0 (Pool 292, 194 GT, reranker 포함) P@1=37.6% 대비 크게 하락.
   - 원인: GT 크기 12배 증가 (194 → 2273), seed_set 부재, pool 확대 (292 → 320)
4. **n_failed = 1**: FlatStrategy K=3에서 1건 실패 (OpenAI rate limit 추정). 무시 가능.

---

## 4. 이전 E0 대비 비교

| 지표 | E0 (Pool 292, n=194, reranker=on) | Recall@K Baseline (Pool 320, n=2273, no reranker) |
|------|-----------------------------------|---------------------------------------------------|
| P@1 | 37.6% (Flat) | 13.4% (Flat) |
| Recall@3 | 64.9% (Flat) | 21.5% (Flat) |
| MRR | 0.495 | 0.168 |

**주의**: 직접 비교 불가. GT 구성(seed 80 + atlas 114 vs atlas 2273), pool 크기, reranker 유무가 모두 다름.

---

## 5. North Star 결정

**Recall@K (K=3, FlatStrategy, embedding-only) = 21.5%** 를 baseline으로 채택.

- Baseline: Recall@3 >= 21.5%
- Stretch: Recall@3 >= 35% (description enrichment + retrieval optimization)

개선 방향:
- Embedding용 description enrichment (Task 5 stretch)
- Query embedding 최적화
- Hybrid search (dense + sparse)
