# E4 실험 보고서: Description Enrichment A/B 검증

> Portfolio note: this is a historical experiment report. Cohere rerank-v3.5 was
> used in this archived run as an external reranking baseline; the current public
> runtime does not require Cohere or `COHERE_API_KEY`.

**실험일**: 2026-04-06
**브랜치**: `feat/pool-gt-expansion`
**담당**: MCP Discovery Platform

---

## 1. 실험 목적

**핵심 테제 검증**: "Description 품질 → Tool 선택률 향상"이 우리 production pipeline
(Qdrant dense embedding + Cohere reranker) 상에서 재현되는가?

외부 논문 5편(ToolRet, Tool-DE, MFTR, GEO 등)에서 인과관계가 이미 증명되었으므로,
E4는 원천 증명이 아닌 **pipeline-specific replication study**로 scope를 한정했다.

---

## 2. 실험 설계

| 항목 | 설명 |
|------|------|
| Version A (Control) | 원본 description (`mcp_tools` collection) |
| Version B (Treatment) | Tool-DE enriched description (`mcp_tools_e4_enriched` collection) |
| Enrichment 방식 | Tool-DE: function_summary + when_to_use + key_params (15-25단어 제한) |
| 파이프라인 | Parallel Strategy + Cohere Rerank 3 (rerank-v3.5) |
| Embedding 모델 | text-embedding-3-large |
| Pool 크기 | 320 servers (이전 E0: 292 servers) |
| GT 쿼리 | 2,273개 (MCP-Atlas per-step, pool-covered) |
| Enrichment 대상 | 94개 unique tools (GT coverage 100%) |
| 통계 검정 | Wilcoxon signed-rank test (tool-level) + cluster bootstrap 95% CI |

### Enrichment 예시

| Tool | 원본 | Enriched |
|------|------|----------|
| `whois::whois_domain` | "Looksup whois information about the domain" (6w) | "Retrieves domain registration details, owner contact, expiry date, and registrar info." (13w) |
| `slack::conversations_history` | "Get messages from the channel by channelID" (7w) | "Retrieves message history from a Slack channel; use when reviewing past conversations or finding specific messages." (17w) |
| `git::git_log` | "Shows the commit logs" (4w) | "Retrieves Git commit history with author, date, and message; use to review changes or trace code evolution." (18w) |

---

## 3. 결과

### 3.1 지표 요약

| 지표 | Version A (원본) | Version B (Enriched) | Delta | 방향 |
|------|-----------------|---------------------|-------|------|
| **Precision@1** | 27.76% | 28.73% | **+0.97pp** (+3.49%) | ↑ |
| Recall@K | 49.85% | 46.94% | **-2.92pp** | ↓ |
| Server Recall@K | 53.89% | 53.10% | -0.79pp | ↓ |
| MRR | 35.48% | 34.62% | -0.86pp | ↓ |
| NDCG@5 | 37.13% | 36.13% | -1.00pp | ↓ |
| **Confusion Rate** | 30.57% | 25.56% | **-5.02pp** | ↑ (개선) |
| ECE | 0.046 | 0.054 | +0.008 | ↓ |
| Latency p50 | 631ms | 631ms | ~0ms | — |

### 3.2 통계 검정

| 검정 항목 | 값 |
|----------|-----|
| 검정 방법 | Wilcoxon signed-rank test (tool-level, n=94) |
| Test statistic | 356.0 |
| **p-value** | **0.833** |
| 95% CI (bootstrap) | **[-2.73pp, +6.19pp]** |
| Mean delta (tool-level) | +1.60pp |
| Improved tools | 18 / 94 (19%) |
| Degraded tools | 20 / 94 (21%) |
| No change | 56 / 94 (60%) |

**결론: 통계적으로 유의미하지 않음 (p=0.833 >> 0.05)**

### 3.3 Per-Tool 분석 — 상위 개선/악화 사례

**Best Improvers (δ ≥ +0.25)**

