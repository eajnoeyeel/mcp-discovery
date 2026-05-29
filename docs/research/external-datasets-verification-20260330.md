# 외부 데이터셋 검증 보고서 — GT 활용 가능성 심층 분석

> 작성: 2026-03-30 | 목적: MCP-Atlas 대안/보완 외부 GT 데이터셋 발굴 및 실제 필드 검증
> 검증 방식: 문서 조사 + HuggingFace API 직접 호출 + GitHub 리포 확인

---

## TL;DR

MCP-Atlas 외에 GT로 활용 가능한 외부 데이터셋을 탐색한 결과, **ToolRet (ACL 2025)**이 가장 유망하나 multi-label 구조와 빈 description 문제가 있고, **MCPToolBench++**는 MCP-native single-step GT를 제공하지만 tool pool이 87개로 작다. 나머지는 execution-based 벤치마크(MCPVerse, MCP-Radar, MCP-Bench)이거나 도메인 불일치(AppSelectBench, ToolBench)로 직접 GT 활용은 어렵다.

**결론: MCP-Atlas per-step 분해 + self seed 80개 전략 유지가 최선. MCPToolBench++ single-step subset을 보조 검증용으로 활용 가능.**

---

## 우리 실험에 필요한 필드 요구사항

데이터셋 평가 기준으로 사용한 필수/선택 필드:

| 필드 | 실험 단계 | 필수 여부 |
|------|----------|----------|
| 자연어 쿼리 (query) | 전체 (E0-E7) | **필수** |
| 정답 tool_id (single) | Precision@1, MRR, NDCG@5 | **필수** |
| 정답 server_id | Server Recall@K, 2-Layer 평가 | **필수** |
| tool description | E4 (Description 품질 실험) | **필수** |
| tool input_schema | Pool 구성, 인덱싱 | 권장 |
| difficulty / ambiguity | 난이도별 분석 | 권장 |
| category | 도메인별 분석 | 권장 |
| alternative_tools | NDCG@5 graded relevance | 선택 |
| retrieval 후보 pool | E5 (Pool 스케일) | 별도 소스 가능 (MCP-Zero) |

---

## 데이터셋별 상세 검증

---

### 1. ToolRet (ACL 2025) ⭐ 신규 발견

- **데이터셋 이름**: ToolRet — Retrieval Models Aren't Tool-Savvy
- **출처**: ACL 2025 Findings, 중국과학기술대학+PKU
- **규모**: 7,961 queries / 44,453 tools
- **포맷**: HuggingFace Parquet (35개 config로 분리)
- **라이선스**: Apache 2.0
- **접근**: `load_dataset("mangopy/ToolRet-Queries", "<config>")` / `load_dataset("mangopy/ToolRet-Tools", "<subset>")`

#### 실제 확인 방식: **API 직접 호출 ✅**

**Query 필드 (실제 확인):**
```
FIELDS: ['id', 'query', 'instruction', 'labels', 'category']
```

**Tool 필드 (실제 확인):**
```
FIELDS: ['id', 'documentation']
documentation = {
  "name": "...",
  "description": "...",
  "doc_arguments": {"type": "object", "properties": {...}},
  // web subset 추가: "category_name", "required_parameters", "optional_parameters", "method"
}
```

**Labels 구조 (실제 확인):**
```json
{
  "id": "toolbench_tool_2857",
  "doc": {"name": "...", "description": "...", ...},
  "relevance": 1
}
```

#### 핵심 발견 — config별 single/multi-label 분포 (API 직접 검증):

| Config | 총 쿼리 (샘플) | Single-label | Multi-label | 빈 description |
|--------|---------------|-------------|-------------|---------------|
| `toolbench` | 301 | 13 (4%) | 288 (96%) | 70개 |
| `metatool` | 200 | 179 (90%) | 21 (10%) | 0 |
| `gorilla-huggingface` | 301 | 301 (100%) | 0 (0%) | 0 |
| `apibank` | 101 | 48 (48%) | 53 (52%) | 0 |
| `toolalpaca` | 94 | 94 (100%) | 0 (0%) | 0 |

