# E4v2 실험 설계: Selection Controllability Experiment

> Portfolio note: this is a historical experiment design. Cohere rerank-v3.5 was
> used in this archived experiment as an external reranking baseline; the current
> public runtime does not require Cohere or `COHERE_API_KEY`.

**상태**: 실행 완료 (2026-04-07). 결과: `docs/experiments/E4v2-report.md`
**설계일**: 2026-04-07
**브랜치**: `feat/pool-gt-expansion`
**선행 실험**: E4 (Description Enrichment A/B, 2026-04-06)

---

## 1. Executive Summary

기존 E4는 enriched description을 embedding과 reranker에 동시 적용하여 retrieval quality를 측정했으나,
Stage 1(embedding)과 Stage 2(reranker)의 효과가 상쇄되어 P@1 +0.97pp (p=0.833)로 유의미하지 않았다.

E4v2는 실험 질문을 근본적으로 재정의한다:

> **기존 E4**: "enriched description이 우리 pipeline의 Precision@1을 높이는가?"
> **E4v2**: "description design이 유사 기능 MCP 집합 내에서 LLM/reranker의 선택을 통제 가능한 레버인가?"

핵심 변경:
- **retrieval candidate set을 고정**하여 embedding confound를 제거
- **functional cluster 단위**로 유사 tool 간 선택 이동을 측정
- **target tool 1개만 treatment** 적용하여 인과 attribution을 명확화
- primary metric을 P@1에서 **Target Selection Rate (TSR)**로 변경

이 설계는 "stage-aware architecture validation"이다:
description을 retrieval-facing text와 reranker-facing text로 분리했을 때
selection controllability를 깨끗하게 검증할 수 있는가를 확인한다.

---

## 2. 기존 E4와의 Mismatch 분석

### 2.1 인과 경로 혼재 (Causal Path Confounding)

기존 E4에서 enriched description은 두 stage를 동시에 통과한다:

```
enriched description
    ├─→ Stage 1 (embedding): 벡터 변환 → cosine similarity → candidate set 변경
    └─→ Stage 2 (reranker): 텍스트 직접 읽기 → relevance 판단 → ranking 변경
```

결과적으로:
- Recall@K -2.9pp → enrichment가 embedding space에서 noise 생성
- Confusion Rate -5pp → enrichment가 reranker의 구분력 향상
- P@1 +0.97pp (p=0.833) → 두 효과가 상쇄되어 signal 소멸

최종 P@1 변화의 원인을 Stage 1과 Stage 2에 attribution할 수 없다.

### 2.2 측정 대상 불일치

증명하려는 명제: "provider가 description을 바꾸면 LLM의 선택이 바뀐다"
기존 E4가 측정한 것: "enriched description이 전체 pipeline 성능을 올리는가"

Provider는 embedding index를 통제하지 않는다.
Provider가 통제하는 것은 **reranker/LLM이 읽는 텍스트**뿐이다.
따라서 실험은 reranker-facing text의 효과만을 격리해야 한다.

### 2.3 실험 단위 불일치

기존 E4는 94개 tool을 한꺼번에 enrich하여 pool 수준 P@1을 측정했다.
그러나 selection controllability의 핵심은 **functional cluster 내에서의 상대적 선택 이동**이다.

유사 기능 tool이 없는 unique tool(예: `clinicaltrials_analyze_trends`, P@1=1.0→1.0)의
enrichment 효과는 이 명제와 무관하다.
오히려 이런 tool이 aggregate P@1에 희석 효과를 일으켜 signal을 약화시킨다.

---

## 3. Two-Design Comparison

### Design A: Offline Fixed-Candidate Evaluation (권장 — E4v2)

```
Query → [Fixed Candidate Pool: cluster 내 모든 tool descriptions] → Cohere Reranker → Ranking
```

- Embedding retrieval stage를 완전히 bypass
- Reranker만이 description을 읽고 판단
- Description text가 유일한 독립 변수

### Design B: Production-Near Dual-Description (후속 — production path sanity check)

