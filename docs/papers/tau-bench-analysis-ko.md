# τ-bench 분석 노트

> 사용자-에이전트 동적 대화 환경에서 도메인 규칙 준수와 반복 실행 일관성(pass^k)을 측정하여, tool-agent 상호작용의 신뢰성을 평가하는 벤치마크.

## 기본 정보

- 논문: [$τ$-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains](https://arxiv.org/abs/2406.12045)
- 학회: ICLR 2025 Poster로 채택
- 제출일: 2024-06-17
- 저자: Shunyu Yao (Princeton→OpenAI), Sierra Research, Karthik Narasimhan (Princeton) 외
- 도메인: 2개 도메인 (retail ~114 tasks, airline 50 tasks)

## 무엇을 해결하려는가

기존 benchmark는 도구 사용 자체는 보지만 `사용자와의 상호작용`, `도메인 규칙 준수`, `여러 번 실행했을 때의 일관성`을 잘 보지 못한다. τ-bench는 이 간극을 메우려 한다.

## 핵심 아이디어

- 사용자와 에이전트가 동적으로 대화하는 환경을 만든다.
- 에이전트는 domain-specific API tools와 policy guidelines를 함께 받는다.
- 대화 종료 시 database state와 goal state를 비교해 평가한다.
- 단발 성공률이 아니라 `pass^k`를 도입해 여러 번 실행했을 때의 신뢰성을 측정한다.

논문 abstract 기준으로도 당시 최고 수준 function calling agent가 `50% 미만` task success를 보이고, 반복 실행 일관성도 낮다.

## 우리 프로젝트에 중요한 이유

이 논문은 `추천이 맞았는가`보다 더 중요한 질문을 던진다. 바로 “같은 조건에서 여러 번 돌려도 안정적으로 맞는가”다.

MCP 추천 최적화도 실제 운영에서는 아래가 중요하다.

- 한 번 잘 맞는가
- 반복 실행에도 일관적인가
- 규칙/정책을 어기지 않는가

## 4대 프로젝트 축에 주는 시사점

### 1. 선택 기준/평가 체계

- top-1 accuracy만으로 부족하다.
- `pass^k` 또는 유사한 reliability metric이 필요하다.
- policy compliance와 final state correctness를 별도로 볼 필요가 있다.

### 2. 추천 최적화

- 추천 대상 metadata에 capability뿐 아니라 policy/rule compatibility를 넣어야 할 수 있다. (논문에서 직접 제안한 것은 아니나, 추천 시스템 맥락에서의 확장 해석)

### 3. 로그 기반 개선

- 실제 로그에서 variance와 consistency를 추적해야 한다.
- 동일 질의 반복 시 추천 결과의 안정성을 측정할 필요가 있다.

### 4. 운영/품질 게이트

- 배포 전에 rule-following regression test와 repeated-run reliability gate를 넣는 방향이 타당하다.

## 한계

- MCP registry나 deployment lifecycle 자체를 직접 다루지 않는다.
- 추천 전 retrieval보다 interaction benchmark에 더 초점이 있다.
- 운영 자동화보다는 agent behavior reliability를 평가한다.

## 현재 판단

- 분류: `신뢰성 평가 핵심 논문`
- 프로젝트 활용도: 매우 높음
- 역할: `일관성/정책 준수 평가` 기준
- 최종 프로젝트 반영 포인트:
  - repeated-run reliability
  - policy compliance metric
  - final state based evaluation

## 관련 research 문서

- [Evaluation & Benchmark Design 조사](../research/evaluation-benchmark-design.md)
