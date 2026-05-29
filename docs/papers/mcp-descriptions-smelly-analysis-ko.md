# MCP Tool Descriptions Are Smelly!

> 출처: Hasan et al., arXiv:2602.14878, 2026
> 한 줄 요약: 103개 MCP 서버의 856개 도구를 분석한 결과 97.1%가 최소 1개 이상의 품질 결함을 보유하며, 설명 augmentation으로 작업 성공률이 +5.85pp 향상됨을 실증한 연구.

---

## 해결하려는 문제

MCP 도구 설명(description)의 품질이 실제로 어떤 수준인지 대규모로 분석한 연구. LLM 기반 에이전트가 도구를 올바르게 선택하고 사용하려면 설명이 충분해야 하지만, 현실의 MCP 서버들이 제공하는 설명에는 체계적인 품질 결함("smell")이 존재하는지 검증하고자 함.

## 핵심 아이디어

도구 설명의 품질을 6가지 차원으로 분해한 rubric을 정의하고, LLM-as-Jury (3명의 독립적 LLM 판사) 방식으로 각 차원을 1-5점 Likert 척도로 평가. 결함이 발견된 설명을 augmentation(보강)하여 실제 작업 성공률 변화를 측정.

## 방법론

**평가 대상**: 856개 도구, 103개 MCP 서버 (23개 공식 서버 -- Anthropic, GitHub, PayPal, Microsoft, Airbnb 등 + 80개 커뮤니티 서버)

**설명 품질 6가지 차원 (1-5점 Likert)**:
1. **Purpose** -- "이 도구가 정확히 무엇을 하는가?"
2. **Guidelines** -- "언제 어떻게 사용하는가?"
3. **Limitations** -- "어떤 제약이나 실패 케이스가 있는가?"
4. **Parameter Explanation** -- "입력값들이 무엇을 의미하는가?"
5. **Length/Completeness** -- "충분한 세부사항이 있는가?"
6. **Examples** -- "사용 예제가 있는가?"

**평가 방식**: LLM-as-Jury -- 3개의 독립적 LLM judge (GPT-4.1-mini, Claude-Haiku-3.5, Qwen3-30B-A3B)가 동일한 rubric으로 평가하고 결과를 집계. ICC(Intraclass Correlation) 범위 0.62~0.90.

**Smell 판정 기준**: 평균 점수 < 3.0 (Likert 척도)인 차원이 있으면 해당 차원에서 "smell"로 판정.

**검증**: 설명 augmentation 전후의 작업 성공률 비교, 차원별 ablation study 수행.

## 주요 결과

| 지표 | 값 |
|------|-----|
| 전체 결함율 | **97.1%** (최소 1개 이상의 quality defect 보유) |
| 목적 미명확 | **56%** |
| 사용 가이드 부재 | **89.3%** (정확한 출처 위치 확인 필요) |
| 설명 augmentation 후 작업 성공률 향상 | **+5.85pp** |
| Evaluator 단계 개선 | **+15.12%** |

**Ablation 결과**: Examples 차원을 제거해도 성능 저하 없음 -- Examples는 scoring에서 제외 가능.

## 장점

- **대규모 실증 분석**: 103개 서버, 856개 도구라는 의미 있는 규모의 데이터셋
- **체계적인 rubric 정의**: 6가지 명시적 차원으로 품질을 분해하여 측정 가능하게 만듦
- **LLM-as-Jury 기법**: 단일 LLM 판단의 편향을 줄이는 3-judge ensemble 방식 제안
- **인과 검증**: 단순 상관이 아닌 augmentation 실험을 통해 설명 품질 개선이 실제 성능 향상으로 이어짐을 입증
- **Ablation study**: 각 차원의 기여도를 개별적으로 분석하여 불필요한 차원(Examples) 식별

## 한계

- "Length/Completeness"가 다른 차원들의 메타 차원처럼 작동할 수 있음 (독립성 문제)
- LLM-as-Jury 방식이 특정 LLM 모델에 의존적일 수 있음
- 856개 도구가 MCP 생태계 전체를 대표하는지에 대한 일반화 가능성
- 설명 augmentation의 비용 트레이드오프: 실행 단계가 67.46% 증가하고, 일부 케이스에서 16.67% 성능 하락이 발생. 설명 개선이 항상 전체 성능 향상으로 이어지지는 않을 수 있음

## 프로젝트 시사점

MCP Discovery Platform의 DQS(Description Quality Score) 설계에 가장 직접적인 근거를 제공하는 핵심 논문. 97.1% 결함율은 품질 점수 시스템의 필요성을 강력히 뒷받침하며, 6가지 차원 rubric은 우리 5-차원 DQS의 기반이 됨. 특히 Purpose(56% 실패)와 Limitations(89.3% 부재) 수치는 가중치 설계 방향의 참고로 활용. 다만 augmentation의 비용 트레이드오프(실행 단계 증가, 일부 성능 하락)도 고려해야 하며, DQS 개선이 무조건적 성능 향상을 보장하지는 않음에 유의.

## 적용 포인트

- **DQS 차원 설계**: Paper A의 6개 차원에서 Examples를 제거한 5개 차원 체계의 근거
- **Purpose Clarity 가중치**: 56% 실패율 데이터를 기반으로 Purpose 차원에 높은 가중치(0.30) 부여
- **Negative Instruction 차원**: Limitations 89.3% 부재를 근거로 별도 차원으로 분리
- **LLM-as-Judge 방식**: 3-judge ensemble 기법을 LLM 스코어러(`llm_scorer.py`)에 직접 채택
- **E7 파일럿 설계**: augmentation 효과 검증 방법론 참고

## 관련 research 문서
- [Description Quality Scoring 조사](../research/description-quality-scoring.md)
