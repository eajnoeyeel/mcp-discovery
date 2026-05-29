# E4v2b 실험 보고서: Description Design Pattern Comparison

> Portfolio note: this is a historical experiment report. Cohere rerank-v3.5 was
> used in this archived run as an external reranking baseline; the current public
> runtime does not require Cohere or `COHERE_API_KEY`.

**실험일**: 2026-04-07
**브랜치**: `feat/pool-gt-expansion`
**설계 문서**: `docs/experiments/E4v2b-design.md`

---

## 1. 실험 목적

**핵심 질문**: 어떤 description design pattern이, 어떤 baseline 조건에서, selection uplift를 만들고
어떤 경우 gaming을 유발하는가?

E4v2에서 "description이 selection을 바꿀 수 있다"는 인과를 증명한 후,
"어떤 방향으로 바꿔야 하는가"에 대한 actionable guidance를 도출하기 위한 실험.

---

## 2. 실험 설계

| 항목 | 설명 |
|------|------|
| 방법 | Offline Fixed-Candidate Evaluation |
| Reranker | Cohere rerank-v3.5 |
| Variants | 7 (V0-V6): Control, Tool-DE, Differentiation, Use-case, I/O, Boundary, Overclaiming |
| V0/V1 | E4v2에서 import |
| New API calls | 3,055 (V2-V6 × 611 queries) |
| Bias control | hashlib.sha256 per-query shuffle |
| Statistical test | Cochran's Q + Pairwise McNemar (Bonferroni α=0.0024) |

---

## 3. 결과

### 3.1 Pattern × Baseline Interaction Matrix — TSR

| Pattern | file_ops (ceiling, 98%) | git_vcs (high BL, 100%) | db_records (mid BL, 77%) |
|---------|------------------------|------------------------|-------------------------|
| **V0 Control** | 97.56% | **100.00%** | 77.32% |
| V1 Tool-DE | 96.34% | 66.67% | 82.47% |
| V2 Differentiation | 93.90% | 83.33% | 68.04% |
| **V3 Use-case** | **98.78%** | 12.50% | 37.11% |
| **V4 I/O explicit** | 95.12% | 20.83% | **86.60%** |
| V5 Boundary | 96.34% | 41.67% | 46.39% |
| V6 Overclaiming | 85.37% | 8.33% | 77.32% |

### 3.2 FSR (False Selection Rate)

| Pattern | file_ops | git_vcs | db_records |
|---------|----------|---------|------------|
| V0 Control | 23.36% | 4.88% | 6.15% |
| V1 Tool-DE | 22.43% | 0.00% | 1.15% |
| V2 Differentiation | 26.17% | 0.00% | 0.38% |
| V3 Use-case | 24.30% | 0.00% | 1.92% |
| V4 I/O explicit | 22.43% | 0.00% | 2.31% |
| V5 Boundary | **27.10%** | 0.00% | **0.00%** |
| V6 Overclaiming | 16.82% | 0.00% | 4.62% |

### 3.3 Selection Precision (SP)

| Pattern | file_ops | git_vcs | db_records |
|---------|----------|---------|------------|
| V0 Control | 76.19% | 92.31% | 82.42% |
| V1 Tool-DE | 76.70% | 100.0% | 96.39% |
| V2 Differentiation | 73.33% | 100.0% | **98.51%** |
| V3 Use-case | 75.70% | 100.0% | 87.80% |
| V4 I/O explicit | 76.47% | 100.0% | 93.33% |
| V5 Boundary | 73.15% | 100.0% | **100.0%** |
| V6 Overclaiming | **79.55%** | 100.0% | 86.21% |

### 3.4 Cochran's Q Test

| Cluster | Statistic | p-value | Significant |
|---------|-----------|---------|-------------|
| file_operations | 38.79 | **0.000001** | YES |
| git_vcs | 76.56 | **< 0.000001** | YES |
| database_records | 121.37 | **< 0.000001** | YES |

**3개 cluster 모두 p < 0.001 — 7개 variant의 TSR이 유의미하게 다름.**

### 3.5 Pattern Ranking (by TSR)

| Rank | file_ops | git_vcs | db_records |
|------|----------|---------|------------|
| 1st | **V3** (Use-case) | **V0** (Control) | **V4** (I/O) |
| 2nd | V0 (Control) | V2 (Differentiation) | V1 (Tool-DE) |
| 3rd | V1/V5 (tie) | V1 (Tool-DE) | V0/V6 (tie) |
| Last | **V6** (Overclaiming) | **V6** (Overclaiming) | V3 (Use-case) |

### 3.6 Gaming Detection

