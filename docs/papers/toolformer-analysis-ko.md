# Toolformer 분석 노트

> self-supervised 방식으로 LLM 내부에 "언제, 어떤 도구를, 어떤 인자로 호출할지"를 학습시켜, 외부 retriever 없이 도구 사용 정책을 내재화한 선구적 연구.

## 기본 정보

- 논문: [Toolformer: Language Models Can Teach Themselves to Use Tools](https://arxiv.org/abs/2302.04761)
- 학회: NeurIPS 2023
- 제출일: 2023-02-09
- 저자: Timo Schick 외
- 베이스 모델: GPT-J (6.7B)

## 무엇을 해결하려는가

Toolformer는 언어모델이 일반 언어 능력은 강하지만 계산, 사실 조회, 날짜 처리처럼 외부 도구가 더 잘하는 작업에는 약하다는 문제를 다룬다. 핵심 질문은 아래와 같다.

- 모델이 `언제` 도구를 써야 하는가
- `어떤` 도구를 써야 하는가
- `어떤 인자`를 넘겨야 하는가
- 결과를 이후 생성에 `어떻게 반영`해야 하는가

## 핵심 아이디어

- 소수의 API 사용 예시만으로 self-supervised 방식의 데이터 생성을 수행한다.
- CCNet 데이터에서 API 호출 삽입 전후의 token prediction loss 차이로 유용한 API 호출만 필터링한다 — Toolformer의 핵심 기여 메커니즘.
- 모델이 텍스트 생성 중 API 호출 위치와 호출 인자를 삽입하도록 학습한다.
- 6가지 도구 유형: calculator, Wikipedia search, Bing search, ATLAS QA, machine translation, calendar를 한 모델 안에서 사용 가능하게 한다.

즉, Toolformer는 별도 추천기보다 `모델 내부 정책`을 학습해 도구 사용을 결정하는 접근에 가깝다.

## 우리 프로젝트에 중요한 이유

`MCP 추천 최적화` 관점에서 Toolformer는 외부 retrieval 없이도 모델 내부에서 tool-use policy를 학습할 수 있다는 기준점이다.

- 장점:
  - 언제 도구를 호출할지를 모델이 내재적으로 배울 수 있다.
  - API 인자 생성까지 통합적으로 다룬다.
- 한계:
  - 후보 도구 수가 매우 많아질 때 prompt bloat와 discovery 문제를 직접 해결하지는 않는다.
  - registry 규모의 MCP 생태계 추천 문제보다는 `tool invocation policy learning`에 더 가깝다.

## 4대 프로젝트 축에 주는 시사점

### 1. 선택 기준/평가 체계

- 단순 top-k retrieval뿐 아니라 `도구 호출 여부 판단 정확도`도 평가 대상이어야 한다.
- 잘못된 호출과 호출 누락을 분리해서 측정할 필요가 있다.

### 2. 추천 최적화 (프로젝트 확장 해석)

- 외부 retriever와 내부 policy를 분리할지, 통합할지 비교 기준이 된다. (논문이 직접 다루는 주제는 아니며, Toolformer의 내부 정책 학습 접근에서 영감을 받은 프로젝트 해석)
- 최종 시스템이 `retrieval + LLM policy` 혼합 구조가 될 가능성을 보여준다.

### 3. 로그 기반 개선 (프로젝트 확장 해석)

- 실제 사용 로그에서 `도구를 불필요하게 호출한 경우`와 `써야 하는데 안 쓴 경우`를 따로 추적해야 함을 시사한다. (논문이 직접 제안하는 것이 아닌 프로젝트 맥락의 확장 해석)

### 4. 운영/품질 게이트

- 인자 생성 오류가 실제 위험으로 이어질 수 있으므로 schema validation과 실행 전 검증이 중요하다.

## 한계

- 대규모 MCP registry 수준의 추천 문제를 직접 다루지 않는다.
- 운영/배포/버전/호환성 같은 시스템 계층은 범위 밖이다.
- retrieval benchmark나 후보 축소 전략에 대한 논의는 약하다.

## 현재 판단

- 분류: `핵심 배경 논문`
- 프로젝트 활용도: 높음
- 역할: `LLM 내부 도구 사용 정책`의 기준선
- 최종 프로젝트 반영 포인트:
  - 호출 여부 판단
  - 인자 생성 정확도
  - retrieval 이후 정책 모델 필요성

## 관련 research 문서

- [Tool Selection & Retrieval 조사](../research/tool-selection-retrieval.md)
