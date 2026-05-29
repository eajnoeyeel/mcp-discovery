# AgentBoard 분석 노트

> multi-turn LLM agent의 평가에서 최종 성공률 외에 progress rate, subgoal, trajectory 등 세밀한 분석 지표를 도입한 통합 평가 프레임워크.

## 기본 정보

- 논문: [AgentBoard: An Analytical Evaluation Board of Multi-turn LLM Agents](https://arxiv.org/abs/2401.13178)
- 학회: NeurIPS 2024 (Oral)
- 최초 제출일: 2024-01-24
- 최신 arXiv 개정 확인일: v2, 2024-12-23
- 저자: Chang Ma 외
- 벤치마크 규모: 9개 task, 1013 environments, 4 categories (Embodied AI, Game, Web, Tool), 12 SOTA models

## 무엇을 해결하려는가

AgentBoard는 multi-turn LLM agent를 평가할 때 단순 성공률만으로는 행동 특성과 실패 원인을 이해하기 어렵다는 문제를 다룬다.

핵심 문제는 아래와 같다.

- 다양한 환경에서 agent를 일관되게 평가할 수 있는가
- multi-round interaction을 분석적으로 해석할 수 있는가
- 최종 성공 외에 intermediate progress를 추적할 수 있는가

## 핵심 아이디어

- 부분 관측 환경과 multi-round interaction을 포함한 통합 benchmark를 제공한다.
- `progress rate` 같은 세밀한 분석 지표를 도입한다.
- subgoal, trajectory, grounding 등 행동 분석 도구를 함께 제공한다.
- 주요 결과: GPT-4 기준 progress rate 79.2% (easy) / 62.7% (hard), success rate 65.6% (easy) / 34.4% (hard). Easy→hard 평균 31.2% 하락.

## 우리 프로젝트에 중요한 이유

MCP 추천 최적화도 결국 agent behavior의 일부이므로, 잘못된 추천을 단순 실패 한 줄로만 보면 개선이 어렵다. AgentBoard는 `과정 분석`의 필요성을 강하게 보여준다.

- retrieval은 맞았지만 invocation이 틀렸는가
- 후보는 맞았지만 장기 상호작용에서 무너졌는가
- grounding/상태 추적이 약해서 실패했는가

이런 구분은 향후 로그 기반 개선에 중요하다.

## 4대 프로젝트 축에 주는 시사점

### 1. 선택 기준/평가 체계

- 최종 성공률 외에 progress, subgoal completion, trajectory quality가 필요하다.

### 2. 추천 최적화

- 추천기는 단일 선택 모듈이 아니라 agent loop의 일부로 평가해야 할 가능성이 크다.

### 3. 로그 기반 개선

- 로그는 final outcome만 저장하면 부족하다.
- intermediate state, candidate set, rejected options, retry path도 저장해야 분석이 가능하다.

### 4. 운영/품질 게이트

- 배포 전 분석형 regression dashboard가 있으면 좋다.
- 단순 pass/fail 외에 failure pattern drift를 감지할 필요가 있다.

## 한계

- MCP 자체나 registry lifecycle을 직접 다루지 않는다.
- 추천 모델보다는 agent evaluation framework에 가깝다.
- 실운영 보안/호환성 관점은 약하다.

## 현재 판단

- 분류: `분석형 평가 참고 논문`
- 프로젝트 활용도: 높음
- 역할: `실패 원인 분석 체계` 참고
- 최종 프로젝트 반영 포인트:
  - progress metric
  - trajectory logging (논문 본문에서 trajectory 분석 방법론의 구체적 정의 확인 필요 — abstract에서는 "analytical evaluation"으로 포괄적으로 기술)
  - subgoal-aware evaluation (논문은 각 데이터 샘플에 대해 subgoal을 수동 annotation하고 progress rate를 subgoal 완료 비율로 정의함 — subgoal은 핵심 기여의 일부)

## 관련 research 문서

- [Evaluation & Benchmark Design 조사](../research/evaluation-benchmark-design.md)