#### 직접 제공 필드:
- ✅ query, instruction (자연어 쿼리 + 지시문)
- ✅ labels (정답 tool ID + doc + relevance)
- ✅ tool documentation (name, description, parameters)
- ✅ category (web/code/customized)

#### 가공 가능 필드:
- 🔧 `correct_tool_id`: single-label config에서 추출 가능 (gorilla-*, toolalpaca, metatool)
- 🔧 `server_id`: 없음. tool_id prefix에서 유추 가능하나 MCP 서버 구조와 매핑 불가
- 🔧 `difficulty`: 없음. query-tool embedding 유사도로 자동 추정 가능

#### 부족한 핵심 필드:
- ❌ **server_id**: RapidAPI/HuggingFace API 기반이라 MCP server 개념 없음
- ❌ **MCP tool 구조**: `tools/list` 포맷이 아님 (REST API 또는 HuggingFace model)
- ❌ **difficulty / ambiguity / category (우리 기준)**: 미제공
- ❌ **toolbench config description 품질**: 70/301 쿼리의 정답 tool description이 빈 문자열

#### 주의사항:
- 35개 config가 완전히 다른 데이터 출처에서 온 것으로, config 간 스키마 일관성이 낮음
- web subset의 tool corpus가 37,292개로 거대하지만 MCP tool이 아닌 RapidAPI 기반
- relevance score가 전부 1 (binary) — graded relevance 없음

#### 전체 판정: **제한적 사용**

#### 추천 활용 방식:
- `gorilla-huggingface` (301 single-label, 설명 풍부) + `toolalpaca` (94 single-label)을 **method validation**에 사용
- 우리 파이프라인의 retrieval 성능을 범용 IR 벤치마크와 비교할 때 참조 데이터로 활용
- GT로 직접 사용하기엔 MCP 도메인 불일치 + server_id 부재가 치명적

---

### 2. MCPToolBench++ ⭐ 신규 발견

- **데이터셋 이름**: MCPToolBench++ — Large Scale MCP Tool Use Benchmark
- **출처**: arXiv:2508.07575 (Aug 2025)
- **규모**: 1,509 instances / 87 unique tools / 6 categories
- **포맷**: HuggingFace JSON
- **라이선스**: CC-BY 4.0 (논문), 리포 라이선스 미명시
- **접근**: `load_dataset("MCPToolBench/MCPToolBenchPP")`

#### 실제 확인 방식: **API 직접 호출 ✅**

**Entry 필드 (실제 확인):**
```
FIELDS: ['uuid', 'category', 'call_type', 'tools', 'mcp_tools_dict', 'query', 'function_call_label']
```

**function_call_label 구조 (실제 확인):**
```json
{
  "name": "playwright_iframe_click",
  "step": "1",
  "id": "1",
  "mcp_server": "playwright",
  "similar_tools": [],
  "input": "{\"iframeSelector\":\"#embedFrame\",\"selector\":\"#search-input\"}",
  "output": {"status_code": 200, "result": "{}"}
}
```

**Tool 스키마 (실제 확인):**
```json
{
  "name": "start_codegen_session",
  "description": "Start a new code generation session to record Playwright actions",
  "input_schema": {"type": "object", "properties": {...}}
}
```

#### API 직접 검증 통계:

| 항목 | 값 |
|------|-----|
| 총 엔트리 | ~1,509 |
| Categories (first 200) | browser: 188, filesystem: 12 |
| Call types (first 200) | single: 200 (100%) |
| Description 비어있음 | **0/3,200** (전부 존재) |
| Description 평균 길이 | 42자 (min 17, max 129) |
| Tools per entry | 32 (browser), 11 (filesystem) |

#### 직접 제공 필드:
- ✅ query (자연어)
- ✅ function_call_label.name (정답 tool name)
- ✅ function_call_label.mcp_server (정답 MCP server!)
- ✅ function_call_label.similar_tools (대안 tool 목록)
- ✅ tools[].name, description, input_schema (MCP 포맷)
- ✅ call_type (single/multi)
- ✅ category (browser/filesystem/search/map/finance/pay)

