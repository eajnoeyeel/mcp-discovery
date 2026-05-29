# ADR-0009: 보조 도구 스택

**Date**: 2026-03-24
**Status**: accepted
**Deciders**: 프로젝트 설계 단계

## Context

실험 추적, LLM 트레이싱, 웹 프레임워크, 패키지 관리, 린팅 도구를 선택해야 한다.
각 카테고리에서 여러 옵션이 존재하며, 5주 프로젝트에서 무료로 사용 가능해야 한다.

## Decision

| 역할 | 선택 | 대안 | 이유 |
|------|------|------|------|
| 실험 추적 | W&B | MLflow, TensorBoard | 실험 결과 자동 기록 + 비교 그래프, 무료 |
| LLM 트레이싱 | Langfuse | LangSmith, PromptLayer | LLM 호출 trace + 비용 추적, 오픈소스 |
| 웹 프레임워크 | FastAPI | Flask, Django | Async 네이티브, Pydantic 통합, Lambda 배포 용이 |
| 패키지 관리 | uv | pip, poetry | 가장 빠른 Python 패키지 매니저 |
| 린트/포맷 | ruff | black + flake8 + isort | 단일 도구로 lint + format, 속도 압도적 |
| 테스트 | pytest-asyncio | asynctest | pytest 생태계 통합, `asyncio_mode="auto"` |

## Consequences

### Positive
- W&B + Langfuse로 실험/추적 파이프라인 완성, 무료 tier로 충분
- FastAPI + Pydantic v2 조합으로 타입 안전성 + 자동 OpenAPI 문서
- ruff 단일 도구로 black + isort + flake8 대체 → CI 설정 단순화
- uv로 의존성 설치 속도 대폭 향상

### Negative
- 여러 SaaS 서비스(W&B, Langfuse) 계정 관리 필요
- Langfuse 자체 호스팅 시 추가 인프라 비용

### Risks
- W&B / Langfuse 무료 tier 제한 초과 시 실험 데이터 유실 위험 → 주기적 로컬 백업 권장
