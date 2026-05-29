# Ground Truth Schema — Pydantic 모델, JSON 예시, 검증 규칙

> 최종 업데이트: 2026-03-29
> 설계 개요/Seed 전략: `./ground-truth-design.md`
> ADR: `../adr/0012-per-step-ground-truth-decomposition.md`

---

## Pydantic 모델

```python
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo
from enum import StrEnum
from typing import Literal


class Difficulty(StrEnum):
    EASY = "easy"        # 명시적 키워드 매칭 (e.g., "search papers" → search_papers)
    MEDIUM = "medium"    # 의미적 유사 (e.g., "find academic research" → search_papers)
    HARD = "hard"        # 모호/다의적 (e.g., "help me with my research" → 여러 후보)


class Ambiguity(StrEnum):
    LOW = "low"          # 정답이 하나로 명확
    MEDIUM = "medium"    # 2-3개 후보, 최선 구분 가능
    HIGH = "high"        # 여러 Tool이 비슷하게 적합


class Category(StrEnum):
    SEARCH = "search"
    CODE = "code"
    DATABASE = "database"
    COMMUNICATION = "communication"
    PRODUCTIVITY = "productivity"
    SCIENCE = "science"
    FINANCE = "finance"
    GENERAL = "general"


TOOL_ID_SEPARATOR = "::"


class GroundTruthEntry(BaseModel):
    """단일 Ground Truth 엔트리 — 하나의 (쿼리, 정답 tool) 쌍.

    모든 GT는 single-tool / single-step (ADR-0012).
    """

    # 필수 필드 — 모든 지표 계산에 필요
    query_id: str = Field(description="고유 ID, e.g., 'gt-search-001', 'gt-atlas-042-s00'")
    query: str = Field(description="자연어 쿼리")
    correct_server_id: str = Field(description="정답 MCP 서버 ID")
    correct_tool_id: str = Field(
        description="정답 Tool ID (server_id::tool_name 형식, TOOL_ID_SEPARATOR='::')"
    )

    # 분류 필드 — 세분화 분석용
    difficulty: Difficulty
    category: Category
    ambiguity: Ambiguity

    # 메타데이터 — 품질 관리
    source: Literal[
        "manual_seed",
        "llm_synthetic",
        "llm_verified",
        "external_mcp_atlas",
        "external_mcp_zero",
    ] = Field(description="Origin of this ground truth entry")
    manually_verified: bool = Field(default=False)
    author: str = Field(description="작성자 ID 또는 'gpt-4o-mini' 등")
    created_at: str = Field(description="ISO 8601 날짜")
    task_type: Literal["single_step"] = Field(
        default="single_step",
        description="모든 GT는 single_step (ADR-0012 per-step 분해)"
    )

    # Lineage 필드 — MCP-Atlas 원본 추적 (ADR-0012)
    origin_task_id: str | None = Field(
        default=None,
        description="MCP-Atlas 원본 task ID (e.g., 'atlas-task-042'). Seed set은 None."
    )
    step_index: int | None = Field(
        default=None,
        description="원본 trajectory 내 위치 (0-indexed). Seed set은 None."
    )

    # 선택 필드 — NDCG graded relevance용
    alternative_tools: list[str] | None = Field(
        default=None,
        description="부분 관련 대안 Tool ID 목록 (relevance_grade=1)"
    )
    notes: str | None = Field(
        default=None, description="어노테이션 메모"
    )
```

---

## 필드-지표 매핑

| 필드 | 지원 지표 |
|------|----------|
| `query` | 모든 지표의 입력 |
| `correct_server_id` | Server Recall@K, MRR, Server Error Rate |
| `correct_tool_id` | Precision@1, Tool Recall@10, NDCG@5, Confusion Rate |
| `difficulty` | 난이도별 성능 분석 (Easy/Medium/Hard 그룹별 Precision@1) |
| `category` | 도메인별 성능 분석, Taxonomy-gated 전략 평가 |
| `ambiguity` | 모호도별 분석, Confusion Rate 교차 분석 |
| `alternative_tools` | NDCG@5 graded relevance (정답=2, 대안=1, 기타=0) |
| `manually_verified` | seed set vs synthetic 구분, 품질 기준점 |
| `source` | 데이터 품질 추적 |
| `origin_task_id` | MCP-Atlas per-step 분해 추적 |
| `step_index` | 원본 trajectory 내 위치 추적 |

---

## JSON 예시 (JSONL 형식)

**Easy** — 키워드 직접 매칭 (self seed):
```jsonl
{"query_id":"gt-search-001","query":"find recent papers about transformer architectures","correct_server_id":"semantic_scholar","correct_tool_id":"semantic_scholar::search_papers","difficulty":"easy","category":"search","ambiguity":"low","source":"manual_seed","manually_verified":true,"author":"iyeonjae","created_at":"2026-03-20","task_type":"single_step","origin_task_id":null,"step_index":null,"alternative_tools":["mcp_arxiv::search_arxiv"],"notes":"키워드 'papers'가 명시적으로 매칭됨"}
```

