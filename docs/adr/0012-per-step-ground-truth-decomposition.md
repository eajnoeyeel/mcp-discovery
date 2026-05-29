# ADR-0012: MCP-Atlas Multi-step GT → Per-Step Single-Tool 분해

**Date**: 2026-03-29
**Status**: accepted
**Deciders**: MCP `tools/call` 프로토콜 분석 + GT granularity 불일치 발견 후 결정
**Supersedes**: 기존 multi-label / Hit@K 접근 (정식 ADR 미작성, 2026-03-29 폐기)

## Context

MCP-Atlas는 multi-step 벤치마크(평균 4.8 tool calls/task)이지만, MCP Discovery의 `find_best_tool`은 **단일 쿼리 → 단일 tool 매칭** 시스템이다. MCP 프로토콜의 `tools/call`이 한 번에 하나의 tool만 호출하는 구조이며, LLM이 복잡한 task를 분해한 후 각 스텝마다 개별적으로 tool discovery를 요청하는 것이 실제 사용 패턴이다.

기존 접근(multi-label `correct_tool_ids` + Hit@K)은 **쿼리 granularity 불일치** 문제를 안고 있었다:

- MCP-Atlas 쿼리: 유저가 LLM에게 말하는 **task-level** 기술 (e.g., "GitHub에서 Python 레포 검색 후 클론")
- `find_best_tool` 입력: LLM이 분해한 **step-level** 쿼리 (e.g., "GitHub 레포 검색")

Task-level 쿼리로 single-tool retrieval을 평가하면, 정답 tool이 여러 개인 상황에서 메트릭이 왜곡된다. Multi-label Hit@K는 이 불일치를 우회하려 한 것이지, 해결한 것이 아니다.

## Decision

MCP-Atlas multi-step task를 **per-step single-tool GT로 분해**한다 (Option C).

1. **분해 방식**: MCP-Atlas 원본 trajectory에서 각 substantive tool call마다, 해당 tool 호출을 유발할 자연어 쿼리를 LLM으로 생성
2. **부분 분해**: 전체 500 task가 아닌 **50~80 task를 선별** 분해하여 ~150~240개 single-step GT 생성 (통계적 충분성: Precision@1 ±10%p @ 95% CI에 ~200개면 충분)
3. **스키마 단순화**: `correct_tool_ids` / `correct_server_ids` multi-label 필드 제거. 모든 GT는 `correct_tool_id` (단일) 사용
4. **task_type**: 분해된 엔트리는 `single_step`으로 표기. `origin_task_id` 필드로 원본 MCP-Atlas task 추적
5. **메트릭 통일**: Hit@K 폐기. 전체 GT에 대해 Precision@1, Recall@K, NDCG@5 통일 적용

### 분해 프로세스

```
MCP-Atlas parquet (500 tasks)
    ↓ 선별 (50~80 tasks, 카테고리/난이도 균형)
    ↓ 보일러플레이트 blocklist 적용
    ↓ LLM per-step query 생성 (trajectory 컨텍스트 포함)
    ↓ Human review (전수 검토)
data/ground_truth/mcp_atlas.jsonl (150~240 single-step entries)
```

### 선별 기준

- MCP-Atlas 36 servers 중 MCP-Zero 308 servers에 존재하는 서버만 대상 (tool pool에 없는 서버의 GT는 무의미)
- 카테고리별 균등 분배 목표
- 보일러플레이트 제외 후 substantive tool이 2개 이상인 task 우선 (분해 효율)

### LLM Query 생성 프롬프트 (핵심)

```
Given this MCP tool and the context of what the user is trying to accomplish:

Tool: {server_id}::{tool_name}
Tool description: {description}
Task context: {original_task_description}
Step position: {n}th step of {total} steps

Generate a natural language query that a user would give to an LLM,
which would lead the LLM to call this specific tool.

Rules:
- The query must be self-contained (no reference to previous steps)
- Do NOT include the tool name or server name in the query
- Write as if a human is asking for help, not describing an API call
```

### 변경되는 스키마

```diff
 # 필수 필드 — 변경 없음
 query_id, query, correct_server_id, correct_tool_id,
 difficulty, category, ambiguity, source,
 manually_verified, author, created_at, task_type

-# Multi-label 필드 (폐기)
-correct_tool_ids: list[str]     # 제거
-correct_server_ids: list[str]   # 제거

+# Lineage 필드 (신규)
+origin_task_id: str | None      # MCP-Atlas 원본 task ID (e.g., "atlas-task-042")
+step_index: int | None          # 원본 trajectory 내 위치 (0-indexed)
```

