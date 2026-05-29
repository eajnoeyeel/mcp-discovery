# 추천 시스템 안전성/강건성 리스크 평가 조사

> 최종 업데이트: 2026-03-22
> 조사 목적: 추천 시스템의 안전성/강건성 리스크 평가

---

## 해결하려는 기능/문제

적대적 공격 방어 및 추천 신뢰성 확보. 핵심 질문: "악의적 Provider가 description을 조작하거나, 유사 Tool을 대량 등록하여 추천을 왜곡하는 공격에 어떻게 대응하는가?"

## 검토한 논문/자료 목록

| 논문 | 파일 | 핵심 기여 |
|------|------|-----------|
| ToolEmu | [toolemu-analysis-ko.md](../papers/toolemu-analysis-ko.md) | LM-emulated sandbox로 도구 사용 리스크 저비용 탐색. Risk-weighted evaluation 프레임워크 |
| MCP-Landscape-Security | [mcp-landscape-security-analysis-ko.md](../papers/mcp-landscape-security-analysis-ko.md) | MCP 생태계 lifecycle 기반 16개 보안 위협 시나리오 체계화 |
| ToolFlood | [toolflood-analysis-ko.md](../papers/toolflood-analysis-ko.md) | Semantic covering attack — 유사 description으로 정상 Tool의 선택을 방해하는 공격 패턴 |

## 각 자료에서 가져온 핵심 포인트

- **ToolEmu**: 실제 도구를 모두 구동하지 않고 LM이 도구 실행을 에뮬레이션하여 안전성 리스크를 저비용으로 탐색. 자동 safety evaluator로 실패와 위험도를 정량화. 핵심 시사점: 추천 시스템은 정확도 시스템이면서 동시에 위험 제어 시스템이어야 한다. 잘못된 추천의 비용이 서로 다르므로 severity-aware metric이 필요.
- **MCP-Landscape-Security**: MCP lifecycle을 4단계(생성-배포-운영-유지보수) × 16개 활동으로 정리. 4개 공격자 유형(악의적 서버 제작자, 중간자, 악의적 클라이언트, 내부자)과 16개 위협 시나리오를 구조화. 우리 프로젝트에서 특히 관련 있는 위협:
  - **Tool Poisoning**: 악의적 description으로 정상 Tool처럼 위장하여 선택 유도
  - **Rug Pull**: 초기 정상 동작 후 악의적 버전으로 업데이트
  - **Privilege Escalation**: 과도한 권한을 가진 Tool이 추천되어 보안 경계 침범
- **ToolFlood**: Semantic covering attack — 공격자가 정상 Tool의 description과 의미적으로 유사한 다수의 가짜 Tool을 등록하여 검색 결과를 점령. 핵심 메커니즘: 임베딩 공간에서 정상 Tool 주변을 악의적 Tool들로 "덮는" 전략. 우리 dense retrieval 파이프라인이 이 공격에 본질적으로 취약함을 시사.

## 후보 접근 방식 비교

| 전략 | 방법 | 장점 | 단점 | 논문 근거 |
|------|------|------|------|-----------|
| **A: Pre-deploy Safety Testing** | 등록 시 description 분석 + 유사도 이상 탐지 + sandbox 실행 검증 | 악의적 Tool 사전 차단, 등록 게이트 역할 | 구현 비용 높음, 정상 Tool 오탐 리스크, 우회 가능 | ToolEmu의 sandbox + MCP-Security의 lifecycle gate |
| **B: Runtime Monitoring** | 실시간 추천 결과 모니터링 + 이상 패턴 탐지 (급격한 선택률 변화, 클러스터링 이상) | 사후 탐지로 운영 중 방어, 데이터 기반 | 공격 발생 후 대응, 초기 피해 불가피 | MCP-Security의 운영 단계 위협 대응 |
| **C: Adversarial Robustness Training** | Ground Truth에 adversarial 케이스 포함 + description 정규화 + 임베딩 정규화 | 파이프라인 자체의 강건성 향상 | 알려진 공격에만 효과, 신규 공격 패턴에 취약 | ToolFlood의 adversarial description 패턴 |

## 채택안 / 제외안

**채택**: Core 이후 구현 (DP0 깊이 배분에 따른 우선순위 조정)

현 단계(5주 프로젝트)에서는 full safety framework 구현이 비현실적. 대신 다음 두 가지를 즉시 반영:

1. **Confusion Rate 지표 설계에 리스크 인식 반영**: 혼동 실패(confusion failure)를 분석할 때, 의도적 adversarial confusion과 자연적 confusion을 구분할 수 있는 메타데이터 구조 준비
2. **Ground Truth에 adversarial 케이스 포함**: High Similarity Pool(E6 실험)에 ToolFlood 패턴을 모사한 stress test 케이스 포함 — 동일 기능의 유사 description을 가진 Tool 클러스터 의도적 배치