| Tool | Before | After | Delta | 원본 길이 |
|------|--------|-------|-------|-----------|
| `national-parks::getVisitorCenters` | 0.00 | 1.00 | **+1.00** | 9단어 |
| `national-parks::getCampgrounds` | 0.00 | 0.80 | **+0.80** | 8단어 |
| `osm-mcp-server::find_ev_charging_stations` | 0.33 | 1.00 | **+0.67** | 121단어 (장황) |
| `whois::whois_domain` | 0.20 | 0.65 | **+0.45** | 6단어 |
| `slack::conversations_history` | 0.39 | 0.83 | **+0.44** | 7단어 |
| `filesystem::list_directory` | 0.16 | 0.46 | **+0.30** | 9단어 |
| `airtable::search_records` | 0.32 | 0.55 | **+0.23** | 6단어 |

**Worst Degraders (δ ≤ -0.20)**

| Tool | Before | After | Delta | 원본 길이 | 원본 Description |
|------|--------|-------|-------|-----------|-----------------|
| `github::search_users` | 1.00 | 0.50 | **-0.50** | 4단어 | "Search for GitHub users" |
| `national-parks::getParkDetails` | 0.93 | 0.43 | **-0.50** | 8단어 | "Get detailed information about a specific national park" |
| `github::search_repositories` | 0.90 | 0.52 | **-0.38** | 4단어 | "Search for GitHub repositories" |
| `mongodb::collection-schema` | 0.68 | 0.32 | **-0.36** | 6단어 | "Describe the schema for a collection" |
| `open-library::get_authors_by_name` | 0.59 | 0.32 | **-0.27** | 7단어 | "Search for author information on Open Library." |
| `met-museum::search-museum-objects` | 0.61 | 0.36 | **-0.25** | 67단어 | (이미 장문) |
| `git::git_log` | 0.92 | 0.71 | **-0.21** | 4단어 | "Shows the commit logs" |

---

## 4. 해석 및 분석

### 4.1 원본 description 길이별 enrichment 효과

| 원본 길이 | 대상 tool 수 | 평균 delta |
|----------|-------------|-----------|
| 0-5 단어 | 12개 | **-0.111** (악화) |
| 6-10 단어 | 34개 | **+0.058** (개선) |
| 11+ 단어 | 48개 | **+0.018** (미미) |

**관찰**: 짧은 description(0-5단어)은 enrichment로 오히려 악화된다. 이 category의 tool들은
원본 description이 이미 최적의 embedding anchor로 작동하고 있을 가능성이 높다.

### 4.2 핵심 발견: Stage 1 vs Stage 2 최적화의 충돌

우리 pipeline은 2-stage로 구성된다:
- **Stage 1 (Qdrant embedding search)**: description을 벡터로 변환해 cosine similarity로 후보 추출
- **Stage 2 (Cohere reranker)**: 텍스트를 직접 읽고 query-document 관련성 판단

두 stage는 description에 서로 다른 것을 요구한다:

| Stage | 요구 사항 | 최적 description |
|-------|-----------|-----------------|
| Stage 1 (embedding) | 쿼리와 근접한 의미 벡터 | 짧고 핵심 키워드 밀집 |
| Stage 2 (reranker) | 텍스트 comprehension 용이 | 컨텍스트 풍부, 구조적 |

**E4 enrichment는 두 stage 모두에 동일한 description을 사용했다** — 이것이 충돌의 원인이다.

**증거**:
- Confusion Rate: -5.02pp 개선 → enrichment가 reranker(Stage 2)의 도구 구분을 도움
- Recall@K: -2.92pp 악화 → enrichment가 embedding retrieval(Stage 1) 품질을 저하
- `github::search_repositories` (4단어): P@1 0.90→0.52. GT 쿼리가 "search github repos"
  → "Search for GitHub repositories"가 이미 완벽한 embedding match.
  Enrichment 후 "Finds public/private repos by keyword, language, or topic"으로 변경되면서 벡터 드리프트 발생.

### 4.3 external paper와의 비교

