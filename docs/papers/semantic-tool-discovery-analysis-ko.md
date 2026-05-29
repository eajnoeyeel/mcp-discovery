# Semantic Tool Discovery for LLMs: Vector-Based MCP Tool Selection 분석 노트

> MCP 환경에서 벡터 임베딩 기반 의미 검색으로 도구를 동적 선택하여, 전체 도구 목록을 LLM 컨텍스트에 넣는 대신 top-K개만 제공함으로써 토큰 소비를 99.6% 줄이면서 97.1% hit rate를 달성한 연구.

## 기본 정보

- 논문: [Semantic Tool Discovery for Large Language Models: A Vector-Based Approach to MCP Tool Selection](https://arxiv.org/abs/2603.20313)
- 출처: arXiv:2603.20313v1 (2026-03-19)
- 저자: Sarat Mudunuri (primary contributor), Jian Wan, Ally Qin, Srinivasan Manoharan
- 분류: cs.SE, cs.AI
- 라이선스: CC BY 4.0
- 코드: 오픈소스 공개 예정 (논문 시점 "GitHub repository link coming soon")

## 무엇을 해결하려는가

MCP 기반 시스템에서 LLM에 사용 가능한 모든 도구를 제공하는 "Static Tool Provisioning" 방식의 확장성 문제를 해결한다. 논문이 직접 제시한 4가지 문제점:

1. **토큰 오버헤드**: 도구 스키마(JSON Schema 등)가 도구당 200–800 토큰. 100개 도구면 쿼리 전에 20,000–80,000 토큰 소비
2. **비용**: GPT-4 기준($0.03/1K input tokens), 50,000 토큰의 도구 정의 처리 비용이 요청당 $1.50. 월 1M 요청 시 $1.5M
3. **정확도 저하**: 컨텍스트가 길어지면 LLM 성능이 저하됨 ("Lost in the Middle" [8] 인용). 무관한 도구가 노이즈로 작용
4. **컨텍스트 윈도우 제약**: 128K–200K 토큰 모델도 대화 이력, 검색 문서, 시스템 프롬프트와 경쟁

기존 접근(Static Provisioning, Manual Categorization)의 한계를 짚고, MCP 프로토콜 특화 의미 검색이 연구 공백임을 주장한다.

## 연구 질문 (RQ)

- **RQ1**: 사용자 쿼리와 도구 설명 간 의미 유사도(semantic similarity)로 MCP 도구를 효과적으로 동적 선택할 수 있는가?
- **RQ2**: 의미 기반 도구 필터링이 토큰 효율, 비용, 시스템 성능에 미치는 정량적 영향은?
- **RQ3**: 의미 도구 선택이 전체 도구 제공 대비 LLM 도구 호출 정확도에 어떤 영향을 미치는가?
- **RQ4**: recall과 precision 균형을 위한 최적 파라미터(K, 유사도 임계값, 임베딩 모델)는?

## 핵심 아이디어

- MCP 도구 스키마를 구조화된 텍스트 문서(tool name + purpose + capabilities + parameters)로 변환하여 dense vector embedding 생성
- 사용자 쿼리를 동일 임베딩 공간에 투영하고 유사도 검색으로 top-K 도구만 선택
- 선택된 도구만 LLM 컨텍스트에 주입하여 50–100+개 도구 대신 3–5개만 제공
- 선택적으로 유사도 임계값 필터링과 하이브리드 리랭킹 적용 가능

## 시스템 아키텍처

### Tool Indexing Pipeline
1. Tool Discovery → MCP 서버에서 도구 열거
2. Schema Extraction → 이름, 설명, 파라미터, 제약조건 추출
3. Document Construction → 의미 정보 극대화 텍스트 템플릿 생성
4. Embedding Generation → dense vector 변환
5. Vector Storage → 메타데이터와 함께 벡터 DB에 인덱싱

**Document Construction 템플릿:**
```
Tool: {tool_name}
Purpose: {description}
Capabilities: {expanded_description}
Parameters: {parameter_descriptions}
```

### Query Processing
1. Query Embedding → 쿼리의 dense vector 생성
2. Similarity Search → 벡터 스토어에서 top-K 검색
3. Threshold Filtering (선택) → 유사도 임계값 이하 도구 제거
4. Reranking (선택) → 하이브리드 검색으로 정밀도 개선

### Feedback Loop (선택적)
- 실제 호출된 도구, 태스크 성공/실패, 사용자 피드백 수집
- 임베딩 개선 또는 검색 파라미터 조정에 활용

## 기술 스택

- **벡터 DB**: Milvus Vector Store
- **임베딩 모델**: text-embedding-ada-002 (1536차원)
- **유사도 메트릭**: Dot Product
- **MCP SDK**: Official Python MCP SDK
- **LLM**: GPT-4o (downstream 평가용)
- **언어**: Python 3.10+
- **Top-K 범위**: K ∈ {1, 2, 3, 5, 10}

## 실험 설정

### 데이터셋
5개 MCP 서버, 총 **121개 도구**:

| MCP 서버 | 도구 수 | 도메인 |
|---|---|---|
| Filesystem | 23 | 파일 작업, 디렉토리 관리 |
| MySQL Database | 23 | SQL 쿼리, 스키마 조회 |
| Slack | 34 | 채널 관리, 메시징 |
| GitHub | 31 | 레포 작업, 이슈 트래킹 |
| Time/Weather | 10 | 현재 시간, 날씨 데이터 |

**쿼리 벤치마크**: 140개 쿼리 (5개 서버에 macro-averaged)
- 단순 사실 쿼리: "What files are in /home/user?"
- 태스크 지향 쿼리: "Create a new issue in the backend repository"
- 모호한 쿼리: "Help me with my project"
- 엣지 케이스: 다중 도구 필요 또는 도구 불필요 쿼리

### 평가 지표
- **Precision@K**: 검색된 도구 중 관련 도구 비율
- **Recall@K**: 관련 도구 중 검색된 비율
- **F1@K**: Precision과 Recall의 조화 평균
- **Hit Rate@K**: top-K에 정답 도구가 1개 이상 포함된 쿼리 비율
- **MRR**: 첫 번째 정답 도구의 역순위 평균
- **Token Reduction Rate (TRR)**: 1 − (Tokens_semantic / Tokens_baseline)
- **End-to-End Latency**: 쿼리 → 도구 검색 완료까지 시간(ms)

## 주요 결과

### Table 1: Aggregate Performance (text-embedding-ada-002, 140 queries, 5 servers)

| K | Precision@K | Recall@K | F1@K | Hit Rate@K | MRR | Token Reduction | Latency (ms) |
|---|---|---|---|---|---|---|---|
| 1 | 92.1% | 31.5% | 46.9% | 85.0% | 0.8500 | 99.6% | 87.1 |
| 2 | 70.0% | 48.3% | 57.0% | 95.7% | 0.9036 | 99.6% | 90.2 |
| 3 | 57.6% | 59.6% | 58.4% | 97.1% | 0.9083 | 99.6% | 87.8 |
| 5 | 42.1% | 72.5% | 53.2% | 97.1% | 0.9083 | 99.6% | 87.0 |
| 10 | 26.5% | 90.6% | 40.9% | 98.6% | 0.9107 | 99.6% | 88.1 |

### 핵심 수치 해석
- **K=3이 최적 운영점**: F1 최고(58.4%), Hit Rate 97.1%, MRR 0.91, 토큰 절감 99.6%
- **토큰 절감은 K에 무관하게 99.6%**: K=10에서도 121개 중 10개만 제공하므로 사실상 동일
- **Latency는 모든 K에서 91ms 미만**: 벡터 검색이 LLM 추론 대비 무시할 수 있는 오버헤드
- **MRR은 K≥3에서 ~0.91로 안정화**: 정답 도구가 일반적으로 top-3 이내에 위치

### 서버별 분석 (Table 2 기준)

| 서버 | K=1 Hit Rate | K=3 Hit Rate | K=1 MRR | 특성 |
|---|---|---|---|---|
| GitHub | 88.2% | 100% | 0.8824 | 도메인 어휘가 명확하여 K=2부터 완벽 |
| MySQL | 92.0% | 96.0% | 0.9200 | 가장 높은 K=1 MRR — DB 쿼리가 의미적으로 구별됨 |
| Slack | 88.9% | 94.4% | 0.8889 | K=2에서 안정화, K=10에서 97.2% |
| Filesystem | 84.0% | 96.0% | 0.8400 | 가장 낮은 MRR — 의미 중복(read/write/copy/move) |
| Time/Weather | 65.0% | 100% | 0.6500 | K=1 최저 → K=3에서 100%. 도구 설명이 광범위 |

### 실패 모드 (논문 Section 6.2)
1. **모호한 쿼리**: "Help me with my project" 같은 쿼리는 도메인 구분 불가 → 여러 서버의 도구가 혼합 검색됨
2. **의미적으로 중복되는 도구**: Filesystem의 read_file, write_file, copy_file, move_file이 유사도가 높아 오검색 빈번 → MRR 0.84–0.89로 가장 낮음
3. **크로스 도메인 쿼리**: "Commit the database schema changes to GitHub" 같이 복수 서버 도구가 필요한 경우 단일 쿼리로 양쪽 도구를 모두 검색하기 어려움

## 저자가 명시한 한계 (Section 6.6)

1. **벤치마크 규모**: 5개 서버, 121개 도구, 140개 쿼리 — 실제 엔터프라이즈(수천 도구)에서의 효과는 미검증
2. **단일 임베딩 모델**: text-embedding-ada-002만 평가. 다른 모델(text-embedding-3-large, Qwen3-Embedding 등)과 비교 없음
3. **Single-turn 평가**: 멀티턴 대화에서의 이전 컨텍스트(사용 이력, 누적 상태) 미활용
4. **도구 설명 의존성**: 설명이 빈약한 도구는 임베딩 품질과 무관하게 검색 성능 저하
5. **단일 LLM 평가**: GPT-4o만 사용. 다른 모델에서 최적 K가 다를 수 있음
6. **오프라인 평가만**: 온라인 A/B 테스트 미수행

## 확장성 논의 (Section 6.5)

저자가 직접 제안한 확장 방향:
- **Multi-agent 도구 라우팅**: 에이전트 능력 설명도 임베딩하여 2단계 라우팅(에이전트 선택 → 도구 선택)
- **Cross-organizational 도구 발견**: 조직별 벡터 인덱스를 연합(federated) 검색으로 통합
- **Dynamic tool composition**: 자주 함께 호출되는 도구 시퀀스의 복합 임베딩 학습

## 프로젝트 시사점

### MCP Discovery Platform과의 관계

이 논문은 우리 프로젝트의 **핵심 아키텍처 패턴(벡터 기반 MCP 도구 검색)**과 가장 직접적으로 대응하는 연구다. RAG-MCP(arXiv:2505.03275)와 유사한 접근이며, 서버별 분석과 다양한 K 값 비교 등 평가 지표 구성이 더 상세하다 (이 비교는 프로젝트 자체 판단이며, 이 논문이 RAG-MCP를 직접 비교하지는 않음).

### 직접적으로 근거가 되는 시사점

1. **K=3 최적점 근거**: F1, Hit Rate, MRR 모두 K=3에서 최적 균형 → 우리 시스템의 Retriever 출력 K 설정 참고 가능 (단, 121개 도구/5서버 규모에서의 결과이므로 우리 규모에서 재검증 필요)
2. **토큰 절감 효과 정량화**: 99.6% 토큰 절감은 벡터 기반 검색의 비용 효율성에 강한 근거 제공
3. **Latency 무시 가능**: sub-91ms 검색 지연은 LLM 추론 시간 대비 무시할 수 있음을 입증
4. **도메인별 성능 편차**: 의미적으로 구별되는 도구(GitHub, MySQL)는 낮은 K에서도 높은 성능, 중복 도구(Filesystem)는 더 높은 K 필요 → 우리 시스템의 도구 카테고리별 K 조정 설계에 참고

### 프로젝트 자체 해석 (논문이 직접 제시하지 않은 확장)

1. **DQS와의 연결**: 이 논문은 도구 설명 품질이 검색 성능의 상한을 결정함(한계 #4)을 보여주므로, 우리 DQS 기반 설명 품질 개선이 검색 성능에 직접 기여할 수 있다는 가설을 지지 — 단, 이 논문이 DQS를 다루는 것은 아님
2. **2-Layer 구조 타당성**: Multi-agent 라우팅 논의(Section 6.5)가 우리의 Layer 1(서버) → Layer 2(도구) 구조와 방향이 일치하나, 이 논문은 단일 레이어 검색만 실험함
3. **Reranker 필요성**: Filesystem 서버의 낮은 MRR(0.84)이 의미 중복 도구 간 구별 한계를 보여줌 → 벡터 검색 후 reranking 단계의 필요성을 시사하나, 이 논문은 reranking을 실험하지 않음

### 기존 분석 논문과의 차이점

| 비교 대상 | 이 논문 | 차이점 |
|---|---|---|
| RAG-MCP (arXiv:2505.03275) | Semantic Tool Discovery | 유사 접근. 이 논문이 서버별 분석, 다양한 K 비교, MRR/F1 등 더 상세한 평가 지표를 포함 (프로젝트 자체 비교, 논문에서 RAG-MCP를 직접 인용하지는 않음) |
| JSPLIT (arXiv:2510.14537) | Semantic Tool Discovery | JSPLIT은 taxonomy 기반 분류, 이 논문은 순수 벡터 검색. 상호보완적 |
| MCP-Bench (arXiv:2508.20453) | Semantic Tool Discovery | MCP-Bench는 벤치마크 설계, 이 논문은 검색 시스템 + 자체 벤치마크 |

## 적용 포인트

- **Retriever K 설정**: 논문의 K=3 최적점을 초기 설정으로 참고 (프로젝트 규모에서 재검증 필수)
- **Document Construction 템플릿**: tool name + purpose + capabilities + parameters 구조를 인덱싱 시 참고
- **서버별 성능 편차 대응**: 의미 중복 도구가 많은 카테고리는 K를 높이거나 reranking 적용
- **벤치마크 설계**: 140개 쿼리, 4가지 쿼리 유형(사실/태스크/모호/엣지) 분류 체계를 참고
- **실패 모드 분석**: 모호 쿼리, 의미 중복 도구, 크로스 도메인 쿼리 3가지 실패 패턴을 우리 시스템 평가에 반영

## 한계

- MCP 환경 특화 연구이지만, 121개 도구/5서버/140쿼리로 규모가 작음
- 임베딩 모델 1개(ada-002), LLM 1개(GPT-4o)만 평가하여 일반화 제한
- Single-turn 평가로 멀티턴 대화에서의 컨텍스트 활용 미검증
- Reranking, threshold filtering은 아키텍처에 포함하지만 실험에서 평가하지 않음
- 온라인 A/B 테스트 없이 오프라인 벤치마크만 수행
- 코드가 아직 공개되지 않음 ("coming soon")

## 현재 판단

- 분류: `핵심 아키텍처 참고 논문`
- 프로젝트 활용도: 매우 높음
- 역할: `벡터 기반 MCP 도구 검색` 시스템 설계의 직접 참고자료
- 최종 프로젝트 반영 포인트:
  - K=3 최적 운영점 (규모별 재검증 전제)
  - Document Construction 템플릿
  - 서버/도메인별 성능 편차 분석 프레임
  - 실패 모드 분류 체계

## 관련 research 문서

- [Tool Selection & Retrieval 조사](../research/tool-selection-retrieval.md)
- [Evaluation & Benchmark Design 조사](../research/evaluation-benchmark-design.md)
