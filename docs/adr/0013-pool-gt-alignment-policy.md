# ADR-0013: Pool-GT Alignment Policy

**Date**: 2026-04-02
**Status**: accepted

## Context

E5 scale sweep 분석 결과 실험 타당성 문제가 발견됨:

- MCP-Zero 292서버 pool에서 GT 40개 서버 중 11개(27.5%)만 포함
- 알파벳 슬라이스 `pool[:50]` = 2 GT servers(airtable + calculator) → E5 sweep 비교 불가
- pool=5(66q)와 pool=292(194q)의 GT set이 달라 "같은 조건의 scale 비교" 자체가 무효
- ADR-0012의 "MCP-Zero 내 서버만 대상" 선별 기준이 `convert_mcp_atlas.py`에 미구현

### 근본 원인 3계층

1. **Specification-Implementation Gap**: ADR-0012 line 42 "MCP-Atlas 36 servers 중
   MCP-Zero 308 servers에 존재하는 서버만 대상"이 인간 큐레이션 의도로만 기록됨 —
   코드 constraint로 구현되지 않음
2. **Pool Selection Logic 오류**: `_load_pool_server_ids()` 내 `sorted_ids[:pool_size]`
   (알파벳 슬라이스) — GT servers가 알파벳 순서 90-245위에 있어 small pool에서 제외됨
3. **Alignment Validation Gate 부재**: GT 변환 후 pool-GT coverage를 수치로 측정하는
   스크립트가 없어 11/40 coverage 상태가 alarm 없이 지속됨

## Decision

### 1. GT-first Pool Ordering

`_load_pool_server_ids(gt_paths=...)` 파라미터 추가:
- GT-covered servers를 pool 앞쪽에 배치 (알파벳순 정렬 within group)
- 나머지 servers는 뒤에 배치 (알파벳순)
- `gt_paths=None`이면 기존 알파벳 정렬 유지 (하위 호환)

효과: pool[:20]만으로 11개 GT servers 전부 포함 (194 queries 고정)

### 2. Pool-GT Alignment Validation Script

`scripts/validate_pool_gt_alignment.py` 신규 생성:
- Pool과 GT 간 coverage 측정 (covered/missing servers, query distribution)
- GT-first ordering 기반 pool_size별 coverage 계산
- HIGH SKEW 경보: 단일 서버 > 25% query 집중 시 경고
- CLI: `--min-coverage` exit gate (0.0 = warn only)

### 3. convert_mcp_atlas.py Pool Filter

`--pool-file` 옵션 추가 → `_process_tasks(allowed_servers=frozenset)`:
- pool에 없는 서버의 tool call steps를 GT 생성에서 제외
- ADR-0012 "MCP-Zero 내 서버만 대상" 기준을 코드로 구현

### 4. Domain Skew 경보

`run_e0.py`에 coverage gate 추가:
- 단일 서버 > 30% query 집중 시 WARNING 로그
- `--min-gt-coverage` CLI arg로 abort threshold 설정 가능

## Consequences

### 긍정적

- E5 sweep: 동일 GT set(194 queries) 유지하며 pool_size만 변경 → 유효한 scale 비교
- ADR-0012 선별 기준이 코드로 구현되어 specification-implementation gap 해소
- 외부 데이터셋 추가 시 alignment check가 표준 gate로 존재

### 부정적/트레이드오프

- 기존 `mcp_atlas.jsonl` (394 entries)는 pool filter 없이 생성됨 — 재생성 필요
  (백업: `mcp_atlas.jsonl.bak-pre-filter`)
- GT-first 정렬로 E0/E5 실험 결과가 이전 실행과 다를 수 있음 (의도된 변경)
- pool=5로 실행 시 5개 GT servers만 포함 — small pool 실험의 의미가 축소됨

## Verification

```bash
# Pool-GT 현황 확인
uv run python scripts/validate_pool_gt_alignment.py \
  --pool data/raw/mcp_zero_servers.jsonl \
  --gt data/ground_truth/seed_set.jsonl data/ground_truth/mcp_atlas.jsonl \
  --pool-sizes 5 20 50 100 200 292

# GT-first 효과 확인 (pool=50에서 all 11 GT servers 포함)
# Expected:
#   pool=5:   5 GT servers
#   pool=20:  11 GT servers, 194 queries (100.0%)
#   pool=50:  11 GT servers, 194 queries (100.0%)
```

## 재발 방지

`docs/design/external-dataset-checklist.md` 참조 — 외부 데이터셋 추가 전 필수 gate.
