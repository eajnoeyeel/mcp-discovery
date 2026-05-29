# Ground Truth 설계 — 스키마, Seed 전략, 품질 규칙

> 최종 업데이트: 2026-03-29
> Pydantic 모델/JSON 예시: `./ground-truth-schema.md`

---

## 스키마 개요

- 파일 형식: **JSONL** (한 줄 = 한 엔트리, Git diff 추적 용이, 스트리밍 로딩 가능)
- 파일 위치: `data/ground_truth/seed_set.jsonl`, `data/ground_truth/synthetic.jsonl`
- 모든 엔트리는 `GroundTruthEntry` Pydantic 모델로 검증

### 필수 필드

| 필드 | 설명 | 지원 지표 |
|------|------|----------|
| `query_id` | 고유 ID (e.g., `gt-search-001`) | 전체 |
| `query` | 자연어 쿼리 | 모든 지표 입력 |
| `correct_server_id` | 정답 MCP 서버 ID (primary, backward compat) | Server Recall@K, MRR, Server Error Rate |
| `correct_tool_id` | 정답 Tool ID — primary tool (`server_id::tool_name`) | Precision@1, Tool Recall@10, NDCG@5, Confusion Rate |
| `difficulty` | easy / medium / hard | 난이도별 Precision@1 분석 |
| `category` | 8개 카테고리 | 도메인별 분석, Taxonomy-gated 평가 |
| `ambiguity` | low / medium / high | 모호도별 분석 |
| `source` | manual_seed / llm_synthetic / llm_verified / external_mcp_atlas / external_mcp_zero | 데이터 품질 추적 |
| `manually_verified` | boolean | seed vs synthetic 구분 |
| `author` | 작성자 ID 또는 모델명 | 출처 추적 |
| `created_at` | ISO 8601 | 버전 추적 |
| `task_type` | `single_step` | 모든 GT는 single-step (ADR-0012 per-step 분해). 분석 필터링용 |

### Lineage 필드 (ADR-0012: Per-Step Decomposition)

| 필드 | 설명 | 용도 |
|------|------|------|
| `origin_task_id` | MCP-Atlas 원본 task ID (e.g., `atlas-task-042`) | 원본 추적 (seed set은 `null`) |
| `step_index` | 원본 trajectory 내 위치 (0-indexed) | 분해 순서 추적 (seed set은 `null`) |

- 모든 GT는 **single-tool / single-step** — `correct_tool_id` 하나만 사용
- MCP-Atlas 분해 엔트리: `origin_task_id` + `step_index`로 원본 trajectory 추적 가능
- ~~`correct_tool_ids` / `correct_server_ids` multi-label 필드는 폐기~~ (ADR-0012)

### 선택 필드

| 필드 | 설명 | 지원 지표 |
|------|------|----------|
| `alternative_tools` | 부분 관련 대안 Tool ID 목록 | NDCG@5 graded relevance (정답=2, 대안=1, 기타=0) |
| `notes` | 어노테이션 메모 | 판단 근거 기록 |

---

## Seed Set 구성 계획 — 80개 수동 작성

### 카테고리별 분배 (8개 x 10개)

| 카테고리 | 쿼리 수 | Easy | Medium | Hard | 대표 서버 |
|----------|---------|------|--------|------|-----------|
| Search | 10 | 4 | 4 | 2 | semantic_scholar, mcp-arxiv, brave_search |
| Code | 10 | 4 | 4 | 2 | github, mcp-code-review |
| Database | 10 | 4 | 4 | 2 | postgres, sqlite, supabase |
| Communication | 10 | 4 | 4 | 2 | slack, gmail, discord |
| Productivity | 10 | 4 | 4 | 2 | notion, todoist, calendar |
| Science | 10 | 4 | 4 | 2 | mcp-arxiv, wolfram_alpha |
| Finance | 10 | 4 | 4 | 2 | stock_api, currency_converter |
| General | 10 | 4 | 4 | 2 | mcp-calculator, weather, translator |
| **총합** | **80** | **32** | **32** | **16** | — |

### 난이도 기준

- **Easy (40%)**: 쿼리에 Tool 이름/핵심 키워드 직접 포함. BM25만으로 찾을 수 있는 수준.
  - 용도: 베이스라인 측정. 이것도 못 찾으면 근본적 문제.
- **Medium (40%)**: 의미적 유사성으로 연결, 직접 키워드 없음. Dense retrieval 필요.
  - 용도: Dense retrieval vs BM25 차이 측정.
- **Hard (20%)**: 모호/다의적, 여러 Tool이 부분 적합. Top-K disambiguation + Confidence 분기 필요.
  - 용도: Confusion Rate, disambiguation, NDCG@5 측정 핵심.

### Ambiguity 분포 가이드라인

- Easy 쿼리: 대부분 Low ambiguity
- Medium 쿼리: Low ~ Medium ambiguity
- Hard 쿼리: Medium ~ High ambiguity
- High ambiguity → `alternative_tools` 필수 기재

---

## 어노테이션 규칙

