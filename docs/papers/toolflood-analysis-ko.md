# ToolFlood: Beyond Selection -- Hiding Valid Tools from LLM Agents via Semantic Covering

> 출처: arxiv:2603.13950
> 한 줄 요약: 악의적 도구가 정당한 도구의 의미적 영역을 "덮어씌우는(semantic covering)" 공격으로 LLM의 도구 선택을 교란하는 보안 위협을 분석한 연구.

---

## 해결하려는 문제

LLM 기반 에이전트가 도구를 선택할 때, 공격자가 악의적 도구(malicious tool)를 등록하여 정당한 도구의 의미적 영역을 "덮어씌우는(cover)" 방식으로 선택을 교란할 수 있는 보안 위협을 분석한다. 개방형 도구 생태계(MCP 등)에서 누구나 도구를 등록할 수 있을 때, 이러한 semantic covering 공격이 얼마나 효과적인지를 검증한다.

## 핵심 아이디어

- **Semantic Covering Attack**: 정당한 도구의 description과 의미적으로 유사하지만 악의적인 기능을 가진 도구를 전략적으로 배치하여, LLM이 정당한 도구 대신 악의적 도구를 선택하도록 유도. 단순 대량 등록이 아닌 임베딩 공간의 기하학적 배치 전략을 사용하는 2단계 공격(1단계: 도구명/설명 생성, 2단계: 탐욕적 선택)
- ToolTweak이 "단일 도구의 description을 조작"하는 것이라면, ToolFlood는 "임베딩 기하학 기반으로 악의적 도구를 전략적 배치하여 의미 공간을 covering"하는 전략
- 도구 생태계의 무결성(integrity)과 신뢰성(reliability)에 대한 근본적인 보안 위협을 제기

## 방법론

### 2단계 공격 전략

**Phase 1 — 몬테카를로 샘플링**: 타겟 쿼리 ��분집합을 반복 추출, LLM으로 각 부분집합에 의미적으로 관련된 다양한 도구 메타데이터 생성 → ~10,000개 후보 도구 풀 생성

**Phase 2 — 탐욕적 선택**: 임베딩 공간에서 남은 쿼리를 가장 많이 커버하는 도구를 반복적으로 선택. 커버 기준: 코사인 거리 <= δ(0.3). 예산 내에서 모든 쿼리를 커버할 때까지 반복. (Budgeted Multi-Cover 문제)

### 공격 목표

Top-K 검색 결과의 모든 슬롯을 악의적 도구로 채워 정당한 도구가 LLM 컨텍스트에 진입하지 못하게 함.

## 주요 결과

### 벤치마크별 공격 성공

| 벤치마크 | 정당 도구 수 | 주입 도구 수 | 독성률 | TDR | ASR |
|----------|-------------|-------------|--------|-----|-----|
| MetaTool | 199 | 171 | 86.3% | 97.2% | 99.0-99.6% (LLM 모델별) |
| **ToolBench** | **11,760** | **145** | **1.2%** | **91%** | **94.6-96.1%** |

- ToolBench에서 **1.2% 독성률로 91% 도미네이션**: 11,760개 도구 중 145개만 주입하면 top-K를 장악
- Random Sybil baseline: 0-4.6% ASR → 전략적 배치의 우월성 입증

### 교차 임베딩 모델 전이성

| 최적화 모델 | 평가 모델 | TDR | ASR |
|------------|----------|-----|-----|
| all-MiniLM-L6-v2 | text-embedding-3-small | 84% | 91.2% |
| all-MiniLM-L6-v2 | text-embedding-3-large | 88.2% | 93.7% |

교차 모델 전이성이 강함 → 특정 임베��� 방어로 해결 불가

### 방어 메커니즘 평가

| 방어 | TDR | ASR | 효과 |
|------|-----|-----|------|
| 없음 (baseline) | 91% | 96.1% | ��� |
| **MMR 리랭킹** | **44.8%** | **~91%** | TDR 절반 감소, ASR 유지 |
| Llama Prompt Guard | 91% | 96.1% | **효과 없음** |

- MMR: 도미네이션은 줄이지만 부분 침투로도 선택 교란 충분
- Prompt Guard: ToolFlood는 프롬프트 인젝션이 아닌 의미적 유사성 기반 → 탐지 불가

## 장점

- 개방형 도구 생태계의 근본적 보안 취약점을 체계적으로 분석
- 실용적인 공격 시나리오를 제시하여 방어 메커니즘 설계의 필요성을 입증
- ToolTweak(개별 도구 조작)과 상호보완적인 관점 제공

## 한계

- ToolTweak과 직접 비교 미수행 (논문은 ToolTweak 코드 미공개와 5개 도구 소규모 설정이 대규모 검색에 부적합하다는 점을 비교 제외 사유로 제시)
- 방어 메커니즘 평가가 제한적 (MMR, Prompt Guard만)
- 실제 MCP 마켓플레이스가 아닌 학술 ���치마크에서만 평가
- 저자 소속 기관 불명확

## 프로젝트 시사점

MCP Discovery Platform은 개방형 MCP 생태계에서 도구를 추천하는 시스템이므로, ToolFlood가 경고하는 semantic covering 공격에 직접적으로 노출된다. 누구나 MCP 서버를 등록할 수 있는 환경에서, 악의적 Provider가 정당한 서버의 의미적 영역을 덮어씌우는 도구를 대량 등록할 수 있다.

이는 다음 시스템 설계에 영향을 미친다:
- **Spec Compliance 검증**: 등록 시 schema validation과 기능 검증으로 악의적 도구 필터링
- **신뢰도 기반 추천**: 검증된 Provider의 도구를 우선 추천
- **이상 탐지**: 기존 도구와 의미적으로 매우 유사한 신규 등록을 감지

architecture.md의 논문 참고 목록에서 ToolFlood를 "Semantic covering attack on tool selection" 기여로 직접 인용하고 있다.

## 적용 포인트

- **Spec Compliance (Provider 필수 기능)**: 등록 시 MCP 스펙 준수 여부 자동 검사 + 의미적 중복 도구 탐지
- **Tool Pool 관리**: 기존 도구와 description 유사도가 비정상적으로 높은 신규 등록 시 경고/심사
- **Provider 신뢰도 모델**: 검증된 Provider vs 미검증 Provider 구분, 신뢰도 기반 추천 가중치
- **보안 모니터링**: semantic covering 패턴 탐지 — 특정 카테고리에 유사 description 도구가 급증하는 이상 탐지

## 관련 research 문서

- [evaluation-metrics.md](../research/evaluation-metrics.md) — 참고 논문 목록에 ToolFlood 포함
