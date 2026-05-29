# ADR-0011: 외부 데이터셋(MCP-Zero, MCP-Atlas) 활용 전략

**Date**: 2026-03-28
**Status**: accepted
**Deciders**: Synthetic GT 수동 검증 과정에서 구조적 문제 발견 후 결정

## Context

자체 Synthetic GT(838개, gpt-4o-mini) 수동 검증 중 3가지 구조적 문제 발견: (1) Ambiguity 과소평가 — 생성 프롬프트가 tool 하나만 보여줌, (2) Difficulty 기준 모호 — LLM이 감으로 판단, (3) 크로스-서버 대안 미반영 — `alternative_tools`가 같은 서버 내부만 참조. 외부 리서치 결과, 이미 고품질 데이터셋(MCP-Zero 308 servers/2,797 tools, MCP-Atlas 500 human-authored tasks)과 관련 논문(Description Smells: +11.6% selection rate, p<0.001)이 존재. 바퀴를 재발명하지 않고 가져다 쓴다.

## Decision

1. **Tool Pool**: MCP-Zero 308 servers (2,797 tools) 기반으로 확장. 기존 Smithery 크롤링 데이터(8 servers)는 보조 소스로 유지.
2. **Ground Truth**: MCP-Atlas per-step 분해 ~150-240 single-step GT + 자체 seed 80 = ~230-320 primary GT (ADR-0012). Synthetic GT(838)는 보조 자료로 격하.
3. **Description 품질 평가**: GEO Score 6차원 + Description Smells 4차원(Accuracy/Functionality/Completeness/Conciseness) 병행 비교.
4. **Distractor 설계**: MCPAgentBench 방식(정답 + 비슷한 distractor 혼합) 참고하여 E6 ambiguity 평가 체계화.

## Alternatives Considered

### Alternative 1: 자체 Synthetic GT만 계속 사용
- **Pros**: 외부 의존성 없음, 기존 파이프라인 유지
- **Cons**: 구조적 품질 문제 해결에 수주 소요, human review 비용 높음
- **Why not**: 시간 대비 품질 개선 효율이 낮음

### Alternative 2: 대규모 자체 데이터셋 구축
- **Pros**: 완전한 커스터마이징, 도메인 특화
- **Cons**: 4주+ 소요, 인력 부족, 마감 2026-04-26 촉박
- **Why not**: 바퀴 재발명 — 이미 고품질 데이터가 존재

### Alternative 3: MCP-Atlas만 단독 사용 (자체 seed 제거)
- **Pros**: 단일 소스로 관리 단순
- **Cons**: MCP-Atlas는 36 servers만 커버, 우리 특화 도메인(한국어 뉴스, 학술 검색 등) 미포함
- **Why not**: 자체 seed가 E4 A/B 테스트에 필수 (자체 MCP 서버의 Version A/B 포함)

## Consequences

### Positive
- 데이터 준비 시간 수주 → 수일로 단축
- Human-authored GT(MCP-Atlas)로 품질 대폭 향상
- 308 servers로 E5 Pool Scale 실험이 의미 있는 규모로 확장
- Description Smells 논문과의 직접 비교로 학술적 정당성 확보
- text-embedding-3-large 벡터(MCP-Zero 제공)로 E2 실험 조건 추가 (재임베딩 비용 없음)

### Negative
- 외부 데이터셋 가용성에 의존 (다운로드 필요)
- MCP-Atlas parquet → JSONL 포맷 변환 스크립트 작성 필요
- MCP-Atlas는 36 servers만 커버 — 308 servers 중 나머지는 GT 없음

### Risks
- MCP-Atlas 라이선스 조건 확인 필요 (Scale AI, 학술 목적)
- MCP-Zero 서버 표현이 우리 MCPServer/MCPTool 모델과 완전히 맞지 않을 수 있음 → 변환 스크립트에서 처리
- 외부 GT와 자체 seed 간 서버 중복 시 충돌 가능 → query_id 네이밍으로 분리 (`gt-atlas-*` vs `gt-{category}-*`)