```
Query → Stage 1 (original description으로 embedding 검색)
      → Stage 2 (original + enriched_description을 concat하여 reranker에 전달)
```

- Qdrant payload에 `enriched_description` field 추가
- Reranker input: `f"{tool.tool_name}: {tool.description}\n{tool.enriched_description}"`
- Embedding index는 original description 유지 → retrieval candidate set 불변

### 비교

| 기준 | Design A (Offline) | Design B (Production-Near) |
|------|-------------------|---------------------------|
| **Confound 제거** | 완전 (embedding bypass) | 부분적 (retrieval이 candidate set 결정) |
| **인과 추론 강도** | 높음 — description만 변인 | 중간 — retrieval이 candidate를 바꿀 수 있음 |
| **Production 대표성** | 낮음 — 실제 pipeline과 다름 | 높음 — 실제 배포 가능한 구조 |
| **구현 복잡도** | 낮음 — Cohere API 직접 호출 | 중간 — Qdrant payload 변경 + pipeline 수정 |
| **실행 시간** | ~1시간 (API call만) | ~3시간 (인덱싱 + 전체 evaluation) |
| **이번 주 실행 가능성** | ✅ 즉시 가능 | ⚠️ 코드 변경 필요 |

### 왜 이번 주에는 Design A인가

1. **인과 추론이 먼저다**: "description이 selection을 바꿀 수 있는가?"를 가장 깨끗하게 증명하려면 confound를 완전히 제거해야 한다. Design B는 retrieval의 candidate set 변동이라는 confound가 남는다.

2. **실행 속도**: Design A는 기존 코드 변경 없이 Cohere API 호출 스크립트만 작성하면 된다. Design B는 Qdrant payload schema 변경, pipeline 코드 수정, 재인덱싱이 필요하다.

3. **순서가 맞다**: 먼저 Design A로 "selection controllability가 존재한다"를 증명한 뒤, Design B로 "production pipeline에서도 재현된다"를 확인하는 것이 과학적으로 올바른 순서다.

---

## 4. E4v2 Experiment Design

### 4.1 실험 가설

**Primary Hypothesis (H1): Selection Steering**

> 기능적으로 유사한 MCP tool cluster 내에서, target tool의 description을
> selection-oriented variant로 교체하면, 해당 tool의 Target Selection Rate(TSR)이
> baseline 대비 유의미하게 상승한다.
>
> **성공 기준**: TSR uplift ≥ +15pp, McNemar p < 0.05

**Secondary Hypothesis (H2): Precision Preservation**

> TSR 상승이 "맞는 쿼리에서 더 자주 선택"에 의한 것이지
> "아무 쿼리에서나 과잉 선택"에 의한 것이 아니다.
>
> **성공 기준**: False Selection Rate(FSR) 상승 ≤ 3pp

**Composite Success Criterion:**

```
SUCCESS       = (TSR uplift ≥ +15pp) AND (FSR increase ≤ 3pp)
    → "selection optimization" — description이 맞는 상황에서의 선택을 강화

PARTIAL       = (TSR uplift ≥ +15pp) AND (FSR increase > 3pp)
    → "selection gaming" — description이 과잉 매칭을 유도

WEAK SIGNAL   = (TSR uplift 5-15pp) AND (FSR increase ≤ 3pp)
    → 방향은 맞지만 레버리지가 약함

NO EFFECT     = (TSR uplift < 5pp)
    → description이 reranker selection에 충분한 영향력 없음
```

H1과 H2는 동시 충족이 필요하다. H1만 충족되면 "gaming"이지 "optimization"이 아니다.

### 4.2 실험 단위: Functional Cluster

#### Cluster 선정 기준

1. **기능적 중첩**: 동일 쿼리가 cluster 내 2개 이상 tool에 relevant할 수 있음
2. **실제 혼동 발생**: 기존 E4에서 Confusion이 관찰된 영역
3. **최소 규모**: cluster 내 tool ≥ 3개, GT 쿼리 ≥ 15개 (McNemar power)

