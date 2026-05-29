# MCP-Bench: MCP 특화 벤치마크

> 출처: arxiv:2508.20453 (2025), NeurIPS 2025 Workshop 승인
> 한 줄 요약: MCP(Model Context Protocol) 환경에 특화된 벤치마크로, Schema Understanding, Task Completion, Tool Usage, Planning의 4차원 평가 프레임워크를 통해 LLM의 MCP 도구 활용 능력을 종합적으로 평가한다.

---

## 해결하려는 문제

기존 도구 사용(tool-use) 벤치마크들은 일반 API나 REST endpoint를 대상으로 하여, MCP 프로토콜 고유의 특성(서버-도구 계층 구조, 스키마 기반 파라미터, 프록시 실행 등)을 반영하지 못한다. MCP 생태계가 성장함에 따라 MCP에 특화된 평가 체계가 필요하다.

## 핵심 아이디어

- MCP 서버와 도구의 계층적 구조를 반영한 벤치마크를 설계한다.
- 도구 선택(tool selection)뿐 아니라 스키마 이해, 작업 완수, 계획 수립까지 포함하는 종합적 평가를 수행한다.
- 4차원 평가 프레임워크: Schema Understanding (rule-based), Task Completion (LLM-as-judge), Tool Usage, Planning

## 방법론

### 벤치마크 규모

- **28개 MCP 서버**, **250개 도구** 포함
- **20개 LLM** 모델 평가
- Multi-tool coordination 시나리오 포함 (단일 도구 선택이 아닌 복수 도구 연계 평가)

### 4차원 평가 프레임워크

| 차원 | 평가 방식 | 측정 내용 |
|------|-----------|-----------|
| Schema Understanding | Rule-based (결정론적) | MCP 도구 스키마의 파라미터 구조, 타입, 제약조건 이해도 |
| Task Completion | LLM-as-judge | 주어진 작업의 최종 완수 여부 및 품질 |
| Tool Usage | Rule-based + LLM | 올바른 도구 선택 및 파라미터 전달 정확도 |
| Planning | LLM-as-judge | 복수 도구를 연계하는 계획 수립의 적절성 |

- Recall@K 등 표준 IR 지표는 사용하지 않음 — 도구 검색이 아닌 도구 활용 능력 평가에 초점

## 주요 결과

| 모델 | 종합 점수 | 순위 |
|------|-----------|------|
| GPT-5 | 0.749 | 1위 |
| o3 | 0.715 | 2위 |
| ... | ... | ... |
| llama-3-1-8b-instruct | 0.428 | 최하위 |

- 최상위(GPT-5)와 최하위(llama-3-1-8b-instruct) 간 0.321 차이 — MCP 도구 활용 능력에서 모델 간 유의미한 격차 존재
- Schema Understanding에서는 rule-based 평가로 명확한 정량적 비교 가능
- Task Completion은 LLM-as-judge 방식으로 최종 사용자 관점의 품질 평가

## 장점

- MCP 프로토콜의 고유한 특성을 반영한 최초의 MCP 특화 벤치마크
- 서버 레벨과 도구 레벨을 분리하여 평가할 수 있는 구조
- 4차원 평가 프레임워크로 단순 정확도를 넘어선 종합적 능력 평가
- NeurIPS 2025 Workshop 승인으로 학술적 검증
- 20개 LLM 모델에 대한 포괄적 비교 결과 제공

## 한계

- Multi-tool coordination 중심 평가로, 단일 도구 검색/선택 정확도(Precision@1 등) 측정에는 직접 적용 불가
- 28개 서버 / 250개 도구 규모 — 대규모 MCP 생태계(수천 서버) 환경과의 차이 존재
- LLM-as-judge 방식의 Task Completion/Planning 평가는 판정 모델 편향 가능성
- 벤치마크 데이터셋의 도메인 분포 편향 가능성 (공개된 도메인 분포 정보 제한적)

## 프로젝트 시사점

MCP 환경에서의 multi-tool coordination 평가라는 점에서 참고 가능하다. ToolBench/ToolLLM이 일반 API 검색을 다뤘다면, MCP-Bench는 MCP 프로토콜 환경에서의 도구 활용 품질을 특화하여 평가한다.

단, MCP-Bench는 도구 검색/추천이 아닌 도구 활용(사용) 능력 평가에 초점이 맞춰져 있으므로, 본 프로젝트의 검색 파이프라인 평가 지표(Precision@1, Recall@K, MRR 등)와는 직접적으로 대응하지 않는다.

## 적용 포인트

- **Schema Understanding 차원**: MCP 도구 스키마 이해도 평가 방식을 Ground Truth 설계 시 참고 (스키마 복잡도별 난이도 구분)
- **Ground Truth 설계**: MCP-Bench의 쿼리-정답 쌍 형식을 참고하여 seed_set.jsonl 구조 설계
- **실험 설계**: MCP 특화 시나리오(서버 계층 구조, 스키마 기반 매칭)를 포함한 테스트 케이스 설계
- **모델 간 차이**: GPT-5(0.749) vs 오픈소스 최하위(0.428) 격차는 Bridge MCP Server가 다양한 LLM 클라이언트를 지원할 때 고려해야 할 변수

## 관련 research 문서

- [evaluation-metrics.md](../research/evaluation-metrics.md) — 평가 지표 논문 근거