#### 가공 가능 필드:
- 🔧 `tool_id`: `"{mcp_server}::{tool_name}"` 조합으로 생성 가능 (우리 포맷과 일치!)
- 🔧 `server_id`: `function_call_label.mcp_server`에서 직접 추출
- 🔧 `difficulty`: 미제공이나, query-description 유사도로 추정 가능

#### 부족한 핵심 필드:
- ❌ **difficulty / ambiguity**: 미제공
- ❌ **category 다양성 부족**: 실제로 browser와 filesystem이 지배적 (200개 샘플 중 188+12)
- ❌ **tool pool 크기**: 87개 unique tools (우리 target pool 308+ 대비 매우 작음)
- ❌ **서버 수 부족**: mcp_tools_dict 기준 4~6개 MCP 서버에 집중

#### 주의사항:
- HuggingFace Parquet 변환 에러 존재 (일부 JSON 파싱 실패) — 전체 iteration 불가, 대용량 분석 시 직접 GitHub에서 JSON 다운로드 필요
- Description이 짧음 (평균 42자) — E4 description 품질 실험에 사용하기엔 분량 부족
- 쿼리가 매우 구체적/지시적 ("Click the button within the iframe...") — 자연어 탐색 쿼리와 거리 있음

#### 전체 판정: **일부 가공 후 사용 가능**

#### 추천 활용 방식:
- **single-step subset**을 파이프라인 smoke test용으로 활용 (MCP 포맷 호환!)
- `mcp_server` 필드 존재 → server_id 기반 2-Layer 평가 가능
- E0/E1 파이프라인 검증용 소규모 외부 GT로 활용 (regression test 성격)
- 단, primary GT로는 부적합 (pool 작음, 쿼리 자연스럽지 않음, 카테고리 편향)

---

### 3. MCPVerse (2025)

- **데이터셋 이름**: MCPVerse — An Expansive, Real-World Benchmark for Agentic Tool Use
- **출처**: arXiv:2508.16260
- **규모**: 250 tasks / 65 MCP servers / 552 tools
- **포맷**: CSV + JSON (GitHub)
- **라이선스**: Apache 2.0
- **접근**: https://github.com/hailsham/mcpverse

#### 실제 확인 방식: **문서 + GitHub 구조 확인**

**Task 필드:**
```
question, required_MCPs, required_tools, time_sensitivity, complexity, task_type, ground_truth
```

**Tool Registry:** `tool_full.json` — 표준 MCP tool 스키마 (name, description, inputSchema)

#### 직접 제공 필드:
- ✅ question (자연어 쿼리)
- ✅ required_tools (정답 tool 목록)
- ✅ required_MCPs (정답 server 목록)
- ✅ complexity (L1/L2/L3)
- ✅ ground_truth (정답 값)
- ✅ tool registry with descriptions and input schemas

#### 가공 가능 필드:
- 🔧 `tool_id`: tool_full.json에서 `"{server}::{tool_name}"` 조합
- 🔧 Per-step 분해: L2/L3 multi-step task → MCP-Atlas와 같은 분해 가능

#### 부족한 핵심 필드:
- ❌ **single-tool GT**: required_tools가 리스트 (multi-tool). L1만 single-tool일 가능성
- ❌ **difficulty (우리 기준)**: L1/L2/L3는 step 수 기반이지 retrieval 난이도가 아님
- ❌ **ambiguity / alternative_tools**: 미제공
- ❌ **time-sensitive tasks**: 실시간 API 접근 필요 (재현성 문제)

#### 주의사항:
- Outcome-based 평가 (task completion) — tool selection이 아닌 task 성공 여부 측정
- 쿼리가 task description 형태 ("Can you provide the air quality forecast...") — 검색 쿼리보다 지시형
- v1.1에서 deprecated 서버 제거됨 — 데이터 안정성 확인 필요

#### 전체 판정: **제한적 사용**

#### 추천 활용 방식:
- **L1 single-tool tasks만 필터링**하여 보조 GT로 활용 가능
- `tool_full.json` (552 tools)을 MCP-Zero 보완 pool로 활용 — 실제 MCP 서버 기반이라 도메인 일치
- E6 (Pool 유사도) 실험에서 유사 도메인 서버 구성 참조

---

### 4. MCP-Radar (May 2025)