#### 후보 Cluster (기존 E4 per-tool 데이터 기반)

| Cluster | Tools (pool 내) | 추정 GT 쿼리 | 기존 E4 혼동 증거 |
|---------|----------------|-------------|-------------------|
| **C1: File Operations** | `filesystem::list_directory`, `filesystem::read_file`, `filesystem::write_file`, `desktop-commander::*` | ~80+ | list_directory P@1=0.16 (높은 혼동) |
| **C2: Search / Lookup** | `brave-search::brave_web_search`, `ddg-search::search`, `ddg-search::fetch_content`, `wikipedia::get_article`, `arxiv::search_papers` | ~100+ | brave P@1=0.0, ddg P@1=0.0 (상호 혼동) |
| **C3: Git Operations** | `git::git_log`, `git::git_diff`, `git::git_status`, `github::search_repositories`, `github::search_code` | ~60+ | search_repositories 0.90→0.52 (enrichment 후 악화) |
| **C4: Data / Records** | `airtable::search_records`, `airtable::list_tables`, `mongodb::*`, `postgres::*` | ~100+ | search_records P@1=0.32 |
| **C5: Location / Map** | `osm-mcp-server::find_nearby_places`, `osm-mcp-server::find_ev_charging_stations`, `national-parks::*` | ~30+ | nearby_places P@1=0.0 |

**최소 3개 cluster 선택** 권장. 우선순위: C1, C2, C3 (GT 쿼리 충분 + 혼동 증거 명확).

#### Query 분류

각 cluster에 대해 GT 쿼리를 두 유형으로 자동 분류:

| Query Type | 정의 | Gold Label 소스 |
|------------|------|---------------|
| **T (Target-relevant)** | target tool이 GT 정답인 쿼리 | `gt.correct_tool_id == target` |
| **C (Cluster-relevant, Target-irrelevant)** | cluster 내 다른 tool이 GT 정답인 쿼리 | `gt.correct_tool_id in cluster_tools AND != target` |

기존 MCP-Atlas GT의 `correct_tool_id`를 그대로 사용. 추가 labeling 불필요.

### 4.3 Treatment / Control

| 조건 | Description 사용 | 적용 범위 |
|------|-----------------|-----------|
| **Control (V0)** | 모든 tool이 original description | cluster 전체 |
| **Treatment** | **target tool만** enriched description으로 교체, 나머지는 original 유지 | target 1개만 |

#### One-Tool-Only Treatment 권장 근거

- **인과 attribution 명확**: "이 tool의 description이 바뀌었기 때문에 선택이 이동했다"
- **교차 효과 방지**: multi-tool treatment에서는 A의 enrichment가 B의 selection을 낮출 수 있음
  - 예: git_log와 git_diff를 동시에 enrich하면, 둘 다 더 잘 설명되어 상대적 차이가 불분명
- **데모 직관성**: "하나만 바꿨는데 선택이 이동했다"가 가장 강한 이야기

Multi-tool treatment는 E4v2의 one-tool 결과를 확인한 후 E4v2b로 검증 가능.

#### Description Variant Design

이번 E4v2에서는 enrichment 방법론 자체를 비교하는 것이 아니므로,
**단일 enriched variant**를 사용한다. Tool-DE 기반 enrichment (기존 E4에서 사용)를 그대로 활용.

```
V0 (Control): original description
V1 (Treatment): Tool-DE enriched description (function_summary + when_to_use + key_params)
```

> **왜 variant를 1개로 한정하는가**: 이번 실험의 독립 변수는 "enriched vs original"이지
> "어떤 enrichment가 최고인가"가 아니다. Stage separation의 효과를 보는 것이 목적이므로
> variant 수 비교는 E4v2b에서 7개 패턴으로 완료됨.

### 4.4 실험 조건 매트릭스

> **Note**: 아래는 초기 설계안이다. 실제 실행 시 Search cluster를 database_records로 교체하고
> 쿼리 수가 611로 확정되었다. 실제 실행된 조건은 `E4v2-report.md` 참조.

**초기 설계안** (Search cluster 포함):