- file_ops V5(Boundary): FSR 27.10% vs V0 23.36% → **Gaming Index +3.74pp** (gaming detected)
- db_records V6(Overclaiming): FSR 4.62% vs V0 6.15% → Gaming Index -1.53pp (no gaming)
- git_vcs: 모든 variant에서 FSR=0% (V0만 4.88%) → gaming 불가

---

## 4. 핵심 발견

### 4.1 Baseline-Pattern Interaction이 강력하게 확인됨

**같은 pattern이 cluster마다 정반대 효과를 냄**:

| Pattern | git_vcs (high BL) | db_records (mid BL) | 방향 |
|---------|-------------------|---------------------|------|
| V3 Use-case | TSR **12.50%** (최악) | TSR 37.11% | 두 cluster 모두에서 나쁨 |
| V4 I/O | TSR 20.83% | TSR **86.60%** (최고) | mid BL에서만 효과 |
| V2 Diff | TSR **83.33%** (2nd) | TSR 68.04% | high BL에서만 효과 |
| V0 Control | TSR **100%** (1st) | TSR 77.32% (3rd) | high BL에서 최적 |

**이것이 이 실험의 가장 중요한 발견**: 일률적 enrichment 권장은 불가능하다.

### 4.2 High-Baseline Tool: "건드리지 마라"

git_vcs에서 V0(100%)를 이길 수 있는 variant가 없다.
가장 가까운 V2(Differentiation)도 83.33%로 -16.67pp 하락.
V3(Use-case), V4(I/O), V6(Overclaiming)은 모두 25% 미만으로 추락.

**결론**: 이미 완벽한 짧은 description은 어떤 enrichment도 해롭다.

### 4.3 Mid-Baseline Tool: "I/O explicit이 가장 효과적"

database_records에서:
- V4(I/O): 86.60% (+9.28pp from V0) — **최대 uplift**
- V1(Tool-DE): 82.47% (+5.15pp)
- V2(Differentiation): 68.04% (-9.28pp) — 오히려 악화

V4가 효과적인 이유: `search_records`의 baseline description("Search for records containing specific text")에는
파라미터 정보(base_id, table_name)가 없다. V4는 이를 명시하여 reranker가 기술적 매칭을 할 수 있게 함.

### 4.4 Overclaiming은 거의 항상 해로움

V6은 3개 cluster 중 2개에서 최하위(git_vcs 8.33%, file_ops 85.37%).
database_records에서는 V0와 동점(77.32%)이지만 개선 없음.

### 4.5 Boundary Pattern의 이중성

- file_ops에서 FSR +3.74pp → **gaming detected** (의도와 반대)
- db_records에서 FSR 0.00% → **최고의 precision** (SP 100%)
- "하지 않는 것을 명시"하는 전략은 cluster 특성에 따라 역효과 가능

---

## 5. Provider Dashboard Recommendation Rules (실험 기반)

```python
def recommend_pattern(baseline_tsr: float, cluster_type: str) -> str:
    if baseline_tsr >= 0.95:
        return "DO NOT CHANGE your description."
        # Evidence: git_vcs V0=100%, all variants worse
        # Evidence: file_ops V0=97.56%, only V3 marginally better

    elif baseline_tsr >= 0.70:
        return "Add I/O details: specify input parameters and output format."
        # Evidence: db_records V4=86.60% (+9.28pp from V0)
        # Secondary: Add Tool-DE enrichment (V1=82.47%, +5.15pp)

    else:
        return "Start with Tool-DE enrichment, then add I/O details."
        # Low baseline tools need general information first

    # WARNINGS
    # - NEVER use Use-case pattern on high-baseline tools (git_vcs V3=12.50%)
    # - NEVER overclaim capabilities (V6 consistently worst or tied worst)
    # - Boundary pattern can backfire (file_ops FSR +3.74pp)
```

---

## 6. 다음 단계

1. **E4v3**: Production-Near Dual-Description — V4(I/O) pattern을 실제 pipeline에서 적용하여 재현 확인
2. **GEO Score 연결**: V0-V6 각각을 GEO 6D로 채점하여 `(GEO_dimension, TSR)` correlation 계산
3. **Provider Dashboard MVP**: baseline TSR 추정 → conditional pattern recommendation

---

## 7. 실험 아티팩트

| 파일 | 설명 |
|------|------|
| `docs/experiments/E4v2b-design.md` | 실험 설계 |
| `docs/experiments/E4v2b-report.md` | 이 보고서 |
| `data/e4v2b/variants.json` | 21개 description variant 정의 |
| `data/e4v2b/results.json` | 전체 실험 결과 |
| `scripts/run_e4v2b_patterns.py` | 실험 스크립트 |
