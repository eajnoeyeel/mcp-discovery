# Obtaining Well Calibrated Probabilities Using Bayesian Binning into Quantiles (Naeini et al., AAAI 2015)

> 출처: Naeini et al., AAAI 2015
> 한 줄 요약: ECE(Expected Calibration Error) 지표의 binning 기반 공식을 제안하고, BBQ(Bayesian Binning into Quantiles) calibration 방법을 통해 예측 확률의 보정 품질을 개선한 연구.

---

## 해결하려는 문제

분류 모델이 출력하는 확률(confidence score)이 실제 정확도와 일치하지 않는 "보정 오류(miscalibration)" 문제를 해결하려 한다. 예를 들어, 모델이 "90% 확신"이라고 말할 때 실제로 90%가 맞아야 잘 보정된 것인데, 실제로는 이 일치가 보장되지 않는 경우가 많다.

## 핵심 아이디어

- **ECE(Expected Calibration Error)** 지표의 binning 기반 공식을 제안: 예측 확률 구간별로 실제 정확도와 예측 확률의 차이를 가중 평균하여 보정 오류를 정량화. **참고**: calibration error 개념은 Foster & Vohra (1997) 등에서 기원하며, Naeini et al.은 이를 binning 기반 ECE 형태로 공식화함. 이후 Guo et al. (2017, "On Calibration of Modern Neural Networks")를 통해 딥러닝 calibration의 표준 지표로 확산됨
- **BBQ(Bayesian Binning into Quantiles)** 방법 제안: 고정 구간 대신 데이터 분포에 따라 적응적으로 binning하여 더 정확한 calibration 수행

```
ECE = Σ (|B_m|/n) × |acc(B_m) - conf(B_m)|
```

- B_m: m번째 bin의 샘플 집합
- acc(B_m): 해당 bin의 실제 정확도
- conf(B_m): 해당 bin의 평균 confidence

## 방법론

- 예측 확률을 여러 구간(bin)으로 나누고, 각 구간에서 실제 정확도와 예측 확률의 차이를 측정
- Bayesian 접근으로 최적 binning을 학습하여 고정 크기 binning보다 안정적인 calibration 달성
- Reliability diagram(신뢰도 다이어그램)으로 시각화: x축(예측 확률) vs y축(실제 정확도)

## 주요 결과

- ECE가 낮을수록 모델의 confidence가 실제 정확도를 잘 반영함
- BBQ가 기존 Platt scaling, isotonic regression 등과 비교하여 경쟁력 있는 calibration 성능 달성

## 후속 영향

- ECE가 confidence 기반 의사결정의 신뢰도를 판단하는 표준 지표로 자리잡음 (특히 Guo et al. 2017 이후 딥러닝 분야에서 대중화)

## 장점

- 직관적이고 해석 가능한 calibration 품질 지표
- Reliability diagram과 함께 사용하면 시각적으로 보정 상태를 즉시 파악 가능
- 다양한 분류 문제에 범용 적용 가능

## 한계

- 고정 크기 binning의 경우 bin 개수 선택에 따라 결과가 달라질 수 있음
- 매우 적은 샘플에서는 bin별 통계가 불안정할 수 있음

## 프로젝트 시사점

MCP Discovery Platform의 Health Metric #5 (ECE)의 직접적인 논문 근거이다. 우리 시스템의 confidence 분기(DP6)는 Reranker의 rank1-rank2 gap(threshold 0.15)을 기반으로 "Top-1만 반환할지, Top-3 + 힌트를 반환할지"를 결정한다.

이 confidence 분기가 의미있으려면, confidence 점수가 실제 정확도를 잘 반영해야 한다. ECE가 높으면 gap-based 분기가 신뢰할 수 없게 되어, "확신이 높다고 판단했는데 실제로는 틀린" 케이스가 빈번해진다.

metrics-rubric.md에서 ECE < 0.15를 정상, > 0.25를 위험으로 설정하고 있다. 이 임계값은 Naeini 논문이 제시한 것이 아니라 프로젝트 자체 설계임에 유의.

## 적용 포인트

- **ECE (Metric #5)**: confidence 점수의 실제 보정 품질 측정. 목표 < 0.15 (프로젝트 자체 설정, 논문이 제시한 임계값이 아님)
- **Confidence 분기 (DP6)**: ECE가 나쁘면 gap-based 분기 로직(Top-1 vs Top-3 + 힌트) 자체의 신뢰성이 떨어짐
- **Reliability Diagram**: confidence 구간별 실제 정확도를 시각화하여 보정 상태 진단
- **Alert Threshold**: ECE > 0.25이면 confidence 분기 로직 재검토 필요 (프로젝트 자체 설정 임계값)

## 관련 research 문서

- [evaluation-metrics.md](../research/evaluation-metrics.md) — ECE 지표 정의 및 Naeini et al. 인용