| 조건 ID | Cluster | Target Tool | Description | 쿼리 유형 |
|---------|---------|-------------|-------------|-----------|
| E4v2-C1-V0 | File Ops | filesystem::list_directory | Original | T + C |
| E4v2-C1-V1 | File Ops | filesystem::list_directory | Enriched | T + C |
| E4v2-C2-V0 | Search | brave-search::brave_web_search | Original | T + C |
| E4v2-C2-V1 | Search | brave-search::brave_web_search | Enriched | T + C |
| E4v2-C3-V0 | Git Ops | git::git_log | Original | T + C |
| E4v2-C3-V1 | Git Ops | git::git_log | Enriched | T + C |

**실제 실행된 조건** (Search → database_records 교체):

| 조건 ID | Cluster | Target Tool | Description | 쿼리 수 |
|---------|---------|-------------|-------------|---------|
| E4v2-C1 | file_operations | filesystem::list_directory | V0/V1 | 189 |
| E4v2-C2 | git_vcs | git::git_log | V0/V1 | 65 |
| E4v2-C3 | database_records | airtable::search_records | V0/V1 | 357 |

교체 사유: Search cluster의 모든 tool이 기존 E4에서 P@1=0.0 — 기능적으로 identical한 tool 간 선택은
description이 아닌 provider preference 문제로 판단.

3 clusters × 2 conditions × 611 queries = 1,222 Cohere API calls.

---

## 5. Metrics and Protocol

### 5.1 Metric 정의

#### Primary Endpoint

| Metric | 정의 | 역할 |
|--------|------|------|
| **TSR (Target Selection Rate)** | T-type 쿼리 중 target tool이 Top-1으로 선택된 비율 | "맞는 상황에서 얼마나 자주 선택되는가" |

#### Secondary Endpoints

| Metric | 정의 | 역할 |
|--------|------|------|
| **FSR (False Selection Rate)** | C-type 쿼리 중 target tool이 Top-1으로 (잘못) 선택된 비율 | selection gaming 탐지 |
| **SP (Selection Precision)** | TSR×n_T / (TSR×n_T + FSR×n_C) | 선택 정밀도 — TSR과 FSR의 tradeoff 단일 수치 |
| **Score Gap** | T-type 쿼리 중 **target이 Top-1인 경우에만** target score - 2위 score의 평균 | 선택 confidence / differentiation 강도 |
| **Rank Displacement** | C-type 쿼리에서 target tool 순위의 control→treatment 변화 | 과잉 promotion 탐지 |

#### 정밀 정의 (Python)

```python
def target_selection_rate(results: list[QueryResult], target: str) -> float:
    """T-type 쿼리에서 target이 Top-1인 비율."""
    t_queries = [r for r in results if r.gold_label == "T"]
    return sum(1 for r in t_queries if r.top1_tool == target) / len(t_queries)

def false_selection_rate(results: list[QueryResult], target: str) -> float:
    """C-type 쿼리에서 target이 Top-1으로 잘못 선택된 비율."""
    c_queries = [r for r in results if r.gold_label == "C"]
    return sum(1 for r in c_queries if r.top1_tool == target) / len(c_queries)

def selection_precision(tsr: float, fsr: float, n_t: int, n_c: int) -> float:
    """선택될 때 맞는 비율."""
    tp, fp = tsr * n_t, fsr * n_c
    return tp / (tp + fp) if (tp + fp) > 0 else float("nan")

def mean_score_gap(results: list[QueryResult], target: str) -> float:
    """T-type 쿼리에서 target과 2위 간 score 차이 평균."""
    t_queries = [r for r in results if r.gold_label == "T"]
    gaps = []
    for r in t_queries:
        scores = sorted(r.all_scores.values(), reverse=True)
        target_score = r.all_scores[target]
        others_max = max(s for tid, s in r.all_scores.items() if tid != target)
        gaps.append(target_score - others_max)
    return sum(gaps) / len(gaps) if gaps else float("nan")
```

### 5.2 통계 검정