| 논문 | 결과 | 우리 E4와의 관계 |
|------|------|----------------|
| Tool-DE (2025) | +8.4pp P@1 improvement (BM25 + reranker) | BM25는 exact keyword match → 단어 추가가 직접 도움됨. Dense retrieval에서는 다름 |
| SAGEO Arena (2025) | Body text GEO가 BM25 retrieval에 -9~-36% 피해 | **우리 결과와 일치**: semantic enrichment가 dense retrieval에 노이즈 |
| ToolRet (2024) | functional signature + example로 P@1 +15% | 시스템이 다름 (separate meta-field 사용, 동일 description 미적용) |

### 4.4 낮은 baseline P@1에 대한 주석

Version A P@1 = 27.76% (목표치 50% 대비 낮음). 원인:
- MCP-Atlas GT는 multi-step workflow task 기반 (avg 4.8 tool calls/task) → per-step 쿼리가 세분화되어 ambiguous
- 320-server pool에는 similar function tool들이 다수 (filesystem 5개, git 4개, search 4개 등)
- Confusion Rate 30%: 1/3의 쿼리가 "근처 server의 비슷한 tool"로 잘못 라우팅됨

---

## 5. 결론

### 현재 E4 결과 요약

> Tool-DE enrichment(15-25단어)를 전체 pipeline(dense embedding + reranker)에 동일하게 적용했을 때,
> P@1은 통계적으로 유의미하게 변하지 않았다 (delta=+0.97pp, p=0.833).
> Confusion Rate는 개선(-5pp)되었으나 Recall은 악화(-2.9pp)되었다.

### 테제 검증 상태

"Description 품질 → Tool 선택률 향상" 테제는 **E4에서 부분적으로 확인되었으나 증명되지 않았다**.

- **확인된 것**: enriched description이 reranker(Stage 2)의 confusion을 줄임 (Confusion Rate -5pp)
- **예상치 못한 것**: embedding retrieval(Stage 1)에서 단어 추가가 벡터 품질을 저하시킴
- **병목**: 두 stage에 동일한 description을 사용하는 단일 field 설계

---

## 6. 다음 단계 제안

### 단기 (E4-v2)

**Stage 분리 실험**: 두 개의 description field를 분리:
- `description` (원본, Stage 1 embedding에 사용)
- `enriched_description` (enriched, Stage 2 reranker에만 추가 컨텍스트로 전달)

이는 SAGEO Arena의 structural metadata 접근법과 유사하다.
Qdrant payload에 `enriched_description` field를 추가하고,
Cohere reranker에 전달하는 document text를
`f"{tool.tool_name}: {tool.description}\n{tool.enriched_description}"`로 구성.

예상 효과: Confusion Rate 개선(-5pp 유지) + Recall 악화 해소 → P@1 통계적 유의미 개선

### 중기 (E5-E6)

- **E5**: Pool scale 검증 (50 → 100 → 200 → 320 servers에서 P@1 변화)
- **E6**: Pool similarity 검증 (tool 간 description 유사도가 높을수록 confusion 증가하는가)

### 제품 시사점

Provider Dashboard에서 description 품질 점수를 제공할 때:
- Stage 1 최적화 가이드라인: 핵심 동작 키워드 밀집, 15단어 이하 권장
- Stage 2 최적화 가이드라인: when_to_use + key_params 추가, 구조적 문장
- 두 가이드라인이 상충할 경우 Stage 1 우선 (recall이 precision보다 중요한 early stage)

---

## 7. 실험 아티팩트

| 파일 | 설명 |
|------|------|
| `data/e4/e4_result.json` | 전체 실험 결과 (per-tool breakdown 포함) |
| `data/e4/enriched_descriptions.jsonl` | 94개 Tool-DE enriched descriptions |
| `scripts/run_e4.py` | 실험 실행 스크립트 |
| `scripts/enrich_descriptions.py` | GPT-4o-mini enrichment 스크립트 |
| `scripts/index_enriched.py` | 증분 Qdrant 인덱싱 스크립트 |
| `src/analytics/statistical.py` | Wilcoxon + cluster bootstrap 구현 |
| `tests/unit/test_statistical.py` | 통계 모듈 테스트 |
