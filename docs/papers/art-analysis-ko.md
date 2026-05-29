# ART 분석 노트

> task library에서 유사 시연을 선택하여 frozen LLM의 다단계 추론과 도구 사용을 program처럼 자동 오케스트레이션하는 프레임워크.

## 기본 정보

- 논문: [ART: Automatic multi-step reasoning and tool-use for large language models](https://arxiv.org/abs/2303.09014)
- 발표: arXiv preprint (학회 미발표)
- 제출일: 2023-03-16
- 저자: Bhargavi Paranjape 외 (University of Washington, Microsoft Research, UC Irvine)

## 무엇을 해결하려는가

ART는 다단계 추론과 도구 사용이 필요한 문제를 풀 때, 사람이 task별 prompt와 tool interleaving을 일일이 손으로 설계해야 하는 부담을 줄이려 한다.

핵심 문제는 아래와 같다.

- multi-step reasoning을 일반화할 수 있는가
- reasoning과 tool use를 하나의 절차로 다룰 수 있는가
- 새로운 작업에도 task library 기반으로 transfer가 가능한가

## 핵심 아이디어

- frozen LLM을 사용한다.
- reasoning step과 tool call을 `program`처럼 표현한다.
- 새 문제를 받으면 task library에서 비슷한 reasoning/tool-use 시연을 선택한다.
- 실행 중 tool call이 나오면 중단하고 결과를 받아 다시 reasoning을 이어간다.

즉, ART는 추천보다 `orchestration`과 `multi-step execution` 쪽에 강한 논문이다.

## 우리 프로젝트에 중요한 이유

최종 MCP 추천 최적화가 단일 선택이 아니라 다단계 워크플로우로 확장될 가능성이 높기 때문에, ART는 `추천 이후 실행 계획`을 설계할 때 중요하다.

- RAG-MCP는 후보를 줄이는 데 초점이 있다.
- ART는 선택된 도구들을 어떻게 순서 있게 사용할지에 초점이 있다.

둘은 경쟁이라기보다 상호보완적이다.

## 4대 프로젝트 축에 주는 시사점

### 1. 선택 기준/평가 체계

- 단일 top-1 accuracy만으로는 부족하다.
- 여러 단계에서의 tool sequence 품질과 intermediate success도 평가해야 한다.

### 2. 추천 최적화

- 추천 시스템은 개별 MCP 추천뿐 아니라 `task library`나 workflow template과 결합될 수 있다.

### 3. 로그 기반 개선

- 실패 로그를 단일 실패가 아니라 `어느 단계에서 reasoning/tool-use가 무너졌는지`로 쪼개서 봐야 한다.

### 4. 운영/품질 게이트

- 실행 계획 단위 테스트, step-level replay, failure classification이 필요하다는 점을 시사한다.

## 한계

- 대규모 후보 검색 문제를 직접 다루지 않는다.
- registry, versioning, compatibility 문제는 범위 밖이다.
- retrieval 계층보다 reasoning program 구조에 무게가 있다.

## 현재 판단

- 분류: `후속 실행/오케스트레이션 참고 논문`
- 프로젝트 활용도: 중상
- 역할: `추천 이후 multi-step execution 설계` 참고
- 최종 프로젝트 반영 포인트:
  - workflow-aware recommendation — *프로젝트 확장 해석 (ART는 recommendation이 아닌 execution 프레임워크)*
  - step-level evaluation — *논문에서 직접 도출 (ART는 step 단위 실행/평가 구조를 제시)*
  - failure localization — *프로젝트 확장 해석 (논문은 human-in-the-loop 수정을 언급하지, 자동 failure localization이 아님)*

## 관련 research 문서

- [Tool Selection & Retrieval 조사](../research/tool-selection-retrieval.md)
