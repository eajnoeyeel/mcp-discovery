# E4v2b 실험 설계: Description Design Pattern Comparison

> Portfolio note: this is a historical experiment design. Cohere rerank-v3.5 was
> used in this archived experiment as an external reranking baseline; the current
> public runtime does not require Cohere or `COHERE_API_KEY`.

**상태**: 설계 완료, 실행 대기
**설계일**: 2026-04-07
**브랜치**: `feat/pool-gt-expansion`
**선행 실험**: E4v2 (Selection Controllability, 2026-04-07)

---

## 1. Executive Summary

E4v2는 "description이 selection을 바꿀 수 있는가"를 증명했다 (git_vcs p=0.008).
그러나 Tool-DE enrichment는 baseline이 이미 좋은 tool에서 역효과를 냈다.

E4v2b는 그 다음 질문에 답한다:

> **"어떤 description design pattern이, 어떤 baseline 조건에서, selection uplift를 만들고
> 어떤 경우 gaming을 유발하는가?"**

이 실험의 목적은 Provider Dashboard에서 "당신의 tool은 X 상태이니 Y 패턴으로 description을
작성하세요"라는 **conditional recommendation**의 근거를 만드는 것이다.

---

## 2. E4v2에서 배운 것

| Baseline 조건 | Cluster | Tool-DE 결과 | 교훈 |
|--------------|---------|-------------|------|
| TSR ~100% (완벽한 짧은 desc) | git_vcs | **-33pp** (p=0.008) | generic enrichment가 이미 최적인 anchor를 훼손 |
| TSR ~77% (불충분한 desc) | database_records | **+5pp TSR, +14pp SP** | 정보 보충이 효과적 |
| TSR ~98% (ceiling) | file_operations | 무변화 | 개선 여지 없음 |

**핵심 교훈**: enrichment 효과는 **what you add**뿐 아니라 **what the baseline already has**에 의존한다.
따라서 단일 enrichment 전략이 아닌, baseline-aware pattern matching이 필요하다.

---

## 3. 실험 가설

### Primary Hypothesis (H1)