- **데이터셋 이름**: MCP-RADAR — Multi-Dimensional Benchmark for Tool Use
- **출처**: arXiv:2505.16700
- **규모**: 507 tasks / ~50 tools / 6 domains
- **포맷**: 미확인 (anonymous repository)
- **라이선스**: 미명시
- **접근**: https://anonymous.4open.science/r/MCPRadar-B143

#### 실제 확인 방식: **문서만 (anonymous repo)**

**Task 구조 (논문 기반):**
- Precise Answer tasks: query → 단일 정답 값 (Math, Web Search)
- Fuzzy Match tasks: query → 정답 tool sequence + arguments (Email, Calendar, File, Terminal)

#### 직접 제공 필드:
- ✅ query/problem statement
- ✅ ground truth (answer or tool sequence)
- ✅ tool specifications (name, arguments, output format)
- ✅ 5-dimensional evaluation metrics

#### 부족한 핵심 필드:
- ❌ **tool_id / server_id**: MCP 서버 매핑 불명확
- ❌ **tool description quality data**: tool spec은 있으나 description 품질 분석 없음
- ❌ **single-tool retrieval GT**: Precise tasks는 answer-based, Fuzzy는 tool sequence
- ❌ **라이선스 미명시**: 상업적/학술적 사용 가능 여부 불명
- ❌ **재현성**: anonymous repo로 장기 접근성 미보장

#### 전체 판정: **부적합**

#### 추천 활용 방식:
- 5-dimensional 평가 프레임워크 (accuracy, tool selection, resource efficiency, parameter construction, speed)를 우리 metric 설계 참고로만 활용
- GT 데이터로 사용 불가

---

### 5. ToolBench / StableToolBench (ICLR 2024 / ACL 2024)

- **데이터셋 이름**: ToolBench (OpenBMB) / StableToolBench
- **출처**: arXiv:2307.16789 (ICLR 2024 Spotlight)
- **규모**: 16,464 APIs / 126,486 instruction pairs / 3,451 high-quality tools
- **포맷**: JSON/JSONL (GitHub + HuggingFace)
- **라이선스**: Apache 2.0
- **접근**: https://github.com/OpenBMB/ToolBench

#### 실제 확인 방식: **문서 + 구조 확인**

**핵심 한계 (ToolRet 논문에서 지적):**
- Task당 10-20개 pre-selected tool만 제공 → 대규모 pool에서의 retrieval 평가 불가
- G1 (single-tool) split 존재하나, 후보 pool이 극소 (retrieval 난이도 없음)
- RapidAPI 기반 → MCP tool 구조와 불일치

**StableToolBench 개선점:**
- API 불안정성 해결 (virtual API server)
- 평가 일관성 개선 (SoPR, SoWR)
- 765 solvable tasks로 축소

#### 전체 판정: **부적합** (tool retrieval이 아닌 function calling 벤치마크)

#### 추천 활용 방식:
- 3,451개 high-quality RapidAPI tool description을 description 품질 분석 참고 자료로 활용
- 방법론 참고만 (SoPR 같은 solvable filter 개념은 우리 GT 품질 게이트에 참고 가능)

---

### 6. AppSelectBench (Microsoft, Nov 2025)

- **데이터셋 이름**: AppSelectBench — Application-Level Tool Selection
- **출처**: arXiv:2511.19957
- **규모**: 100 apps / 100K+ tasks
- **라이선스**: CC-BY-SA 4.0

#### 전체 판정: **부적합** (도메인 불일치)

데스크톱 애플리케이션 선택 (Word, Excel, Chrome 등)이 대상. MCP tool/API 선택과 완전히 다른 도메인. multi-label GT 구조도 우리 single-tool 요구사항과 불일치.

---

### 7. MCP-Bench (Accenture, NeurIPS 2025 Workshop)

- **데이터셋 이름**: MCP-Bench
- **출처**: arXiv:2508.20453
- **규모**: 28 servers / 250 tools
- **라이선스**: Apache 2.0
- **접근**: https://github.com/Accenture/mcp-bench

#### 실제 확인 방식: **문서 확인**

Execution-based E2E 벤치마크. LLM agent가 실제로 MCP 서버에 tool call을 보내고 결과를 평가.