1. **모든 쿼리: 반드시 하나의 `correct_tool_id`** (ADR-0012). MCP-Atlas multi-step task는 per-step 분해 후 각각 single-tool GT로 변환. 차선은 `alternative_tools`에 기록
2. **`correct_server_id`는 `correct_tool_id`에서 파생 가능하지만 명시적 기재**: Layer 1 독립 평가에 필요
3. **difficulty 판정**:
   - "BM25만으로 찾을 수 있나?" → Easy
   - "임베딩 검색이 필요한가?" → Medium
   - "Top-K disambiguation이 필요한가?" → Hard
4. **ambiguity 판정**: "5명에게 물어보면 같은 Tool을 고를까?" — 5/5 → Low, 3-4/5 → Medium, 2/5 이하 → High
5. **alternative_tools**: ambiguity Medium 이상이면 필수. "이것이 정답이어도 틀렸다고 할 수 없는" Tool들
6. **notes**: 난이도/모호도 분류 근거, 특수 케이스 판단 로직 기록

---

## Synthetic 쿼리 생성 — LLM 기반

### 프로세스

```
Tool Description 입력
    |
LLM (GPT-4o-mini) — Tool당 10개 쿼리 생성
    |
난이도 자동 분류 (LLM에게 Easy/Medium/Hard 태깅 요청)
    |
품질 게이트 (아래 기준)
    |
data/ground_truth/synthetic.jsonl에 저장
```

### 품질 게이트 (Quality Gate)

| 기준 | 측정 방법 | 통과 조건 |
|------|----------|----------|
| 난이도 분포 일치 | seed set 비율과 비교 | 각 비율 차이 < 15% |
| 쿼리 다양성 | 생성 쿼리 간 코사인 유사도 평균 | 평균 유사도 < 0.7 |
| 키워드 누출 | Medium/Hard에 Tool 이름 직접 포함 여부 | 0% |
| 사람 검증 샘플 | 무작위 20% 수동 확인 | 난이도/모호도 판정 일치율 >= 80% |
| Obvious 쿼리 비율 | Tool description과 ROUGE-L >= 0.6인 쿼리 | < 10% |

### 검증 파일럿 절차

1. Seed set 80개 중 20개 선택
2. 해당 20개 Tool에 LLM으로 쿼리 10개씩 생성 (200개)
3. 생성 200개와 seed 20개 비교: 겹침 비율, 난이도 분포 차이, 수동 품질 평가 (1-5점)
4. 품질 게이트 통과 확인 후 나머지 Tool에 확대 생성

---

## 외부 GT 소스 — MCP-Atlas (ADR-0011, ADR-0012)

### MCP-Atlas (Scale AI)

- **출처**: HuggingFace `ScaleAI/MCP-Atlas` (arxiv:2602.00933)
- **규모**: 500 human-authored tasks, 40개 서버, 307 tools
- **품질**: Human-authored (자연어, tool 이름 미포함 → 자연스러운 Medium/Hard 난이도)
- **특성**: Multi-step task (평균 4.8 tool calls/task, min 3, max 17)
- **task_type**: `multi_step` (전체 500개)

### Per-Step 분해 전략 (ADR-0012)

MCP-Atlas는 multi-step 벤치마크이지만, `find_best_tool`은 single-tool retrieval 시스템이다.
MCP `tools/call` 프로토콜이 한 번에 하나의 tool만 호출하며, LLM이 task를 분해한 후 각 스텝마다 개별 tool discovery를 수행하는 것이 실제 사용 패턴이다. 따라서 **task-level 쿼리를 step-level로 분해**하여 single-tool GT로 변환한다.

1. **선별**: 500 task 중 50~80개 선별 (MCP-Zero pool과 overlap하는 서버, 카테고리 균형)
2. **보일러플레이트 blocklist 적용**: 초기화 호출 제거
   - `filesystem_list_allowed_directories`, `cli-mcp-server_show_security_rules`, `desktop-commander_get_config` 등
   - 변환 스크립트에서 `BOILERPLATE_TOOLS` 상수로 관리
3. **Per-step query 생성**: 각 substantive tool call마다 LLM으로 단일 스텝 자연어 쿼리 생성
4. **Human review**: 생성된 쿼리 전수 검토 (difficulty 재평가 포함)
5. **서버/도구 ID 변환**: `github_search_repositories` → `github::search_repositories` (첫 번째 `_` 기준 분리)

### 분해 품질 기준

- 쿼리가 self-contained일 것 (이전 step에 대한 참조 없음)
- tool name이나 server name이 쿼리에 포함되지 않을 것
- difficulty 재평가: step-level 쿼리는 task-level보다 구체적이므로 easy 쪽으로 치우칠 수 있음 → 수동 보정

### 평가 메트릭 (통일)

| 메트릭 | 적용 GT | 의미 |
|--------|---------|------|
| Precision@1 | 전체 | 정확히 정답 1개 매칭 (North Star) |
| Recall@K | 전체 | top-K에 정답 포함 여부 |
| NDCG@5 | 전체 | 순위 품질 (alternative_tools로 graded relevance) |

### 변환 메타데이터

