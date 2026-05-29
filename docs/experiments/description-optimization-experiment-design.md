# Description Optimization — Rigorous Experiment Design

**Date:** 2026-04-14
**Status:** DRAFT — 리뷰 후 실행
**Source:** `.omc/specs/deep-interview-description-quantification.md`

---

## 1. 가설 (Hypotheses)

### H1: Information Effect (정보 효과)
> 원본 description 대비 enriched description은 LLM의 도구 선택률을 유의미하게 높인다.

- **독립 변수:** description (V_orig vs V_enriched)
- **종속 변수:** hit rate (target tool 선택 여부, 0/1)
- **통제:** 동일 쿼리, 동일 경쟁 도구, 동일 LLM
- **파일럿 결과:** GPT 0% → 100%, Claude 60% → 100% (n=5, web_search)
- **기대:** p < 0.05, effect size (Cohen's h) > 0.8 (large)

### H2: Format Specificity (포맷 특이성)
> 각 LLM 벤더에 최적화된 포맷이 neutral prose 대비 선택률을 높인다.

- **독립 변수:** format (V_prose vs V_vendor_matched)
- **종속 변수:** hit rate
- **통제:** 동일 정보 내용, 동일 쿼리, 동일 경쟁 도구
- **파일럿 결과:** GPT는 포맷 무관 100%. Claude는 XML=prose=100%.
- **기대:** 효과가 작거나 없을 수 있음 (포맷 < 정보)

### H3: Cross-Vendor Interference (교차 간섭)
> 다른 벤더에 최적화된 포맷이 선택률을 neutral prose 대비 유의미하게 낮춘다.

- **독립 변수:** format (V_prose vs V_wrong_vendor)
- **종속 변수:** hit rate
- **통제:** 동일 정보 내용
- **파일럿 결과:** Claude에 GPT-markdown 제시 시 100% → 20% (n=5)
- **기대:** p < 0.05 for Claude+markdown. GPT는 간섭 없을 것.

---

## 2. 실험 조건 (Conditions)

### Description Variants

모든 enriched variant는 **동일한 4가지 핵심 정보**를 포함:
1. 핵심 기능 (what it does)
2. 차별화 기능 (unique capability)
3. 사용 시나리오 (when to use)
4. 출력 형식 (what it returns)

| ID | Format | 정보량 | 용도 |
|----|--------|-------|------|
| V_orig | 원본 그대로 | 원본 (적음) | H1 baseline |
| V_prose | Plain prose | enriched (동일) | H2/H3 control |
| V_md | GPT-markdown (## headers, **bold**) | enriched (동일) | GPT-optimized |
| V_xml | Claude-XML (`<capabilities>` tags) | enriched (동일) | Claude-optimized |
| V_spec | Gemini-specsheet (key-value) | enriched (동일) | Gemini-optimized |

### 가설별 비교 쌍

| 가설 | 비교 | 기대 방향 |
|------|------|----------|
| H1 | V_orig vs V_prose | V_prose > V_orig (정보 효과) |
| H2-GPT | V_prose vs V_md | V_md >= V_prose (GPT 포맷 효과) |
| H2-Claude | V_prose vs V_xml | V_xml >= V_prose (Claude 포맷 효과) |
| H2-Gemini | V_prose vs V_spec | V_spec >= V_prose (Gemini 포맷 효과) |
| H3-Claude | V_prose vs V_md | V_md < V_prose (markdown이 Claude 방해) |
| H3-GPT | V_prose vs V_xml | V_xml <= V_prose (XML이 GPT 방해 안 함 예상) |

---

## 3. 클러스터 선정 (Cluster Selection)

### 3.1 자동 발견 알고리즘

MCP-Zero 2,898개 도구에서 "자연 경쟁 클러스터" 발견:

```
Step 1: 도구 이름에서 동사 추출 (search_, list_, get_, create_, send_, ...)
Step 2: 동일 동사 그룹 내에서 description embedding 유사도 계산
Step 3: 유사도 > threshold인 도구 5개+ 그룹 = 후보 클러스터
Step 4: 필터링 — 이름만으로 구분 가능한 그룹 제외
```

### 3.2 필터링 기준 (토큰 낭비 방지)

**제외 조건:**
- 도구 이름에 고유 서비스명 포함 (slack_post_message → "slack"이 이름에 있음)
- 클러스터 내 도구 수 < 5개 (경쟁 부족)
- 도구 description이 전부 다른 도메인 (list_invoices vs list_workflows → 혼동 안 됨)

**포함 조건 (효과 나올 가능성 높음):**
- 도구 이름이 거의 동일 (search_*, send_*, create_*, get_*)
- description도 비슷한 표현 ("Search for...", "Perform... search")
- 쿼리를 기능 기반으로 만들면 다수 도구가 후보

### 3.3 사전 검증 (Pilot Gate)

자동 발견된 클러스터를 본 실험에 투입하기 전에 **pilot 2회**로 검증:
- V_orig 조건에서 GPT hit rate < 80%인 클러스터만 본 실험 진행
- 이미 원본으로 100% 맞추는 클러스터는 description 효과를 측정할 수 없으므로 제외
- 이 단계에서 최대 2 × 후보 수 = ~40회 API 호출 (GPT-4o-mini ~$0.10)

### 3.4 예상 클러스터 (파일럿 기반)

| 클러스터 | 도구 예시 | 파일럿 V_orig hit rate | 본 실험 진행 |
|----------|----------|---------------------|------------|
| web_search | tavily, exa, kagi, firecrawl, brave, google | 0% (GPT) | YES |
| file_search | filesystem, desktop-commander, golang_fs, unity, xmind | 80% (GPT) | YES |
| messaging | slack, discord, gmail, linkedin | 100% (GPT) | NO (이름 구분) |
| (자동 발견) | ... | pilot 결과 대기 | TBD |

---

## 4. 쿼리 설계 (Query Design)

### 4.1 원칙

1. **제품명/서비스명 금지** — "Slack으로 보내줘" ❌ → "팀 채널에 배포 알림 보내줘" ✅
2. **기능 기반 서술** — what을 설명, how/where는 생략
3. **클러스터당 3개 쿼리** — 동일 클러스터에서 다른 각도로 테스트하여 쿼리 의존성 제거
4. **한국어 + 영어** — 벤더 간 다국어 처리 차이 확인

### 4.2 쿼리 생성 방법

각 클러스터에서 target tool의 고유 기능을 기반으로 LLM이 쿼리를 생성:
```
"이 도구의 고유 기능을 사용하고 싶은 상황을 3가지 서술하라.
단, 도구 이름, 서비스명, 회사명은 포함하지 말 것.
기능적 필요만 서술할 것."
```

### 4.3 예시 (web_search 클러스터, target: tavily_search)

| # | 쿼리 | 왜 tavily가 맞는지 |
|---|------|-------------------|
| Q1 | "최근 1주일 내 AI 규제 관련 뉴스를 검색해줘" | date filtering 기능 |
| Q2 | "reddit과 twitter를 제외하고 학술적 소스만 웹 검색해줘" | domain exclusion 기능 |
| Q3 | "웹에서 검색해서 기사 전문을 추출해줘" | content extraction 기능 |

---

## 5. Description 생성 방법

### 5.1 정보 추출 (클러스터당 1회)

Target tool의 원본 description + input_schema에서 4가지 핵심 정보를 추출:
1. **핵심 기능:** 도구가 무엇을 하는지 (1문장)
2. **차별화 기능:** 경쟁 도구와 구별되는 특징 (1-2개)
3. **사용 시나리오:** 언제 이 도구를 써야 하는지 (1문장)
4. **출력 형식:** 무엇을 반환하는지 (1문장)

### 5.2 포맷 변환 (정보 고정, 포맷만 변경)

동일한 4가지 정보를 5가지 포맷으로 변환:

**V_prose (control):**
```
{핵심 기능}. {차별화 기능}. {사용 시나리오}. {출력 형식}.
```

**V_md (GPT-markdown):**
```
{핵심 기능 1문장}

## Key Features
- **{차별화 기능 1}**: {설명}
- **{차별화 기능 2}**: {설명}

## Best For
- {사용 시나리오}
```

**V_xml (Claude-XML):**
```xml
<tool name="{name}">
<description>{핵심 기능}</description>
<capabilities>
<capability>{차별화 기능 1}</capability>
<capability>{차별화 기능 2}</capability>
</capabilities>
<rationale>{사용 시나리오}</rationale>
</tool>
```

**V_spec (Gemini-specsheet):**
```
Tool: {name}
Category: {category}
Function: {핵심 기능}
Features:
  - {차별화 기능 1}
  - {차별화 기능 2}
Returns: {출력 형식}
Use When: {사용 시나리오}
```

### 5.3 검증: 정보 동등성

변환 후 각 variant에서 4가지 정보를 추출하여 동일한지 체크:
- 누락된 정보 = 재작성
- 추가된 정보 = 제거
- 이 단계를 자동화하여 human error 방지

---

## 6. 실험 실행 계획

### 6.1 Phase 1: 클러스터 발견 + Pilot (API 호출 ~100회)

```
MCP-Zero 2,898 tools
  → 동사 그룹핑 + description 유사도 클러스터링
  → 후보 ~20개 클러스터
  → Pilot (V_orig × GPT × 2 reps per cluster)
  → V_orig hit rate < 80% 필터
  → 최종 10개 클러스터 확정
```

**소요:** GPT ~40회 (pilot) + 임베딩 계산 (기존 Qdrant 활용)
**결과물:** `data/experiments/clusters.json`

### 6.2 Phase 2: Description 생성 + 검증 (~0 API 호출)

```
10 clusters × 1 target tool
  → 4가지 핵심 정보 추출 (수동/LLM)
  → 5가지 포맷 변환
  → 정보 동등성 검증
```

**결과물:** `data/experiments/descriptions.json`

### 6.3 Phase 3: 쿼리 생성 + 검증 (~30 API 호출)

```
10 clusters × 3 queries
  → LLM 생성 + 제품명 포함 여부 자동 체크
  → 수동 리뷰
```

**결과물:** `data/experiments/queries.json`

### 6.4 Phase 4: 본 실험 (API 호출 ~4,500회)

```
10 clusters × 3 queries × 5 conditions × 30 reps = 4,500 per vendor

GPT-4o-mini:  4,500 calls → ~$5 → ~15분
Gemini Flash: 4,500 calls → 무료 → ~300분 (15 RPM) → 5시간 (백그라운드)
Claude:       4,500 calls → 서브에이전트 → ~150분 (2초/call)
```

**총 API 호출:** ~13,500 + Phase 1-3 ~130 = **~13,630회**
**총 비용:** ~$5 (GPT) + $0 (Gemini 무료) + $0 (Claude 서브에이전트) = **~$5**
**총 시간:** GPT 15분 + Gemini 5시간(백그라운드) + Claude 2.5시간 = **~8시간 (병렬 시 5시간)**

### 6.5 Phase 5: 통계 분석 + 보고서

```
가설별 검정:
  H1: McNemar's test (paired, V_orig vs V_prose per query)
  H2: McNemar's test (V_prose vs V_vendor_matched)
  H3: McNemar's test (V_prose vs V_wrong_vendor)

보고 항목:
  - p-value per hypothesis per vendor
  - Effect size (Cohen's h)
  - 95% confidence interval for hit rate difference
  - Cluster-level breakdown (어떤 클러스터에서 효과가 큰지)
```

---

## 7. 기대 결과 (Expected Outcomes)

### 7.1 파일럿 기반 예측

| 가설 | GPT | Claude | Gemini |
|------|-----|--------|--------|
| **H1 (정보 효과)** | V_orig ~20% → V_prose ~90% | V_orig ~50% → V_prose ~95% | 예측 불가 |
| **H2 (포맷 특이성)** | V_prose ≈ V_md (차이 없음) | V_prose ≈ V_xml (차이 없음) | TBD |
| **H3 (교차 간섭)** | 간섭 없음 (V_xml ≈ V_prose) | V_md < V_prose (markdown 간섭) | TBD |

### 7.2 시나리오별 해석

**Best case (전부 확인):**
> "Enriched description은 선택률을 +70%p 올린다 (p < 0.001). 또한 GPT-markdown은 Claude 선택률을 -60%p 떨어뜨린다 (p < 0.001). 벤더별 최적화가 필수적이다."

**Partial (정보 효과만):**
> "Description 품질이 선택률을 결정한다 (p < 0.001). 포맷 효과는 유의미하지 않다. Per-client optimization의 가치는 정보 enrichment에 있다."

**Null (효과 없음):**
> "Description 변경은 LLM 도구 선택에 유의미한 영향을 주지 않는다. 선택은 도구 이름과 쿼리-이름 매칭에 의해 결정된다."
> → 이 경우 per-client optimization 기능의 가치 재검토 필요

---

## 8. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| Gemini 429 지속 | 3 벤더 중 1개 누락 | 5초 간격으로 재시도. 실패 시 GPT+Claude만으로 보고 |
| Claude 서브에이전트 ≠ 진짜 tool_use | Claude 결과의 신뢰성 | 보고서에 limitation 명시 |
| 자동 발견 클러스터가 10개 미달 | 일반화 약화 | 수동 보완 (단, 보고서에 명시) |
| 모든 클러스터에서 V_orig이 0% | 정보 효과만 확인, 포맷 비교 불가 | V_prose를 baseline으로 포맷 비교 |
| API 비용 초과 | 예산 초과 | Phase 4에서 5 clusters로 축소 가능 |

---

## 9. Phase 6: Synthetic Traffic Generation (사용량 데이터)

실험과 별도로, GT 쿼리를 실제 파이프라인에 태워 LLM 선택 시뮬레이션 → execution_log에 기록.

### 목적
- operability 시스템에 사용량 데이터 공급 (selection_rate, success_rate)
- 실제 트래픽 없이도 운영 신호 파이프라인(C+D) 점검 가능
- 실험(Phase 4)과 독립 — 실험의 통제 변수에 영향 없음

### 흐름
```
GT 쿼리 474개
  → RAGService.search(query, top_k=5)    ← 실제 파이프라인
  → Top-K 결과를 GPT tool_use로 제시
  → GPT가 선택한 tool_id 기록
  → Supabase execution_log에 INSERT
    (tool_id, server_id, selected=true, source="synthetic")
  → 선택되지 않은 Top-K 도구도 기록
    (tool_id, server_id, selected=false, source="synthetic")
```

### 기록 스키마
```json
{
  "query_id": "gt-atlas-001-s01",
  "query": "Search for GitHub repositories about machine learning",
  "tool_id": "github::search_repositories",
  "server_id": "github",
  "selected": true,
  "source": "synthetic",
  "model": "gpt-4o-mini",
  "timestamp": "2026-04-14T...",
  "top_k_position": 1,
  "top_k_size": 5
}
```

### 규모
- 474 GT 쿼리 × 1 LLM call/query = **474 API calls** (~$0.50)
- 474 × 5 (top-K) = **2,370 execution_log rows**
- 시간: ~5분 (GPT-4o-mini)

### 활용
- `tool_operability_view`에 selection_rate 반영
- Provider 대시보드에서 "내 도구가 몇 번 선택됐는지" 확인 가능
- operability score 계산에 call_count 공급 → cold_start 해소

---

## 10. 결과물 (Deliverables)

| 파일 | 내용 |
|------|------|
| `data/experiments/clusters.json` | 자동 발견 + 필터링된 클러스터 10개 |
| `data/experiments/descriptions.json` | 클러스터별 5 variant descriptions |
| `data/experiments/queries.json` | 클러스터별 3 queries |
| `data/experiments/raw_results.json` | 전체 실험 raw data (13,500+ trials) |
| `data/experiments/statistics.json` | 가설별 p-value, effect size, CI |
| `data/experiments/synthetic_traffic.jsonl` | Phase 6 synthetic selection log (2,370 rows) |
| `docs/experiments/description-optimization-rigorous-report.md` | 최종 보고서 |