| 검정 | 대상 | 방법 |
|------|------|------|
| Per-cluster TSR 차이 | V0 vs V1의 T-type 쿼리 binary outcomes | **McNemar's exact test**, p < 0.05 |
| Cross-cluster 일관성 | 3개 cluster의 TSR uplift | 평균 ± 95% CI (cluster = unit of analysis) |
| Effect size | TSR uplift 크기 | Cohen's g (McNemar effect size) |

McNemar 검정에 필요한 최소 discordant pair 수: ~20개.
T-type 쿼리가 15개 미만인 cluster는 제외하거나 보조 분석으로만 사용.

### 5.3 실험 프로토콜

#### Step 1: Cluster 선정 & Candidate Pool 확정

```python
clusters = [
    {
        "name": "file_operations",
        "tools": ["filesystem::list_directory", "filesystem::read_file",
                  "filesystem::write_file", "desktop-commander::execute_command"],
        "target": "filesystem::list_directory",
    },
    # ... C2, C3
]
```

#### Step 2: GT에서 Query 추출 & T/C 분류

```python
for entry in mcp_atlas_gt:
    for cluster in clusters:
        if entry.correct_tool_id == cluster["target"]:
            entry.label = "T"
        elif entry.correct_tool_id in cluster["tools"]:
            entry.label = "C"
```

#### Step 3: Reranker 실행

```python
for cluster in clusters:
    for variant in ["V0_control", "V1_enriched"]:
        candidates = build_candidate_docs(cluster, variant)

        for query in cluster_queries:
            # 매 query마다 candidate 순서 shuffle (positional bias 통제)
            shuffled = random_shuffle(candidates, seed=hash(query.query_id + variant))

            response = await cohere.rerank(
                query=query.query,
                documents=[doc.text for doc in shuffled],
                model="rerank-v3.5",
                top_n=len(shuffled),  # 전체 순위 반환
            )

            record_result(query, response, cluster, variant)
```

#### Step 4: 분석 & 보고

Per-cluster 결과표 → cross-cluster summary → McNemar test → 보고서 작성.

---

## 6. Threats to Validity / Bias Controls

### 6.1 Bias Control Protocol

| Bias | 위험 | 통제 방법 |
|------|------|----------|
| **Positional bias** | Cohere reranker가 문서 순서에 민감할 수 있음 | 매 query마다 candidate 순서를 random shuffle. seed = `hash(query_id + variant_id)` → 동일 query는 모든 variant에서 동일 순서 |
| **Name bias** | tool name 자체가 selection에 영향 | 모든 condition에서 tool name 동일 유지 (description만 변경). 추가: pilot에서 generic name(`tool_1`) vs real name의 차이 확인 |
| **Length bias** | enriched description이 original보다 길어서, content가 아닌 length에 의한 효과 | enriched description의 단어 수 기록. 유의미한 효과 발견 시 length-matched control 추가 분석 |
| **Brand bias** | server name이 description에 포함되어 특정 브랜드 선호 유발 | Reranker에 전달하는 document에서 server name prefix 제거. format: `"tool_name: description"` |

### 6.2 Determinism 확인

Cohere reranker는 temperature 파라미터가 없고 near-deterministic이다.

**Pilot test**: 5개 query × 3회 반복 실행으로 output variance 측정.
- variance = 0 → 반복 불필요, 1회 실행으로 충분
- variance > 0 → 5회 반복의 majority vote

### 6.3 Threats to Validity

| 위협 | 유형 | 완화 |
|------|------|------|
| Cluster 크기가 작아 statistical power 부족 | Internal | 3개 이상 cluster 사용, cross-cluster aggregation |
| Offline evaluation이 production과 다름 | External | `MCPTool.selection_description` + reranker 변경을 unit/integration test로 검증 |
| Enriched description이 특정 cluster에서만 작동 | External | 최소 3개 서로 다른 도메인의 cluster 선택 |
| GT 자체의 quality | Construct | MCP-Atlas GT는 Scale AI human-authored — 품질 신뢰 가능 |
| Cohere reranker 특이성 | External | 결과 해석 시 "Cohere rerank-v3.5 기준"임을 명시 |

