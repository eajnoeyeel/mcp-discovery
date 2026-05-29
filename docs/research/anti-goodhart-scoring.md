# Anti-Goodhart 품질 점수 설계 — 리서치 종합

> 조사 목적: GEO Score가 gaming에 강건하도록 재설계하기 위한 방법론 조사
> 해결하려는 기능/문제: GEO Score v2 설계, E7 실험 (GEO 점수 방식 비교)
> 작성일: 2026-04-06

---

## 조사 목적

현재 GEO Score 6D의 구조적 문제:
- 정규식 휴리스틱 → 패턴 삽입으로 쉽게 gaming 가능
- boundary 차원 95% 환각률
- **GEO Score 상승 ↔ P@1 하락 음의 상관 (Pearson ≈ -0.468, n=18)**

질문: gaming에 강건하면서도 실제 retrieval 성능과 양의 상관을 갖는 quality score를 어떻게 설계하는가?

## 검토한 논문/자료 목록

| 논문 | 핵심 기여 |
|------|----------|
| Reward Model Overoptimization (Gao et al., ICML 2023) | Proxy point 개념, KL penalty의 한계 |
| RAGAS (Shahul Es et al., EACL 2024) (arXiv metadata에서 venue 미확인, 공식 proceedings에서 확인 필요) | Claim 추출 → 이진 검증 패턴 |
| FActScore (Min et al., EMNLP 2023) | Atomic fact 분해 → 독립 검증 |
| LLM-as-Judge (Zheng et al., NeurIPS 2023) | 4가지 편향과 완화 전략 |
| G-Eval (Liu et al., EMNLP 2023) (arXiv metadata에서 venue 미확인, 공식 proceedings에서 확인 필요) | CoT 기반 평가, self-enhancement bias |
| Reward Model Ensembles (Coste et al., ICLR 2024) | 보수적 앙상블로 overoptimization 70% 감소 |
| LLM-Rubric (ACL 2024, arXiv:2501.00274) | 다차원 독립 채점 → 단일 차원 gaming 방지 |
| Goodhart 4유형 (Garrabrant, 2017) | Regressional/Extremal/Causal/Adversarial 분류 |

## Goodhart 4유형과 현재 GEO Score 매핑

| 유형 | 정의 | 현재 GEO에서의 발현 |
|------|------|-------------------|
| **Regressional** | Proxy와 goal 사이 노이즈 | 정규식이 실제 품질과의 노이즈가 큼 |
| **Extremal** | 극단값에서 관계 붕괴 | GEO=1.0에 가까운 description이 부자연스러울 수 있음 |
| **Causal** | 비인과적 상관에 개입 | "NOT" 키워드 ≠ 실제 disambiguation |
| **Adversarial** | 의도적 proxy 조작 | keyword stuffing, contrast phrasing 남용 |

## 핵심 방어 전략 (우선순위 순)

### 1. 측정과 최적화를 분리 (Gao et al.)
- GEO Score로 "측정"만 하고, "최적화 목표"로는 P@1 사용
- Description optimizer가 GEO Score를 직접 최대화하는 것은 금지

### 2. Atomic Fact Verification (FActScore + RAGAS)
- Description → atomic claims 분해 → input_schema 대비 검증
- 허위 주장 즉시 탐지 (환각 방지)

### 3. DimensionAwareFilter (LLM-Rubric)
- 최약 차원이 임계값 미달이면 총점에 cap 적용
- 단일 차원만 극대화하는 gaming 차단

### 4. Optimizer/Evaluator LLM 분리 (LLM-as-Judge)
- 최적화 LLM ≠ 평가 LLM ≠ 최종 검증 (P@1)
- Self-enhancement bias 차단

### 5. Proxy Point 모니터링 (Gao et al.)
- Spearman(GEO, P@1) 주기적 측정
- 상관 하락 시 scorer 재보정

### 6. 보수적 앙상블 (Coste et al.)
- UWO: score = mean - λ × std
- 4-5개 독립 신호면 충분 (수확체감)

## 채택안: 단계적 적용

| 단계 | 작업 | 효과 |
|------|------|------|
| **즉시** | boundary 제거 + fluency 추가 | 환각 유발 차원 제거 |
| **E4 전** | DimensionAwareFilter | 단일 차원 gaming 차단 |
| **E7** | LLM-based scorer (G-Eval CoT) + Optimizer/Evaluator 분리 | 정규식 한계 극복 |
| **Phase 2** | Atomic Fact Verification + Ensemble + Proxy Point 탐지 | 프로덕션 방어 |

## 판단 근거

- 즉시 적용 가능한 것(boundary 제거, DimensionAwareFilter)부터 시작
- LLM 기반 scorer는 비용이 들어 실험(E7)에서 먼저 검증
- 프로덕션 방어(Ensemble, Proxy Point)는 Phase 2에서 구현

## 관련 papers

- `../papers/naeini-ece-analysis-ko.md`
- `../papers/llm-rubric-analysis-ko.md`
- `../papers/tooltweak-analysis-ko.md`
- `../papers/toolflood-analysis-ko.md`
