# 도구 설명 최적화를 통한 LLM Tool Selection/Retrieval 개선 — 문헌 서베이

> 최종 업데이트: 2026-04-06
> 조사 목적: MCP 도구 설명의 어떤 특성이 검색/선택 성능을 개선하고, 어떤 특성이 저하시키는지를 최신 논문(2025-2026)에서 체계적으로 정리

---

## 조사 배경

MCP Discovery Platform의 핵심 테제: "Description 품질이 높을수록 Tool 선택률이 높아진다"

이 서베이는 11개 핵심 논문에서 다음을 추출한다:
1. 어떤 설명 특성이 검색/선택을 **개선**하는가
2. 어떤 특성이 **저하**시키는가
3. 구체적 수치(NDCG, MRR, P@1, Selection Rate 변화)
4. MCP Discovery Platform에의 시사점

---

## 1. 설명 특성별 영향 종합

### 1.1 검색/선택을 개선하는 특성

| 특성 | 근거 논문 | 효과 크기 | 메커니즘 |
|------|----------|----------|----------|
| **기능 요약 (function_description)** | Tool-DE | NDCG@10 일관 향상 | 핵심 기능의 의미적 표현 강화 |
| **사용 시나리오 (when_to_use)** | Tool-DE, CallNavi | 라우팅 최우선 요인 | 사용자 의도와 직접 매핑 |
| **키워드 태그 (tags)** | Tool-DE | BM25/Dense 모두 향상 | 의미 공간에서 anchor 역할 |
| **제약조건 (limitations/boundaries)** | Tool-DE, Smelly | 89.3% 부재로 성능 저하 | 오선택 방지, 음성 신호 |
| **고유한 도구명** | Docs→Desc | 73% 중복 시 +11.6%p 손실 | 의미적 구별력 |
| **명확한 트리거 조건** | Docs→Desc | Functionality 차원 최대 영향 | LLM의 호출 결정 기준 |
| **파라미터 의미 정확성** | Docs→Desc | Accuracy +8.8%p | 스키마-설명 일관성 |
| **반환값 문서화** | MFTR | 특정 도메인에서 40% 기여 | 출력 기대 매칭 |
| **LLM 기반 설명 보강** | Dynamic ReAct, Trace-Free+ | Top-5 +50% 상대, QL +28.9%p (G3 Instruction 서브셋 기준. Overall QL은 54.0% vs EasyTool 43.7% = +10.3%p) | 암묵적 기능/사용례 확장 |
| **도메인 특화 어휘** | Semantic Discovery | GitHub/MySQL MRR 0.88-0.92 | 임베딩 공간에서 명확한 클러스터링 |

### 1.2 검색/선택을 저하시키는 특성

| 특성 | 근거 논문 | 효과 크기 | 이유 |
|------|----------|----------|------|
| **API 호출 예제 (example_usage)** | Tool-DE | 제거 시 NDCG@10 향상 | API 구문이 의미 공간에 노이즈로 작용 |
| **중복된 도구명** | Docs→Desc | 73% 발생, +11.6%p 손실 | 의미적 구별 불가 |
| **의미적으로 중첩되는 설명** | Semantic Discovery | Filesystem MRR 0.84 (최저) | read/write/copy/move 구별 불가 |
| **과도한 기술 용어** | Docs→Desc | Conciseness +1.5%p 영향 | 사용자 쿼리와 어휘 불일치 |
| **주관적/단정적 표현** | ToolTweak | 적대적 우위 81.6% | 공정한 선택 방해, 편향 유발 |
| **불완전한 파라미터 문서** | Docs→Desc | 3,449건 오류 | 스키마-설명 불일치 |
| **YAML 형식 스키마** | CallNavi | JSON 대비 정확도 0.525 vs 0.925 (LLAMA 3.1 기준) | LLM의 YAML 파싱 취약 |
| **모호한 쿼리 대응 부재** | Semantic Discovery | 크로스 도메인 쿼리 실패 | 단일 도메인 가정 위반 |

---

## 2. 논문별 핵심 수치 요약

### 2.1 검색 성능 (Retrieval)

