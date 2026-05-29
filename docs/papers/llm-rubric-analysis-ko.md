# LLM-Rubric

> 출처: arXiv:2501.00274, Microsoft, ACL 2024
> 저자: Helia Hashemi, Jason Eisner, Corby Rosset, Benjamin Van Durme, Chris Kedzie (Microsoft)
> 평가 도메인: IT help desk 대화 (Microsoft Azure 관련 정보 탐색 대화) 평가에 특화. 다른 도메인에서의 검증은 없음.
> 한 줄 요약: LLM 확률 분포 위에 작은 신경망 calibration layer를 추가하여 비보정 baseline 대비 rubric 기반 평가 정확도를 2배 향상시킨 연구.

---

## 해결하려는 문제

LLM을 평가자(judge)로 활용할 때, raw LLM 출력의 점수가 인간 평가와 충분히 일치하지 않는 문제. LLM이 rubric을 기반으로 텍스트를 평가할 때 나타나는 편향과 불일치를 보정(calibration)하여 평가 신뢰도를 높이고자 함.

## 핵심 아이디어

LLM의 확률 분포(probability distribution) 위에 **작은 신경망 calibration layer**를 추가하여, LLM의 rubric 기반 평가 결과를 인간 평가와 더 잘 일치하도록 보정. LLM 자체를 재학습하지 않고, 출력 확률만을 입력으로 받는 경량 모델로 calibration 수행.

## 방법론

1. LLM에 rubric과 평가 대상 텍스트를 제공하여 점수별 확률 분포를 추출
2. 이 확률 분포를 입력으로 받는 작은 신경망(calibration layer)을 학습
3. 소량의 인간 레이블 데이터로 calibration layer를 fine-tune
4. 보정된 점수를 최종 평가 결과로 사용

## 주요 결과

| 지표 | 비보정 baseline | LLM-Rubric (보정 후) |
|------|----------------|---------------------|
| RMSE | 0.901 (uncalibrated baseline) | **0.422** (real data 기준) |
| 향상도 | -- | **약 53% 감소** (0.901 → 0.422) |

> 참고: 0.901 → 0.422 수치는 real data 실험 조건에서의 결과이며 논문에서 확인된 수치임.

- Calibration layer 추가만으로 평가 정확도가 baseline 대비 RMSE 약 50% 이상 감소
- 소량의 인간 레이블 데이터만으로도 효과적인 calibration 가능
- LLM 모델 자체의 재학습 없이 경량 보정만으로 성능 향상

## 장점

- **실용적 접근**: LLM 재학습 없이 경량 calibration layer만 추가하여 비용 효율적
- **ACL 2024 발표**: 최상위 NLP 학회에서 Microsoft가 발표한 검증된 기법
- **범용성**: 다양한 rubric 기반 평가 작업에 적용 가능한 일반적 프레임워크
- **소량 데이터**: 대규모 레이블 데이터 없이도 calibration 가능

## 한계

- 상세 분석 추가 예정

## 프로젝트 시사점

> **주의**: 이 논문은 IT help desk 대화 품질 평가에 특화된 연구임. DQS/tool description 평가에의 적용은 기법적 참고 수준이며, 프로젝트의 확장 해석임 (논문이 직접 DQS나 tool description 평가를 다루지는 않음).

MCP Discovery Platform에서 DQS 점수의 정확도를 높이기 위한 고급 기법으로 활용 가능. 초기 E7 파일럿에서 LLM-as-Judge 방식의 점수를 수집한 후, 인간 평가 데이터와의 calibration을 통해 점수 신뢰도를 크게 향상시킬 수 있음. 특히 DQS 점수를 실제 선택률과 correlate시키는 Evidence Triangulation(8b, 8c) 단계에서 활용 가치가 높음.

## 적용 포인트

- **DQS 점수 보정**: E7 파일럿 후 인간 평가 데이터로 LLM 스코어의 calibration layer 학습 가능
- **E4 실험 연동**: DQS 점수를 실제 선택률과 correlate시킬 때, calibration 모델을 적용하여 상관도 향상
- **하이브리드 방식**: 휴리스틱 스코어와 LLM 스코어의 최적 결합 비율을 calibration으로 결정
- **점진적 개선**: 초기에는 비보정 LLM 점수를 사용하고, 인간 레이블 축적에 따라 calibration layer를 추가하는 단계적 접근 가능
- ~~**Regression R²(8c) 향상**~~: *프로젝트 추측 (논문 근거 없음)* — calibration된 DQS 점수를 사용하면 R²가 향상될 것이라는 기대는 논문에서 직접 지지하지 않는 프로젝트 측 추측임

## 관련 research 문서
- [Description Quality Scoring 조사](../research/description-quality-scoring.md)