- **query_id 네이밍**: `gt-atlas-{task:03d}-s{step:02d}` (e.g., `gt-atlas-042-s00`, `gt-atlas-042-s01`)
- **source 필드**: `external_mcp_atlas`
- **task_type**: `single_step` (분해 후 모든 엔트리)
- **origin_task_id**: 원본 MCP-Atlas task ID (e.g., `atlas-task-042`)
- **step_index**: 원본 trajectory 내 위치 (0-indexed)
- **검증 규칙**: `manually_verified=True` (Human review 후), `author="scale_ai+llm_decomposed"`
- **변환 스크립트**: `scripts/convert_mcp_atlas.py` (parquet → per-step JSONL)
- **저장 위치**: 원본 `data/external/mcp-atlas/`, 변환 후 `data/ground_truth/mcp_atlas.jsonl`

### GT 통합 전략

| 소스 | 수량 | 역할 | source 필드 |
|------|------|------|------------|
| Self seed | 80 | 자체 도메인 특화 (A/B 서버 포함) | `manual_seed` |
| MCP-Atlas (per-step 분해) | 394 | 외부 human GT 기반 single-step 변환 | `external_mcp_atlas` |
| **합계** | **474개 (MCP-Atlas per-step 394 + seed 80), pool covered 194개** | **Primary GT (all single-step)** | — |
| Synthetic | 838 | 보조 (필요 시 참고) | `llm_synthetic` |

> **Note**: MCP-Atlas 500 task 중 선별 분해. 실제 분해 결과 394개 per-step GT 확보. pool covered 194개 (GT-covered 서버 11개 기준).

---

## 자체 MCP 서버 — A/B Description 실험용

### A/B Pair 구조

| 서버 | Version A (Poor) | Version B (Good) |
|------|-----------------|-------------------|
| `mcp-arxiv` | "A tool for searching papers" | "Search arXiv academic papers by keyword, author, or date range. Returns title, abstract, authors, and PDF link. NOT for web search or news." |
| `mcp-calculator` | "Calculator tool" | "Evaluate math expressions, convert units (metric/imperial, currency with live rates), compute statistics (mean, median, std). NOT for symbolic math." |
| `mcp-korean-news` | "Korean news search" | "Search Korean news from major outlets (조선일보, 한겨레, 연합뉴스 등) by keyword and date. Returns headline, summary, source, URL. NOT for English news." |

### A/B 실험 프로세스

1. 동일 쿼리셋 → Version A Pool, Version B Pool에 각각 실행
2. Precision@1 차이 = **Selection Rate Lift** (primary evidence)
3. 모든 Tool의 (quality_score, selection_rate) → **Spearman** (secondary evidence)
4. 다변량 회귀로 quality 요소별 기여도 = **Regression R-squared** (supplementary evidence)

---

## Pool Construction Rules

**Tool pool 정렬 방식**: `data/tool-pools/base_pool.json`은 모든 292개 MCP-Zero 서버를
GT-first 우선순위로 정렬 (`scripts/build_base_pool.py` 참조):

1. **GT-covered 서버** (11개: MCP-Atlas 40개 ∩ MCP-Zero 292개 겹침) — GT entry 수 내림차순 정렬
2. **나머지 MCP-Zero 서버** (281개) — 알파벳 순 정렬

**Coverage 속성**:
- pool[:N < 11]: 부분 GT coverage (N × ~17 entries 근사)
- pool[:N ≥ 11]: 194 entries로 안정 (E1–E7 기본 pool_size=50 이상 → 항상 194)

**GT-first 정렬이 필요한 이유**: 알파벳 정렬은 pool size별로 GT coverage를 무작위로 변동시켜
E5 Precision@1 저하 곡선을 해석 불가능하게 만듦 (실제 난이도 vs GT 고갈 혼동).
GT-first 정렬로 저하 곡선이 실제 retrieval 난이도를 반영하도록 보장.

---

## 데이터 디렉토리 구조

```
data/
+-- ground_truth/
|   +-- seed_set.jsonl           # 수동 작성 80개
|   +-- mcp_atlas.jsonl          # MCP-Atlas per-step 분해 394개 (primary)
|   +-- synthetic.jsonl          # LLM 생성 + 품질 게이트 통과분 (보조)
|   +-- quality_gate_report.json # 파일럿 검증 결과
+-- external/                    # Git-ignored, 별도 다운로드
|   +-- mcp-zero/                # MCP-Zero 308 servers (repo-local canonical input: servers.json)
|   +-- mcp-atlas/               # MCP-Atlas 원본 (*.parquet)
|   +-- README.md                # 다운로드 방법, 라이선스 정보
+-- tool-pools/
|   +-- base_pool.json           # 기본 50서버 Pool 정의
|   +-- high_similarity_pool.json
|   +-- low_similarity_pool.json
|   +-- description_quality_pool.json  # A/B pair 포함
+-- server-metadata/
    +-- smithery_crawl.json      # Smithery 서버 메타데이터
    +-- self_built/              # 자체 MCP 서버 tools/list 결과
        +-- mcp_arxiv_v1.json / v2.json
        +-- mcp_calculator_v1.json / v2.json
        +-- mcp_korean_news_v1.json / v2.json
```