---

## 7. Stage Separation의 위치

### 이번 E4v2의 프레이밍

E4v2는 **"stage-aware architecture validation"**이다:

- 핵심 질문: "description을 retrieval-facing text와 reranker-facing text로 분리했을 때, selection controllability를 검증할 수 있는가?"
- Stage 1 (embedding)은 고정 — original description 유지
- Stage 2 (reranker)만이 enriched description을 읽음
- 이 분리를 통해 "description → selection" 인과를 깨끗하게 격리

### SAGEO는 이번 E4v2의 독립 변수가 아니다

기존 E4 보고서에서 SAGEO Arena와의 비교가 있었지만, E4v2에서:
- SAGEO-inspired enrichment는 여러 가능한 enrichment strategy 중 하나일 뿐
- 이번 실험의 독립 변수는 "enriched vs original"이지 "어떤 enrichment가 최고인가"가 아님
- Tool-DE 기반 enrichment를 그대로 사용 (이미 94개 tool에 대해 생성 완료)

### Follow-up Roadmap

```
E4v2 (이번 주)
  "description이 selection을 바꿀 수 있는가?" — Offline Fixed-Candidate
  독립 변수: enriched vs original (1개)
  confound: 없음 (embedding bypass)
    │
    │ [H1 충족 시]
    │ → production path는 MCPTool.selection_description + CohereReranker
    │   unit/integration test로 검증 (별도 Cohere API 실험 불필요)
    ▼
E4v4 (이후)
  "어떤 enrichment 패턴이 가장 효과적인가?" — Enrichment Methodology Comparison
  독립 변수: enrichment 방법론 (3-4개)
  후보:
    - Tool-DE (function_summary + when_to_use + key_params)
    - SAGEO-inspired (structural metadata + cite sources + stats)
    - Differentiation-first (cluster 내 다른 tool과의 차이 명시)
    - Use-case anchored (구체적 시나리오 제시)
  이 단계에서 비로소 "어떤 writing 전략이 selection rate를 가장 높이는가" 질문에 답
```

---

## 8. 결과 해석 프레임

### 4가지 결과 패턴

| 패턴 | TSR | FSR | Score Gap | 해석 | 제품 시사점 |
|------|-----|-----|-----------|------|-----------|
| **A: Clean Win** | ↑ ≥15pp | ≤ +3pp | ↑ | 맞는 상황에서의 선택 강화, 과잉 선택 없음 | Provider Dashboard 핵심 가치 증명 |
| **B: Gaming** | ↑ ≥15pp | ↑ >3pp | ↑ | 과잉 매칭 유도 — 맞지 않는 쿼리에서도 선택됨 | Gaming detection 필요 → guardrail 제품 기능 |
| **C: Weak Signal** | ↑ 5-15pp | ≤ +3pp | 미미 | 방향은 맞지만 레버리지 약함 | E4v4에서 더 강한 variant 탐색 |
| **D: No Effect** | < +5pp | — | — | Reranker가 description 변화에 둔감 | Pipeline 변경 필요 (LLM-as-judge 등) |

### 데모 시나리오 (CTO 시연용)

가장 직관적인 before/after:

```
[Before — V0 Control]
Query: "Show me the recent commit history of this project"
Candidates:
  - git::git_log:    "Shows the commit logs"
  - git::git_diff:   "Shows changes between commits"
  - git::git_status: "Shows the working tree status"

Reranker Result: git_status selected (WRONG) — score gap: 0.02

[After — V1 Treatment: git_log만 enriched]
Query: (동일)
Candidates:
  - git::git_log:    "Retrieves Git commit history with author, date, and message;
                      use to review changes or trace code evolution."
  - git::git_diff:   "Shows changes between commits" (원본 유지)
  - git::git_status: "Shows the working tree status" (원본 유지)

Reranker Result: git_log selected (CORRECT) — score gap: 0.18
```