> 서로 다른 description design pattern은 동일 cluster에서 유의미하게 다른 TSR/FSR 프로파일을 만든다.
>
> **성공 기준**: 최소 1개 pattern pair에서 TSR 차이 ≥ 10pp (Cochran's Q p < 0.05)

### Secondary Hypothesis (H2): Baseline-Pattern Interaction

> 특정 pattern의 효과가 baseline description quality에 따라 달라진다.
> - High-baseline cluster (git_vcs): differentiation-first가 generic enrichment보다 TSR 유지에 우월
> - Mid-baseline cluster (database_records): use-case anchored가 최대 TSR uplift
>
> **성공 기준**: cluster × pattern interaction이 관찰됨

### Negative Control Hypothesis (H3)

> Overclaiming description은 TSR을 올리지만 FSR도 함께 올려 SP를 악화시킨다.
>
> **성공 기준**: overclaiming variant의 FSR > V0 FSR + 5pp (gaming 검출)

---

## 4. Description Design Patterns (6 variants)

E4v2의 V0(control) + V1(Tool-DE)에 4개 새 pattern + 1개 negative control을 추가.

### Pattern 정의

| ID | Pattern | 전략 | 무엇을 추가하는가 |
|----|---------|------|-----------------|
| V0 | **Control** | 원본 그대로 | (baseline) |
| V1 | **Tool-DE** (기존) | function_summary + when_to_use + key_params | 일반적 정보 보충 |
| V2 | **Differentiation-first** | cluster 내 다른 tool과의 차이를 명시 | 상대적 positioning |
| V3 | **Use-case anchored** | 구체적 사용 시나리오 + trigger condition | 상황 매칭 단서 |
| V4 | **I/O explicit** | 입력 파라미터와 출력 형태를 명시 | 기술적 정밀도 |
| V5 | **Boundary explicit** | 기능의 한계와 범위를 명시 (무엇을 하지 않는지) | 오선택 방어 |
| V6 | **Overclaiming** (negative control) | 과장된 기능 범위 + 모호한 표현 | **의도적 gaming trigger** |

### Pattern 설계 근거

| Pattern | 기대 효과 | E4v2 교훈과의 관계 |
|---------|----------|------------------|
| V2 Differentiation | High-baseline tool에서 TSR 유지 + FSR 감소 | git_vcs에서 V1이 실패한 이유는 "generic해짐" — V2는 다른 tool과의 차이를 명시하여 anchor를 보존 |
| V3 Use-case | Mid-baseline tool에서 TSR uplift | db_records에서 V1의 +5pp는 "언제 쓰는지"가 부족해서 — V3은 이를 직접 제공 |
| V4 I/O | 기술적으로 정밀한 쿼리에서 효과적 | parameter/output 정보가 reranker의 technical matching을 도움 |
| V5 Boundary | FSR 감소에 특화 — "이 도구는 X를 하지 않는다" | selection precision 최적화 — 과선택 방어에 집중 |
| V6 Overclaiming | TSR 올리지만 FSR도 올림 → gaming | "everything tool" 표현이 진짜로 gaming을 유발하는지 실증적 검증 |

### Per-Cluster Variant 작성

#### git_vcs (target: `git::git_log`, baseline TSR=100%, 4 words)

| ID | Description |
|----|-------------|
| V0 | Shows the commit logs |
| V1 | Retrieves and displays the commit logs for a specified repository, useful for tracking changes and understanding project history. |
| V2 | Shows the commit history of a local repository. Unlike git_status (working tree state), git_diff (file-level changes), or git_show (single commit contents), git_log provides the chronological sequence of past commits with author, date, and message. |
| V3 | Retrieves Git commit history. Use when you need to review who changed what and when, trace the evolution of a file across commits, or find the commit that introduced a specific change. |
| V4 | Returns a list of commit entries (hash, author, date, message) for a Git repository. Accepts optional path filter, author filter, date range, and count limit. |
| V5 | Shows the commit logs. Does not show file-level diffs (use git_diff), working tree state (use git_status), or single commit details (use git_show). Only outputs the commit log sequence. |
| V6 | Comprehensive Git analysis tool that shows commit history, tracks all changes, analyzes code evolution, reviews diffs, and helps understand repository patterns and working tree state. Essential for any Git-related task. |

#### database_records (target: `airtable::search_records`, baseline TSR=77%, 6 words)

| ID | Description |
|----|-------------|
| V0 | Search for records containing specific text |
| V1 | Searches for records in a specified table that contain a specific text, useful for retrieving relevant data based on defined criteria. |
| V2 | Searches for records in an Airtable base by text match. Unlike list_tables (table metadata), list_records (full table dump), or mongodb::find (MongoDB-specific query), search_records does targeted text search within Airtable fields. |
| V3 | Searches Airtable records by text match. Use when you need to find specific entries in an Airtable base by keyword, filter records by content, or look up data matching a search term. |
| V4 | Accepts base_id, table_name, and search_text. Returns matching record objects with field values. Searches across all text fields in the specified table. |
| V5 | Search for records containing specific text in Airtable. Does not list all records (use list_records), describe table structure (use list_tables), or query MongoDB (use mongodb::find). Airtable-only text search. |
| V6 | Universal data search and retrieval tool. Finds records across any database, queries structured data from multiple sources, handles complex search patterns, filters, and aggregations. Works with any data format. |

#### file_operations (target: `filesystem::list_directory`, baseline TSR=98%, 8 words)

| ID | Description |
|----|-------------|
| V0 | List directory contents with [FILE] or [DIR] prefixes |
| V1 | Lists the contents of a specified directory, using [FILE] or [DIR] prefixes to categorize items. Use when needing to view directory structure. Key parameter: path. |
| V2 | Lists files and subdirectories in a given path. Unlike read_file (reads content), read_multiple_files (batch content read), or desktop-commander::list_directory (detailed listing with sizes), filesystem::list_directory gives a simple categorized listing with [FILE]/[DIR] prefixes. |
| V3 | Lists directory contents. Use when you need to see what files exist in a folder, explore a project structure, or check if a specific file is present before reading it. |
| V4 | Accepts a path parameter. Returns an array of entries, each prefixed with [FILE] or [DIR] to indicate type. Does not recurse into subdirectories. |
| V5 | List directory contents with [FILE] or [DIR] prefixes. Does not read file contents (use read_file), handle multiple files at once (use read_multiple_files), or provide file sizes (use desktop-commander::list_directory). Simple listing only. |
| V6 | Comprehensive file system exploration tool that lists directories, reads files, discovers content, searches file systems, and helps navigate any file structure. Ideal for all file browsing and reading needs. |

---

## 5. 실험 설계

### 5.1 구조

E4v2와 동일한 **offline fixed-candidate evaluation** (Cohere rerank-v3.5, embedding bypass).
One-tool-only treatment: target tool의 description만 variant별로 교체, 나머지 tool은 V0(original) 고정.

### 5.2 조건 매트릭스

| Cluster | Variants | T-queries | C-queries | API calls per variant | Subtotal |
|---------|----------|-----------|-----------|----------------------|----------|
| file_operations | V0-V6 | 82 | 107 | 189 | 1,323 |
| git_vcs | V0-V6 | 24 | 41 | 65 | 455 |
| database_records | V0-V6 | 97 | 260 | 357 | 2,499 |

**Total**: 3 clusters × 7 variants × 611 queries = **4,277 Cohere API calls**
At 95 RPM: ~45분. At 10 RPM: ~7.1시간.

> **V0 재사용**: E4v2의 V0 결과를 그대로 가져올 수 있으므로 실제 추가 호출은
> 5 variants × 611 = 3,055 calls (~32분 at 95 RPM). V1도 E4v2에서 재사용하면
> 4 variants × 611 = 2,444 calls (~26분).

### 5.3 One-Tool-Only Treatment 유지

각 variant에서 target tool만 description이 바뀌고, cluster 내 다른 tool은 **모두 V0(original)**을 유지.
이로써 "이 description pattern이 target tool의 선택을 어떻게 바꾸는가"에 대한 인과 attribution이 가능.

---

## 6. Metrics

E4v2와 동일한 metric set + pattern comparison용 추가 분석.

### 6.1 Per-Variant Metrics (E4v2 동일)

| Metric | 정의 |
|--------|------|
| **TSR** | T-queries 중 target이 Top-1인 비율 |
| **FSR** | C-queries 중 target이 (잘못) Top-1인 비율 |
| **SP** | TP / (TP + FP) — 선택 정밀도 |
| **Score Gap** | target이 Top-1인 T-queries에서 1위-2위 score 차이 평균 |

### 6.2 Pattern Comparison Metrics (신규)

| Metric | 정의 |
|--------|------|
| **Pattern Win Rate** | 6개 variant 중 최고 TSR을 가진 pattern (per cluster) |
| **Gaming Index** | FSR_variant - FSR_V0. 양수 = gaming, 음수 = precision 개선 |
| **Net Selection Score** | TSR_uplift - Gaming_Index. TSR 개선에서 gaming을 뺀 순효과 |

### 6.3 통계 검정

| 검정 | 목적 | 방법 |
|------|------|------|
| 7-variant 차이 | V0-V6 중 TSR이 다른 variant가 있는가 | **Cochran's Q test** (k-way McNemar) |
| Pairwise comparison | 어떤 pair가 유의미한가 | **McNemar with Bonferroni correction** (21 pairs, α=0.0024) |
| Gaming detection | V6(overclaiming)의 FSR이 V0보다 높은가 | **One-sided binomial test** |
| Boundary effect | V5(boundary)의 FSR이 V0보다 유의미하게 낮은가 | **One-sided binomial test** |

### 6.4 Success Criteria

```
PATTERN_EFFECT     = Cochran's Q p < 0.05 (7 variants are not all equal)
BEST_PATTERN       = 최소 1개 pattern이 V0 대비 TSR ≥ +10pp (pairwise McNemar p < 0.0024)
GAMING_DETECTED    = V6(overclaiming) FSR > V0 FSR + 5pp
BOUNDARY_EFFECT    = V5(boundary) FSR < V0 FSR - 3pp
BASELINE_INTERACT  = git_vcs와 database_records에서 winning pattern이 다름
```

---

## 7. 분석 프레임: Pattern × Baseline Interaction Matrix

### 7.1 결과 정리 형식

```
              | git_vcs (High BL) | db_records (Mid BL) | file_ops (Ceiling) |
|-------------|-------------------|--------------------|--------------------|
| V0 Control  |  TSR/FSR/SP       |  TSR/FSR/SP        |  TSR/FSR/SP        |
| V1 Tool-DE  |  TSR/FSR/SP       |  TSR/FSR/SP        |  TSR/FSR/SP        |
| V2 Diff     |  TSR/FSR/SP       |  TSR/FSR/SP        |  TSR/FSR/SP        |
| V3 UseCase  |  TSR/FSR/SP       |  TSR/FSR/SP        |  TSR/FSR/SP        |
| V4 I/O      |  TSR/FSR/SP       |  TSR/FSR/SP        |  TSR/FSR/SP        |
| V5 Boundary |  TSR/FSR/SP       |  TSR/FSR/SP        |  TSR/FSR/SP        |
| V6 Overclaim|  TSR/FSR/SP       |  TSR/FSR/SP        |  TSR/FSR/SP        |
```

### 7.2 Provider Dashboard Recommendation 연결

실험 결과에서 추출할 **conditional recommendation rules**:

```
IF baseline_tsr >= 0.95:
    recommendation = "DO NOT CHANGE — your description is already optimal"
    secondary = "Consider BOUNDARY pattern if FSR is high (reduce false selections)"
    evidence = "file_operations cluster: all variants ≤ V0"

ELIF baseline_tsr >= 0.80:
    recommendation = "Use DIFFERENTIATION pattern — clarify what makes you different"
    secondary = "Add BOUNDARY clauses if cluster has many similar tools"
    evidence = "git_vcs cluster: V2 > V1 (if confirmed)"

ELIF baseline_tsr >= 0.50:
    recommendation = "Use USE-CASE pattern — explain when to choose you"
    secondary = "Combine with I/O pattern for technical queries"
    evidence = "database_records cluster: V3 > V1 (if confirmed)"

ELSE:
    recommendation = "Use I/O EXPLICIT pattern — be technically precise"
    evidence = "(hypothesis — low baseline may need specificity)"

WARNING overclaiming:
    IF gaming_index > 0.05:
        flag = "OVERCLAIMING DETECTED — your description promises more than the tool delivers"
        action = "Remove superlative claims, add boundary statements"

OPTIMIZATION high_fsr:
    IF fsr > 0.10:
        recommendation += " + BOUNDARY pattern to reduce false selections"
```

### 7.3 GEO Score 연결 (E4v4 준비)

각 variant의 description을 GEO 6D로 채점하면:

| Pattern | 기대 GEO 프로파일 |
|---------|------------------|
| V0 Control | Low clarity, low disambiguation |
| V1 Tool-DE | High clarity, moderate disambiguation |
| V2 Differentiation | High disambiguation, high boundary |
| V3 Use-case | High clarity, moderate parameter_coverage |
| V4 I/O | High parameter_coverage, high precision |
| V5 Boundary | High boundary, moderate disambiguation — "하지 않는 것"을 명시 |
| V6 Overclaiming | Superficially high clarity, LOW precision and boundary — 의도적 anti-pattern |

실험 후 `(GEO_dimension, TSR_uplift)` correlation을 계산하면
"어떤 GEO 차원이 selection에 가장 영향을 미치는가"를 정량화할 수 있다.
이것이 E7(GEO Score 비교)의 input이 된다.

---

## 8. Bias Control

E4v2와 동일 + variant 수 증가에 따른 추가 통제.

| Bias | 통제 |
|------|------|
| Positional | hashlib.sha256 기반 per-query shuffle (E4v2에서 수정 완료) |
| Name | tool name은 모든 variant에서 동일 |
| Length | variant별 word count 기록, 유의미한 효과 시 length-controlled 추가 분석 |
| Order effect | 6 variant를 임의 순서로 실행하지 않음 — 모든 query가 V0-V5 전부 통과하므로 순서 무관 |
| Multiple comparison | Bonferroni correction (15 pairwise, α=0.0033) |

### Length 통제를 위한 variant word count

| Cluster | V0 | V1 | V2 | V3 | V4 | V5 (Boundary) | V6 (Overclaim) |
|---------|----|----|----|----|----|----|-----|
| git_vcs | 4 | 18 | 35 | 27 | 22 | 27 | 24 |
| db_records | 6 | 21 | 30 | 24 | 17 | 24 | 22 |
| file_ops | 8 | 25 | 33 | 23 | 20 | 28 | 18 |

V2(Differentiation)가 가장 길다. V5(Boundary)는 V0를 그대로 포함하고 "하지 않는 것"을 추가하므로
V0+α 길이. length confound가 의심되면 비슷한 길이의 variant pair를 비교하여 content vs length를 분리.

---

## 9. Threats to Validity

| 위협 | 유형 | 완화 |
|------|------|------|
| Description이 human-authored → 저자 편향 | Internal | V5(overclaiming)를 negative control로 포함하여 "좋은 description = 항상 높은 TSR"이 아님을 보임 |
| 3개 cluster만으로 일반화 한계 | External | 결과를 "these 3 clusters에서 관찰됨"으로 한정, 일반화는 추후 확장 |
| Variant 수가 많아 multiple comparison 위험 | Statistical | Bonferroni correction 적용 (α=0.0033) |
| Cohere reranker 특이성 | External | "Cohere rerank-v3.5 기준"임을 명시 |
| Low n in git_vcs (24 T-queries) | Statistical | pairwise McNemar power 부족 가능 → Cochran's Q로 omnibus 먼저 확인 |

---

## 10. 실행 계획

### Phase 1: Variant 작성 검수 (~30분)

- [ ] Section 4의 21개 description (3 clusters × 7 variants) 최종 검수
- [ ] Word count 확인 및 기록
- [ ] 특히 V2(Differentiation)에서 다른 tool 이름을 정확히 참조하는지 확인
- [ ] V5(Overclaiming)가 실제로 과장인지 — FSR을 올릴 만큼 모호한지 확인

### Phase 2: 스크립트 확장 (~1시간)

- [ ] `scripts/run_e4v2b_patterns.py`를 별도 작성 (E4v2 스크립트를 base로)
- [ ] V0/V1 결과는 E4v2 results.json에서 import (API call 절약)
- [ ] V2-V6 (5 new variants × 611 queries = 3,055 calls) 실행
- [ ] Cochran's Q test 구현 추가
- [ ] Pairwise McNemar with Bonferroni (21 pairs, α=0.0024) 구현
- [ ] `data/e4v2b/variants.json`에 21개 description 정의 저장

### Phase 3: 실행 (~40분 at 95 RPM)

- [ ] 3,055 new API calls 실행 (V0/V1 재사용, V2-V6만 신규)
- [ ] `data/e4v2b/results.json` 저장

### Phase 4: 분석 & 보고서 (~1시간)

- [ ] Pattern × Baseline interaction matrix 작성
- [ ] Cochran's Q + pairwise McNemar 결과
- [ ] Gaming detection (V5 FSR analysis)
- [ ] Provider Dashboard recommendation rules 도출
- [ ] `docs/experiments/E4v2b-report.md` 작성

**총 소요**: ~3시간 (실행 시간 포함)

---

## 11. 산출물

| 파일 | 설명 |
|------|------|
| `docs/experiments/E4v2b-design.md` | 이 문서 |
| `data/e4v2b/variants.json` | 18개 description variant 정의 |
| `data/e4v2b/results.json` | 전체 실험 결과 |
| `scripts/run_e4v2b_patterns.py` | 실험 스크립트 |
| `docs/experiments/E4v2b-report.md` | 결과 보고서 |

---

## 12. E4-series 실험 계보 (업데이트)

```
E4 (04-06) — Description Enrichment A/B (confounded)
  결과: P@1 +0.97pp (p=0.833)
    │
E4v2 (04-07) — Selection Controllability (offline, 2 variants)
  결과: description → selection 인과 증명 (p=0.008), baseline dependent
    │
E4v2b (계획) — Pattern Comparison (offline, 7 variants incl. boundary + overclaiming) [이 문서]
  질문: 어떤 pattern이 어떤 baseline에서 효과적인가? gaming은 언제 발생하는가?
  산출물: Provider Dashboard conditional recommendation rules + gaming detection
    │
E4v3 (계획) — Production-Near Dual-Description
  질문: 최적 pattern을 production pipeline에서 적용하면 재현되는가?
    │
E4v4 (계획) — GEO Dimension → Selection Rate Correlation
  질문: 어떤 GEO 차원이 selection rate와 가장 상관이 높은가?
```
