# RAG-MCP 심층 분석서

> RAG 기반 MCP 검색으로 prompt bloat를 줄이고 도구 선택 정확도를 높이는 3단계 파이프라인(indexing → retrieval → focused selection)을 제안한 논문 분석 및 참고 저장소(`/root/rag-mcp`) 구현 분석.

## 기본 정보

- 논문: [RAG-MCP: Mitigating Prompt Bloat in LLM Tool Selection via Retrieval-Augmented Generation](https://arxiv.org/abs/2505.03275)
- 저자: Tiantian Gan, Qiyao Sun 외
- 모델: Qwen-max-0125 (base LLM), Qwen (retriever), Deepseek-v3 (judge)
- 평가: MCPBench web search subset, 20 trials, 10 rounds/trial
- 배경: 4,400+ publicly listed MCP servers (mcp.so, 2025년 4월 기준)

---

# Part 1: 논문 분석

## 핵심 기여

- **문제 정의**: 다수 MCP를 프롬프트에 넣으면 prompt bloat, selection complexity, performance degradation 발생
- **해결 방법**: MCP discovery를 생성 밖으로 분리 — 외부 인덱스에서 관련 MCP만 먼저 검색
- **3단계 파이프라인**: indexing → retrieval(top-k 의미 검색) → focused selection/invocation
- **validation 단계**: 검색 MCP에 synthetic example 또는 sanity check 수행 후 최종 실행 후보로 활용

## 방법론 핵심 (논문)

| 논문 단계 | 설명 |
| --- | --- |
| indexing | MCP tool 메타데이터를 벡터 인덱스에 저장 |
| retrieval | 대화 문맥 기반 top-k 의미 검색 |
| focused selection | 검색된 도구만 프롬프트에 주입하여 선택/실행 |
| baseline (Blank Conditioning) | 도구 정보 없이 LLM이 응답 시도 — 검색 없는 하한선 |

- 논문은 `MCP server retrieval`을 다루며, 3단계 분리의 유효성을 실증

## 실험 결과

| 조건 | 정확도 |
| --- | --- |
| **RAG-MCP** | **43.13%** |
| Actual Match (키워드 매칭) | 18.20% |
| Blank Conditioning (도구 정보 없음) | 13.62% |

- **정확도 차이**: RAG-MCP 43.13% vs Actual Match 18.20% vs Blank Conditioning 13.62% — retrieval 분리가 유효
- **토큰 절감**: 평균 prompt token 1084 vs 2133.84 — prompt bloat 완화 확인
- Blank Conditioning은 "도구 정보를 전혀 제공하지 않는" 정당한 하한 baseline 정의

## 논문 자체 한계

- **스케일 한계**: 수천 개 이상에서 retrieval precision 저하 가능성 — 현재 실험 규모 ~100 수준에서 ceiling 존재
- **중간 규모 변동성**: mid-range tool pool에서 성능 변동이 관찰되나 원인 분석 부족
- **평가 범위**: MCPBench web search subset에 한정, 다른 도메인 일반화 미검증

## 프로젝트 적용 포인트 (논문 기반)

### 차용 가능한 요소
- retrieval을 통한 prompt 축소 아이디어 (핵심 아키텍처 패턴)
- 세션-질의-검색-도구실행 루프 구조
- token/latency/accuracy 비교 실험 harness

### 재설계 필요 사항
- **추천 대상 정의**: tool vs MCP server vs package vs version
- **평가 지표**: retrieval quality (MRR, nDCG) + execution success + UX quality
- **metadata schema**: 기능, 비용, 보안, 권한, latency, 호환성, 실패율
- **offline/online 피드백 루프**: 사용 로그 수집 → retriever/reranker 개선
- **운영 자동화**: MCP registry, 버전관리, 호환성 검증, 품질 게이트

### 최종 판단

- **권고**: `부분 차용`
- retrieval 기반 prompt 축소와 tool selection 비교 harness는 재사용 가치 있음
- retriever abstraction, metadata model, ranking/validation, logging/ops는 새로 설계 필요

---

# Part 2: Repository 구현 분석 (`/root/rag-mcp`)

> 아래 분석은 논문 저자의 공개 저장소 구현에 대한 별도 분석이다. 논문의 학술적 기여와는 분리하여 판단해야 한다.

## 저장소 구현 매핑

| 논문 단계 | 저장소 구현 | 차이 |
| --- | --- | --- |
| indexing | MCP tool → Bedrock tool spec → JSONL → S3 → KB ingestion | AWS 서비스에 종속적 구현 |
| retrieval | 대화 문맥 → `BedrockKB.query(top_k=2)` | top-2를 그대로 모델에 제공 |
| focused selection | Bedrock Converse toolConfig에 선택 도구만 주입 | validation 단계 거의 없음 |
| full baseline | `queryall()` — broad semantic query(max=100) | 논문의 Blank Conditioning과는 다른 구현 |

- 저장소는 논문의 `MCP server retrieval`이 아닌 `tool schema retrieval`에 가까움
- AWS Bedrock KB, S3, Bedrock Converse에 강하게 의존 (논문 자체는 AWS를 언급하지 않음)

## 저장소 구현 한계

- **인프라 의존성**: pluggable retriever abstraction 없이 AWS Bedrock/S3에 강하게 묶임 — 논문의 일반적 파이프라인을 특정 클라우드로 제한한 구현
- **baseline 구현 차이**: `queryall()`은 논문의 Blank Conditioning(도구 정보 없는 하한)과 다른 방식 — broad semantic query(max=100)로 구현됨
- **재현성 문제**: 하드코딩된 경로, 특정 KB ID 등으로 인해 환경 재현이 어려움
- **테스트 체계 부족**: offline benchmark/online feedback loop 미분리

## 관련 research 문서

- [Tool Selection & Retrieval 조사](../research/tool-selection-retrieval.md)
