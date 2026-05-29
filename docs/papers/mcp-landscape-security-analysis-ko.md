# MCP Landscape & Security 분석 노트

> MCP를 lifecycle 전체(생성-배포-운영-유지보수)로 조망하여, 4개 공격자 유형과 16개 위협 시나리오로 보안 위협을 체계적으로 정리한 서베이 논문.

## 기본 정보

- 논문: [Model Context Protocol (MCP): Landscape, Security Threats, and Future Research Directions](https://arxiv.org/abs/2503.23278)
- 최초 제출일: 2025-03-30
- 최신 arXiv 개정 확인일: v3, 2025-10-07 (재확인 필요 — arXiv에서 최신 버전 다시 체크할 것)
- 저자: Xinyi Hou 외

## 무엇을 해결하려는가

이 논문은 MCP를 단순한 tool-calling 인터페이스가 아니라 `생성-배포-운영-유지보수` 전체 lifecycle을 가진 생태계로 보고, 그 아키텍처와 보안 위협을 체계적으로 정리한다.

## 핵심 아이디어

- MCP 서버 lifecycle을 4개 단계와 16개 활동으로 정리한다.
- 위협 모델을 4개 공격자 유형과 16개 위협 시나리오로 구조화한다.
- 실제 사례를 통해 공격 표면을 보여주고, lifecycle 단계별 대응책을 제안한다.
- 동시에 MCP adoption landscape (MCPWorld 26,404 서버, MCP.so 16,592 서버 규모)와 integration pattern도 정리한다.
- 3가지 integration pattern 분류: Agent Frameworks (OpenAI), Development IDEs (Cursor), Cloud Platforms (Cloudflare).

이 논문은 추천 모델보다 `운영 시스템` 관점에서 매우 중요하다.

## 우리 프로젝트에 중요한 이유

우리 프로젝트 4번 축인 `등록-배포-버전관리-호환성 검증 자동화`와 직접 연결되는 거의 유일한 선행 자료다.

이 논문이 중요한 이유는 아래와 같다.

- MCP는 추천만 잘하면 끝나는 문제가 아니다.
- 누가 만들고, 어떻게 배포하고, 어떤 권한을 갖고, 어떻게 유지보수되는지가 함께 관리되어야 한다.
- 추천기는 이 lifecycle metadata를 이해해야 안전하고 운영 가능한 선택을 할 수 있다.

## 4대 프로젝트 축에 주는 시사점

### 1. 선택 기준/평가 체계

- 품질 지표에 security, trust, privilege, maintenance health를 넣어야 한다.

### 2. 추천 최적화

- 기능 유사도만으로 추천하면 위험하다.
- 추천 feature에 version, maintainer trust, auth model, sandboxability, side effects가 필요하다. *(이는 논문의 위협 모델에서 유추한 프로젝트 자체 설계임)*

### 3. 로그 기반 개선

- 실제 운영 로그에는 security incident, compatibility failure, deprecation event도 포함돼야 한다.

### 4. 운영/품질 게이트

- 이 논문은 보안 관점에서 우리 4번 축 설계의 참고 자료이다.
- 등록 시 schema 검증, 권한 검증, 배포 정책, 유지보수 상태, 취약점 대응 상태를 gate로 둘 근거를 제공한다.

## 한계

- 추천 알고리즘 성능 자체는 평가하지 않으나, tool selection의 보안 취약점 (preference manipulation 등)은 상당히 다룬다.
- tool selection benchmark보다는 lifecycle/security survey에 가깝다.
- 실제 추천 feature engineering은 추가 설계가 필요하다.

## 현재 판단

- 분류: `운영/보안 핵심 논문`
- 프로젝트 활용도: 매우 높음
- 역할: `MCP registry/ops layer` 설계 기준
- 최종 프로젝트 반영 포인트:
  - lifecycle metadata schema
  - trust/risk aware recommendation
  - registration/deployment quality gate

## 관련 research 문서

- [Tool Reliability & Safety 조사](../research/tool-reliability-safety.md)
