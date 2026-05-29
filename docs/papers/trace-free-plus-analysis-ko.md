# Learning to Rewrite Tool Descriptions for Reliable LLM-Agent Tool Use (Trace-Free+)

> 출처: arXiv:2602.20426 (2026-02-23)
> 저자: Ruocheng Guo, Kaiwen Dong, Xiang Gao, Kamalika Das (Intuit AI Research)
> 한 줄 요약: 실행 트레이스에서 추출한 규칙으로 도구 설명을 자동 재작성하면 전체 기준 최대 +10.3%p (Overall QL vs EasyTool), 난이도 높은 G3 서브셋에서 최대 +28.9%p 향상되며, 커리큘럼 학습으로 트레이스 없이도 cold-start 배포가 가능함을 입증.

---

## 해결하려는 문제

LLM 에이전트의 성능은 에이전트 자체뿐 아니라 도구 인터페이스(설명, 파라미터 스키마) 품질에도 의존한다. 기존 연구는 에이전트 fine-tuning에 집중했지만, 도구 설명은 여전히 "인간 지향적(human-oriented)"이며 LLM이 소비하기에 부적합한 경우가 많다. 특히 100+개 도구 후보에서 선택해야 할 때 설명 품질이 병목이 된다.

## 핵심 아이디어

- **도구 설명을 LLM 에이전트에 최적화하여 자동 재작성**: 인간이 아닌 LLM이 소비하기 좋은 형태로 변환
- **2단계 파이프라인**: (1) 범용 가이드라인으로 명확성/완전성 개선, (2) 실행 트레이스에서 추출한 실패 규칙(RIMRULE) 반영
- **Trace-Free+ 커리큘럼 학습**: 트레이스 기반 학습 → 점진적으로 트레이스 없는 예제로 전환 → cold-start 배포 가능

## 방법론

### Stage 1: Data-Independent 개선

- 도구의 의도(intent) 명확화
- 필수/선택 파라미터 구분
- 예상 입력 형식 문서화
- 범용 가이드라인 기반 재작성

### Stage 2: Trace-Aware 규칙 반영

- RIMRULE: 실행 실패 트레이스에서 root-cause 오류 식별
- "compact, generalizable rules" 추출 (예: "IPv4/IPv6 형식 모두 허용", "호출 순서 제약")
- 추출된 규칙을 설명에 반영

### 커리큘럼 학습

- Phase 1: 트레이스 포함 예제 `{(aᵢ, hᵢ), dᵢ′}`로 학습
- Phase 2: 점진적으로 트레이스 없는 예제 `{aᵢ, dᵢ′}` 비율 증가
- 목표: 배포 시 실행 트레이스 없이도 설명 개선 가능

## 주요 결과

### In-Domain (StableToolBench)

| 방법 | Subtask-Level | Query-Level |
|------|---------------|-------------|
| D₀ (원본 설명) | 67.3% | 48.0% |
| D₁ (GPT-4 프롬프트 개선) | 66.5% | 49.4% |
| EasyTool (수동 프롬프트) | — | 17.5% (G3) |
| Trace-Free | 67.8% | 51.6% |
| **Trace-Free+** | **70.1%** | **54.0%** |

### Cross-Domain (RestBench)

| 도메인 | Trace-Free+ SL | Trace-Free+ QL | D₀ SL | D₀ QL |
|--------|----------------|----------------|-------|-------|
| TMDB | 88.1% | 74.9% | 69.8% | 49.5% |
| Spotify | 68.1% | 49.3% | 57.1% | 34.9% |

### vs EasyTool (G3 Instruction 서브셋)

| 방법 | Query-Level |
|------|-------------|
| D₀ (원본) | 24.6% |
| EasyTool | 17.5% |
| D₁ (GPT-4) | 25.4% |
| **Trace-Free+** | **46.4%** |

### vs EasyTool (Overall)

| 방법 | Overall Query-Level |
|------|---------------------|
| EasyTool | 43.7% |
| **Trace-Free+** | **54.0%** |
| 차이 | **+10.3%p** |

**Trace-Free+가 EasyTool 대비 +28.9%p 향상** (G3 Instruction 서브셋 기준, 전체 Overall QL은 54.0% vs EasyTool 43.7% = +10.3%p) — 학습 기반 재작성이 프롬프트 기반보다 우월

### 확장성

- 100+ 도구 규모에서도 성능 유지 (Figure 3)
- 기존 baseline은 도구 수 증가에 따라 급격히 성능 저하

## 장점

- 도구 인터페이스 최적화를 에이전트 학습과 동등한 중요도로 격상
- Cold-start 배포 가능: 새 API에 대해 실행 트레이스 없이도 설명 개선
- 107개 API provider, StableToolBench ~764개 + RestBench 157개 쿼리로 검증
- 단일 모델로 100+ 도구 처리 (도구별 학습 불필요)
- 프라이버시 보존: 실행 트레이스 없이 오프라인 컴파일

## 한계

- 구체적인 재작성 전후 예시 미공개
- 기반 LLM 모델명 불명확 (open-weight LLM으로만 기술)
- 재작성이 기존 설명의 의미를 왜곡할 위험에 대한 분석 부족
- 도구 수가 3.4%에서 성능 저하 발생 → 재작성이 항상 개선을 보장하지는 않음

## 프로젝트 시사점

1. **"도구 인터페이스 품질 = 에이전트 품질"**: 프로젝트의 핵심 테제("description 품질이 높을수록 tool 선택률이 높아진다")를 학습 기반 재작성 실험으로 입증한 연구
2. **Cold-Start 도구 개선**: 새로 등록된 MCP 서버의 설명을 자동 개선하는 파이프라인에 Trace-Free+ 방법론 적용 가능
3. **EasyTool 방식의 한계**: 단순 프롬프트 기반 설명 개선(EasyTool)은 오히려 성능을 저하시킬 수 있음 → 학습 기반 접근 필요
4. **Provider Analytics**: 실행 실패 트레이스에서 설명 개선 규칙을 자동 추출하는 RIMRULE 방법론을 Provider 피드백 시스템에 적용 가능

## 적용 포인트

- **Description Enrichment**: 인덱싱 전 LLM 기반 설명 재작성 파이프라인 설계 참고
- **Provider 피드백**: 실행 실패 로그에서 설명 개선점 자동 추출 (RIMRULE 참고)
- **E4 실험**: Description Quality → Selection Rate 인과 관계 검증 시 재작성 전/후 비교 방법론 참고

## 관련 research 문서

- [Description Quality Scoring 조사](../research/description-quality-scoring.md)
