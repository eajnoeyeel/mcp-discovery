# ToolScan: A Benchmark for Characterizing Errors in Tool-Use LLMs

> 출처: arxiv:2411.13547 (v1: 2024-11-20, SpecTool / v2: 2025-06-26, ToolScan으로 제목 변경)
> 저자: Shirley Kokane 외 17명
> 한 줄 요약: LLM의 도구 사용에서 발생하는 7가지 오류 패턴(IAC, IAV, IAN, IAT, RAC, IFN, IFE)을 체계적으로 분류하는 벤치마크를 구축한 연구.

---

## 해결하려는 문제

LLM이 도구를 사용할 때 발생하는 오류를 "맞았다/틀렸다"로만 평가하면 개선 방향을 알 수 없다. 어떤 유형의 오류가 발생하는지, 각 오류의 원인이 무엇인지를 체계적으로 분류하고 진단하는 프레임워크가 필요하다.

## 핵심 아이디어

- LLM의 도구 사용 오류를 **7가지 패턴**으로 분류하는 taxonomy를 제안한다:
  1. **IAC (Insufficient API Calls)**: 필요한 API 호출이 누락됨
  2. **IAV (Incorrect API Values)**: API 파라미터에 잘못된 값을 전달
  3. **IAN (Incorrect API Names)**: 잘못된 API 이름을 호출
  4. **IAT (Incorrect API Types)**: API 파라미터 타입 오류 (string 대신 int 등)
  5. **RAC (Redundant API Calls)**: 불필요한 API 호출이 추가됨
  6. **IFN (Incorrect Format - Naming)**: 출력 형식의 네이밍 오류
  7. **IFE (Incorrect Format - Extra)**: 출력 형식에 불필요한 추가 내용 포함
- POMDP(Partially Observable Markov Decision Process) 프레임워크로 도구 사용을 모델링하여 오류 분류의 이론적 기반을 제공한다.
- 각 오류 패턴별 특성과 해결 방향을 제시한다.

## 방법론

- **POMDP 프레임워크**: 도구 사용 과정을 Partially Observable Markov Decision Process로 모델링. 환경 상태, 관찰, 행동(API 호출)의 관계를 수학적으로 정의하여 오류 유형을 체계적으로 분류하는 이론적 기반 제공.
- **10개 환경 카테고리**: 다양한 도메인(날씨, 금융, 소셜 미디어, 여행 등)에 걸쳐 도구 사용 시나리오를 구성.
- **150개 쿼리**: 각 카테고리별 쿼리를 설계하여 벤치마크 데이터셋 구축.
- 각 쿼리에 대해 LLM의 도구 사용 결과를 7가지 오류 패턴으로 자동 분류하여 정량적으로 평가.

## 주요 결과

- GPT-4, Code-Llama-13b, Vicuna-13b, Mixtral-8x7B 등 다수 모델을 벤치마크로 평가.
- **IAC(Insufficient API Calls)가 가장 빈번한 오류 유형**으로 나타남 — 모델이 필요한 API 호출을 누락하는 경우가 가장 많음.
- 오류 유형 분포가 모델별로 상이하여, 모델 특성에 따른 targeted 개선이 필요함을 시사.
- Section 8.1.4의 ablation study에서 **구조적으로 유사한 API 이름 환경**에서 모델 정확도가 하락함을 보고 — 이는 유사 도구 혼동(similar tool confusion) 현상에 대한 간접적 실증이나, 7가지 오류 패턴 자체에는 포함되지 않음.

## 장점

- 도구 사용 오류를 7가지 패턴으로 분류하는 체계적 분류 체계 (POMDP 이론적 기반)
- 오류 유형별 진단이 가능하여 targeted 개선이 가능
- 다수의 모델(GPT-4, Code-Llama 등)에 걸쳐 일반화 가능한 벤치마크 제공
- Ablation study를 통해 유사 API 이름 환경에서의 정확도 하락을 실증적으로 보고

## 한계

- 벤치마크 규모가 10개 카테고리, 150개 쿼리로 제한적 — 실 서비스 규모의 도구 풀(수백~수천 개)에서의 일반화 검증이 부족.
- 오류 분류가 API 호출의 정확성에 집중되어 있어, 도구 선택(tool selection) 자체의 실패(잘못된 도구를 선택하는 문제)보다는 선택된 도구의 사용 오류에 초점.
- Ablation study에서 유사 API 혼동을 관찰했으나, 이를 7가지 패턴 중 독립 카테고리로 분류하지는 않음 — 체계적 대응 방법론은 제시하지 않음.

## 프로젝트 시사점

MCP Discovery Platform의 Confusion Rate 지표(Metric #3)의 **관련 참고 연구**이다(주 근거는 MetaTool). 단, confusion vs miss 분류는 **프로젝트 자체 설계이며 ToolScan이 직접 제안한 것이 아님**에 유의. ToolScan의 ablation study(Section 8.1.4)에서 유사 API 환경에서의 정확도 하락을 보고한 것이 간접적 참고 자료로 활용된다.

두 실패 유형은 처방이 다르다:

- **Confusion** (정답이 Top-K에 있지만 rank-1이 아님): description disambiguation 개선 → Provider에게 안내
- **Miss** (정답이 Top-K에 없음): 임베딩/검색 전략 자체를 개선

metrics-rubric.md에서 Confusion Rate 목표를 "전체 오류의 50% 이하가 confusion"으로 설정하고 있으며, 특정 Tool 쌍의 confusion count > 5이면 Provider에게 disambiguation 알림을 보내도록 설계되어 있다.

또한 ToolScan의 7가지 오류 패턴 분류(IAC, IAV, IAN, IAT, RAC, IFN, IFE)는 우리 평가 하네스에서 오류 원인 분석(error analysis)의 참고 프레임워크로 활용된다.

## 적용 포인트

- **Confusion Rate (Metric #3)**: ToolScan의 ablation study(유사 API 혼동 관찰)를 참고하되, confusion vs miss 분류 자체는 프로젝트 자체 설계
- **Provider Analytics — Confusion Matrix (D-5)**: 어떤 Tool 쌍에서 confusion이 발생하는지 시각화
- **Alert 시스템**: 특정 Tool 쌍의 confusion count > 5이면 Provider에게 disambiguation 개선 안내
- **오류 분석 프레임워크**: 7가지 오류 패턴(IAC, IAV, IAN, IAT, RAC, IFN, IFE)을 참고하여 평가 하네스의 error analysis 모듈 설계

## 관련 research 문서

- [evaluation-metrics.md](../research/evaluation-metrics.md) — Confusion Rate 지표 정의 및 ToolScan 인용
