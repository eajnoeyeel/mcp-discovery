# ADR-0004: 벡터 스토어 — Qdrant Cloud Free Tier

**Date**: 2026-03-24
**Status**: accepted
**Deciders**: 프로젝트 설계 단계

## Context

벡터 검색을 위한 스토어가 필요하다. Sequential Strategy Stage 2에서 `server_id` 기반 필터링 + 벡터 검색을 단일 API 호출로 처리해야 한다. 실험 단계이므로 인프라 비용은 최소화해야 하고, 데이터 추가/변경이 잦아 upsert를 지원해야 한다.

## Decision

Qdrant Cloud free tier(1GB)를 벡터 스토어로 사용한다. `mcp_servers`와 `mcp_tools` 두 컬렉션을 운영하며, ID는 `uuid.uuid5(MCP_DISCOVERY_NAMESPACE, tool_id)`로 생성해 upsert-safe를 보장한다.

## Alternatives Considered

### Alternative: FAISS + S3
- **Pros**: 비용 ~$0, 완전 오프라인
- **Cons**: 인덱스 업데이트 시 파일 전체 재생성 필요, payload 필터 직접 구현 필요
- **Why not**: 실험 루프에서 데이터 추가/변경이 잦아 upsert 불가 구조가 치명적

### Alternative: Pinecone
- **Pros**: 관리형, 안정적
- **Cons**: 무료 티어 100MB (Pool 규모 확장 실험 시 부족), 블랙박스
- **Why not**: Qdrant 무료 1GB 대비 용량 1/10, 튜닝 불가

### Alternative: pgvector (Supabase)
- **Pros**: 기존 Postgres와 통합, SQL 친숙
- **Cons**: 기존 Postgres 인프라 없음, payload 필터 대신 SQL 직접 작성 필요
- **Why not**: Qdrant payload 필터 API 대비 개발 부담 큼, 도입 비용 정당화 어려움

### Alternative: OpenSearch Serverless (AWS)
- **Pros**: AWS 네이티브 통합
- **Cons**: 최소 비용 ~$700/월
- **Why not**: 데모 프로젝트 규모에 완전 오버킬

## Consequences

### Positive
- `server_id` 필터 + 벡터 검색 단일 API 호출로 Sequential Strategy Layer 2 구현 단순화
- 무료 1GB로 약 4만 개 Tool 수용 가능 → 실험 단계 인프라 비용 $0
- Upsert 지원으로 데이터 변경 시 전체 재인덱싱 불필요
- 오픈소스(Rust) — 로컬 테스트 가능

### Negative
- 외부 서비스 의존성 → 네트워크 레이턴시 추가
- Free tier 제한 초과 시 유료 전환 필요

### Risks
- Qdrant Cloud 장애 시 검색 파이프라인 전체 중단 → 향후 로컬 Qdrant 폴백 고려