**제외 (현 단계)**:
- Pre-deploy Safety Testing (Strategy A): 등록 게이트 구현은 Distribution 기능(DP0에서 "높음" 깊이)의 일부로 후속 구현. 현재는 큐레이션 기반 Pool이므로 악의적 등록 리스크가 낮음
- Runtime Monitoring (Strategy B): Provider Analytics 파이프라인이 완성된 후(Phase 4 이후) 이상 탐지 모듈 추가 가능
- Adversarial Robustness Training (Strategy C): description 정규화는 DQS(Description Quality Score) 모듈에서 부분적으로 커버. 임베딩 정규화는 E2 실험 이후 검토

## 판단 근거

1. **5주 프로젝트 범위 제약**: DP0에서 확정한 깊이 배분(추천+Analytics=극한, Distribution=높음, Spec=견고, OAuth=동작)에 따라, 안전성은 Distribution/Spec 레이어에 속하며 현 단계에서 극한 수준 구현 대상이 아님.

2. **ToolFlood의 adversarial description 패턴 인지**: 이 공격은 우리 dense retrieval 파이프라인의 본질적 취약점을 드러냄. 임베딩 공간에서 의미적으로 가까운 악의적 Tool이 정상 Tool을 밀어낼 수 있음. 현 단계에서 직접 방어는 어렵지만, Ground Truth의 High Similarity Pool에 이 패턴을 모사한 stress test 케이스를 포함하여 "우리 파이프라인이 이 공격에 얼마나 취약한지" 측정 가능.

3. **ToolEmu의 risk-weighted evaluation**: 잘못된 추천의 비용이 균등하지 않다는 통찰. 파일 삭제 Tool을 잘못 추천하는 것은 날씨 Tool을 잘못 추천하는 것보다 심각. 현 단계에서 severity 가중치를 Precision@1에 반영하기는 어렵지만, Ground Truth에 severity 필드를 미리 포함하여 향후 risk-weighted metric 확장 가능성 확보.

4. **MCP-Landscape-Security의 현실적 위협**: 현재 큐레이션 기반 Pool(Smithery 크롤링 + 직접 MCP 연결)에서는 악의적 서버 등록 리스크가 낮음. 그러나 오픈 레지스트리로 확장 시 Tool Poisoning, Rug Pull이 현실적 위협이 됨. 아키텍처 설계 시 이를 고려한 확장 포인트 마련.

## 프로젝트 반영 방식

### 즉시 반영 (Phase 1-2)

- **Confusion Rate metric 설계**: `src/evaluation/metrics/precision.py`에서 confusion failure 분석 시, 오답 Tool의 provider/등록 시점/description 유사도를 함께 로깅. 향후 "자연적 혼동 vs 의도적 혼동" 분류의 기반 데이터.
- **Ground Truth adversarial 케이스**: `data/ground_truth/` 구조에 severity 필드 추가 — `"severity": "low" | "medium" | "high"`. ToolEmu의 risk-weighted evaluation 개념을 GT 스키마에 선반영.
- **High Similarity Pool에 adversarial 케이스 포함**: E6 실험(Pool 유사도 실험)의 High Similarity Pool 정의 시, ToolFlood 패턴을 모사한 Tool 클러스터 의도적 포함:
  - 동일 기능의 3-5개 Tool이 미세하게 다른 description 보유
  - 정상 Tool 1개 + 의미적으로 유사한 distractor 2-4개
  - Confusion Rate이 이 패턴에서 어떻게 변하는지 측정

### 후속 구현 (Core 완성 후)

- **Description 정규화**: DQS 모듈에서 description의 비정상 패턴 탐지 (과도한 키워드 반복, 경쟁 Tool명 언급 등)
- **등록 게이트**: Distribution 기능의 일부로, 신규 등록 시 기존 Tool과의 임베딩 유사도 검사 + 이상치 플래깅
- **Runtime 이상 탐지**: Provider Analytics 파이프라인의 Selection Frequency에서 급격한 변화 감지 → 알림

### E6 실험과의 연결

E6(Pool 유사도 실험)의 High Similarity Pool은 자연적 유사도와 의도적 adversarial 유사도를 모두 테스트하는 이중 목적을 가짐:

| E6 조건 | 유형 | 목적 |
|---------|------|------|
| E6-High (natural) | 실제로 기능이 유사한 Tool 클러스터 | Disambiguation 능력 측정 |
| E6-High (adversarial) | ToolFlood 패턴 모사 | Adversarial 강건성 측정 |

두 조건에서 Confusion Rate 차이가 크면 → 파이프라인이 adversarial manipulation에 취약하다는 증거.

## 관련 papers

- [ToolEmu](../papers/toolemu-analysis-ko.md)
- [MCP-Landscape-Security](../papers/mcp-landscape-security-analysis-ko.md)
- [ToolFlood](../papers/toolflood-analysis-ko.md)
