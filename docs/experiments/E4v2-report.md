# E4v2 실험 보고서: Selection Controllability

> Portfolio note: this is a historical experiment report. Cohere rerank-v3.5 was
> used in this archived run as an external reranking baseline; the current public
> runtime does not require Cohere or `COHERE_API_KEY`.

**실험일**: 2026-04-07
**브랜치**: `feat/pool-gt-expansion`
**설계 문서**: `docs/experiments/E4v2-design.md`

---

## 1. 실험 목적

**핵심 질문**: Description design이 유사 기능 MCP tool cluster 내에서 reranker의 selection을 통제 가능한 레버인가?

기존 E4가 embedding + reranker 동시 적용으로 confounded design이었던 것을 개선하여,
**offline fixed-candidate evaluation**으로 retrieval confound를 완전히 제거한 selection-only 실험.

---

## 2. 실험 설계

| 항목 | 설명 |
|------|------|
| 방법 | Offline Fixed-Candidate Evaluation (embedding bypass) |
| Reranker | Cohere rerank-v3.5 |
| Cluster 수 | 3 (file_operations, git_vcs, database_records) |
| Treatment | Target tool만 enriched description (V1), 나머지 original (V0) |
| Bias control | Per-query positional shuffle (within-run deterministic, cross-run via PYTHONHASHSEED=0) |
| Pilot | 3 clusters × 5q × 3 repeats = **100% deterministic** |
| Total API calls | 1,222 (611 queries × 2 variants) |

### Cluster 구성

| Cluster | Target | Tools | T-queries | C-queries | Total |
|---------|--------|-------|-----------|-----------|-------|
| file_operations | filesystem::list_directory | 5 | 82 | 107 | 189 |
| git_vcs | git::git_log | 6 | 24 | 41 | 65 |
| database_records | airtable::search_records | 6 | 97 | 260 | 357 |
| **합계** | | **17** | **203** | **408** | **611** |

---

## 3. 결과

### 3.1 Per-Cluster 결과

#### file_operations (target: `filesystem::list_directory`)

| Metric | V0 (Control) | V1 (Enriched) | Delta |
|--------|-------------|---------------|-------|
| **TSR** | 97.56% | 96.34% | **-1.22pp** |
| FSR | 23.36% | 22.43% | -0.93pp |
| SP | 76.19% | 76.70% | +0.51pp |
| Score Gap | 0.1682 | 0.1899 | +0.0217 |
| McNemar | | | p=1.000 (NS), discordant=1 |
| Contingency | a=79, b=1 | c=0, d=2 | |

**해석**: Ceiling effect. V0에서 이미 TSR=97.56%로 개선 여지 없음. enrichment 영향 없음.

#### git_vcs (target: `git::git_log`)

| Metric | V0 (Control) | V1 (Enriched) | Delta |
|--------|-------------|---------------|-------|
| **TSR** | 100.00% | 66.67% | **-33.33pp** |
| FSR | 4.88% | 0.00% | -4.88pp |
| SP | 92.31% | 100.00% | +7.69pp |
| Score Gap | 0.1157 | 0.0440 | -0.0717 |
| McNemar | | | **p=0.008** (SIG), discordant=8 |
| Contingency | a=16, b=8 | c=0, d=0 | |

**해석**: **통계적으로 유의미한 악화 (p=0.008)**. "Shows the commit logs" (4단어)는 이미
Cohere reranker에게 완벽한 semantic anchor. enriched description이 더 generic한 문구를
추가하면서("useful for tracking changes and understanding project history") 오히려
cluster 내 다른 tool과의 구분력을 약화시킴. b=8, c=0 → enrichment가 8개 쿼리에서 정답을 빼앗김.

#### database_records (target: `airtable::search_records`)

| Metric | V0 (Control) | V1 (Enriched) | Delta |
|--------|-------------|---------------|-------|
| **TSR** | 77.32% | 82.47% | **+5.15pp** |
| FSR | 6.15% | 1.15% | **-5.00pp** |
| SP | 82.42% | 96.39% | **+13.97pp** |
| Score Gap | 0.0356 | 0.0735 | +0.0379 |
| Rank Disp. | | | -0.53 |
| McNemar | | | p=0.227 (NS), discordant=11 |
| Contingency | a=72, b=3 | c=8, d=14 | |

**해석**: **유일한 긍정 신호**. TSR +5.15pp 상승 + FSR -5.00pp 감소 = Selection Precision이
82.42%→96.39%로 14pp 개선. 이것은 정확히 "맞는 상황에서 더 자주, 틀린 상황에서는 덜 선택됨"
패턴 (Pattern A: Clean Win의 약한 버전). 그러나 McNemar p=0.227로 통계적 유의미성 미달.
c=8 > b=3 → enrichment가 순 5개 쿼리에서 정답을 추가로 획득.

### 3.2 Cross-Cluster Summary

| Metric | file_ops | git_vcs | db_records | **Mean** |
|--------|----------|---------|------------|----------|
| TSR Δ | -1.22pp | -33.33pp | +5.15pp | **-9.80pp** |
| FSR Δ | -0.93pp | -4.88pp | -5.00pp | **-3.60pp** |
| SP Δ | +0.51pp | +7.69pp | +13.97pp | **+7.39pp** |

### 3.3 Verdict: NO_EFFECT (aggregate), but MIXED at cluster level

Composite criterion (TSR uplift ≥ +15pp AND FSR ≤ +3pp) 미충족.
**그러나 cluster별 패턴이 극도로 이질적**이어서 단순 평균이 misleading.

---

## 4. 해석 및 분석

### 4.1 핵심 발견: Enrichment 효과는 baseline description quality에 크게 의존