| 논문 | 모델/방법 | NDCG@10 | Recall@10 | 비교 대상 |
|------|----------|---------|-----------|----------|
| **ToolRet** | NV-Embed-v1 (범용 SOTA) | 33.83 | — | 범용 IR 벤치마크 |
| **ToolRet** | Qwen3-Embedding-8B | 46.21 (Tool-DE 벤치마크 기준) | 57.52 | ToolRet 학습 후 |
| **Tool-DE** | Tool-Embed-4B | 52.23 | 63.13 | Document Expansion |
| **Tool-DE** | + Tool-Rank-4B | **56.44** | **67.81** | + Reranking |
| **MFTR** | MiniLM-L6 (Multi-Field) | 54.12 | 62.56 | ToolBench |
| **MFTR** | vs Full-Doc baseline | +94.0% | — | ToolBench |
| **Semantic Discovery** | ada-002, K=3 | — | — | F1=58.4%, MRR=0.91 |
| **Dynamic ReAct** | voyage-context-3 + enrichment | — | — | Top-5: 60% (+50% rel.) |

### 2.2 선택 성능 (Selection/Routing)

| 논문 | 조건 | Selection Rate | 비교 대상 |
|------|------|---------------|----------|
| **Docs→Desc** | 표준 준수 설명 | **72%** | vs 비준수 20% (260% 증가) |
| **ToolTweak** | 적대적 조작 | **81.6%** | vs baseline 20% (DeepSeek) |
| **Trace-Free+** | 학습 기반 재작성 | **46.4% QL** | vs EasyTool 17.5% (+28.9%p, G3 Instruction 서브셋 기준. Overall QL은 54.0% vs 43.7% = +10.3%p) |
| **CallNavi** | GPT-4o 라우팅 | **91.9%** Exact Match | 115개 후보 풀 |
| **RAG-MCP** | 의미 검색 필터링 | **43.13%** | vs baseline 13.62% (3x) |

### 2.3 공격/방어 (Security)

| 논문 | 공격 유형 | ASR | 방어 효과 |
|------|----------|-----|----------|
| **ToolTweak** | 설명 조작 (선택 단계) | 81.6% | Paraphrasing: -33%p |
| **ToolFlood** | 의미 공간 커버링 (검색 단계) | 96.1% | MMR: TDR -46%p, ASR 유지 |
| **AMA** | 메타데이터 최적화 | 81-95% | Prompt Guard: 효과 없음 |

---

## 3. 핵심 인사이트

### 3.1 Description이 "설득 입력(persuasive input)"이다

ToolTweak, Docs→Desc, Tool Preferences Unreliable 모두 동일한 결론:
- LLM의 도구 선택은 설명의 표현 방식에 극도로 민감
- 동일 기능이라도 설명이 다르면 선택률이 20% → 72-81%로 변화 (다른 실험 설계: 전자는 품질 준수, 후자는 적대적 공격)
- 이는 검색(retrieval) 단계뿐 아니라 선택(selection) 단계 모두에서 확인

### 3.2 "무엇을 하는가" > "어떻게 사용하는가" > "무엇을 반환하는가" > "파라미터"

여러 논문의 일관된 발견:
1. **기능/목적 (What)**: 모든 논문에서 최고 기여 (Tool-DE, CallNavi, MFTR, Docs→Desc)
2. **사용 시나리오 (When)**: Tool-DE, CallNavi에서 라우팅 핵심 요인
3. **반환값 (Output)**: MFTR에서 도메인별로 최대 53% 기여
4. **파라미터 (Input)**: 일관적으로 최저 기여 (MFTR ~0.28, CallNavi "상대적 덜 중요")

### 3.3 Example Usage는 검색에 해롭다

- Tool-DE ablation: example_usage 제거 시 NDCG@10 향상
- Smelly: Examples 차원 제거해도 성능 저하 없음
- 추정 원인: API 호출 구문(코드)이 자연어 임베딩 공간에서 노이즈로 작용

### 3.4 범용 IR 모델은 도구 검색에 부적합

- ToolRet: 범용 SOTA(NV-Embed-v1)가 도구 검색에서 NDCG@10 33.83
- Semantic Discovery: ada-002만으로는 의미 중복 도구 구별 한계 (Filesystem MRR 0.84)
- Tool-DE: 도구 검색 특화 학습 시 +10pp 이상 향상
- 원인: "기능적 관련성(functional relevance)"은 "주제적 유사성(topical similarity)"과 근본적으로 다름

### 3.5 다중 필드 분해가 단일 필드보다 우월

- MFTR: 단일 필드 최고(Description ~0.46) < 다중 필드 결합(0.54) on ToolBench
- Tool-DE: 4개 필드 결합이 원본 문서 대비 NDCG@10 +10pp
- 필드별 기여도가 도메인/쿼리 유형에 따라 크게 변동 → 적응적 가중치 필요

### 3.6 설명 품질은 검색 성능의 상한을 결정

