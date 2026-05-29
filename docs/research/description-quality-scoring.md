# MCP Tool Description 품질 점수 (DQS) — 리서치 요약

> 작성: 2026-03-21 | 최종 업데이트: 2026-03-26
> 맥락: OQ-1 (GEO 점수 산정 방식) 해결
> **2026-03-26 업데이트**: CTO 멘토링에서 SEO Score → GEO Score로 개념 전환. 5-dimension DQS에 GEO 기법 2개(stats_score, precision_score) 추가 → 6-dimension GEO Score. 최신 정의는 `docs/design/metrics-rubric.md`가 SOT.

---

## 결정

**5-dimension DQS 채택 → 6-dimension GEO Score로 확장** (동등 가중치 1/6 x 6, E7 calibration)

- 원래 차원: Purpose Clarity, Specificity, Disambiguation, Negative Instruction, Parameter Description
- **2026-03-26 확장**: GEO 기법 반영으로 재명명 + 2개 차원 추가
  - clarity_score (← Purpose Clarity + Specificity 통합)
  - disambiguation_score (유지)
  - parameter_coverage_score (← Parameter Description)
  - boundary_score (← Negative Instruction)
  - stats_score (신규 — GEO: Statistics Addition)
  - precision_score (신규 — GEO: Technical Terms)
- 초기 가중치: 동등(1/6 x 6) — E7 파일럿에서 calibration
- 스코어링 방식: E7에서 휴리스틱 vs LLM-as-Judge 비교 후 결정
- **SOT**: `docs/design/metrics-rubric.md` — GEO Score 섹션

---

## 논문 핵심 발견

### Paper A: "MCP Tool Descriptions Are Smelly!" (Hasan et al., 2025, arXiv:2602.14878)

- 856개 도구/103개 서버 분석 — **97.1%** 최소 1개 quality defect 보유
- 목적 미명확 56%, 사용 가이드 부재 높은 비율 (정확한 출처 위치 확인 필요)
- 설명 augmentation → **+5.85pp 작업 성공률**
- Examples 제거 ablation에서 성능 저하 없음 → scoring에서 제외 가능

### Paper B: "From Docs to Descriptions" (Wang et al., 2025)

- 10,831개 MCP 서버 분석 — 표준 준수 설명 선택률 72% vs 비준수 20% (**260% 증가**)
- 18가지 문제 카테고리 (Accuracy, Functionality, Completeness, Conciseness)
- Functionality 차원이 선택률에 가장 큰 영향 (+11.6%)

### Paper F: "Tool Preferences in Agentic LLMs are Unreliable" (EMNLP 2025)

- 설명의 작은 편집 → 선택 도구의 큰 변화
- 설명은 "설득 입력(persuasive input)" — 핵심 테제의 타당성 증명

### Paper G: CallNavi (2025)

- GPT-4o 라우팅 정확도 91.9% — 라우팅은 높은 정확도(0.78+), 파라미터 생성은 훨씬 어려운 태스크. Description component ablation은 수행하지 않음
- 파라미터 세부사항은 상대적으로 덜 중요

### Paper L: LLM-Rubric (Microsoft, ACL 2024, arXiv:2501.00274)

- LLM 확률 분포 위에 calibration layer → 비보정 대비 **2배 향상**
- E4 후 calibration 모델 학습 가능

---

## 5-차원 DQS 정의 (원본 리서치 기반)

> **주의**: 아래는 원본 논문 리서치 기반의 5-차원 정의. 2026-03-26 CTO 멘토링 이후 6-차원 GEO Score로 확장됨. 최신 정의는 `docs/design/metrics-rubric.md`가 SOT.

| # | 원본 차원 | → GEO Score 차원 | 정의 | 근거 |
| --- | ------ | ------ | ------ | ------ |
| 1 | **Purpose Clarity** | `clarity_score` | 이 도구가 정확히 무엇을 하고 언제 사용하는가? + 구체적 범위 | Paper A (56% 실패), Paper G (라우팅 최우선), GEO: Fluency Optimization |
| 2 | ~~Specificity~~ | *(clarity에 통합)* | 구체적 데이터 소스, 출력 형식, 범위 경계 | Paper B (Accuracy +11.6%) |
| 3 | **Disambiguation** | `disambiguation_score` | 유사 도구와 명확히 구분되는가? | Confusion Rate 지표, MetaTool |
| 4 | **Negative Instruction** | `boundary_score` | 이 도구가 NOT 하는 것이 명확한가? | Paper A (Limitations 높은 비율 부재, 정확한 출처 위치 확인 필요) |
| 5 | **Parameter Description** | `parameter_coverage_score` | 입력값이 타입/제약/예제와 함께 설명되는가? | Paper A, Paper G (낮은 우선도) |
| 6 | *(신규)* | `stats_score` | 수치/커버리지/성능 정보 포함 여부 | GEO: Statistics Addition |
| 7 | *(신규)* | `precision_score` | 표준/프로토콜/기술 용어 정확도 | GEO: Technical Terms |