#### 전체 판정: **제한적 사용**

#### 추천 활용 방식:
- Bridge proxy 구현 (Phase 13) 참고
- 28개 MCP 서버의 tool registry를 pool 보강 데이터로 참고 가능
- GT로는 부적합 (task completion 기반, tool selection GT 없음)

---

### 8. MCPBench (ModelScope)

- **데이터셋 이름**: MCPBench
- **출처**: https://github.com/modelscope/MCPBench
- **규모**: Web Search 200 QA + DB Query + GAIA
- **용도**: MCP 서버 성능 비교 (같은 task를 다른 MCP 서버로 수행)

#### 전체 판정: **부적합**

서버 간 성능 비교가 목적이지, tool selection GT를 제공하지 않음.

---

### 9. MCPMark

- **데이터셋 이름**: MCPMark
- **출처**: https://github.com/eval-sys/mcpmark
- **용도**: MCP 서버 stress-testing

#### 전체 판정: **부적합**

스트레스 테스트 벤치마크. tool selection과 무관.

---

## 실험 단계별 활용 가능성 종합

| 실험 | MCP-Atlas (기존) | ToolRet (신규) | MCPToolBench++ (신규) | MCPVerse (신규) | 비고 |
|------|-----------------|---------------|---------------------|----------------|------|
| **E0** (1L vs 2L) | ✅ Primary GT | ❌ server_id 없음 | 🔧 가능 (소규모) | 🔧 L1만 가능 | MCPToolBench++로 smoke test 가능 |
| **E1** (전략 비교) | ✅ Primary GT | ❌ MCP 불일치 | 🔧 가능 (소규모) | ❌ multi-tool | — |
| **E2** (임베딩) | ✅ Primary GT | ⚠️ 참조 비교용 | 🔧 가능 | ❌ | ToolRet의 retrieval 결과와 비교 가능 |
| **E3** (Reranker) | ✅ Primary GT | ❌ | ❌ | ❌ | 외부 데이터 추가 불필요 |
| **E4** (Description) | ✅ + self seed | ❌ | ⚠️ desc 짧음 | ❌ | Description Smells가 더 적합 |
| **E5** (Pool 스케일) | ✅ | ❌ | ❌ | 🔧 552 tools pool | MCPVerse tool registry로 pool 보강 |
| **E6** (Pool 유사도) | ✅ | ❌ | ❌ | 🔧 domain 참조 | — |
| **E7** (GEO 점수) | ✅ | ❌ | ❌ | ❌ | Description Smells가 핵심 |

---

## 우리 GT 요구사항 충족도 비교

| 요구 필드 | MCP-Atlas | ToolRet | MCPToolBench++ | MCPVerse |
|----------|-----------|---------|----------------|----------|
| 자연어 query | ✅ | ✅ | ⚠️ 지시형 | ⚠️ task형 |
| single correct_tool_id | 🔧 분해 필요 | ⚠️ config 의존 | ✅ | ❌ multi |
| server_id | 🔧 변환 필요 | ❌ 없음 | ✅ mcp_server | ✅ required_MCPs |
| tool description | ✅ (307 tools) | ⚠️ 일부 빈값 | ✅ (평균 42자) | ✅ (552 tools) |
| input_schema | ✅ | ⚠️ 일부만 | ✅ | ✅ |
| difficulty | ❌ 수동 추가 | ❌ | ❌ | ⚠️ L1/L2/L3 |
| MCP 도메인 일치 | ✅ | ❌ REST API | ✅ MCP native | ✅ MCP native |
| Human-authored | ✅ Scale AI | ❌ LLM+template | ❌ template | ⚠️ 반자동 |
| 라이선스 | ✅ | ✅ Apache 2.0 | ⚠️ 미확인 | ✅ Apache 2.0 |

---

## 최종 권장 전략

### Primary GT (변경 없음)
- **MCP-Atlas per-step 분해** (~150-240) + **self seed** (80) = ~230-320개
- 이유: human-authored, MCP 도메인 일치, single-step 변환 가능, 가장 높은 품질

### 보조 활용 (신규 추가 권장)

