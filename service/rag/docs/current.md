# RAG Module — Development Status

> Last updated: 2026-04-04

## Current Phase: Plan 1 — RAG Core

**Status**: Complete

## Completed

- [x] Plan 1: RAG Core (2026-04-04)
  - QueryCache (TTL 인메모리 캐시) — `mlp/rag/cache.py`, 6 tests
  - ResultMerger (결과 병합 + 중복 제거) — `mlp/rag/merger.py`, 6 tests
  - SupabaseFallback (Supabase FTS 클라이언트) — `mlp/rag/fallback.py`, 5 tests
  - RAGService (파이프라인 오케스트레이터) — `mlp/rag/service.py`, 8 tests
  - RAGServiceFactory (config → RAGService 빌드) — `mlp/rag/factory.py`, 3 tests
  - E2E test harness (10 시나리오) — `mlp/rag/tests/test_harness.py`
  - `__init__.py` public exports 설정

### Verification Results

```
VERIFICATION REPORT
===================
Tests:     38/38 PASS (100%)
Coverage:  100% (source modules: cache, factory, fallback, merger, service)
Lint:      PASS (ruff check + format clean)
Regression: 기존 tests/ 462 테스트 중 RAG 변경과 무관한 1건 기존 실패 외 전부 PASS

Module Coverage:
  mlp/rag/cache.py      22 stmts  100%
  mlp/rag/factory.py    10 stmts  100%
  mlp/rag/fallback.py   24 stmts  100%
  mlp/rag/merger.py     11 stmts  100%
  mlp/rag/service.py    42 stmts  100%
```

### 개발 중 발견/수정 사항

1. **테스트 위치 변경**: `tests/mlp/rag/` → `mlp/rag/tests/`로 이동 (모듈과 테스트 co-location)
2. **pyproject.toml 수정**: `pythonpath`에 `"."` 추가, `testpaths`에 `"mlp/rag/tests"` 추가
3. **lint 수정**: `test_service.py`에서 `resp1`, `resp2` 미사용 변수 → `await` 호출로 수정 (ruff F841)

## Backlog

- [ ] Lambda handler 리팩토링 (search handler → RAGService 사용)
