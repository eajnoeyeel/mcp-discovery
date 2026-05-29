# StableToolBench 분석 노트

> 실제 API 상태 변화로 인한 벤치마크 불안정 문제를 virtual API server와 caching system으로 해결하여, 재현 가능한 대규모 tool learning 벤치마크를 구축한 연구.

## 기본 정보

- 논문: [StableToolBench: Towards Stable Large-Scale Benchmarking on Tool Learning of Large Language Models](https://arxiv.org/abs/2403.07714)
- 제출일: 2024-03-12 (현재 v5, 2025-03-05로 업데이트됨)
- 저자: Zhicheng Guo 외

## 무엇을 해결하려는가

StableToolBench는 대규모 tool benchmark가 현실 API 상태 변화 때문에 불안정해진다는 문제를 해결하려 한다.

- hand-crafted benchmark는 규모가 작다.
- real online API benchmark는 API status가 바뀌어 재현성이 나빠진다.

즉, 이 논문은 성능 향상보다 `benchmark stability` 자체를 핵심 문제로 본다.

## 핵심 아이디어

- ToolBench를 기반으로 virtual API server를 도입한다.
- caching system과 API simulators로 실 API 상태 변화 문제를 줄인다.
- GPT-4 기반 자동 평가기와 pass/win rate (Solvable Pass Rate, Solvable Win Rate) 정의를 통해 평가 랜덤성을 낮춘다.

## 우리 프로젝트에 중요한 이유

우리 프로젝트 3번 축인 `실제 사용 로그 기반 측정, 테스트, 피드백 루프`와 강하게 연결된다. 추천 시스템은 좋아 보여도 benchmark가 흔들리면 개선 루프 자체가 신뢰를 잃는다.

특히 MCP 추천 프로젝트에서는 다음이 중요하다.

- registry 상태가 바뀌어도 benchmark가 유지되는가
- 외부 MCP availability 변화가 평가 결과를 얼마나 왜곡하는가
- 품질 회귀를 안정적으로 감지할 수 있는가

## 4대 프로젝트 축에 주는 시사점

### 1. 선택 기준/평가 체계

- benchmark는 `정확도`뿐 아니라 `재현성`과 `평가 안정성`을 설계 목표로 가져야 한다.

### 2. 추천 최적화

- 추천 알고리즘 비교는 고정된 테스트 환경 위에서만 의미가 있다.

### 3. 로그 기반 개선

- 온라인 로그 외에 `stable offline replay benchmark`가 반드시 필요하다.
- virtualized MCP execution layer가 있으면 회귀 테스트에 유리하다.

### 4. 운영/품질 게이트

- 배포 전 gate로 replay benchmark, canned environment, deterministic regression test를 둘 필요가 있다.

## 한계

- MCP-specific security, version compatibility는 직접 다루지 않는다.
- 추천 feature engineering보다 evaluation infra에 집중한다.
- 실제 사용자 상호작용보다 안정된 benchmark 설계에 중점을 둔다.

## 현재 판단

- 분류: `평가 인프라 핵심 논문`
- 프로젝트 활용도: 매우 높음
- 역할: `재현 가능한 MCP benchmark` 설계 참고
- 최종 프로젝트 반영 포인트:
  - virtualized tool sandbox
  - stable replay
  - regression gate 설계

## 관련 research 문서

- [Evaluation & Benchmark Design 조사](../research/evaluation-benchmark-design.md)