**복합 점수 (GEO Score)**: `GEO_score = (1/6) x (clarity + disambiguation + parameter_coverage + boundary + stats + precision)`

---

## 스코어링 방식 비교 (E7 파일럿에서 결정)

### 방식 A: 휴리스틱 (`geo_score.py`)

- Clarity: 행동 동사 시작, "what"+"when-to-use", 구체적 범위 — Regex 패턴 (GEO: Fluency Optimization)
- Disambiguation: "unlike", "only", domain qualifier — Contrast regex
- Parameter Coverage: 파라미터명, 타입명, inputSchema 완성도
- Boundary: "NOT for", "cannot" — 부정 패턴
- Stats: 수치, 커버리지, 성능 정보 — 숫자/단위 패턴 (GEO: Statistics Addition)
- Precision: 표준/프로토콜 명칭 — 기술 용어 사전 (GEO: Technical Terms)
- 장점: 무료, 결정론적, 즉시 실행

### 방식 B: LLM-as-Judge (`llm_scorer.py`)

- GPT-4o-mini, 3-judge ensemble (Paper A 기법), 6-차원 rubric 1-5점
- 출력: JSON, [0.0, 1.0] 정규화 — 비용 ~$0.03 (30개)
- 장점: 의미론적 이해, 미묘한 차이 감지

---

## E7 파일럿 실험 설계

- **샘플**: 30개 설명 (자체 서버 6 + Smithery 12 + 다양 카테고리 12)
- **인간 레이블**: 6개 차원별 1-5점 (GEO Score rubric)
- **비교**: Spearman (인간 vs 휴리스틱/LLM), MAE, Williams' test

### 결정 기준

- 둘 다 r_s >= 0.7 → **휴리스틱** (무료, 빠름)
- LLM >= 0.7, 휴리스틱 < 0.5 → **LLM**
- LLM >= 0.7, 휴리스틱 0.5-0.7 → **하이브리드**
- 둘 다 < 0.5 → rubric 차원 재검토

---

## Evidence Triangulation 연결

### Metric 8b: Spearman(GEO Score, Selection Rate)

- `r_s = Spearman(geo_score_i, Precision@1_i)` for all tools
- 목표: r_s > 0.6, p < 0.05

### Metric 8c: Regression R²

- `OLS(selection_rate ~ clarity + disambiguation + parameter_coverage + boundary + stats + precision)`
- 목표: R² > 0.4, 최소 1개 요소 p < 0.05
- Provider에게 "설명의 어떤 부분이 선택률에 가장 기여하는가" actionable 피드백

---

## E7 파일럿에서 답해야 할 질문

1. 동등 가중치로도 인간 평가와 r_s >= 0.6 상관이 나오는가?
2. 특히 높은/낮은 상관을 보이는 차원은?
3. 휴리스틱 vs LLM 어느 방식이 인간 평가와 더 일치하는가?

---

## 관련 papers

- [`../papers/mcp-descriptions-smelly-analysis-ko.md`](../papers/mcp-descriptions-smelly-analysis-ko.md) — Paper A
- [`../papers/from-docs-to-descriptions-analysis-ko.md`](../papers/from-docs-to-descriptions-analysis-ko.md) — Paper B
- [`../papers/tool-preferences-unreliable-analysis-ko.md`](../papers/tool-preferences-unreliable-analysis-ko.md) — Paper F
- [`../papers/callnavi-analysis-ko.md`](../papers/callnavi-analysis-ko.md) — Paper G
- [`../papers/llm-rubric-analysis-ko.md`](../papers/llm-rubric-analysis-ko.md) — Paper L
- [`../papers/tool-de-analysis-ko.md`](../papers/tool-de-analysis-ko.md) — Tool-DE: 5개 필드 Document Expansion, example_usage 해로움
- [`../papers/toolret-analysis-ko.md`](../papers/toolret-analysis-ko.md) — ToolRet: functional relevance vs topical similarity
- [`../papers/mftr-analysis-ko.md`](../papers/mftr-analysis-ko.md) — MFTR: 다중 필드 독립 매칭, Description > Parameters
- [`../papers/trace-free-plus-analysis-ko.md`](../papers/trace-free-plus-analysis-ko.md) — Trace-Free+: 학습 기반 설명 재작성 +28.9%p
- [`../papers/dynamic-react-analysis-ko.md`](../papers/dynamic-react-analysis-ko.md) — Dynamic ReAct: MCP 설명 enrichment Top-5 +50%

## 관련 research 문서

- [`description-optimization-survey.md`](./description-optimization-survey.md) — 도구 설명 최적화 종합 서베이 (2026-04-06)