- Semantic Discovery 명시: "Retrieval quality is fundamentally bounded by the informativeness of tool descriptions"
- Dynamic ReAct 명시: "Poorly documented tools significantly reduce retrieval accuracy"
- Trace-Free+ 입증: 설명 재작성만으로 QL +28.9%p 향상 (G3 Instruction 서브셋 기준. Overall QL은 54.0% vs EasyTool 43.7% = +10.3%p) → 설명이 에이전트 성능과 동등한 중요도

---

## 4. MCP Discovery Platform 시사점

### 4.1 인덱싱 파이프라인 (`build_tool_text()`)

**현재**: `"{tool_name}: {description}"`

**개선 방향** (논문 근거):
```
{tool_name}: {function_description}
When to use: {when_to_use}
Limitations: {limitations}
Tags: {tags}
```
- Tool-DE의 4개 유효 필드 구조 채택
- **example_usage 제외** (Tool-DE ablation 근거)
- **파라미터 스키마는 인덱싱 텍스트에서 제외하거나 최소화** (MFTR, CallNavi 근거)

### 4.2 GEO Score 차원 검증

| GEO Score 차원 | 대응 논문 발견 | 지지 강도 |
|----------------|---------------|----------|
| clarity_score | Tool-DE function_description, CallNavi purpose, Docs→Desc Functionality | **매우 강함** |
| disambiguation_score | Semantic Discovery 의미 중복 문제, Docs→Desc Functionality | **강함** |
| boundary_score | Tool-DE limitations, Smelly Limitations 89.3% 부재 | **강함** |
| parameter_coverage_score | MFTR Parameters (최저 기여), CallNavi (덜 중요) | **약함** (가중치 하향 근거) |
| stats_score | MFTR Response (도메인별 변동) | 중간 |
| precision_score | Tool-DE tags, Docs→Desc Accuracy | 중간 |

### 4.3 보안 고려사항

- ToolTweak: 설명 조작으로 선택률 4배 증가 → Provider Analytics에서 "비정상적 선택률" 탐지 필요
- ToolFlood: 1.2% 도구 주입으로 검색 장악 → 등록 시 의미적 중복 검사 필요
- Paraphrasing 방어가 부분적 효과 → 설명 정규화(normalization) 파이프라인 검토

### 4.4 E4 실험 설계

프로젝트의 핵심 가설 검증에 활용 가능한 방법론:
- **Tool-DE ablation 방식**: 필드별 제거 후 P@1 변화 측정
- **Docs→Desc mutation 방식**: 표준 준수 vs 비준수 설명의 선택률 비교
- **ToolTweak A/B 방식**: 동일 기능 도구의 설명만 변경하여 인과 관계 직접 증명

---

## 5. 검토한 논문 목록

| # | 논문 | 출처 | 핵심 기여 |
|---|------|------|----------|
| 1 | Tool-DE | arXiv:2510.22670, 2025 | 5개 필드 Document Expansion, example_usage 해로움 |
| 2 | ToolTweak | arXiv:2510.02554, 2025, Oxford/Microsoft | 적대적 설명 조작 → 20%→81% 선택률 |
| 3 | ToolFlood | arXiv:2603.13950, 2026, ICML 제출 | 임베딩 공간 semantic covering 공격 |
| 4 | Semantic Tool Discovery | arXiv:2603.20313, 2026 | MCP 특화 벡터 검색, 설명이 검색 상한 결정 |
| 5 | ToolRet | arXiv:2503.01763, ACL 2025 | 기능적 관련성 vs 주제적 유사성 구별 |
| 6 | CallNavi | arXiv:2501.05255, 2025, Luxembourg | 라우팅 요인 분석, 목적>파라미터 |
| 7 | From Docs to Descriptions | arXiv:2602.18914, 2026, UCLA/NTU | 18개 smell 카테고리, 260% 선택률 차이 |
| 8 | MCP Descriptions Smelly | Hasan et al., 2025, arXiv:2602.14878 | 97.1% 결함, augmentation +5.85pp |
| 9 | MFTR | arXiv:2602.05366, 2026, Tsinghua | 4개 필드 독립 매칭, 적응적 가중치 |
| 10 | Trace-Free+ | arXiv:2602.20426, 2026, Intuit | 학습 기반 설명 재작성, +28.9%p |
| 11 | Dynamic ReAct | arXiv:2509.20386, 2025, Agentr.dev | MCP 설명 enrichment, Top-5 +50% |

---

## 관련 papers

각 논문의 상세 분석은 `../papers/{논문명}-analysis-ko.md` 참조. 위 표의 11개 논문 + `rag-mcp-analysis-ko.md`.