**Product Narrative:**
> "MCP 생태계에서 비슷한 도구가 늘어나면, LLM이 어떤 도구를 선택할지가 description에 의해 결정됩니다.
> 우리 실험에서 description을 바꾸는 것만으로 선택률이 [X]pp 상승했고,
> 이것은 맞는 쿼리에서만 일어났습니다 (FSR 변화 없음).
> 이것이 Provider Dashboard의 핵심 가치입니다."

---

## 9. This-Week Execution Plan

### Day 1 (4/7, 월): Cluster 선정 & Data Preparation

- [ ] E4 결과의 per_tool 오답 패턴 분석 → 실제 혼동 pair 식별
- [ ] MCP-Atlas GT에서 cluster별 query 추출 & T/C 분류
- [ ] 3개 cluster 확정, 각 cluster의 candidate pool & query set 문서화
- [ ] `data/e4v2/clusters.json` 생성

**산출물**: `data/e4v2/clusters.json` (cluster 정의 + query 분류)

### Day 2 (4/8, 화): Enriched Description 준비 & Pilot

- [ ] 3개 target tool의 enriched description 확인 (기존 `data/e4/enriched_descriptions.jsonl`에서 추출)
- [ ] Cohere determinism pilot: 5 queries × 3 repeats → variance 측정
- [ ] Positional bias pilot: 동일 query, 다른 순서 → 결과 차이 확인
- [ ] Bias control 결과에 따라 프로토콜 최종 확정

**산출물**: Pilot 결과 기록, 프로토콜 확정

### Day 3 (4/9, 수): 실험 스크립트 작성 & 실행

- [ ] `scripts/run_e4v2_selection.py` 작성
  - cluster 로딩
  - Cohere rerank API 호출 (with shuffle)
  - TSR/FSR/SP/ScoreGap 계산
  - McNemar test
  - per-query 결과 JSONL 출력
- [ ] 전체 실행: 3 clusters × 2 variants × ~50 queries = ~300 API calls
- [ ] `data/e4v2/results.json` 생성

**산출물**: `scripts/run_e4v2_selection.py`, `data/e4v2/results.json`

### Day 4 (4/10, 목): 분석 & 보고서

- [ ] Per-cluster 결과표 작성
- [ ] Cross-cluster summary (평균 TSR uplift ± 95% CI)
- [ ] McNemar p-value 계산
- [ ] 결과 패턴 판정 (A/B/C/D)
- [ ] `docs/experiments/E4v2-report.md` 작성

**산출물**: `docs/experiments/E4v2-report.md`

### Day 5 (4/11, 금): 문서 정리

- [ ] E4v2 결과를 experiment-design.md에 반영
- [ ] production path sanity check: unit/integration test 통과 확인

---

## 10. 실험 아티팩트

| 파일 | 설명 |
|------|------|
| `docs/experiments/E4v2-design.md` | 이 문서 (실험 설계) |
| `data/e4v2/clusters.json` | Cluster 정의 + query 분류 |
| `data/e4v2/results.json` | 전체 실험 결과 |
| `scripts/run_e4v2_selection.py` | 실험 실행 스크립트 |
| `docs/experiments/E4v2-report.md` | 결과 보고서 |

---

## 11. E4-series 실험 계보

```
E4 (2026-04-06) — Description Enrichment A/B
  결과: P@1 +0.97pp (p=0.833), 유의미하지 않음
  교훈: embedding과 reranker에 동일 description → confounded
    │
    ▼
E4v2 (2026-04-07~11) — Selection Controllability [이 문서]
  질문: "description → selection" 인과가 존재하는가?
  방법: Offline Fixed-Candidate, cluster 단위
    │
    ▼
  [production path] MCPTool.selection_description + CohereReranker
  unit/integration test로 검증 (별도 Cohere API 실험 불필요)
    │
    ▼
E4v4 (계획) — Enrichment Methodology Comparison
  질문: 어떤 enrichment 패턴이 가장 효과적인가?
  후보: Tool-DE / SAGEO-inspired / Differentiation-first / Use-case anchored
```