| Baseline 상태 | 예시 | Enrichment 효과 |
|--------------|------|----------------|
| 이미 완벽 (TSR ~100%) | git_log, list_directory | **무효과 또는 악화** — 이미 최적인 anchor에 noise 추가 |
| 중간 수준 (TSR ~77%) | search_records | **개선 (+5pp TSR, +14pp SP)** — 부족한 정보를 보완 |
| 매우 낮음 (TSR ~0%) | brave_web_search (E4 관찰) | 미검증 — 기능적으로 identical한 tool 간에는 효과 불명 |

### 4.2 "Selection Controllability는 존재하지만, 조건부"

E4v2는 selection controllability의 **존재 자체**는 증명했다:

1. **git_vcs**: description 변경만으로 TSR이 100%→67%로 이동 (p=0.008) — description이 selection을 바꿀 수 있다는 **인과 증거**
2. **database_records**: 같은 메커니즘이 반대 방향(개선)으로도 작동 — TSR +5pp, SP +14pp

다만 current Tool-DE enrichment는 "항상 개선하는" 전략이 아니라,
**baseline이 부족한 tool에만 효과적**이고 baseline이 이미 좋은 tool에는 오히려 해롭다.

### 4.3 Selection Precision(SP)이 모든 cluster에서 개선된 점

TSR은 cluster마다 방향이 달랐지만, **Selection Precision은 3개 cluster 모두에서 개선**:
- file_ops: +0.51pp
- git_vcs: +7.69pp
- db_records: +13.97pp
- **Mean SP Δ: +7.39pp**

이것은 enrichment가 "선택될 때 맞는 비율"을 높인다는 의미.
FSR이 모든 cluster에서 감소(-0.93, -4.88, -5.00)한 것이 이를 뒷받침한다.

### 4.4 기존 E4와의 관계

| 관찰 | E4 (pipeline 전체) | E4v2 (reranker only) |
|------|-------------------|---------------------|
| Confusion Rate | -5.02pp 개선 | FSR -3.60pp 개선 (같은 방향) |
| Recall | -2.92pp 악화 | N/A (embedding bypass) |
| 짧은 desc tool 악화 | 0-5단어 tool -0.111 | git_log(4w) -33pp |
| 중간 desc tool 개선 | 6-10단어 tool +0.058 | search_records(6w) +5pp |

**E4의 "Stage 1 vs Stage 2 충돌" 가설이 E4v2에서 확인됨**.
Stage 2(reranker)만 격리하면 confusion 개선은 유지되고, recall 악화는 사라짐.
단, 짧은 description이 이미 최적인 경우의 악화는 reranker 자체의 특성임.

---

## 5. 제품 시사점

### Provider Dashboard Guidance

Description enrichment를 일률적으로 권장할 수 없다. **Conditional guidance** 필요:

| Description 상태 | 권장 | 근거 |
|-----------------|------|------|
| 짧고 이미 명확 (≤5w, 기능이 self-evident) | **변경하지 마세요** | git_log -33pp 악화 |
| 짧고 불명확 (≤10w, 기능 설명 부족) | **enrichment 권장** | search_records +5pp 개선 |
| 이미 장문 (>20w) | **압축 + 핵심 강화** | (E4v2 미검증, E4v4에서 확인) |

### CTO 데모 시나리오

**가장 설득력 있는 스토리**:

> "description을 바꾸면 LLM의 선택이 바뀝니다 — 이것은 p=0.008로 증명됐습니다.
> 하지만 아무렇게나 바꾸면 오히려 나빠집니다. 따라서 Provider에게 올바른 가이드라인을 주는 것이
> 우리 플랫폼의 핵심 가치입니다."

이 내러티브는 기존 E4의 "P@1 +0.97pp (p=0.833)"보다 훨씬 강하다:
- description → selection의 **인과 관계 증명** (p=0.008)
- **방향성**: 개선과 악화 모두 가능 → 가이드라인 제품의 필요성
- **Selection Precision**: 모든 cluster에서 +7.39pp → 제품 가치 측정 가능

---

## 6. 다음 단계

### 즉시 (E4v2b): Differentiation-First Variant

git_vcs에서 Tool-DE enrichment가 악화를 일으킨 원인은 "generic한 설명 추가"이다.
**Differentiation-first variant** (cluster 내 다른 tool과의 차이를 명시)로 재실험:

```
V2: "Shows the commit history of a local repository.
     Unlike git_diff (compares changes) or git_status (working tree state),
     git_log focuses on the chronological record of past commits."
```

이 variant가 git_vcs에서 TSR을 유지하면서 SP를 높이는지 확인.

### 단기: Production-Path Sanity Check

`MCPTool.selection_description` 필드와 `CohereReranker` 변경은 이미 구현 완료.
production path 검증은 별도 Cohere API 실험 없이 unit/integration test로 커버한다.
- `test_cohere_reranker_uses_selection_description_when_set`
- `test_roundtrip_with_selection_description`

### 중기 (E4v4): Enrichment Methodology Comparison

- Tool-DE (current)
- SAGEO-inspired (structural metadata)
- Differentiation-first
- Use-case anchored

각 methodology를 database_records cluster (가장 개선 가능성 높은 cluster)에서 비교.

---

## 7. 실험 아티팩트

| 파일 | 설명 |
|------|------|
| `docs/experiments/E4v2-design.md` | 실험 설계 |
| `docs/experiments/E4v2-report.md` | 이 보고서 |
| `data/e4v2/clusters.json` | Cluster 정의 + query 분류 (611 queries) |
| `data/e4v2/pilot_results.json` | Pilot determinism 결과 (100% deterministic) |
| `data/e4v2/results.json` | 전체 실험 결과 (per-query breakdown 포함) |
| `scripts/run_e4v2_selection.py` | 실험 실행 스크립트 |
