# ToolEmu 분석 노트

> LM이 도구 실행을 에뮬레이션하는 sandbox와 자동 safety evaluator를 도입하여, LM agent의 도구 사용 안전성 리스크를 저비용으로 탐색하는 프레임워크를 제안한 연구.

## 기본 정보

- 논문: [Identifying the Risks of LM Agents with an LM-Emulated Sandbox](https://arxiv.org/abs/2309.15817)
- 발표: **ICLR 2024 Spotlight**
- 최초 제출일: 2023-09-25
- 최신 arXiv 개정 확인일: v2, 2024-05-17
- 저자: Yangjun Ruan (University of Toronto & Vector Institute) 외, Tatsunori Hashimoto (Stanford) 포함
- 실험 규모: 36 toolkits (311 tools), 144 test cases

## 무엇을 해결하려는가

LM agent가 외부 도구를 사용할 때 생기는 안전성 리스크를 찾는 비용이 너무 높다는 점을 해결하려는 논문이다.

- 실제 도구를 모두 구현하고
- 환경을 각각 세팅하고
- 고위험 failure case를 일일이 찾는 과정이 비싸다

도구가 많아질수록 이 문제는 더 심해진다.

## 핵심 아이디어

- `ToolEmu`라는 LM-emulated sandbox를 도입한다.
- 실제 도구를 모두 띄우지 않고, LM이 도구 실행을 에뮬레이션한다.
- 자동 safety evaluator를 붙여 실패와 위험도를 정량화한다.
- adversarial/emulated 환경으로 long-tail 위험 시나리오를 더 쉽게 찾는다.

### 주요 결과

- 식별된 실패 사례의 **68.8%**가 실제 환경에서도 진짜 문제가 될 수 있는 것으로 확인됨
- 가장 안전한 LM agent조차 **23.9%**의 시간에 실패를 보임

## 우리 프로젝트에 중요한 이유

이 논문은 추천 품질보다 `잘못 추천했을 때 얼마나 위험한가`를 보게 만든다. MCP 추천 최적화에서도 아래 문제가 중요하다.

- 잘못된 MCP를 추천했을 때 정보 유출이 일어나는가
- 권한이 과도한 MCP를 추천하는가
- compatibility 문제로 파괴적 실행이 발생하는가

즉, 추천기는 정확도 시스템이면서 동시에 위험 제어 시스템이어야 한다. *(이하 시사점은 프로젝트 확장 해석 — 논문은 추천 시스템이 아닌 안전성 평가 프레임워크를 다룸)*

## 4대 프로젝트 축에 주는 시사점

### 1. 선택 기준/평가 체계

- 정확도 외에 `risk-weighted evaluation`이 필요하다.
- 잘못된 추천의 비용이 서로 다르므로 severity-aware metric이 필요하다.

### 2. 추천 최적화

- *(프로젝트 확장 해석)* metadata에 privilege, data sensitivity, side-effect severity를 포함할 필요가 있다.

### 3. 로그 기반 개선

- 실패 로그는 단순 실패가 아니라 `위험도`, `영향 범위`, `복구 가능성`까지 기록해야 한다.

### 4. 운영/품질 게이트

- *(프로젝트 확장 해석)* registry 등록 전 sandbox simulation, red-team scenario, risk scoring을 자동화할 필요가 있다.

## 한계

- MCP 표준 자체를 직접 다루지는 않는다.
- 추천 알고리즘 자체보다 위험 평가 프레임워크에 초점이 있다.
- 실제 운영 환경과 에뮬레이션 사이 갭은 남는다.

## 현재 판단

- 분류: `안전성/리스크 핵심 논문`
- 프로젝트 활용도: 매우 높음
- 역할: `risk-aware MCP recommendation` 설계 참고
- 최종 프로젝트 반영 포인트:
  - risk-weighted metrics
  - tool sandbox
  - pre-deploy red-teaming

## 관련 research 문서

- [Tool Reliability & Safety 조사](../research/tool-reliability-safety.md)
