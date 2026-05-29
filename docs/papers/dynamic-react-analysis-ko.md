# Dynamic ReAct: Scalable Tool Selection for Large-Scale MCP Environments

> 출처: arXiv:2509.20386 (2025-09-22)
> 저자: Nishant Gaurav, Adit Akarsh, Ankit Ranjan, Manoj Bajaj (Agentr.dev)
> 한 줄 요약: MCP 환경에서 Sonnet 4로 도구 설명을 의미적으로 enrichment하면 Top-5 검색 정확도가 40%→60%로 50% 상대 향상되며, voyage-context-3 임베딩이 OpenAI text-embedding-3-large를 능가함을 실증.

---

## 해결하려는 문제

수백~수천 개의 MCP 도구가 있는 대규모 환경에서 ReAct 에이전트가 모든 도구를 컨텍스트에 로드하는 것이 불가능하다. LLM 컨텍스트 윈도우 제약 내에서 효율적으로 올바른 도구를 선택하는 확장 가능한 아키텍처가 필요하다.

## 핵심 아이디어

- 5가지 점진적 아키텍처를 비교하여 최적의 Search & Load 패턴 도출
- **Description Enrichment**: Sonnet 4로 도구 설명에 "암묵적 기능과 사용 사례"를 추가하여 임베딩 품질 향상
- 임베딩 모델 비교: Voyage AI 모델이 OpenAI 모델을 능가

## 방법론

### 5가지 아키텍처 비교

| 아키텍처 | 방식 | 도구 로딩 |
|----------|------|-----------|
| 1. Direct Semantic Search | 쿼리 → 벡터 검색 → 도구 바인딩 | K>=10 필요 |
| 2. Meta-Tool Query | LLM이 검색 쿼리 구성 후 검색 | K>=10, LLM 오버헤드 |
| 3. **Search & Load** | search_tools + load_tools 메타도구 | **<5개 로드 (최적)** |
| 4. App-Aware Hierarchical | search_apps → search_tools → load_tools | 추가 호출 오버헤드 |
| 5. Fixed Tool Set | 4개 메타도구, 동적 호출 | 긴 대화에서 성능 저하 |

### 임베딩 모델 비교

| 모델 | Top-5 정확도 | Top-10 정확도 |
|------|-------------|---------------|
| OpenAI text-embedding-3-large | 40% | 64% |
| voyage-context-3 | 48% | 68% |
| **voyage-context-3 + Sonnet enrichment** | **60%** | **68%** |
| voyage-3-large | 56% | 68% |
| voyage-3-large + Sonnet enrichment | 56% | 68% |
| voyage-context-3 + Sonnet + BM25 hybrid | 56% | 72% |

### Description Enrichment 방법

- Sonnet 4를 사용하여 기존 도구 문서에 추가 컨텍스트 생성
- 포함 내용: "암묵적 기능(implicit functionalities)과 사용 사례(use cases)"
- 명시적 문서에 없는 기능을 의미적으로 확장
- 구체적 프롬프트 미공개

### Search & Load (권장 아키텍처)

- `search_tools`: 쿼리 기반 벡터 검색으로 후보 도구 식별
- `load_tools`: 선택된 도구를 에이전트 컨텍스트에 동적 로드
- 중복 제거 및 앱당 상한(per-app cap) 적용
- 일반적으로 5개 미만 도구만 로드

## 주요 결과

- **Description Enrichment로 Top-5 정확도 50% 상대 향상** (40% → 60%)
- voyage-context-3가 OpenAI text-embedding-3-large 대비 Top-5에서 +8%p (48% vs 40%)
- Search & Load가 최적 아키텍처: 도구 로딩 50% 감소, 정확도 유지
- Hybrid (BM25 + dense) 검색은 Top-10에서 최고 (72%)이나 Top-5에서는 dense only가 우수

## 장점

- MCP 환경 실측 실험 (이론이 아닌 실제 MCP 서버 사용)
- 5개 아키텍처 점진적 비교로 설계 결정의 근거 제공
- Description Enrichment의 효과를 정량적으로 입증
- 산업 환경(Agentr.dev) 기반의 실용적 접근

## 한계

- 정확한 도구 수/서버 수 미공개 ("proprietary registry")
- Description Enrichment 프롬프트 미공개
- 정량적 메트릭이 Top-5/Top-10 정확도에 한정 (NDCG, MRR 미보고)
- voyage-code-2 등 코드 특화 모델 미비교 (논문 외 관찰)

## 프로젝트 시사점

1. **Description Enrichment 효과**: LLM으로 설명을 보강하면 검색 정확도가 유의미하게 향상 → 프로젝트의 DQS/GEO Score 개선과 방향성 유사 (단, DQS/GEO와는 다른 방법론 — 본 논문은 LLM 기반 자유 형식 enrichment, 프로젝트는 구조화된 품질 점수 기반 접근)
2. **임베딩 모델 선택**: voyage-context-3 > OpenAI text-embedding-3-large (특정 proprietary registry 환경 한정). 단, 프로젝트 DP4에서 voyage-code-2는 금지 (코드 특화, MCP description은 자연어). 다른 MCP 환경에서의 일반화 여부는 미검증
3. **Search & Load 패턴**: 프로젝트의 Bridge MCP Server가 채택해야 할 패턴과 일치 — 모든 도구 로드 대신 동적 검색 후 소수 도구만 컨텍스트에 제공
4. **Enrichment는 인덱싱 시 수행**: 실시간 쿼리가 아닌 도구 등록/인덱싱 시 LLM 기반 설명 보강 수행이 비용 효율적

## 적용 포인트

- **인덱싱 파이프라인**: 도구 등록 시 LLM 기반 Description Enrichment 단계 추가 검토
- **E2 임베딩 실험**: voyage-context-3을 후보 모델로 검토 (단, voyage-code-2 제외 원칙 유지)
- **Bridge 아키텍처**: Search & Load 패턴을 Bridge MCP Server 설계에 반영
- **Provider Analytics**: Enrichment 전후 검색 성능 차이를 Provider에게 보고하는 기능 검토

## 관련 research 문서

- [Tool Selection & Retrieval 조사](../research/tool-selection-retrieval.md)