1. **MCPToolBench++ single-step subset** → E0/E1 파이프라인 regression test
   - `call_type="single"` 필터, `mcp_server` → `server_id` 변환
   - tool_id = `"{mcp_server}::{tool_name}"` 자동 생성
   - 200-300개 단위로 빠른 파이프라인 검증 가능

2. **MCPVerse tool registry** (`tool_full.json`, 552 tools) → E5 Pool 확장
   - MCP-Zero 308 + MCPVerse 65 서버 = 더 큰 pool 구성 가능
   - 단, 중복 서버 확인 필요

3. **ToolRet gorilla-huggingface/toolalpaca** → method validation
   - 우리 retrieval 파이프라인 성능을 범용 tool retrieval 벤치마크와 비교
   - 논문에서 "기존 IR 모델은 tool retrieval에 약하다" 결론 → 우리 2-stage의 우위 논증 가능

### 사용 제외 (확정)
- MCP-Radar: 라이선스 미확인, anonymous repo, tool selection GT 부재
- ToolBench/StableToolBench: pre-selected pool이라 retrieval 평가 무의미
- AppSelectBench: 도메인 불일치 (데스크톱 앱)
- MCPBench/MCPMark: 서버 성능 비교/스트레스 테스트 목적

---

## 액션 아이템

### 즉시 (이번 스프린트)
1. ~~MCP-Atlas per-step 분해~~ (기존 계획 유지)
2. **MCPToolBench++ single-step subset 다운로드** → `data/external/mcptoolbench/`
   - GitHub에서 JSON 직접 다운로드 (HuggingFace Parquet 변환 에러 있음)
   - 변환 스크립트: `scripts/convert_mcptoolbench.py` (field mapping → GroundTruthEntry)

### 다음 스프린트
3. MCPVerse `tool_full.json` 다운로드 → E5 pool 확장 검토
4. ToolRet gorilla/toolalpaca subset으로 retrieval 성능 cross-validation 설계

### 논문 작성 시
5. ToolRet 논문 인용: "기존 IR 모델은 Recall@10 < 52%" → 우리 2-stage 파이프라인의 차별점 강조
6. MCPToolBench++ 인용: 외부 MCP-native 데이터에서도 파이프라인 작동 확인 (external validity)

---

## 링크 모음 (기존 + 신규)

| 자원 | 링크 | 상태 |
|------|------|------|
| ToolRet GitHub | https://github.com/mangopy/tool-retrieval-benchmark | ✅ 공개 |
| ToolRet Queries (HF) | https://huggingface.co/datasets/mangopy/ToolRet-Queries | ✅ API 검증 완료 |
| ToolRet Tools (HF) | https://huggingface.co/datasets/mangopy/ToolRet-Tools | ✅ API 검증 완료 |
| ToolRet 논문 | https://arxiv.org/abs/2503.01763 | ACL 2025 |
| MCPToolBench++ GitHub | https://github.com/mcp-tool-bench/MCPToolBenchPP | ✅ 공개 |
| MCPToolBench++ HF | https://huggingface.co/datasets/MCPToolBench/MCPToolBenchPP | ⚠️ Parquet 에러 |
| MCPToolBench++ 논문 | https://arxiv.org/abs/2508.07575 | Aug 2025 |
| MCPVerse GitHub | https://github.com/hailsham/mcpverse | ✅ 공개 |
| MCPVerse 논문 | https://arxiv.org/abs/2508.16260 | Aug 2025 |
| MCP-Radar 논문 | https://arxiv.org/abs/2505.16700 | May 2025 |
| MCP-Radar Repo | https://anonymous.4open.science/r/MCPRadar-B143 | ⚠️ Anonymous |
| MCP-Bench GitHub | https://github.com/Accenture/mcp-bench | ✅ Apache 2.0 |
| MCPBench GitHub | https://github.com/modelscope/MCPBench | ✅ 공개 |
| ToolBench GitHub | https://github.com/OpenBMB/ToolBench | ✅ Apache 2.0 |
| StableToolBench | https://zhichengg.github.io/stb.github.io/ | ✅ 공개 |
| AppSelectBench | https://microsoft.github.io/appselectbench/ | CC-BY-SA 4.0 |