## Alternatives Considered

### Alternative 1: Multi-label GT + Hit@K (기존 다중 라벨 접근, 정식 ADR 미작성)
- **Pros**: 변환 비용 낮음 (task-level 쿼리 그대로 사용)
- **Cons**: granularity 불일치 미해결, Hit@K가 `find_best_tool`의 실제 사용 패턴과 괴리, Precision@1과 Hit@K 혼용으로 실험 해석 복잡
- **Why not**: 문제를 우회하지 해결하지 않음. "Hit@K가 높다"가 "tool discovery가 잘 된다"를 의미하지 않음

### Alternative 2: Multi-label GT 유지 + Hit@K를 보조 지표로 격하 (Option B)
- **Pros**: 기존 설계 최소 변경
- **Cons**: 보조 지표라도 존재하면 해석 혼란 유발, 불필요한 복잡도
- **Why not**: 우리 실험 규모에서 불필요한 복잡성. 할 거면 제대로 하자

### Alternative 3: MCP-Atlas 전체 500 task 분해
- **Pros**: 최대 GT 확보 (~2400 single-step)
- **Cons**: LLM 생성 + Human review에 3~5일 소요, 테제 증명에 불필요한 규모
- **Why not**: 시간 대비 효용이 낮음. ~250개면 통계적으로 충분

## Consequences

### Positive
- 전체 GT가 single-tool / single-step으로 통일 — 메트릭 해석 단순화
- `find_best_tool`의 실제 입력 패턴과 GT 쿼리의 granularity 일치
- Precision@1 단일 North Star로 일관된 실험 비교 가능
- `correct_tool_ids` / Hit@K 제거로 스키마·평가 코드 단순화
- `origin_task_id` / `step_index`로 원본 MCP-Atlas와의 추적성(traceability) 유지

### Negative
- LLM query 생성 + Human review 비용 (~1일)
- 분해 과정에서 원본 task의 multi-step 컨텍스트 일부 손실 (각 step이 독립 쿼리가 되므로)
- 500개 중 50~80개만 사용하므로 MCP-Atlas 활용률이 낮음 (10~16%)

### Risks
- LLM이 생성한 per-step 쿼리 품질이 낮을 수 있음 → **Human review 전수 검토**로 완화
- 분해된 쿼리가 너무 쉬워질 수 있음 (step-level은 task-level보다 구체적) → **difficulty 재평가** 필수
- MCP-Zero pool과 MCP-Atlas 서버 간 overlap이 적으면 분해 가능 task가 부족할 수 있음 → 선별 전 overlap 확인 선행

## Implementation Notes

- `scripts/convert_mcp_atlas.py` 수정: per-step 분해 모드 추가
- `src/models.py`의 `GroundTruthEntry`: `correct_tool_ids` / `correct_server_ids` 제거, `origin_task_id` / `step_index` 추가
- `docs/design/ground-truth-design.md`: Multi-label 섹션 → Per-step 분해 섹션으로 교체
- Legacy `.claude/rules/eval-workflow.md` was later deleted from the authority set; keep Hit@K out of current eval guidance.

### Implementation Status (2026-04-02, ADR-0013 적용)

**발견된 구현 누락**: `convert_mcp_atlas.py`에 "MCP-Zero에 존재하는 서버만 대상"
선별 기준이 코드로 구현되지 않았음. ADR-0013에서 `--pool-file` 옵션으로 보완.

**올바른 실행 명령** (ADR-0013 이후):
```bash
uv run python scripts/convert_mcp_atlas.py \
  --pool-file data/raw/mcp_zero_servers.jsonl \
  --max-tasks 80
```

기존 `data/ground_truth/mcp_atlas.jsonl` (394 entries)은 pool filter 없이 생성됨.
재생성 시 `mcp_atlas.jsonl.bak-pre-filter`로 백업 후 위 명령 실행.

**Risks 재평가**: "MCP-Zero pool과 MCP-Atlas 서버 간 overlap이 적으면" 위험이
실제로 발생함 (40개 중 11개, 27.5%). ADR-0013으로 이 위험에 대한 blocking gate 추가.
