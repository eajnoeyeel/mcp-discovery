# ToolTweak: An Attack on Tool Selection in LLM-based Agents

> 출처: arxiv:2510.02554 (2025)
> 저자: Jonathan Sneh 외 8명 (University of Oxford, Microsoft UK)
> 한 줄 요약: 도구 이름과 설명을 체계적으로 조작하면 LLM의 도구 선택률을 ~20%에서 81%까지 끌어올릴 수 있음을 실증적으로 보여준 적대적 공격 연구.

---

## 해결하려는 문제

LLM 기반 에이전트의 도구 선택이 도구 설명(description)의 표현 방식에 얼마나 취약한지를 정량적으로 측정하려 한다. 도구의 실제 기능은 동일하더라도, 이름과 설명을 전략적으로 변경하는 것만으로 LLM이 해당 도구를 선택하는 비율이 극적으로 바뀔 수 있는지를 검증한다.

## 핵심 아이디어

- 도구의 이름(name)과 설명(description)을 반복적으로(iteratively) 조작하는 적대적 공격(adversarial manipulation) 방법론을 제안한다.
- 공격자가 도구의 실제 기능을 바꾸지 않고, 오직 메타데이터(이름, 설명)만 변경하여 LLM이 해당 도구를 더 자주 선택하도록 유도한다.
- 이를 통해 description이 LLM 도구 선택에 미치는 인과적(causal) 영향을 직접 증명한다.

## 방법론

- **PAIR 알고리즘 기반 반복 최적화**: K=10 반복에 걸쳐 공격자 모델이 새 도구 메타데이터 제안 → 피해 LLM 테스트 → 선택률 통계로 다음 반복 유도
- 도구 **이름(name)**과 **설명(description)** 두 요소를 조작 (파라미터 스키마는 고정)
- **조작 전략**: "사실처럼 들리는 편향 삽입", "구조적 패턴과 암묵적 비교", "주관적/단정적 표현" 사용
- 위치 편향(position bias) 통제를 위해 도구 순서 랜덤 셔플링 적용

### 선택률을 높이는 설명 특성

| 특성 | 설명 | 예시 |
|------|------|------|
| 암묵적 우월성 | 다른 도구 대비 우월함을 암시 | "optimal", "best", "actively maintained" |
| 단정적 표현 | 무조건 사용해야 한다는 어조 | "Should be called whenever possible" |
| 기억에 남는 이름 | 우월함을 암시하는 도구명 | 숫자 접미사 "1" vs "2"가 선택에 영향 |
| 구조적 패턴 | 패러프레이징으로 제거하기 어려운 패턴 | 형식적 비교 구조 |

## 주요 결과

### 모델별 공격 성공률 (Best Selection Rate)

| 모델 | No Attack | ToolTweak | Manual Suffix |
|------|-----------|-----------|---------------|
| DeepSeek | 20.2% | **81.6%** | 68.7% |
| GPT-OSS-20B | 19.0% | **73.6%** | 76.4% |
| Grok 3 Mini | 19.9% | **50.7%** | 89.5% |
| Gemini 2.5 Flash Lite | 18.9% | **48.7%** | 56.1% |
| Qwen 2.5-7B | 19.9% | **45.9%** | 61.3% |
| Llama 3.1-8B | 19.8% | **34.0%** | 38.1% |

### 교차 모델 전이성 (Transferability)

- DeepSeek 에이전트: 공격 소스와 무관하게 ~60% 선택률 (가장 취약)
- Gemini/Llama 에이전트: 20-40% (가장 견고)
- **Self-bias 효과**: 모델이 자신이 생성한 공격에 가장 취약
- **최신 모델이 더 전이 가능한 공격 생성**: GPT-OSS, Gemini 2.5, DeepSeek > Llama 3.1, Qwen 2.5

### 방어 메커니즘 평가

| 방어 | DeepSeek | Gemini | GPT-OSS |
|------|----------|--------|---------|
| Undefended | 81.6% | 48.6% | 73.6% |
| **Paraphrasing Defense** | 48.6% | 30.1% | 63.3% |
| 감소율 | -33%p | -18.5%p | -10.3%p |

- Paraphrasing 방어: "객관적 스타일로 재작성" 지시 → 14-40% TSR 감소 (모델별 편차: DeepSeek -40%, Gemini -38%, GPT-OSS -14%, Grok -35%, Llama -20%, Qwen -25%)
- **한계**: 방어 후에도 baseline(~20%)보다 높은 선택률 유지
- Perplexity 필터링(GPT-2): 공격 설명의 perplexity가 원본과 거의 겹침 → 단순 임계값으로 탐지 불가

## 장점

- LLM 도구 선택에서 description의 인과적 영향을 직접적으로 증명 — 도구 선택 취약성을 특성화하고 완화하는 첫 걸음 (a first step toward characterizing and mitigating)
- 적대적 관점에서 도구 생태계의 보안 취약점을 명확히 드러냄
- 방어 메커니즘 설계의 필요성에 대한 정량적 근거 제공

## 한계

- 5개 도구 후보 풀에서의 실험으로, 대규모 도구 풀(100+)에서의 효과는 미검��
- 검색(retrieval) 단계가 아닌 선택(selection) 단계만 평가 — ToolFlood가 검색 단계 공격 담당
- ��라미터 스키마 조작은 미포함 (이름/설명만 조작)
- 도구의 실제 기능 검증(실행 결과 비교) ���이 선택률만 측정

## 프로젝트 시사점

MCP Discovery Platform의 핵심 테제("description 품질이 높을수록 Tool 선택률이 높아진다")를 **역방향으로 이미 증명**한 논문이다. ToolTweak이 "나쁜 의도로 설명을 조작하면 선택률이 올라간다"는 것을 보였다면, 우리 프로젝트는 "좋은 방향으로 설명을 개선하면 선택률이 올라간다"는 동일한 메커니즘을 Provider에게 가치로 전달한다.

Evidence Triangulation의 Primary Evidence (8a. A/B Selection Rate Lift)의 설계가 ToolTweak의 직접적 description 조작 → selection rate 변화 관찰 방법론에 기반한다. ToolTweak은 Spearman이 아닌 직접적 A/B 조작으로 인과 관계를 증명했으며, 이것이 우리 metrics-rubric.md에서 A/B Lift를 Primary Evidence로 설정한 이유이다.

## 적용 포인트

- **Metric 8a (A/B Selection Rate Lift)**: ToolTweak 방법론을 참고하여 자체 MCP 서버의 description 조작 → 선택률 변화 측정 설계
- **Provider Analytics**: description 품질 개선이 선택률에 미치는 인과적 효과의 이론적 근거
- **Description Quality Score (DQS)**: 높은 DQS → 높은 선택률의 가설을 뒷받침하는 핵심 근거 논문
- **Spearman(DQS, Selection Rate) (Metric 8b)**: ToolTweak이 Spearman이 아닌 직접 조작으로 증명했으므로, Spearman은 Secondary Evidence로 위치

## 관련 research 문서

- [description-quality-scoring.md](../research/description-quality-scoring.md) — DQS 설계의 이론적 배경
- [evaluation-metrics.md](../research/evaluation-metrics.md) — Provider 분석용 특수 지표 (Spearman 상관계수, A/B Lift)