**Hard** — 모호/다의적 (self seed):
```jsonl
{"query_id":"gt-search-003","query":"help me with my research","correct_server_id":"semantic_scholar","correct_tool_id":"semantic_scholar::search_papers","difficulty":"hard","category":"search","ambiguity":"high","source":"manual_seed","manually_verified":true,"author":"iyeonjae","created_at":"2026-03-20","task_type":"single_step","origin_task_id":null,"step_index":null,"alternative_tools":["mcp_arxiv::search_arxiv","google_scholar::search"],"notes":"'research'가 모호 — 논문? 웹 검색? 데이터 분석?"}
```

**External (MCP-Atlas per-step 분해)** — human-authored 기반:
```jsonl
{"query_id":"gt-atlas-042-s00","query":"Search for Python repositories on GitHub with more than 1000 stars","correct_server_id":"github","correct_tool_id":"github::search_repositories","difficulty":"medium","category":"code","ambiguity":"low","source":"external_mcp_atlas","manually_verified":true,"author":"scale_ai+llm_decomposed","created_at":"2026-03-29","task_type":"single_step","origin_task_id":"atlas-task-042","step_index":0,"alternative_tools":null,"notes":"MCP-Atlas task per-step 분해 (step 0 of 3)"}
```

---

## Synthetic 쿼리 생성 프롬프트 템플릿

```text
You are generating test queries for a tool recommendation system.

Tool: {tool_name}
Server: {server_id}
Description: {tool_description}

Generate 10 natural language queries that a user would ask when they need this tool.
Distribute difficulty:
- 4 queries: Easy (contains obvious keywords)
- 4 queries: Medium (semantic match, no direct keywords)
- 2 queries: Hard (ambiguous, could match multiple tools)

For each query, output JSON:
{
  "query": "...",
  "difficulty": "easy|medium|hard",
  "ambiguity": "low|medium|high",
  "notes": "why this difficulty/ambiguity"
}

Rules:
- Do NOT include the tool name in the query
- Vary sentence structures (question, command, description of need)
- Hard queries should genuinely be ambiguous
- Include both English and Korean queries if the tool supports Korean
```

---

## 로딩 유틸리티 인터페이스

```python
from pathlib import Path


def load_ground_truth(
    path: Path,
    difficulty: Difficulty | None = None,
    category: Category | None = None,
    only_verified: bool = False,
) -> list[GroundTruthEntry]:
    """Ground Truth 로딩 + 필터링

    Args:
        path: JSONL 파일 경로
        difficulty: 특정 난이도만 필터
        category: 특정 카테고리만 필터
        only_verified: True면 manually_verified=True만 반환
    """
    ...


def merge_ground_truth(*paths: Path) -> list[GroundTruthEntry]:
    """여러 JSONL 파일 합침 (seed + mcp_atlas + synthetic).
    query_id 중복 검사 수행."""
    ...


def split_by_difficulty(
    entries: list[GroundTruthEntry],
) -> dict[Difficulty, list[GroundTruthEntry]]:
    """난이도별 그룹 분리 — 난이도별 성능 분석용"""
    ...
```

---

## 검증 규칙

### query_id 형식
- Seed set: `gt-{category}-{number}` (e.g., `gt-search-001`)
- A/B 테스트 쿼리: `gt-ab-{server}-{number}` (e.g., `gt-ab-arxiv-001`)
- MCP-Atlas per-step 분해: `gt-atlas-{task:03d}-s{step:02d}` (e.g., `gt-atlas-042-s00`)
- 전체 셋에서 unique해야 함

### tool_id 형식
- 패턴: `{server_id}::{tool_name}` (e.g., `semantic_scholar::search_papers`)
- 구분자 `::` 사용 이유: Smithery qualifiedName에 `/`가 포함되어 단순 `/` 구분자는 모호성 발생
- `correct_server_id`는 `correct_tool_id`에서 `::` 기준으로 split한 첫 번째 부분과 일치해야 함

### 데이터 무결성
- `difficulty`가 hard이면 `ambiguity`는 medium 또는 high
- `ambiguity`가 medium 이상이면 `alternative_tools`는 비어 있지 않아야 함
- `source`가 `manual_seed`이면 `manually_verified`는 True
- `source`가 `external_mcp_atlas`이면 `manually_verified`는 True, `author`는 `"scale_ai+llm_decomposed"`
- `source`가 `external_mcp_atlas`이면 `origin_task_id`와 `step_index`는 non-null
- `created_at`은 유효한 ISO 8601 날짜
- `task_type`은 항상 `"single_step"` (ADR-0012)

### JSONL 형식 규칙
- 한 줄 = 한 엔트리 (줄바꿈 없음)
- Pandas `read_json(lines=True)`로 즉시 DataFrame 변환 가능
- 모든 엔트리는 `GroundTruthEntry.model_validate_json(line)`으로 검증
